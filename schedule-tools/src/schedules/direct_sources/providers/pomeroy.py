from __future__ import annotations

from ..errors import DirectSourceError
from ..parsing import (
    _PoolScheduleParser,
    _closure_dates_from_html_lines,
    _parse_hours_range,
    _payload,
    _session,
)


def _extract_pomeroy(html: str) -> dict:
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
    return _payload("swim_schedule", sessions, closures=_closure_dates_from_html_lines(html))
