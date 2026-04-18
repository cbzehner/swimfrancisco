from __future__ import annotations

from pathlib import Path

from .models import Failed, PoolResult, Proposed, ReviewNote, Skipped, Unchanged, needs_review
from .paths import REPORT_PATH


def write_report(results: list[PoolResult], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    succeeded = sum(isinstance(result, Proposed) for result in results)
    unchanged = sum(isinstance(result, Unchanged) for result in results)
    skipped = sum(isinstance(result, Skipped) for result in results)
    failed = sum(isinstance(result, Failed) for result in results)
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
            "- Inspect raw artifacts under `data/artifacts/` for any flagged pool.",
            "- Commit reviewed overrides under `data/adjudications/` when you intentionally lock a pool to a specific PDF hash.",
            "- Review flagged pools against the source PDFs before committing.",
            "- Suggested add command: `git add content/spots data/extraction-state.json data/adjudications`.",
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
    if isinstance(result, Proposed):
        return "success"
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

    if result.provider:
        lines.append(f"- provider: {result.provider}")
    if result.model:
        lines.append(f"- model: {result.model}")
    if result.pdf_sha256:
        lines.append(f"- pdf_sha256: {result.pdf_sha256[:12]}")
    if result.page_count is not None:
        lines.append(f"- pages: {result.page_count}")

    if result.sessions_count is not None:
        prior = _prior_sessions_count(result)
        delta_text = f" ({result.sessions_count - prior:+d} vs last run)" if prior is not None else ""
        lines.append(f"- sessions: {result.sessions_count}{delta_text}")

    if result.closures_count is not None:
        lines.append(f"- closures: {result.closures_count}")
    if result.schedule_effective:
        lines.append(f"- schedule_effective: {result.schedule_effective}")

    invariants_passed = _invariants_passed(result)
    violations = _violations(result)
    if invariants_passed is not None:
        if invariants_passed:
            lines.append("- invariants: ok")
        else:
            lines.append(f"- invariants: {', '.join(violations)}")

    review_notes = _review_notes(result)
    if review_notes:
        for note in review_notes:
            lines.append(f"- review_note[{note.severity}::{note.kind}]: {note.message}")
    else:
        lines.append("- review_notes: none")

    if result.cost_estimate:
        lines.append(f"- usage: {result.cost_estimate}")
    if result.pdf_text_sha256:
        lines.append(f"- pdf_text_sha256: {result.pdf_text_sha256[:12]}")
    for name, pool_path in sorted(result.artifact_paths.items()):
        lines.append(f"- artifact[{name}]: {pool_path}")

    if isinstance(result, Proposed) and result.adjudication_notes:
        lines.append(f"- notes: {result.adjudication_notes}")
    if isinstance(result, Failed):
        lines.append(f"- error: {result.error}")

    lines.append("")
    return lines


def _prior_sessions_count(result: PoolResult) -> int | None:
    if isinstance(result, Unchanged):
        return result.sessions_count
    if isinstance(result, (Proposed, Failed)):
        return result.prior_sessions_count
    return None


def _invariants_passed(result: PoolResult) -> bool | None:
    if isinstance(result, Unchanged):
        return result.invariants_passed
    if isinstance(result, Proposed):
        return result.invariants_passed
    if isinstance(result, Failed) and result.violations:
        return False
    return None


def _violations(result: PoolResult) -> list[str]:
    if isinstance(result, (Proposed, Failed)):
        return result.violations
    return []


def _review_notes(result: PoolResult) -> list[ReviewNote]:
    if isinstance(result, (Unchanged, Proposed, Failed)):
        return result.review_notes
    return []
