from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser

from .._time import pacific_today
from ..models import DAY_ORDER
from .errors import DirectSourceError

_MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _payload(
    schedule_basis: str,
    sessions: list[dict],
    *,
    access_hours: list[dict] | None = None,
    access_exceptions: list[dict] | None = None,
    closures: list[dict] | None = None,
) -> dict:
    return {
        "schedule_basis": schedule_basis,
        "effective_start": pacific_today().isoformat(),
        "sessions": sorted(sessions, key=lambda s: (DAY_ORDER.index(s["day"]), s["start"], s["end"], s["type"])),
        "access_hours": sorted(
            access_hours or [],
            key=lambda a: (DAY_ORDER.index(a["day"]), a["start"], a["end"], a["label"]),
        ),
        "access_exceptions": sorted(
            access_exceptions or [],
            key=lambda a: (a["date"], a["start"], a["end"], a["label"], a["reason"]),
        ),
        "closures": closures or [],
    }


def _weekly_hours_sessions(kind: str, hours: dict[str, tuple[str, str]], *, evidence: str) -> list[dict]:
    return [_session(day, kind, start, end, evidence) for day, (start, end) in hours.items()]


def _session(day: str, kind: str, start: str, end: str, evidence: str) -> dict:
    return {
        "day": day,
        "type": kind,
        "start": start,
        "end": end,
        "evidence": _squash(evidence),
    }


def _access_hour(day: str, start: str, end: str, label: str, evidence: str) -> dict:
    return {
        "day": day,
        "start": start,
        "end": end,
        "label": label,
        "evidence": _squash(evidence),
    }


def _access_exception(date_iso: str, start: str, end: str, label: str, reason: str, evidence: str) -> dict:
    return {
        "date": date_iso,
        "start": start,
        "end": end,
        "label": label,
        "reason": reason,
        "evidence": _squash(evidence),
    }


def _expand_days(value: str) -> list[str]:
    normalized = _squash(value).lower()
    day_names = list(DAY_ORDER)
    aliases = {day[:3]: day for day in day_names}
    parts = [part.strip() for part in re.split(r"\s*-\s*", normalized) if part.strip()]
    if len(parts) == 1:
        return [aliases.get(parts[0][:3], parts[0])]
    if len(parts) == 2:
        start = aliases.get(parts[0][:3])
        end = aliases.get(parts[1][:3])
        if start in DAY_ORDER and end in DAY_ORDER:
            start_i = DAY_ORDER.index(start)
            end_i = DAY_ORDER.index(end)
            if start_i <= end_i:
                return list(DAY_ORDER[start_i : end_i + 1])
    raise DirectSourceError(f"Could not expand day range {value!r}")


def _expand_day_phrase(value: str) -> list[str]:
    normalized = _squash(value).lower().replace("&", " and ")
    normalized = re.sub(r"\s+", " ", normalized)
    if " and " in normalized and "-" not in normalized:
        days: list[str] = []
        for part in normalized.split(" and "):
            days.extend(_expand_days(part))
        return days
    return _expand_days(normalized)


