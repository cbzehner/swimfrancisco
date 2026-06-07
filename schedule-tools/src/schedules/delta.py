from __future__ import annotations

from typing import Any

from .models import ReviewNote


def check_delta(extracted: dict, prior_snapshot: dict[str, Any]) -> list[ReviewNote]:
    """Advisory notes comparing a new extraction to the prior content snapshot.

    Catastrophic conditions (sessions dropped to 0 from non-zero) are handled
    by ``validate()`` as a blocking violation; this function only emits notes
    that the human reviewer should eyeball but that never block the merge.

    Reads from the content snapshot (the prior `content/spots/<slug>.md`
    frontmatter), which is the source of truth for "what was there before."
    """
    prior_sessions = prior_snapshot.get("sessions") or []
    prior_sessions_count = len(prior_sessions)
    if prior_sessions_count == 0:
        # First-time extraction (or previously-empty content) has no
        # meaningful delta to compare against.
        return []

    notes: list[ReviewNote] = []

    new_sessions = extracted.get("sessions") or []
    new_sessions_count = len(new_sessions)
    delta_pct = abs(new_sessions_count - prior_sessions_count) / prior_sessions_count * 100
    if delta_pct > 20:
        notes.append(
            ReviewNote(
                kind="delta_session_count_shift",
                message=f"session count changed by {delta_pct:.1f}% ({prior_sessions_count} -> {new_sessions_count})",
            )
        )

    prior_types = {str(session.get("type")) for session in prior_sessions}
    new_types = {str(session.get("type")) for session in new_sessions}
    missing_types = sorted(value for value in prior_types if value and value not in new_types)
    if missing_types:
        notes.append(
            ReviewNote(
                kind="delta_session_types_missing",
                message=f"session types disappeared: {', '.join(missing_types)}",
            )
        )

    prior_effective = prior_snapshot.get("effective_start")
    new_effective = extracted.get("effective_start")
    if isinstance(prior_effective, str) and isinstance(new_effective, str) and new_effective < prior_effective:
        notes.append(
            ReviewNote(
                kind="delta_schedule_effective_regressed",
                message=f"effective_start regressed ({prior_effective} -> {new_effective})",
            )
        )

    return notes
