from __future__ import annotations

import calendar
import re
from collections import Counter
from datetime import date, timedelta
from html import unescape

from ..._time import pacific_today
from ..errors import DirectSourceError
from ..parsing import (
    _PoolScheduleParser,
    _html_text,
    _parse_hours_range,
    _payload,
    _session,
)


def _extract_pomeroy(html: str, *, observed_on: date | None = None) -> dict:
    table = _PoolScheduleParser.from_html(html)
    sessions: list[dict] = []
    for day, text in table.day_cells():
        lower = text.lower()
        if "lap swim" not in lower and "open swim" not in lower:
            continue
        session_type = "lap_swim" if "lap swim" in lower else "family_swim"
        start, end = _parse_hours_range(text)
        sessions.append(_session(day, session_type, start, end, text))
    if not sessions:
        raise DirectSourceError("Pomeroy PoolSchedule table did not yield any sessions.")
    closures, _ = _pomeroy_closures(html, observed_on or pacific_today())
    return _payload("swim_schedule", sessions, closures=closures)


def _pomeroy_closures(html: str, observed_on: date) -> tuple[list[dict], list[dict]]:
    text = _html_text(html)
    blocks = re.findall(r"Upcoming Pool Closure Dates:\s*(.*?)\s*Therapeutic Swimming", text)
    if len(blocks) != 1:
        raise DirectSourceError("Pomeroy closure inventory is missing or duplicated")
    pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
        r"(January|February|March|April|May|June|July|August|September|October|November|December) "
        r"(\d{1,2})(?:st|nd|rd|th)?(?:,? (20\d{2}))?\s*[-–]\s*"
        r"([A-Za-z][A-Za-z ']*?)(?= (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),|$)"
    )
    block = blocks[0]
    matches = list(pattern.finditer(block))
    if not matches or pattern.sub("", block).strip():
        raise DirectSourceError("Unsupported Pomeroy closure notice")
    closures, evidence = [], []
    for match in matches:
        weekday, month, day, year, reason = match.groups()
        if reason not in {"Labor Day", "Memorial Day", "Juneteenth", "Independence Day", "Thanksgiving", "Christmas", "New Year's Day"}:
            raise DirectSourceError("Unsupported Pomeroy closure reason")
        month_number = list(calendar.month_name).index(month)
        years = [int(year)] if year else range(observed_on.year - 1, observed_on.year + 2)
        candidates = [date(value, month_number, int(day)) for value in years]
        relevant = [value for value in candidates if observed_on <= value < observed_on + timedelta(days=14)]
        if any(value.strftime("%A") != weekday for value in relevant):
            raise DirectSourceError("Pomeroy closure weekday conflicts with date")
        if year and candidates[0].strftime("%A") != weekday:
            raise DirectSourceError("Pomeroy closure weekday conflicts with date")
        if len(relevant) > 1:
            raise DirectSourceError("Ambiguous Pomeroy closure year")
        resolved = relevant[0] if relevant else None
        evidence.append({"text": match.group(0), "date": resolved.isoformat() if resolved else None})
        if resolved:
            closures.append({"start": resolved.isoformat(), "end": resolved.isoformat(), "reason": reason, "reason_code": "holiday"})
    return closures, evidence


_POMEROY_RESTRICTIONS = (
    "Slow lap swimming only. Land a closed lane for in-place exercising and resting open lane for general resting and exercising. Please note, this is not for vigorous exercise.",
    "Your own therapy. No lanes, can be 1-on-1 with participants. No Lane Lines are provided during this time. People are encouraged to do their own exercise.",
)