def _parse_hours_range(text: str) -> tuple[str, str]:
    normalized_text = re.sub(r"\bnoon\b", "12pm", text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\bmidnight\b", "12am", normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\ba\.m\.", "am", normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\bp\.m\.", "pm", normalized_text, flags=re.IGNORECASE)
    match = re.search(
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError(f"Could not parse time range from {text!r}")
    start_h, start_m, start_ampm, end_h, end_m, end_ampm = match.groups()
    start = _to_hhmm(int(start_h), int(start_m or "0"), start_ampm)
    end = _to_hhmm(int(end_h), int(end_m or "0"), end_ampm)
    if end == "00:00" and start > end:
        end = "23:59"
    return (start, end)


def _parse_clock_time(text: str) -> str:
    normalized_text = re.sub(r"\ba\.m\.", "am", text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\bp\.m\.", "pm", normalized_text, flags=re.IGNORECASE)
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", normalized_text, flags=re.IGNORECASE)
    if not match:
        raise DirectSourceError(f"Could not parse clock time from {text!r}")
    hour, minute, ampm = match.groups()
    return _to_hhmm(int(hour), int(minute or "0"), ampm)


def _to_hhmm(hour: int, minute: int, ampm: str) -> str:
    normalized = hour % 12
    if ampm.lower() == "pm":
        normalized += 12
    return f"{normalized:02d}:{minute:02d}"


def _shift_hhmm(value: str, *, minutes: int) -> str:
    shifted = datetime.strptime(value, "%H:%M") + timedelta(minutes=minutes)
    return shifted.strftime("%H:%M")


def _resolve_yearless_date(month: int, day: int, today: date | None = None) -> date:
    """Resolve a month/day to an absolute date, rolling to next year when the
    naive same-year resolution would land more than 30 days in the past. Web
    pages frequently list closures by month/day only — a December scrape that
    sees 'January 15' means next January, not last January."""
    if today is None:
        # Imported lazily (rather than bound at module load) so that tests
        # patching `direct_sources.pacific_today` still take effect here.
        from . import pacific_today as _pacific_today

        today = _pacific_today()
    resolved = date(today.year, month, day)
    if (today - resolved).days > 30:
        resolved = date(today.year + 1, month, day)
    return resolved


def _closure_dates_from_text(text: str) -> list[dict]:
    closures: list[dict] = []
    for match in re.finditer(
        r"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+)?"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?\s*-\s*([A-Za-z][^\n.]+)",
        text,
        flags=re.IGNORECASE,
    ):
        month, day, reason = match.groups()
        iso = _resolve_yearless_date(_MONTH_NUMBERS[month.lower()], int(day)).isoformat()
        closures.append({"start": iso, "end": iso, "reason": _squash(reason)})
    return closures


def _closure_dates_from_html_lines(html: str) -> list[dict]:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</(?:p|li|div|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    closures: list[dict] = []
    for line in unescape(text).splitlines():
        closures.extend(_closure_dates_from_text(line))
    return closures


def _html_text(html: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return _squash(unescape(text))


def _require_text(text: str, needle: str) -> None:
    if needle not in text:
        raise DirectSourceError(f"Expected source text not found: {needle}")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


class _PoolScheduleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_pool_table = False
        self.in_row = False
        self.current_cell: dict | None = None
        self.current_row: list[dict] = []
        self.rows: list[list[dict]] = []

    @classmethod
    def from_html(cls, html: str) -> "_PoolScheduleTable":
        parser = cls()
        parser.feed(html)
        return _PoolScheduleTable(parser.rows)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and "PoolSchedule" in (attrs_dict.get("class") or ""):
            self.in_pool_table = True
            return
        if not self.in_pool_table:
            return
        if tag == "tr":
            self.in_row = True
            self.current_row = []
        elif tag in {"th", "td"} and self.in_row:
            self.current_cell = {
                "tag": tag,
                "class": attrs_dict.get("class") or "",
                "rowspan": int(attrs_dict.get("rowspan") or "1"),
                "text": "",
            }

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if not self.in_pool_table:
            return
        if tag in {"th", "td"} and self.current_cell is not None:
            self.current_cell["text"] = _squash(str(self.current_cell["text"]))
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.in_row:
            self.rows.append(self.current_row)
            self.current_row = []
            self.in_row = False
        elif tag == "table":
            self.in_pool_table = False


class _PoolScheduleTable:
    def __init__(self, rows: list[list[dict]]) -> None:
        self.rows = rows

    def day_cells(self) -> list[tuple[str, str]]:
        header = self.rows[0]
        days = [str(cell["text"]).lower() for cell in header]
        active_rowspans: dict[int, int] = {}
        out: list[tuple[str, str]] = []
        for row in self.rows[1:]:
            col = 0
            for cell in row:
                while active_rowspans.get(col, 0) > 0:
                    active_rowspans[col] -= 1
                    if active_rowspans[col] == 0:
                        del active_rowspans[col]
                    col += 1
                if col < len(days):
                    out.append((days[col], str(cell["text"])))
                rowspan = int(cell.get("rowspan") or 1)
                if rowspan > 1:
                    active_rowspans[col] = rowspan - 1
                col += 1
        return out
