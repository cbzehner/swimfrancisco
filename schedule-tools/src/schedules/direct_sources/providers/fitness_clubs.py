from __future__ import annotations

import re
from datetime import date, timedelta
from html import unescape

from ..._time import pacific_today
from ..errors import DirectSourceError
from ..parsing import (
    _access_hour,
    _expand_days,
    _html_text,
    _parse_hours_range,
    _payload,
    _require_text,
)


def _extract_24_hour_fitness(html: str) -> dict:
    text = _html_text(html)
    if "temporarily closed for renovation" in text.lower():
        match = re.search(r"welcome you back on\s+(\d{2})/(\d{2})/(\d{4})", text, flags=re.IGNORECASE)
        closures: list[dict] = []
        if match:
            month, day, year = match.groups()
            reopen = date(int(year), int(month), int(day))
            end = reopen - timedelta(days=1)
            closures.append({
                "start": pacific_today().isoformat(),
                "end": end.isoformat(),
                "reason": "Temporarily closed for renovation",
            })
        return _payload("temporarily_closed", [], closures=closures)
    _require_text(text, "Gym Hours")
    access_hours: list[dict] = []
    for days_text, hours_text in re.findall(
        r'<span class="ih-days">([^<]+)</span>\s*<span class="ih-hours">([^<]+)</span>',
        html,
        flags=re.IGNORECASE,
    ):
        start, end = _parse_hours_range(unescape(hours_text))
        for day in _expand_days(days_text):
            access_hours.append(_access_hour(day, start, end, "Gym hours", f"{days_text}: {hours_text}"))
    if not access_hours:
        raise DirectSourceError("24 Hour Fitness page did not expose gym hours.")
    return _payload("facility_hours", [], access_hours=access_hours)


def _extract_city_sports(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "SAN FRANCISCO - 20TH AVE")
    _require_text(text, "lap pool")
    match = re.search(
        r"HOURS\s+Mon\s*-\s*Thu\s+([^F]+?)\s+Fri\s+([^S]+?)\s+Sat\s*-\s*Sun\s+(.+?)(?:Special Club Hours|Free pass|Join this club)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("City Sports page did not expose club hours.")
    weekday_hours, friday_hours, weekend_hours = match.groups()
    weekday_start, weekday_end = _parse_hours_range(weekday_hours)
    friday_start, friday_end = _parse_hours_range(friday_hours)
    weekend_start, weekend_end = _parse_hours_range(weekend_hours)
    return _payload("facility_hours", [], access_hours=[
        *[
            _access_hour(day, weekday_start, weekday_end, "Club hours", f"Mon-Thu: {weekday_hours}")
            for day in ("monday", "tuesday", "wednesday", "thursday")
        ],
        _access_hour("friday", friday_start, friday_end, "Club hours", f"Fri: {friday_hours}"),
        _access_hour("saturday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
        _access_hour("sunday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
    ])


def _extract_equinox(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Equinox Sports Club San Francisco")
    _require_text(text, "Indoor Pool")
    matches = re.findall(
        r'"dayOfWeek":\s*\[([^\]]+)\]\s*,\s*"opens":\s*"(\d{2}:\d{2})"\s*,\s*"closes":\s*"(\d{2}:\d{2})"',
        html,
        flags=re.IGNORECASE,
    )
    if not matches:
        raise DirectSourceError("Equinox page did not expose openingHoursSpecification.")
    access_hours: list[dict] = []
    for days_json, start, end in matches:
        for day in re.findall(r'"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"', days_json):
            access_hours.append(_access_hour(day.lower(), start, end, "Club hours", f"{day}: {start}-{end}"))
    return _payload("facility_hours", [], access_hours=access_hours)


def _extract_fitness_sf(html: str) -> dict:
    text = _html_text(html)
    if "fillmore" not in text.lower():
        raise DirectSourceError("Expected source text not found: Fillmore")
    if "pool" not in text.lower():
        raise DirectSourceError("Expected source text not found: pool")
    match = re.search(
        r"Mon\s*-\s*Thu:\s*([^F]+?)\s+Fri:\s*([^S]+?)\s+Sat\s*-\s*Sun:\s*(.+?)(?:\s+1-415|\s+1455|\s+Holiday Hours)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("FITNESS SF page did not expose location hours.")
    weekday_hours, friday_hours, weekend_hours = match.groups()
    weekday_start, weekday_end = _parse_hours_range(weekday_hours)
    friday_start, friday_end = _parse_hours_range(friday_hours)
    weekend_start, weekend_end = _parse_hours_range(weekend_hours)
    return _payload("pool_hours", [], access_hours=[
        *[
            _access_hour(day, weekday_start, weekday_end, "Club hours", f"Mon-Thu: {weekday_hours}")
            for day in ("monday", "tuesday", "wednesday", "thursday")
        ],
        _access_hour("friday", friday_start, friday_end, "Club hours", f"Fri: {friday_hours}"),
        _access_hour("saturday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
        _access_hour("sunday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
    ])


def _extract_sfsu_aquatics(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Natatorium Hours of Operation")
    _require_text(text, "Lap Pool")
    match = re.search(
        r"Natatorium Hours of Operation\s+Mon,\s*Wed,\s*Thur:\s*(.+?)\s+Tue,\s*Fri:\s*(.+?)\s+Saturday/\s*Sunday:\s*Closed",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("SFSU page did not expose natatorium hours in the expected format.")
    monday_wednesday_thursday_hours, tuesday_friday_hours = match.groups()
    monday_wednesday_thursday_start, monday_wednesday_thursday_end = _parse_hours_range(
        monday_wednesday_thursday_hours
    )
    tuesday_friday_start, tuesday_friday_end = _parse_hours_range(tuesday_friday_hours)
    return _payload("pool_hours", [], access_hours=[
        *[
            _access_hour(
                day,
                monday_wednesday_thursday_start,
                monday_wednesday_thursday_end,
                "Natatorium hours",
                f"Mon, Wed, Thur: {monday_wednesday_thursday_hours}",
            )
            for day in ("monday", "wednesday", "thursday")
        ],
        *[
            _access_hour(
                day,
                tuesday_friday_start,
                tuesday_friday_end,
                "Natatorium hours",
                f"Tue, Fri: {tuesday_friday_hours}",
            )
            for day in ("tuesday", "friday")
        ],
    ])
