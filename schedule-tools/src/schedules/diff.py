from __future__ import annotations

from collections import Counter

from .models import ReviewNote


def compare_payloads(
    primary_provider: str,
    primary_payload: dict,
    secondary_provider: str,
    secondary_payload: dict,
) -> list[ReviewNote]:
    notes: list[ReviewNote] = []

    primary_sessions = Counter(_session_key(session) for session in primary_payload.get("sessions") or [])
    secondary_sessions = Counter(_session_key(session) for session in secondary_payload.get("sessions") or [])
    primary_closures = Counter(_closure_key(closure) for closure in primary_payload.get("closures") or [])
    secondary_closures = Counter(_closure_key(closure) for closure in secondary_payload.get("closures") or [])

    if sum(primary_sessions.values()) != sum(secondary_sessions.values()):
        notes.append(
            ReviewNote(
                kind="provider_session_count_disagreement",
                message=(
                    f"{primary_provider} and {secondary_provider} disagree on session count "
                    f"({sum(primary_sessions.values())} vs {sum(secondary_sessions.values())})"
                ),
            )
        )

    only_primary = sorted((primary_sessions - secondary_sessions).elements())
    only_secondary = sorted((secondary_sessions - primary_sessions).elements())
    if only_primary or only_secondary:
        notes.append(
            ReviewNote(
                kind="provider_session_diff",
                message=(
                    f"{primary_provider} and {secondary_provider} produced different session sets "
                    f"({len(only_primary)} only in {primary_provider}, {len(only_secondary)} only in {secondary_provider})"
                ),
            )
        )

    if primary_closures != secondary_closures:
        notes.append(
            ReviewNote(
                kind="provider_closure_diff",
                message=f"{primary_provider} and {secondary_provider} produced different closure sets",
            )
        )

    primary_effective = primary_payload.get("effective_start")
    secondary_effective = secondary_payload.get("effective_start")
    if primary_effective != secondary_effective:
        notes.append(
            ReviewNote(
                kind="provider_schedule_effective_diff",
                message=(
                    f"{primary_provider} and {secondary_provider} disagree on effective_start "
                    f"({primary_effective} vs {secondary_effective})"
                ),
            )
        )

    return notes


def _session_key(session: dict) -> tuple[str, str, str, str, str, str]:
    return (
        str(session.get("day")),
        str(session.get("type")),
        str(session.get("start")),
        str(session.get("end")),
        str(session.get("pool", "")),
        str(session.get("notes", "")),
    )


def _closure_key(closure: dict) -> tuple[str, str, str, str, str]:
    return (
        str(closure.get("start")),
        str(closure.get("end")),
        str(closure.get("reason")),
        str(closure.get("start_time", "")),
        str(closure.get("end_time", "")),
    )
