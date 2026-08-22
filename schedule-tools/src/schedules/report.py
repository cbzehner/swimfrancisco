from __future__ import annotations

from pathlib import Path

from .discover import view_id_from_url
from .models import Aborted, Extracted, PoolResult, ReviewNote, Skipped, Unchanged, Violation, needs_review
from .review import DecisionSet, parse_view_id


def result_counts(results: list[PoolResult]) -> dict[str, int]:
    return {
        "succeeded": sum(isinstance(result, Extracted) and not result.catastrophic for result in results),
        "unchanged": sum(isinstance(result, Unchanged) for result in results),
        "skipped": sum(isinstance(result, Skipped) for result in results),
        "failed": sum(
            isinstance(result, Aborted) or (isinstance(result, Extracted) and result.catastrophic)
            for result in results
        ),
    }


def write_report(results: list[PoolResult], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    counts = result_counts(results)
    flagged = sum(needs_review(result) for result in results)

    lines = [
        "# Extraction Report",
        "",
        f"overall status: {'partial success' if counts['failed'] else 'success'}",
        f"failure count: {counts['failed']}",
        "",
        (
            f"{len(results)} pools processed, {counts['succeeded']} succeeded, "
            f"{counts['unchanged']} unchanged, {counts['skipped']} skipped, "
            f"{counts['failed']} failed, {flagged} flagged for manual review"
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
            "- Eligible Rec & Park grids publish via `just schedules publish-pending`.",
            "- Run `just schedules-review` for FLAG URL adopt or to repair a re-queued dir.",
            "- Suggested add command: `git add content/spots data/`.",
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
        for note in result.review_notes:
            lines.append(f"- review_note[{note.severity}::{note.kind}]: {note.message}")
        lines.append("")
        return lines

    if isinstance(result, Aborted):
        lines.append(f"- sessions: {result.prior_sessions_count} (prior, no extraction)")
        lines.append(f"- closures: {result.prior_closures_count} (prior)")
        if result.prior_schedule_effective:
            lines.append(f"- effective_start: {result.prior_schedule_effective} (prior)")
        if result.review_notes:
            for note in result.review_notes:
                lines.append(f"- review_note[{note.severity}::{note.kind}]: {note.message}")
        else:
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
    if result.effective_start:
        lines.append(f"- effective_start: {result.effective_start}")
    if result.schedule_basis:
        lines.append(f"- schedule_basis: {result.schedule_basis}")

    violations = _violations(result)
    if violations:
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
    return list(getattr(result, "review_notes", []) or [])


def discovery_notes_from_decisions(decisions: DecisionSet) -> dict[str, list[ReviewNote]]:
    """Read review notes from a loaded DecisionSet. Does not re-discover."""
    notes: dict[str, list[ReviewNote]] = {}
    for item in decisions:
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        attached = _notes_for_decision(item)
        if attached:
            notes[slug] = attached
    return notes


def _notes_for_decision(item: dict) -> list[ReviewNote]:
    attached: list[ReviewNote] = []
    action = item.get("action")
    if action == "adopt":
        old_id = view_id_from_url(str(item.get("old_url") or ""))
        new_id = view_id_from_url(str(item.get("new_url") or ""))
        filename = _candidate_filename(item, new_id)
        parts: list[str] = []
        if old_id is not None and new_id is not None:
            parts.append(f"{old_id} → {new_id}")
        elif new_id is not None:
            parts.append(str(new_id))
        if filename:
            parts.append(filename)
        attached.append(
            ReviewNote(
                kind="url_rolled",
                message=", ".join(parts) if parts else "pdf_url rolled",
                severity="info",
            )
        )
    if action == "flag" or item.get("blocking"):
        reason = item.get("reason") or "flag"
        ids = [
            str(view_id)
            for candidate in item.get("candidates") or []
            if isinstance(candidate, dict)
            and (view_id := parse_view_id(candidate.get("view_id"))) is not None
        ]
        id_text = f" ({', '.join(ids)})" if ids else ""
        attached.append(
            ReviewNote(
                kind="discovery_flagged",
                message=f"{reason}{id_text}",
                severity="warning",
            )
        )
    return attached


def _candidate_filename(item: dict, view_id: int | None) -> str | None:
    if view_id is None:
        return None
    for bucket in ("candidates", "extra_candidates"):
        for candidate in item.get(bucket) or []:
            if not isinstance(candidate, dict) or parse_view_id(candidate.get("view_id")) != view_id:
                continue
            filename = candidate.get("filename")
            if isinstance(filename, str) and filename:
                return filename
    return None
