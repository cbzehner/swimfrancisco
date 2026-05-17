from __future__ import annotations

from pathlib import Path

from .models import Aborted, Extracted, PoolResult, ReviewNote, Skipped, Unchanged, Violation, needs_review
from .paths import REPORT_PATH


def write_report(results: list[PoolResult], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    succeeded = sum(isinstance(result, Extracted) and not result.catastrophic for result in results)
    unchanged = sum(isinstance(result, Unchanged) for result in results)
    skipped = sum(isinstance(result, Skipped) for result in results)
    failed = sum(
        isinstance(result, Aborted) or (isinstance(result, Extracted) and result.catastrophic)
        for result in results
    )
    flagged = sum(needs_review(result) for result in results)

    lines = [
        "# Extraction Report",
        "",
        (
            f"{len(results)} pools processed, {succeeded} succeeded, {unchanged} unchanged, "
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
            "- Inspect raw artifacts under `data/<slug>/<fetch-date>-<sha12>/` for any flagged pool.",
            "- Run `just schedules-review` for provider outputs that need human approval.",
            "- Review flagged pools against the source PDFs before committing.",
            "- Suggested add command after review: `git add content/spots data/`.",
            "",
        ]
    )

    path.write_text("\n".join(lines))
    return path


def _status_label(result: PoolResult) -> str:
    if isinstance(result, Skipped):
        return "skipped"
    if isinstance(result, Unchanged):
        return "unchanged"
    if isinstance(result, Extracted):
        return "failed" if result.catastrophic else "success"
    return "failed"


def _render_pool_block(result: PoolResult) -> list[str]:
    lines = [
        f"## {result.slug}",
        "",
        f"- status: {_status_label(result)}",
        f"- official_page_url: {result.official_page_url}",
        f"- pdf_url: {result.pdf_url}",
        f"- source_status: {result.source_status}",
    ]

    if isinstance(result, Skipped):
        if result.notes:
            lines.append(f"- notes: {result.notes}")
        if result.reason:
            lines.append(f"- error: {result.reason}")
        lines.append("")
        return lines

    if isinstance(result, Aborted):
        lines.append(f"- sessions: {result.prior_sessions_count} (prior, no extraction)")
        lines.append(f"- closures: {result.prior_closures_count} (prior)")
        if result.prior_schedule_effective:
            lines.append(f"- schedule_effective: {result.prior_schedule_effective} (prior)")
        lines.append("- review_notes: none")
        lines.append(f"- error: {result.error}")
        lines.append("")
        return lines

    # Unchanged | Extracted — both share rich extraction fields.
    lines.append(f"- provider: {result.provider}")
    lines.append(f"- model: {result.model}")
    lines.append(f"- pdf_sha256: {result.pdf_sha256[:12]}")
    lines.append(f"- pages: {result.page_count}")

    prior = _prior_sessions_count(result)
    delta_text = f" ({result.sessions_count - prior:+d} vs last run)" if prior is not None else ""
    lines.append(f"- sessions: {result.sessions_count}{delta_text}")
    lines.append(f"- closures: {result.closures_count}")
    if result.schedule_effective:
        lines.append(f"- schedule_effective: {result.schedule_effective}")
    if result.schedule_basis:
        lines.append(f"- schedule_basis: {result.schedule_basis}")

    violations = _violations(result)
    if isinstance(result, Unchanged):
        lines.append("- invariants: ok")
    elif violations:
        lines.append(f"- invariants: {', '.join(v.message for v in violations)}")
    else:
        lines.append("- invariants: ok")

    review_notes = _review_notes(result)
    if review_notes:
        for note in review_notes:
            lines.append(f"- review_note[{note.severity}::{note.kind}]: {note.message}")
    else:
        lines.append("- review_notes: none")

    if result.cost_estimate:
        lines.append(f"- usage: {result.cost_estimate}")
    for name, pool_path in sorted(
        result.artifact_paths.items(),
        key=lambda item: (0 if item[0] == "reviewed-snapshot" else 1, item[0]),
    ):
        lines.append(f"- artifact[{name}]: {pool_path}")

    if isinstance(result, Extracted) and result.catastrophic:
        lines.append("- error: Validation refused the extracted payload.")

    lines.append("")
    return lines


def _prior_sessions_count(result: PoolResult) -> int | None:
    if isinstance(result, Unchanged):
        return result.sessions_count
    if isinstance(result, Extracted):
        return result.prior_sessions_count
    return None


def _violations(result: PoolResult) -> list[Violation]:
    if isinstance(result, Extracted):
        return result.violations
    return []


def _review_notes(result: PoolResult) -> list[ReviewNote]:
    if isinstance(result, (Unchanged, Extracted)):
        return result.review_notes
    return []
