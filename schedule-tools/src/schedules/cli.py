from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime, timezone
import click

from .discover import DiscoverError, discover_all, rec_park_entries
from .benchmark import archive_benchmark, benchmark_models, check_model, prepare_benchmark, replay_benchmark, run_benchmark, run_api_benchmark
from .models import PoolResult
from .paths import (
    CONTENT_SPOTS_DIR,
    DATA_DIR,
    TMP_DIR,
    REPO_ROOT,
    latest_reviewed_dir,
)
from .publish import publish_pending_all
from .registry import load_registry
from .eval import collect_pool_evals, load_benchmark_reference, render_report, score_benchmark_run, write_report
from .pipeline import (
    BakeoffRun,
    DirectRun,
    DiscoverAndExpand,
    ExpandFromDecisions,
    PdfRun,
    PinOverride,
    parse_provider,
    run_pipeline,
)
from .automation import automate, open_closure_review_prs
from .report import result_counts
from .project import ProjectError, project as _project
from .review import DecisionSet
from .review_server import ReviewApp, serve_review_app
from .providers.openai_provider import MonthlySpendBudget, SpendBudget


def _default_provider() -> str:
    return os.getenv("SCHEDULES_PROVIDER", "openai")


@click.group()
def cli() -> None:
    """Pool schedule extraction tools."""


@cli.group("budget")
def budget_command() -> None:
    """Durable API accounting; never grants permission to enable automation."""


def _monthly_budget() -> MonthlySpendBudget:
    try:
        return MonthlySpendBudget(REPO_ROOT, float(os.environ.get("SCHEDULES_MONTHLY_BUDGET_USD", "0")))
    except ValueError as error:
        raise click.ClickException(str(error)) from error


@budget_command.command("initialize")
def budget_initialize_command() -> None:
    """Create the separate accounting branch once, after operator approval."""
    _monthly_budget().initialize()


