from __future__ import annotations

from .models import ReviewNote


def check_delta(extracted: dict, prior_state_entry: dict | None) -> list[ReviewNote]:
    """Advisory notes comparing a new extraction to the prior state entry.

    Catastrophic conditions (sessions dropped to 0 from non-zero) are handled
    by ``validate()`` as a blocking violation; this function only emits notes
    that the human reviewer should eyeball but that never block the merge.
    """
    if not prior_state_entry:
        return []

    notes: list[ReviewNote] = []

    prior_sessions = int(prior_state_entry.get("sessions_count") or 0)
    new_sessions = len(extracted.get("sessions") or [])
    if prior_sessions > 0:
        delta_pct = abs(new_sessions - prior_sessions) / prior_sessions * 100
        if delta_pct > 20:
            notes.append(
                ReviewNote(
                    kind="delta_session_count_shift",
                    message=f"session count changed by {delta_pct:.1f}% ({prior_sessions} -> {new_sessions})",
                )
            )

    prior_types = {str(value) for value in prior_state_entry.get("session_types") or []}
    new_types = {str(session.get("type")) for session in extracted.get("sessions") or []}
    missing_types = sorted(value for value in prior_types if value and value not in new_types)
    if missing_types:
        notes.append(
            ReviewNote(
                kind="delta_session_types_missing",
                message=f"session types disappeared: {', '.join(missing_types)}",
            )
        )

    prior_effective = prior_state_entry.get("schedule_effective")
    new_effective = extracted.get("schedule_effective")
    if isinstance(prior_effective, str) and isinstance(new_effective, str) and new_effective < prior_effective:
        notes.append(
            ReviewNote(
                kind="delta_schedule_effective_regressed",
                message=f"schedule_effective regressed ({prior_effective} -> {new_effective})",
            )
        )

    return notes

