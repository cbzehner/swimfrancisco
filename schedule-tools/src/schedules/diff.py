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
                evidence={
                    primary_provider: sum(primary_sessions.values()),
                    secondary_provider: sum(secondary_sessions.values()),
                },
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
                evidence={
                    f"only_{primary_provider}": [list(item) for item in only_primary[:10]],
                    f"only_{secondary_provider}": [list(item) for item in only_secondary[:10]],
                },
            )
        )

    if primary_closures != secondary_closures:
        notes.append(
            ReviewNote(
                kind="provider_closure_diff",
                message=f"{primary_provider} and {secondary_provider} produced different closure sets",
                evidence={
                    primary_provider: [list(item) for item in sorted(primary_closures.elements())],
                    secondary_provider: [list(item) for item in sorted(secondary_closures.elements())],
                },
            )
        )

    primary_effective = primary_payload.get("schedule_effective")
    secondary_effective = secondary_payload.get("schedule_effective")
    if primary_effective != secondary_effective:
        notes.append(
            ReviewNote(
                kind="provider_schedule_effective_diff",
                message=(
                    f"{primary_provider} and {secondary_provider} disagree on schedule_effective "
                    f"({primary_effective} vs {secondary_effective})"
                ),
                evidence={
                    primary_provider: primary_effective,
                    secondary_provider: secondary_effective,
                },
            )
        )

    return notes


def serialize_note(note: ReviewNote) -> dict:
    return {
        "kind": note.kind,
        "message": note.message,
        "severity": note.severity,
        "evidence": note.evidence,
    }


def deserialize_notes(raw_note_details: list | None, raw_messages: list | None = None) -> list[ReviewNote]:
    notes: list[ReviewNote] = []
    if isinstance(raw_note_details, list):
        for raw in raw_note_details:
            if not isinstance(raw, dict):
                continue
            message = raw.get("message")
            kind = raw.get("kind")
            if not isinstance(message, str) or not isinstance(kind, str):
                continue
            severity = raw.get("severity", "warning")
            evidence = raw.get("evidence", {})
            if not isinstance(evidence, dict):
                evidence = {}
            notes.append(
                ReviewNote(
                    kind=kind,
                    message=message,
                    severity=str(severity),
                    evidence=evidence,
                )
            )
    elif isinstance(raw_messages, list):
        for message in raw_messages:
            if isinstance(message, str):
                notes.append(ReviewNote(kind="legacy_note", message=message))
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
