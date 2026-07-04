from __future__ import annotations

import csv
import re
from datetime import timedelta
from io import StringIO

from ..._time import pacific_today
from ...models import DAY_ORDER
from ..errors import DirectSourceError
from ..parsing import (
    _parse_clock_time,
    _parse_hours_range,
    _payload,
    _session,
    _shift_hhmm,
    _squash,
    _weekly_hours_sessions,
)


def _extract_koret(text: str) -> dict:
    sessions: list[dict] = []
    closures: list[dict] = []
    for sheet_name, csv_text in _split_koret_sheets(text).items():
        rows = list(csv.reader(StringIO(csv_text)))
        time_range = _koret_sheet_time_range(sheet_name, rows)
        if time_range is None:
            closure = _koret_closed_sheet_closure(sheet_name, rows)
            if closure is not None:
                closures.append(closure)
            continue
        start, end, evidence = time_range
        if sheet_name == "Weekend":
            weekend_hours = {"saturday": (start, end)}
            if evidence != "Saturday time grid":
                weekend_hours["sunday"] = (start, end)
            sessions.extend(_weekly_hours_sessions(
                "lap_swim",
                weekend_hours,
                evidence=evidence,
            ))
            continue
        sessions.append(_session(sheet_name.lower(), "lap_swim", start, end, evidence))
    return _payload("pool_hours", sessions, closures=closures)


def _koret_sheet_time_range(sheet_name: str, rows: list[list[str]]) -> tuple[str, str, str] | None:
    for row in rows:
        evidence = " ".join(cell for cell in row if cell).strip()
        if not evidence or "hours" not in evidence.lower():
            continue
        try:
            start, end = _parse_hours_range(evidence)
        except DirectSourceError:
            continue
        return start, end, evidence

    if sheet_name != "Weekend":
        return None

    return _koret_weekend_time_grid(rows)


def _koret_weekend_time_grid(rows: list[list[str]]) -> tuple[str, str, str] | None:
    starts: list[str] = []
    for row in rows:
        if any(cell.strip().lower() == "sunday" for cell in row):
            break
        first_cell = row[0].strip() if row else ""
        if first_cell:
            try:
                starts.append(_parse_clock_time(first_cell))
            except DirectSourceError:
                pass
    if not starts:
        return None
    return starts[0], _shift_hhmm(starts[-1], minutes=60), "Saturday time grid"


def _koret_closed_sheet_closure(sheet_name: str, rows: list[list[str]]) -> dict | None:
    if sheet_name.lower() not in DAY_ORDER:
        return None
    for row in rows:
        evidence = " ".join(cell for cell in row if cell).strip()
        match = re.search(r"\bclosed\s+(.+)", evidence, flags=re.IGNORECASE)
        if not match:
            continue
        today = pacific_today()
        weekday = DAY_ORDER.index(sheet_name.lower())
        days_until = (weekday - today.weekday()) % 7
        closed_date = today + timedelta(days=days_until)
        return {
            "start": closed_date.isoformat(),
            "end": closed_date.isoformat(),
            "reason": _squash(match.group(1)),
        }
    return None


def _split_koret_sheets(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        marker = re.fullmatch(r"--- (.+) ---", line.strip())
        if marker:
            current = marker.group(1)
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in out.items() if lines}