@budget_command.command("reserve")
@click.option("--run-id", required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
def budget_reserve_command(run_id: str, output: Path) -> None:
    """Reserve at most $1 for this run before creating its local request ledger."""
    if output.exists() and any(output.iterdir()):
        raise click.ClickException("Budget output directory must be empty")
    if not re.fullmatch(r"\d+-\d+", run_id):
        raise click.ClickException("Budget reservation requires an Actions run/attempt ID")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError("Paid extraction credentials unavailable")
        receipt = _monthly_budget().reserve(month, run_id) | {"status": "reserved"}
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, click.ClickException):
        receipt = {"month": month, "run_id": run_id, "limit_microusd": 0,
                   "status": "unavailable", "reason": "Paid extraction unavailable; free updates continue"}
    output.mkdir(parents=True, exist_ok=True)
    (output / "reservation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["status"] == "unavailable":
        (output / "budget.json").write_text(json.dumps({"limit_microusd": 0, "requests": []}) + "\n")
    else:
        SpendBudget(output / "budget.json", receipt["limit_microusd"] / 1_000_000)._update(lambda _: None)
    click.echo(json.dumps(receipt))


@budget_command.command("settle")
@click.option("--directory", type=click.Path(path_type=Path, exists=True), required=True)
def budget_settle_command(directory: Path) -> None:
    """Settle conservative run charges; missing usage keeps its reservation."""
    receipt = json.loads((directory / "reservation.json").read_text())
    if receipt.get("status") == "unavailable":
        ledger = json.loads((directory / "budget.json").read_text())
        if (type(receipt.get("limit_microusd")) is not int or receipt["limit_microusd"] != 0
                or ledger != {"limit_microusd": 0, "requests": []}
                or type(ledger.get("limit_microusd")) is not int):
            raise click.ClickException("Unavailable paid budget must have no requests or charges")
        click.echo("Paid extraction unavailable; no durable reservation settled")
        return
    if receipt.get("status") != "reserved":
        raise click.ClickException("Unknown budget reservation status")
    _monthly_budget().settle(receipt, directory / "budget.json")


def _parse_slugs(only: str | None) -> list[str] | None:
    if only is None:
        return None
    slugs = [slug.strip() for slug in only.split(",") if slug.strip()]
    if not slugs:
        raise click.ClickException("--only was provided but no valid slugs were parsed.")
    return slugs


def _summary_line(results: list[PoolResult]) -> str:
    counts = result_counts(results)
    return (
        f"{len(results)} pools processed; "
        f"{counts['succeeded']} succeeded, "
        f"{counts['unchanged']} unchanged, "
        f"{counts['skipped']} skipped, "
        f"{counts['failed']} failed."
    )


@cli.command()
@click.option(
    "--only",
    help="Comma-separated pool slugs to process.",
)
@click.option(
    "--direct",
    is_flag=True,
    help="Process every configured provider-independent direct source.",
)
@click.option(
    "--provider",
    type=click.Choice(["openai", "anthropic", "gemini"]),
    help="Process only configured sfrecpark_pdf sources with this provider.",
)
@click.option("--force", is_flag=True, help="Re-fetch PDFs and bypass the unchanged shortcut.")
@click.option(
    "--no-discover",
    is_flag=True,
    help="Do not run Rec & Park PDF discovery; reuse the last discovery decisions.",
)
@click.option(
    "--url",
    "override_url",
    help="Fetch this PDF URL for a single --only slug without rewriting the registry.",
)
def extract(
    only: str | None,
    direct: bool,
    provider: str | None,
    force: bool,
    no_discover: bool,
    override_url: str | None,
) -> None:
    """Fetch PDFs, extract schedules, and write a review report."""

    if override_url and direct:
        raise click.UsageError("--url is incompatible with --direct")
    if direct == bool(provider):
        raise click.UsageError("exactly one of --direct or --provider is required")
    slugs = _parse_slugs(only)
    slug_tuple = tuple(slugs) if slugs is not None else None
    if override_url is not None and (slugs is None or len(slugs) != 1):
        raise click.UsageError("--url requires --only with exactly one slug")
    if direct:
        command = DirectRun(slugs=slug_tuple, force=force)
    elif override_url is not None:
        command = PdfRun(
            provider=parse_provider(provider or ""),
            slugs=slug_tuple,
            force=force,
            urls=PinOverride(override_url),
        )
    else:
        command = PdfRun(
            provider=parse_provider(provider or ""),
            slugs=slug_tuple,
            force=force,
            urls=(
                ExpandFromDecisions(
                    DecisionSet.load(TMP_DIR / "discovery-decisions.json")
                )
                if no_discover
                else DiscoverAndExpand()
            ),
        )
    try:
        exit_code, report_path, results = run_pipeline(command)
    except DiscoverError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    click.echo(f"Wrote {report_path}")
    click.echo(_summary_line(results))
    raise SystemExit(exit_code)


@cli.command("project")
@click.argument("slug")
def project_command(slug: str) -> None:
    """Project the latest reviewed.json for SLUG into content/spots/<slug>.md."""
    review_dir = latest_reviewed_dir(slug, root=DATA_DIR)
    if review_dir is None:
        raise click.ClickException(f"no review dir found for slug={slug!r}")
    reviewed_json = review_dir / "reviewed.json"
    if not reviewed_json.exists():
        raise click.ClickException(f"no reviewed.json found at {reviewed_json}")
    try:
        path = _project(
            slug=slug,
            reviewed_json_path=reviewed_json,
            content_spots_dir=CONTENT_SPOTS_DIR,
        )
    except ProjectError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote {path}")


@cli.command("review")
@click.option("--port", type=int, default=0, help="Local port (default: choose an available port).")
@click.option("--no-open", is_flag=True, help="Do not open the browser automatically.")
def review_command(port: int, no_open: bool) -> None:
    """Open the local browser-based schedule reviewer."""
    if not DATA_DIR.is_dir():
        click.echo("nothing to review (run `schedules extract` first?)")
        return

    if not ReviewApp(data_root=DATA_DIR, content_spots_dir=CONTENT_SPOTS_DIR).list_reviews():
        click.echo("nothing to review")
        return
    serve_review_app(port=port, open_browser=not no_open)


def _parse_adopt(value: str | None) -> tuple[str, int] | None:
    if value is None:
        return None
    if "=" not in value:
        raise click.UsageError("--adopt must be slug=id")
    slug, raw_id = value.split("=", 1)
    slug = slug.strip()
    if not slug:
        raise click.UsageError("--adopt must be slug=id")
    try:
        view_id = int(raw_id.strip())
    except ValueError as exc:
        raise click.UsageError("--adopt id must be an integer") from exc
    return slug, view_id


@cli.command("discover")
@click.option(
    "--only",
    help="Comma-separated pool slugs to process.",
)
@click.option("--dry-run", is_flag=True, help="Report only. Do not write registry.toml.")
@click.option("--adopt", "adopt_spec", help="Confirm a FLAG candidate as slug=id.")
def discover_command(only: str | None, dry_run: bool, adopt_spec: str | None) -> None:
    """Parse Rec & Park Documents tables and roll unique session-grid PDF URLs."""
    slugs = _parse_slugs(only)
    adopt = _parse_adopt(adopt_spec)
    entries = rec_park_entries(load_registry())
    try:
        decisions = discover_all(entries, dry_run=dry_run, slugs=slugs, adopt=adopt)
    except DiscoverError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    click.echo(f"Wrote {TMP_DIR / 'discovery-report.md'}")
    if dry_run:
        click.echo("dry-run: registry not written")
    flagged = sum(1 for decision in decisions if decision.blocking)
    click.echo(f"{len(decisions)} Rec & Park pools; {flagged} flagged.")


@cli.command("discover-blocking")
def discover_blocking_command() -> None:
    """Print slugs with blocking discover flags, one per line.

    Operator/issue signal, not an auto-merge gate. A missing decisions
    file exits 1; that is not "no flags."
    """
    path = TMP_DIR / "discovery-decisions.json"
    if not path.exists():
        click.echo(
            "tmp/discovery-decisions.json is missing; cannot verify discover flags.",
            err=True,
        )
        raise SystemExit(1)
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        return
    for item in payload:
        if isinstance(item, dict) and item.get("blocking"):
            slug = item.get("slug")
            if slug:
                click.echo(slug)


@cli.command("publish-pending")
def publish_pending_command() -> None:
    """Auto-publish eligible unique Rec & Park session grids.

    Writes tmp/publish-pending-report.md. Per-pool refuses exit 0; a
    crash exits 1. Kill switch: SCHEDULES_AUTO_PROJECT=false no-ops.
    """
    try:
        published, report_path = publish_pending_all()
    except Exception as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    payload = json.loads(report_path.with_name("publish-pending.json").read_text())
    refused = payload.get("refused") or []
    click.echo(f"Wrote {report_path}")
    click.echo(f"{published} published; pools with refusals: {len({item['slug'] for item in refused})}; candidate refusals: {len(refused)}")


@cli.command("pending-reviews")
def pending_reviews_command() -> None:
    """Print slugs still awaiting review (no reviewed.json), one per line.

    Operator/issue signal, not an auto-merge gate. After auto-publish this
    set is FLAG, refused, and out-of-scope direct/HTML captures.
    """
    if not DATA_DIR.is_dir():
        return
    for review in ReviewApp(data_root=DATA_DIR, content_spots_dir=CONTENT_SPOTS_DIR).list_reviews():
        click.echo(review["slug"])


@cli.command("automate")
@click.option("--mode", type=click.Choice(["extract-only", "publish"]), default="extract-only")
@click.option("--run-id", required=True)
def automate_command(mode: str, run_id: str) -> None:
    """Run bounded extraction and checked publication in isolated worktrees."""
    try:
        click.echo(json.dumps(automate(REPO_ROOT, mode=mode, run_id=run_id)))
    except Exception as error:
        raise click.ClickException(f"Automation stopped ({type(error).__name__}); inspect its evidence") from error


@cli.command("closure-prs")
@click.option("--evidence", type=click.Path(path_type=Path, exists=True), required=True)
def closure_prs_command(evidence: Path) -> None:
    """Open draft, evidence-only PRs for unclear closures; never publish hours."""
    try:
        result = open_closure_review_prs(REPO_ROOT, evidence.resolve())
        (evidence / "closure-prs.json").write_text(json.dumps(result, indent=2) + "\n")
        click.echo(json.dumps(result))
    except Exception as error:
        raise click.ClickException(f"Closure PR creation stopped ({type(error).__name__}); existing branches were preserved") from error


@cli.command("eval")
@click.option(
    "--stdout",
    is_flag=True,
    help="Print the report to stdout instead of writing to tmp/eval-<ts>.md.",
)
@click.option(
    "--all-dirs",
    is_flag=True,
    help="Include historical review dirs (default: latest review dir per pool).",
)
def eval_command(stdout: bool, all_dirs: bool) -> None:
    """Diff every committed reviewed.json against same-dir provider artifacts.

    No API calls. Output is a per-pool / per-provider scorecard with
    aggregate precision/recall/F1.
    """
    evals = collect_pool_evals(all_dirs=all_dirs)
    if not evals:
        raise click.ClickException("no (review_dir, provider) pairs found.")
    if stdout:
        click.echo(render_report(evals))
        return
    path = write_report(evals)
    click.echo(f"Wrote {path}")


@cli.command("benchmark")
@click.argument("attempt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--reference", "reference_id", required=True, help="Checked development document ID.")
def benchmark_command(attempt: Path, reference_id: str) -> None:
    """Score one recorded attempt against checked PDF facts. No API calls or writes."""
    try:
        reference = load_benchmark_reference(
            REPO_ROOT / "tests/fixtures/schedule-benchmark.json", reference_id, repo_root=REPO_ROOT,
        )
        run = json.loads(attempt.read_text())
        if not isinstance(run, dict):
            raise ValueError("Benchmark attempt must be an object.")
        result = score_benchmark_run(reference, run)
    except (OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2))


