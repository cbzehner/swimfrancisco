from __future__ import annotations

from pathlib import Path

from .models import PoolResult
from .paths import REPORT_PATH


def write_report(results: list[PoolResult], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    succeeded = sum(result.status == "success" for result in results)
    unchanged = sum(result.status == "unchanged" for result in results)
    skipped = sum(result.status == "skipped" for result in results)
    failed = sum(result.status == "failed" for result in results)
    flagged = sum(result.needs_review for result in results)

    lines = [
        "# Extraction Report",
        "",
        (
            f"{len(results)}/9 pools processed, {succeeded} succeeded, {unchanged} unchanged, "
            f"{skipped} skipped, {failed} failed, {flagged} flagged for manual review"
        ),
        "",
    ]

    for result in results:
        lines.extend(_render_pool_block(result))

    lines.extend(
        [
            "## Next Steps",
            "",
            "- Review `git diff content/spots/`.",
            "- Inspect raw artifacts under `data/artifacts/` for any flagged pool.",
            "- Commit reviewed overrides under `data/adjudications/` when you intentionally lock a pool to a specific PDF hash.",
            "- Review flagged pools against the source PDFs before committing.",
            "- Suggested add command: `git add content/spots data/extraction-state.json data/adjudications`.",
            "",
        ]
    )

    path.write_text("\n".join(lines))
    return path


def _render_pool_block(result: PoolResult) -> list[str]:
    lines = [
        f"## {result.slug}",
        "",
        f"- status: {result.status}",
        f"- official_page_url: {result.official_page_url}",
        f"- pdf_url: {result.pdf_url}",
        f"- source_status: {result.source_status}",
    ]

    if result.provider:
        lines.append(f"- provider: {result.provider}")
    if result.model:
        lines.append(f"- model: {result.model}")
    if result.pdf_sha256:
        lines.append(f"- pdf_sha256: {result.pdf_sha256[:12]}")
    if result.page_count is not None:
        lines.append(f"- pages: {result.page_count}")
    if result.sessions_count is not None:
        delta_text = ""
        if result.prior_sessions_count is not None:
            delta = result.sessions_count - result.prior_sessions_count
            delta_text = f" ({delta:+d} vs last run)"
        lines.append(f"- sessions: {result.sessions_count}{delta_text}")
    if result.closures_count is not None:
        lines.append(f"- closures: {result.closures_count}")
    if result.schedule_effective:
        lines.append(f"- schedule_effective: {result.schedule_effective}")

    if result.invariants_passed is not None:
        if result.invariants_passed:
            lines.append("- invariants: ok")
        else:
            lines.append(f"- invariants: {', '.join(result.violations)}")

    if result.review_flags:
        for flag in result.review_flags:
            lines.append(f"- review_flag[{flag.severity}::{flag.kind}]: {flag.message}")
    else:
        lines.append("- review_flags: none")

    if result.cost_estimate:
        lines.append(f"- usage: {result.cost_estimate}")
    if result.pdf_text_sha256:
        lines.append(f"- pdf_text_sha256: {result.pdf_text_sha256[:12]}")
    for name, path in sorted(result.artifact_paths.items()):
        lines.append(f"- artifact[{name}]: {path}")
    if result.notes:
        lines.append(f"- notes: {result.notes}")
    if result.error:
        lines.append(f"- error: {result.error}")

    lines.append("")
    return lines
