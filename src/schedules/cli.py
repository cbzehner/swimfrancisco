from __future__ import annotations

import os

import click

from .models import Failed, PoolResult, Proposed, Skipped, Unchanged
from .pipeline import run_pipeline


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
    return (
        f"{len(results)} pools processed; "
        f"{sum(isinstance(result, Proposed) for result in results)} succeeded, "
        f"{sum(isinstance(result, Unchanged) for result in results)} unchanged, "
        f"{sum(isinstance(result, Skipped) for result in results)} skipped, "
        f"{sum(isinstance(result, Failed) for result in results)} failed."
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
@click.option("--dry-run", is_flag=True, help="Skip content/state writes but still write the report.")
def extract(
    only: str | None,
    provider: str,
    force: bool,
    dry_run: bool,
) -> None:
    """Fetch PDFs, extract schedules, and write a review report."""

    slugs = _parse_slugs(only)
    exit_code, report_path, results = run_pipeline(
        slugs=slugs,
        provider=provider,
        compare_with=None,
        force=force,
        dry_run=dry_run,
    )
    click.echo(f"Wrote {report_path}")
    click.echo(_summary_line(results))
    raise SystemExit(exit_code)


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
    """Run two providers on the same PDFs and surface disagreements. Never writes."""

    if compare_with == provider:
        raise click.ClickException("--compare-with must differ from --provider.")

    slugs = _parse_slugs(only)
    exit_code, report_path, results = run_pipeline(
        slugs=slugs,
        provider=provider,
        compare_with=compare_with,
        force=force,
        dry_run=False,
    )
    click.echo(f"Wrote {report_path}")
    click.echo(_summary_line(results))
    raise SystemExit(exit_code)
