from __future__ import annotations

from datetime import date

from .models import ValidationResult, Violation


def validate(payload: dict, *, prior_sessions_count: int | None = None) -> ValidationResult:
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
    closures = payload.get("closures") if isinstance(payload.get("closures"), list) else []
    violations: list[Violation] = []
    catastrophic = False

    if prior_sessions_count and len(sessions) == 0:
        violations.append(Violation(
            code="sessions_dropped_to_zero",
            message="sessions_count dropped to 0 from a previously non-zero state",
        ))
        catastrophic = True

    if len(sessions) < 5:
        violations.append(Violation(
            code="too_few_weekly_sessions",
            message="fewer than 5 weekly sessions extracted",
        ))

    for index, session in enumerate(sessions, start=1):
        start = session.get("start")
        end = session.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or start >= end:
            violations.append(Violation(
                code="invalid_session_time_range",
                message=f"session #{index} has an invalid time range",
            ))

    for index, closure in enumerate(closures, start=1):
        start = closure.get("start")
        end = closure.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or start > end:
            violations.append(Violation(
                code="invalid_closure_date_range",
                message=f"closure #{index} has an invalid date range",
            ))
            continue

        start_time = closure.get("start_time")
        end_time = closure.get("end_time")
        if start_time is None and end_time is None:
            continue
        if start_time is None or end_time is None:
            violations.append(Violation(
                code="incomplete_closure_time_range",
                message=f"closure #{index} must have both start_time and end_time when either is present",
            ))
            continue
        if not isinstance(start_time, str) or not isinstance(end_time, str) or start_time >= end_time:
            violations.append(Violation(
                code="invalid_closure_time_range",
                message=f"closure #{index} has an invalid time range",
            ))
            continue
        if start != end:
            violations.append(Violation(
                code="multi_day_closure_with_time_range",
                message=f"closure #{index} cannot have start_time/end_time on a multi-day range; expand to one entry per day",
            ))

    schedule_effective = payload.get("schedule_effective")
    try:
        if not isinstance(schedule_effective, str):
            raise ValueError("schedule_effective must be a string")
        date.fromisoformat(schedule_effective)
    except ValueError:
        violations.append(Violation(
            code="invalid_schedule_effective_date",
            message="schedule_effective is not a valid ISO date",
        ))

    return ValidationResult(
        ok=not violations,
        violations=violations,
        stats={"sessions": len(sessions), "closures": len(closures)},
        catastrophic=catastrophic,
    )

