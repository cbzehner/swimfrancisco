from __future__ import annotations

import os
import shlex
import subprocess

import click

from .models import Aborted, Extracted, PoolResult, Skipped, Unchanged
from .paths import (
    CONTENT_SPOTS_DIR,
    DATA_DIR,
    latest_review_dir,
)
from .eval import collect_pool_evals, render_report, write_report
from .pipeline import run_pipeline
from .pr_summary import render_pr_body
from .report import result_counts
from .project import ProjectError, project as _project
from .review import (
    FinalizeError,
    finalize_draft,
    find_review_candidates,
    seed_draft,
)


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
    "--provider",
    type=click.Choice(["anthropic", "gemini"]),
    default=_default_provider(),
    show_default="env SCHEDULES_PROVIDER or gemini",
)
@click.option("--force", is_flag=True, help="Re-fetch PDFs and bypass the unchanged shortcut.")
def extract(
    only: str | None,
    provider: str,
    force: bool,
) -> None:
    """Fetch PDFs, extract schedules, and write a review report."""

    slugs = _parse_slugs(only)
    exit_code, report_path, results = run_pipeline(
        slugs=slugs,
        provider=provider,
        compare_with=None,
        force=force,
    )
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
@click.option("--slug", help="Restrict review to this pool slug.")
def review_command(slug: str | None) -> None:
    """Approve the next pipeline-extracted pool schedule."""
    if not DATA_DIR.is_dir():
        click.echo("nothing to review (run `schedules extract` first?)")
        return

    candidates = find_review_candidates(
        data_root=DATA_DIR,
        only_slug=slug,
    )
    if not candidates:
        click.echo("nothing to review")
        return

    candidate = candidates[0]
    draft = seed_draft(candidate=candidate, data_root=DATA_DIR)
    click.echo(f"Reviewing {candidate.slug} ({candidate.pdf_sha256[:12]})")
    click.echo(f"Source: {candidate.source_path}")
    click.echo(f"Draft:  {draft}")

    if candidate.source_path and candidate.source_path.exists():
        try:
            subprocess.run(["open", str(candidate.source_path)], check=False)
        except FileNotFoundError:
            click.echo(f"(note: `open` not available; source at {candidate.source_path})")

    editor = os.getenv("EDITOR") or "hx"
    subprocess.run([*shlex.split(editor), str(draft)], check=False)

    try:
        final = finalize_draft(
            reviewed_json_path=draft,
            content_spots_dir=CONTENT_SPOTS_DIR,
        )
    except FinalizeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote {final}")


@cli.command("pr-summary")
def pr_summary_command() -> None:
    """Print a PR-optimized summary of currently-staged data/ changes.

    Designed for the auto-extract workflow: highlights pools whose artifact
    files changed, one-liners every other pool, and appends `tmp/eval.md`
    if present. Shells out to `git diff --staged` so it must run after
    `git add data/` and before commit.
    """
    click.echo(render_pr_body())


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
        slugs=slugs,
        provider=provider,
        compare_with=compare_with,
        force=force,
    )
    click.echo(f"Wrote {report_path}")
    click.echo(_summary_line(results))
    raise SystemExit(exit_code)
