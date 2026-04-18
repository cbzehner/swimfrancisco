from __future__ import annotations

from .models import DeltaResult


def check_delta(extracted: dict, prior_state_entry: dict | None) -> DeltaResult:
    if not prior_state_entry:
        return DeltaResult(flags=[], hard_block=False)

    flags: list[str] = []
    hard_block = False

    prior_sessions = int(prior_state_entry.get("sessions_count") or 0)
    new_sessions = len(extracted.get("sessions") or [])
    if prior_sessions > 0:
        delta_pct = abs(new_sessions - prior_sessions) / prior_sessions * 100
        if delta_pct > 20:
            flags.append(f"session count changed by {delta_pct:.1f}% ({prior_sessions} -> {new_sessions})")

    prior_types = {str(value) for value in prior_state_entry.get("session_types") or []}
    new_types = {str(session.get("type")) for session in extracted.get("sessions") or []}
    missing_types = sorted(value for value in prior_types if value and value not in new_types)
    if missing_types:
        flags.append(f"session types disappeared: {', '.join(missing_types)}")

    prior_effective = prior_state_entry.get("schedule_effective")
    new_effective = extracted.get("schedule_effective")
    if isinstance(prior_effective, str) and isinstance(new_effective, str) and new_effective < prior_effective:
        flags.append(f"schedule_effective regressed ({prior_effective} -> {new_effective})")

    if prior_sessions > 0 and new_sessions == 0:
        hard_block = True
        flags.append("sessions_count dropped to 0 from a previously non-zero state")

    return DeltaResult(flags=flags, hard_block=hard_block)

