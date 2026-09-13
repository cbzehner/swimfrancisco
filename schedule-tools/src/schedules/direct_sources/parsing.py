from __future__ import annotations

import re
from datetime import date
from html import unescape
from html.parser import HTMLParser

from .. import _time
from ..models import DAY_ORDER, ScheduleBasis
from .errors import DirectSourceError


def decode_source(content: bytes) -> str:
    """Captured bytes are the evidence; text is derived from them leniently so one bad byte cannot fail a whole pool."""
    return content.decode("utf-8", errors="replace")


def _payload(
    schedule_basis: ScheduleBasis,
    sessions: list[dict],
    *,
    access_hours: list[dict] | None = None,
    access_exceptions: list[dict] | None = None,
    closures: list[dict] | None = None,
) -> dict:
    return {
        "schedule_basis": schedule_basis,
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


def _resolve_yearless_date(month: int, day: int, today: date | None = None) -> date:
    """Resolve a month/day to an absolute date, rolling to next year when the
    naive same-year resolution would land more than 30 days in the past. Web
    pages frequently list closures by month/day only — a December scrape that
    sees 'January 15' means next January, not last January."""
    if today is None:
        today = _time.pacific_today()
    resolved = date(today.year, month, day)
    if (today - resolved).days > 30:
        resolved = date(today.year + 1, month, day)
    return resolved


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
    def from_html(cls, html: str) -> _PoolScheduleTable:
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
            if self.current_cell is not None:
                self.handle_endtag(self.current_cell["tag"])
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
            if self.current_cell is not None:
                self.handle_endtag(self.current_cell["tag"])
            self.rows.append(self.current_row)
            self.current_row = []
            self.in_row = False
        elif tag == "table":
            self.in_pool_table = False


class _PoolScheduleTable:
    def __init__(self, rows: list[list[dict]]) -> None:
        self.rows = rows

    def day_cells(self) -> list[tuple[str, str]]:
        if not self.rows:
            raise DirectSourceError("Missing PoolSchedule table")
        header = self.rows[0]
        days = [str(cell["text"]).lower() for cell in header]
        if len(days) != len(set(days)) or any(day not in DAY_ORDER for day in days):
            raise DirectSourceError("Unknown or duplicate PoolSchedule weekdays")
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
                if col >= len(days):
                    raise DirectSourceError("PoolSchedule row exceeds weekday columns")
                out.append((days[col], str(cell["text"])))
                rowspan = int(cell.get("rowspan") or 1)
                if rowspan > 1:
                    active_rowspans[col] = rowspan - 1
                col += 1
            while col < len(days) and active_rowspans.get(col, 0) > 0:
                active_rowspans[col] -= 1
                col += 1
            if col != len(days):
                raise DirectSourceError("Incomplete PoolSchedule row")
        if any(active_rowspans.values()):
            raise DirectSourceError("PoolSchedule rowspan exceeds table")
        return out
