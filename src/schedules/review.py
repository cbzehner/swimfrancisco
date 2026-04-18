from __future__ import annotations

from collections import Counter

from .models import ReviewFlag


def compare_payloads(
    primary_provider: str,
    primary_payload: dict,
    secondary_provider: str,
    secondary_payload: dict,
) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []

    primary_sessions = Counter(_session_key(session) for session in primary_payload.get("sessions") or [])
    secondary_sessions = Counter(_session_key(session) for session in secondary_payload.get("sessions") or [])
    primary_closures = Counter(_closure_key(closure) for closure in primary_payload.get("closures") or [])
    secondary_closures = Counter(_closure_key(closure) for closure in secondary_payload.get("closures") or [])

    if sum(primary_sessions.values()) != sum(secondary_sessions.values()):
        flags.append(
            ReviewFlag(
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
        flags.append(
            ReviewFlag(
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
        flags.append(
            ReviewFlag(
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
        flags.append(
            ReviewFlag(
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

    return flags


def string_flags(messages: list[str], *, kind: str = "delta", severity: str = "warning") -> list[ReviewFlag]:
    return [ReviewFlag(kind=kind, message=message, severity=severity) for message in messages]


def serialize_flag(flag: ReviewFlag) -> dict:
    return {
        "kind": flag.kind,
        "message": flag.message,
        "severity": flag.severity,
        "evidence": flag.evidence,
    }


def deserialize_flags(raw_flag_details: list | None, raw_messages: list | None = None) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []
    if isinstance(raw_flag_details, list):
        for raw_flag in raw_flag_details:
            if not isinstance(raw_flag, dict):
                continue
            message = raw_flag.get("message")
            kind = raw_flag.get("kind")
            if not isinstance(message, str) or not isinstance(kind, str):
                continue
            severity = raw_flag.get("severity", "warning")
            evidence = raw_flag.get("evidence", {})
            if not isinstance(evidence, dict):
                evidence = {}
            flags.append(
                ReviewFlag(
                    kind=kind,
                    message=message,
                    severity=str(severity),
                    evidence=evidence,
                )
            )
    elif isinstance(raw_messages, list):
        for message in raw_messages:
            if isinstance(message, str):
                flags.append(ReviewFlag(kind="legacy_flag", message=message))
    return flags


def _session_key(session: dict) -> tuple[str, str, str, str]:
    return (
        str(session.get("day")),
        str(session.get("type")),
        str(session.get("start")),
        str(session.get("end")),
    )


def _closure_key(closure: dict) -> tuple[str, str, str]:
    return (
        str(closure.get("start")),
        str(closure.get("end")),
        str(closure.get("reason")),
    )
