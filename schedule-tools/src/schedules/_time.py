from __future__ import annotations

from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def pacific_today() -> date:
    return datetime.now(PACIFIC_TZ).date()


def printed_time_range(start: str, end: str) -> tuple[str, str]:
    def clock(value: str) -> tuple[int, bool]:
        value = re.sub(r"[\s.]", "", value.lower())
        value = re.sub(r"(?<=\d)([ap])$", r"\1m", value)
        if value in {"noon", "midnight"}:
            return (720 if value == "noon" else 0), True
        match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?([ap]m)?", value)
        if not match:
            raise ValueError("unsupported clock time")
        hour, minute, meridiem = match.groups()
        hour, minute = int(hour), int(minute or 0)
        if minute > 59 or hour > 23 or (meridiem and not 1 <= hour <= 12):
            raise ValueError("invalid clock time")
        if meridiem:
            return (hour % 12 + (12 if meridiem == "pm" else 0)) * 60 + minute, True
        return hour * 60 + minute, hour > 12 or hour == 0

    first, first_explicit = clock(start)
    last, last_explicit = clock(end)
    if not last_explicit:
        afternoon_start = first_explicit and bool(re.search(r"p\.?m\.?\s*$", start, re.IGNORECASE))
        afternoon_end = last % 720 + 720
        if not afternoon_start or not 1 <= last // 60 <= 12 or afternoon_end <= first:
            raise ValueError("time range has no explicit end meridiem")
        last = afternoon_end
    if not first_explicit:
        candidates = [first % 720, first % 720 + 720]
        candidates = [value for value in candidates if 0 < (last or 1440) - value <= 720]
        if len(candidates) != 1:
            raise ValueError("ambiguous time range")
        first = candidates[0]
    if last == 0 and first > 0:
        last = 1439
    if not first < last:
        raise ValueError("time range must end after its start")
    return tuple(f"{value // 60:02d}:{value % 60:02d}" for value in (first, last))
