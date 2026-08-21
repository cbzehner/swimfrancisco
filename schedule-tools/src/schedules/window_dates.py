from __future__ import annotations

import re
from datetime import date
from typing import Literal

WindowSource = Literal["page-1", "anchor", "filename"]

# Full names plus the Rec & Park filename aliases (sep/sept → september).
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=lambda name: (-len(name), name)))
# No leading lookbehind on the second month: Aug18toDec26 has no break before Dec.
_MONTH_NAME = rf"({_MONTH_ALT})(?![a-z])"
_MONTH_TOKEN = rf"(?<![a-z]){_MONTH_NAME}"
_YEAR_RE = re.compile(r"20\d{2}")
_MD_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2})-(\d{1,2})_(\d{1,2})-(\d{1,2})"
)
_ORDINAL = r"(?:st|nd|rd|th)?"
# Rec & Park page-1 titles use hyphen/en-dash, not only "to" (August 18- December 12).
_CROSS_MONTH_RE = re.compile(
    rf"(?i){_MONTH_TOKEN}\s*(\d{{1,2}}){_ORDINAL}\s*(?:_to|to|_|[–—-])\s*"
    rf"{_MONTH_NAME}\s*(\d{{1,2}}){_ORDINAL}"
)
_SAME_MONTH_RE = re.compile(
    rf"(?i){_MONTH_TOKEN}\s*(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}})"
)
_PAGE1_LINE_LIMIT = 40


def parse_window_dates(
    *,
    page_text: str | None,
    anchor_text: str | None,
    filename: str | None,
    year_default: int,
) -> tuple[date, date] | None:
    """First successful parse wins: page-1 header, then anchor, then filename."""
    parsed = parse_window_with_source(
        page_text=page_text,
        anchor_text=anchor_text,
        filename=filename,
        year_default=year_default,
    )
    if parsed is None:
        return None
    start, end, _source = parsed
    return start, end


def parse_window_with_source(
    *,
    page_text: str | None,
    anchor_text: str | None,
    filename: str | None,
    year_default: int,
) -> tuple[date, date, WindowSource] | None:
    sources: tuple[tuple[WindowSource, str | None], ...] = (
        ("page-1", _page1_header(page_text)),
        ("anchor", anchor_text),
        ("filename", filename),
    )
    for source, text in sources:
        parsed = _parse_window_text(text, year_default)
        if parsed is not None:
            return parsed[0], parsed[1], source
    return None


def _page1_header(page_text: str | None) -> str:
    if not page_text:
        return ""
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    return "\n".join(lines[:_PAGE1_LINE_LIMIT])


def _parse_window_text(text: str | None, year_default: int) -> tuple[date, date] | None:
    if not text:
        return None
    hits: list[tuple[int, date, date]] = []
    for match in _MD_RANGE_RE.finditer(text):
        parsed = _dates_from_match(
            match,
            text,
            year_default,
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
        )
        if parsed is not None:
            hits.append((match.start(), *parsed))
    for match in _CROSS_MONTH_RE.finditer(text):
        parsed = _dates_from_match(
            match,
            text,
            year_default,
            _MONTHS[match.group(1).lower()],
            int(match.group(2)),
            _MONTHS[match.group(3).lower()],
            int(match.group(4)),
        )
        if parsed is not None:
            hits.append((match.start(), *parsed))
    for match in _SAME_MONTH_RE.finditer(text):
        month = _MONTHS[match.group(1).lower()]
        parsed = _dates_from_match(
            match,
            text,
            year_default,
            month,
            int(match.group(2)),
            month,
            int(match.group(3)),
        )
        if parsed is not None:
            hits.append((match.start(), *parsed))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0])
    return hits[0][1], hits[0][2]


def _dates_from_match(
    match: re.Match[str],
    text: str,
    year_default: int,
    start_month: int,
    start_day: int,
    end_month: int,
    end_day: int,
) -> tuple[date, date] | None:
    year = _year_for_match(match, text, year_default)
    try:
        start = date(year, start_month, start_day)
        end = date(year, end_month, end_day)
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def _year_for_match(match: re.Match[str], text: str, year_default: int) -> int:
    in_token = _YEAR_RE.search(match.group(0))
    if in_token:
        return int(in_token.group(0))
    start, end = match.span()
    best: tuple[int, int, int] | None = None
    for year_match in _YEAR_RE.finditer(text):
        ys, ye = year_match.span()
        if ye <= start:
            dist, side = start - ye, 1
        elif ys >= end:
            dist, side = ys - end, 0
        else:
            dist, side = 0, 0
        candidate = (dist, side, int(year_match.group(0)))
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best is not None else year_default