@cli.command("benchmark-prepare")
@click.option("--poppler", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--comparison", default="source-inventory", type=click.Choice(["source-inventory", "source-holdout", "development", "finalists", "literal-pool-labels"]))
def benchmark_prepare_command(poppler: Path | None, comparison: str) -> None:
    """Prepare label-free comparison inputs in a fresh temporary directory. No model calls."""
    try:
        root = prepare_benchmark(REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT, poppler, comparison)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(root))


@cli.command("benchmark-check")
@click.option("--candidate", required=True, help="Exact candidate ID from the benchmark manifest.")
@click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--pi-extension", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--timeout", default=60, type=click.IntRange(1, 180))
def benchmark_check_command(candidate: str, output: Path, pi_extension: Path | None, timeout: int) -> None:
    """Make ONE CLI inference call to check text/JSON readiness. Uses account quota."""
    try:
        models = benchmark_models(REPO_ROOT / "tests/fixtures/schedule-benchmark.json")
        matches = [model for model in models if model["id"] == candidate]
        if not matches:
            raise ValueError("Unknown benchmark candidate.")
        result = check_model(matches[0], output.resolve(), pi_extension, timeout)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2))
    if result["status"] != "text_ready":
        raise click.exceptions.Exit(1)


@cli.command("benchmark-run")
@click.option("--inputs", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--pi-extension", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--blocked-candidate", multiple=True, help="Record an authentication-blocked candidate without calling it.")
@click.option("--timeout", default=180, type=click.IntRange(1, 300))
def benchmark_run_command(inputs: Path, output: Path, pi_extension: Path,
                          blocked_candidate: tuple[str, ...], timeout: int) -> None:
    """Run and score the frozen development matrix. Uses CLI account quota; never publishes."""
    try:
        results = run_benchmark(inputs.resolve(), output.resolve(),
                                REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT,
                                pi_extension.resolve(), blocked_candidate, timeout, progress=click.echo)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Recorded {len(results)} cells. Report: {output / 'report.md'}")


