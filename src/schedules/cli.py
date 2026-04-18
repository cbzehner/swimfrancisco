from __future__ import annotations

import os

import click

from .pipeline import run_pipeline


def _default_provider() -> str:
    return os.getenv("SCHEDULES_PROVIDER", "gemini")


@click.group()
def cli() -> None:
    """Pool schedule extraction tools."""


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
@click.option(
    "--compare-with",
    type=click.Choice(["anthropic", "gemini"]),
    help="Run a second provider on the same PDFs and surface disagreements without merging its output.",
)
@click.option("--force", is_flag=True, help="Re-fetch PDFs and bypass the unchanged shortcut.")
@click.option("--dry-run", is_flag=True, help="Skip content/state writes but still write the report.")
def extract(
    only: str | None,
    provider: str,
    compare_with: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Fetch PDFs, extract schedules, and write a review report."""

    slugs = None
    if only:
        slugs = [slug.strip() for slug in only.split(",") if slug.strip()]
        if not slugs:
            raise click.ClickException("--only was provided but no valid slugs were parsed.")
    if compare_with == provider:
        raise click.ClickException("--compare-with must differ from --provider.")

    exit_code, report_path, results = run_pipeline(
        slugs=slugs,
        provider=provider,
        compare_with=compare_with,
        force=force,
        dry_run=dry_run,
    )
    click.echo(f"Wrote {report_path}")
    click.echo(
        f"{len(results)} pools processed; "
        f"{sum(result.status == 'success' for result in results)} succeeded, "
        f"{sum(result.status == 'unchanged' for result in results)} unchanged, "
        f"{sum(result.status == 'skipped' for result in results)} skipped, "
        f"{sum(result.status == 'failed' for result in results)} failed."
    )
    raise SystemExit(exit_code)
