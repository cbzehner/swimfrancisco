from __future__ import annotations

import re

from ...models import DAY_ORDER
from ..errors import DirectSourceError
from ..parsing import (
    _MONTH_NUMBERS,
    _access_exception,
    _access_hour,
    _closure_dates_from_text,
    _expand_day_phrase,
    _expand_days,
    _html_text,
    _parse_clock_time,
    _parse_hours_range,
    _payload,
    _require_text,
    _resolve_yearless_date,
    _shift_hhmm,
    _squash,
)


def _extract_ymca_location(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Hours")
    access_hours = _extract_ymca_facility_hours(html, label="Facility hours")
    basis = "facility_hours"
    access_exceptions = _extract_ymca_holiday_access_exceptions(html, basis=basis)
    if "Pool Hours Opens 30 min after, closes 30 min before facility" in text:
        basis = "pool_hours"
        access_hours = _ymca_pool_hours_from_facility_hours(access_hours)
        access_exceptions = _extract_ymca_holiday_access_exceptions(html, basis=basis)
    if not access_hours:
        raise DirectSourceError("YMCA page did not expose location hours.")
    return _payload(
        basis,
        [],
        access_hours=access_hours,
        access_exceptions=access_exceptions,
        closures=_closure_dates_from_text(text),
    )


def _ymca_pool_hours_from_facility_hours(access_hours: list[dict]) -> list[dict]:
    return [
        _access_hour(
            access_hour["day"],
            _shift_hhmm(access_hour["start"], minutes=30),
            _shift_hhmm(access_hour["end"], minutes=-30),
            "Pool hours",
            "Pool opens 30 min after, closes 30 min before facility",
        )
        for access_hour in access_hours
    ]


def _extract_first_day_hour_block(html: str, *, label: str) -> list[dict]:
    access_hours: list[dict] = []
    seen_days: set[str] = set()
    for day, hours in re.findall(
        r"<span>\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*</span>\s*<span>\s*([^<]+)\s*</span>",
        html,
        flags=re.IGNORECASE,
    ):
        day_key = day.lower()
        if day_key in seen_days:
            break
        seen_days.add(day_key)
        clean_hours = _squash(hours)
        if clean_hours.lower() != "closed":
            start, end = _parse_hours_range(clean_hours)
            access_hours.append(_access_hour(day_key, start, end, label, f"{day}: {clean_hours}"))
        if len(seen_days) == 7:
            break
    return access_hours


def _extract_ymca_facility_hours(html: str, *, label: str) -> list[dict]:
    match = re.search(
        r"<h2>\s*Facility Hours\s*</h2>(.*?)(?:<h4>\s*Contact\s*</h4>|<h2>\s*Holiday Hours\s*</h2>)",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return _extract_first_day_hour_block(html, label=label)
    block = match.group(1)
    access_hours: list[dict] = []
    for days, hours in re.findall(
        r"<span>\s*([^<]*?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[^<]*?)\s*</span>\s*<span>\s*([^<]+)\s*</span>",
        block,
        flags=re.IGNORECASE,
    ):
        clean_hours = _squash(hours)
        if clean_hours.lower() == "closed":
            continue
        start, end = _parse_hours_range(clean_hours)
        for day in _expand_day_phrase(days):
            access_hours.append(_access_hour(day, start, end, label, f"{days}: {clean_hours}"))
    return sorted(access_hours, key=lambda a: (DAY_ORDER.index(a["day"]), a["start"], a["end"]))


def _extract_ymca_holiday_access_exceptions(html: str, *, basis: str) -> list[dict]:
    blocks = [
        _html_text(match.group(1))
        for match in re.finditer(
            r"<h[1-6][^>]*>\s*Holiday Hours\s*</h[1-6]>(.{0,1400})",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    if not blocks:
        return []
    pattern = (
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*,?\s*"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*"
        r"\(([^)]+)\)\s*"
        r"(?P<facility_hours>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)\s*[-–]\s*"
        r"\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm))"
        r"(?:\s*Pool Hours:\s*"
        r"(?P<pool_hours>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)\s*[-–]\s*"
        r"\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)))?"
        r"(?:\s*Pool Closes at\s*"
        r"(?P<pool_closes>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)))?"
    )
    exceptions: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for text in blocks:
        for holiday in re.finditer(pattern, text, flags=re.IGNORECASE):
            month = holiday.group(1)
            day = holiday.group(2)
            reason = holiday.group(3)
            facility_hours = holiday.group("facility_hours")
            pool_hours = holiday.group("pool_hours")
            pool_closes = holiday.group("pool_closes")
            start, end = _parse_hours_range(pool_hours or facility_hours)
            label = "Holiday facility hours"
            if basis == "pool_hours":
                label = "Holiday pool hours"
                if not pool_hours:
                    start = _shift_hhmm(start, minutes=30)
                    end = _parse_clock_time(pool_closes) if pool_closes else _shift_hhmm(end, minutes=-30)
            date_iso = _resolve_yearless_date(_MONTH_NUMBERS[month.lower()], int(day)).isoformat()
            key = (date_iso, start, end, label, reason)
            if key in seen:
                continue
            seen.add(key)
            exceptions.append(_access_exception(date_iso, start, end, label, reason, holiday.group(0)))
    return exceptions