def verify_pomeroy(html: str, payload: dict, observed_on: date) -> dict:
    """Inventory original cells independently of the extracting HTML parser."""
    issues: list[str] = []
    cells: list[dict] = []
    notices: list[dict] = []
    text = _html_text(html)
    for program, restriction in zip(("Lap Swim", "Open Swim"), _POMEROY_RESTRICTIONS):
        sections = re.findall(re.escape(program) + r" (.*?) 1 Swim Pass", text)
        if sections != [restriction]:
            issues.append(f"Changed or missing {program} therapeutic restrictions")
    for attributes, label in re.findall(r"<a\b([^>]*)>(.*?)</a>", html, re.S | re.I):
        href = re.search(r"\bhref\s*=\s*([\"'])(.*?)\1", attributes, re.S | re.I)
        if href is None:
            continue
        target = unescape(href.group(2))
        description = target + " " + _html_text(label)
        if re.search(r"schedule|timetable|docs\.google\.com/(?:spreadsheets|sheets)", description, re.I):
            issues.append("Pomeroy page links an unsupported separate schedule source")
    remaining = re.sub(r"Upcoming Pool Closure Dates:.*?Therapeutic Swimming", "", text)
    for restriction in _POMEROY_RESTRICTIONS:
        remaining = remaining.replace(restriction, "")
    if re.search(r"\b(?:closed|closure|cancelled|canceled|unavailable|restricted|reservations?|required|members only|appointments?|booking|compulsory|effective|valid (?:through|until|from)|schedule (?:ends?|ending)|expires?|expiry)\b", remaining, re.I):
        issues.append("Unsupported Pomeroy closure or access restriction outside known sections")
    try:
        tables = re.findall(r'<table\b[^>]*class=["\'][^"\']*\bPoolSchedule\b[^"\']*["\'][^>]*>(.*?)</table>', html, re.S | re.I)
        if len(tables) != 1:
            raise DirectSourceError("Expected one Pomeroy schedule table")
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tables[0], re.S | re.I)
        if len(rows) < 2:
            raise DirectSourceError("Missing Pomeroy schedule rows")
        days = [_html_text(value).lower() for value in re.findall(r"<th\b[^>]*>(.*?)</th>", rows[0], re.S | re.I)]
        if days != ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]:
            raise DirectSourceError("Unsupported Pomeroy weekday inventory")
        occupied: set[tuple[int, int]] = set()
        expected = []
        for row_index, row in enumerate(rows[1:]):
            column = 0
            for attributes, inner in re.findall(r"<td\b([^>]*)>(.*?)(?=</td>|<td\b|$)", row, re.S | re.I):
                while (row_index, column) in occupied:
                    column += 1
                if column >= len(days) or re.search(r"\bcolspan\s*=", attributes, re.I):
                    raise DirectSourceError("Unsupported Pomeroy table columns")
                span_match = re.search(r'\browspan=["\'](\d+)["\']', attributes)
                span = int(span_match.group(1)) if span_match else 1
                if not 1 <= span <= len(rows) - 1 - row_index:
                    raise DirectSourceError("Invalid Pomeroy rowspan")
                for offset in range(span):
                    occupied.add((row_index + offset, column))
                evidence = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", inner))).strip()
                if evidence:
                    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?(am|pm)\s*(Lap Swim|Open Swim|Aquatic Exercise)", evidence)
                    if not match:
                        raise DirectSourceError(f"Unsupported Pomeroy cell: {evidence}")
                    first, minutes, period, last, end_minutes, end_period, program = match.groups()
                    def clock(hour: str, minute: str | None, meridiem: str) -> str:
                        if not 1 <= int(hour) <= 12 or not 0 <= int(minute or 0) < 60:
                            raise DirectSourceError("Invalid Pomeroy cell time")
                        return f"{int(hour) % 12 + (12 if meridiem == 'pm' else 0):02d}:{int(minute or 0):02d}"
                    start, end = clock(first, minutes, period), clock(last, end_minutes, end_period)
                    if end <= start:
                        raise DirectSourceError("Invalid Pomeroy cell duration")
                    kind = {"Lap Swim": "lap_swim", "Open Swim": "family_swim", "Aquatic Exercise": None}[program]
                    cells.append({"row": row_index + 1, "day": days[column], "program": program, "start": start, "end": end, "evidence": evidence, "included": kind is not None})
                    if kind:
                        expected.append((days[column], kind, start, end, evidence))
                column += 1
            if any((row_index, value) not in occupied for value in range(len(days))):
                raise DirectSourceError("Incomplete Pomeroy table row")
        if any(set(value) != {"day", "type", "start", "end", "evidence"} for value in payload.get("sessions", [])):
            issues.append("Pomeroy sessions contain unsupported fields")
        actual = [(value.get("day"), value.get("type"), value.get("start"), value.get("end"), value.get("evidence")) for value in payload.get("sessions", [])]
        if Counter(actual) != Counter(expected) or len(expected) != len(set(expected)):
            issues.append("Pomeroy session inventory differs from original cells")
        closures, notices = _pomeroy_closures(html, observed_on)
        if payload.get("closures", []) != closures:
            issues.append("Pomeroy closure inventory differs from original notices")
        if payload.get("schedule_basis") != "swim_schedule" or payload.get("access_hours") or payload.get("access_exceptions"):
            issues.append("Pomeroy payload has unsupported schedule basis")
    except (DirectSourceError, ValueError) as error:
        issues.append(str(error))
    return {"ok": not issues, "issues": issues, "restrictions": list(_POMEROY_RESTRICTIONS), "cells": cells, "closure_notices": notices}