@cli.command("benchmark-api-run")
@click.option("--inputs", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--budget-usd", required=True, type=click.FloatRange(min=0, max=10, min_open=True))
@click.option("--timeout", default=240, type=click.IntRange(1, 300))
def benchmark_api_run_command(inputs: Path, output: Path, budget_usd: float, timeout: int) -> None:
    """Run the frozen API comparison with a maximum reservation before each call. Never publishes."""
    try:
        results = run_api_benchmark(inputs.resolve(), output.resolve(),
                                    REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT,
                                    budget_usd, timeout, progress=click.echo)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Recorded {len(results)} cells. Report: {output / 'report.md'}")


@cli.command("benchmark-archive")
@click.option("--inputs", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--results", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
def benchmark_archive_command(inputs: Path, results: Path, output: Path) -> None:
    """Preserve frozen inputs, final responses and scores in a new ZIP. No model calls."""
    try:
        archive_benchmark(inputs, results, output, REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT)
    except (OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Verified and archived benchmark: {output}")


@cli.command("benchmark-replay")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", required=True, type=click.Path(file_okay=False, path_type=Path))
def benchmark_replay_command(archive: Path, output: Path) -> None:
    """Verify checksums and reproduce all recorded scores offline. Never calls models."""
    try:
        report = replay_benchmark(archive, output, REPO_ROOT)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Verified all archived cells and reproduced both reports: {report}")


@cli.group()
def debug() -> None:
    """Research tools that never mutate content or state."""


@debug.command("bakeoff")
@click.option(
    "--only",
    required=True,
    help="Comma-separated pool slugs to process.",
)
@click.option(
    "--provider",
    type=click.Choice(["openai", "anthropic", "gemini"]),
    default=_default_provider(),
    show_default="env SCHEDULES_PROVIDER or gemini",
)
@click.option(
    "--compare-with",
    type=click.Choice(["openai", "anthropic", "gemini"]),
    required=True,
    help="Second provider to run against the same PDFs and diff.",
)
@click.option("--force", is_flag=True, help="Re-fetch PDFs and bypass the unchanged shortcut.")
def debug_bakeoff(
    only: str,
    provider: str,
    compare_with: str,
    force: bool,
) -> None:
    """Run two providers on the same PDFs and surface disagreements.

    Writes provider artifact bundles under data/, never content/spots."""

    if compare_with == provider:
        raise click.ClickException("--compare-with must differ from --provider.")

    slugs = _parse_slugs(only)
    exit_code, report_path, results = run_pipeline(
        BakeoffRun(
            provider=parse_provider(provider),
            compare_with=parse_provider(compare_with),
            slugs=tuple(slugs) if slugs is not None else None,
            force=force,
        )
    )
    click.echo(f"Wrote {report_path}")
    click.echo(_summary_line(results))
    raise SystemExit(exit_code)
