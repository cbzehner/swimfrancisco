from __future__ import annotations

from datetime import date
from typing import get_args

from .models import ScheduleBasis, ValidationResult, Violation

_VALID_SCHEDULE_BASES = frozenset(get_args(ScheduleBasis))


def validate(payload: dict, *, prior_sessions_count: int | None = None) -> ValidationResult:
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
    closures = payload.get("closures") if isinstance(payload.get("closures"), list) else []
    access_hours = payload.get("access_hours") if isinstance(payload.get("access_hours"), list) else []
    access_exceptions = payload.get("access_exceptions") if isinstance(payload.get("access_exceptions"), list) else []
    violations: list[Violation] = []
    catastrophic = False
    schedule_basis = payload.get("schedule_basis")

    if schedule_basis is not None and schedule_basis not in _VALID_SCHEDULE_BASES:
        violations.append(Violation(
            code="invalid_schedule_basis",
            message=f"schedule_basis must be one of: {', '.join(sorted(_VALID_SCHEDULE_BASES))}",
        ))

    if prior_sessions_count and len(sessions) == 0:
        violations.append(Violation(
            code="sessions_dropped_to_zero",
            message="sessions_count dropped to 0 from a previously non-zero state",
        ))
        catastrophic = True

    if len(sessions) < 5 and not access_hours and schedule_basis not in {"amenity_only", "temporarily_closed", "unknown"}:
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

    for index, access_hour in enumerate(access_hours, start=1):
        start = access_hour.get("start")
        end = access_hour.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or start >= end:
            violations.append(Violation(
                code="invalid_session_time_range",
                message=f"access_hour #{index} has an invalid time range",
            ))

    for index, access_exception in enumerate(access_exceptions, start=1):
        exception_date = access_exception.get("date")
        try:
            if not isinstance(exception_date, str):
                raise ValueError("date must be a string")
            date.fromisoformat(exception_date)
        except ValueError:
            violations.append(Violation(
                code="invalid_access_exception_date",
                message=f"access_exception #{index} has an invalid date",
            ))

        start = access_exception.get("start")
        end = access_exception.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or start >= end:
            violations.append(Violation(
                code="invalid_access_exception_time_range",
                message=f"access_exception #{index} has an invalid time range",
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

    effective_start = payload.get("effective_start")
    try:
        if not isinstance(effective_start, str):
            raise ValueError("effective_start must be a string")
        date.fromisoformat(effective_start)
    except ValueError:
        violations.append(Violation(
            code="invalid_schedule_effective_date",
            message="effective_start is not a valid ISO date",
        ))

    return ValidationResult(
        ok=not violations,
        violations=violations,
        stats={
            "sessions": len(sessions),
            "closures": len(closures),
            "access_hours": len(access_hours),
            "access_exceptions": len(access_exceptions),
        },
        catastrophic=catastrophic,
    )
