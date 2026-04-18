from __future__ import annotations

from datetime import date

from .models import ValidationResult


def validate(payload: dict) -> ValidationResult:
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
    closures = payload.get("closures") if isinstance(payload.get("closures"), list) else []
    violations: list[str] = []

    if len(sessions) < 5:
        violations.append("fewer than 5 weekly sessions extracted")

    for index, session in enumerate(sessions, start=1):
        start = session.get("start")
        end = session.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or start >= end:
            violations.append(f"session #{index} has an invalid time range")

    for index, closure in enumerate(closures, start=1):
        start = closure.get("start")
        end = closure.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or start > end:
            violations.append(f"closure #{index} has an invalid date range")

    schedule_effective = payload.get("schedule_effective")
    try:
        if not isinstance(schedule_effective, str):
            raise ValueError("schedule_effective must be a string")
        date.fromisoformat(schedule_effective)
    except ValueError:
        violations.append("schedule_effective is not a valid ISO date")

    return ValidationResult(
        ok=not violations,
        violations=violations,
        stats={"sessions": len(sessions), "closures": len(closures)},
    )

