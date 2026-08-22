from __future__ import annotations

import json
import os
import click

from .discover import DiscoverError, discover_all, rec_park_entries
from .models import PoolResult
from .paths import (
    CONTENT_SPOTS_DIR,
    DATA_DIR,
    TMP_DIR,
    latest_review_dir,
)
from .publish import publish_pending_all
from .registry import load_registry
from .eval import collect_pool_evals, render_report, write_report
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
from .pr_summary import render_pr_body, staged_data_has_meaningful_changes
from .report import result_counts
from .project import ProjectError, project as _project
from .review_server import ReviewApp, serve_review_app


def _default_provider() -> str:
    return os.getenv("SCHEDULES_PROVIDER", "gemini")


@click.group()
def cli() -> None:
    """Pool schedule extraction tools."""


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
    type=click.Choice(["anthropic", "gemini"]),
    help="Process only configured sfrecpark_pdf sources with this provider.",
)
@click.option("--force", is_flag=True, help="Re-fetch PDFs and bypass the unchanged shortcut.")
@click.option(
    "--no-discover",
    is_flag=True,
    help="Do not run Rec & Park PDF discovery; fetch working-tree pdf_url.",
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
            urls=ExpandFromDecisions() if no_discover else DiscoverAndExpand(),
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
    review_dir = latest_review_dir(slug, root=DATA_DIR)
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
    click.echo(f"{published} published, {len(refused)} refused")


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


@cli.command("pr-summary")
def pr_summary_command() -> None:
    """Print a PR-optimized summary of currently-staged data/ changes.

    Designed for the auto-extract workflow: highlights pools whose artifact
    files changed, one-liners every other pool, and appends `tmp/eval.md`
    if present. Shells out to `git diff --staged` so it must run after
    `git add data/` and before commit.
    """
    click.echo(render_pr_body())


@cli.command("has-meaningful-staged-data-changes")
def has_meaningful_staged_data_changes_command() -> None:
    """Exit 0 when staged data changes should open a schedule PR."""
    if staged_data_has_meaningful_changes():
        click.echo("meaningful staged data changes detected")
        raise SystemExit(0)
    click.echo("only metadata-only staged data changes detected")
    raise SystemExit(1)


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
    type=click.Choice(["anthropic", "gemini"]),
    default=_default_provider(),
    show_default="env SCHEDULES_PROVIDER or gemini",
)
@click.option(
    "--compare-with",
    type=click.Choice(["anthropic", "gemini"]),
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
