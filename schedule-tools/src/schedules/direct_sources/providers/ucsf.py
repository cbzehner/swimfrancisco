from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from ...models import DAY_ORDER
from ..errors import DirectSourceError
from ..parsing import _access_hour, _html_text, _parse_hours_range, _payload


def _holiday_error(message: str, text: str) -> DirectSourceError:
    from ..html_facts import HtmlClosureReviewRequired
    return HtmlClosureReviewRequired(message, {"lines": [{"id": "ucsf-calendar-notice",
        "section": "Holiday Hours", "scope": "facility", "text": text}]})


def _hours(text: str) -> tuple[str, str]:
    if not re.fullmatch(r"(?:[1-9]|1[0-2]):[0-5][0-9] (?:am|pm)-(?:[1-9]|1[0-2]):[0-5][0-9] (?:am|pm)", text):
        raise DirectSourceError("Unsupported UCSF hours or extra scope text")
    return _parse_hours_range(text)


def _extract_ucsf(html: str, facility: str, observed_on: date) -> dict:
    bodies = re.findall(r'<div[^>]*class="[^"]*field--name-body[^\"]*"[^>]*>(.*?)</div>', html, flags=re.S)
    if len(bodies) != 1:
        raise DirectSourceError("UCSF source must contain one complete holiday schedule")
    outside = _html_text(re.sub(r'<div[^>]*class="[^\"]*field--name-body[^\"]*"[^>]*>.*?</div>', "", html, flags=re.S))
    if re.search(r"\b(?:closed|closures?|maintenance|training|reopen(?:ing)?|(?:changed|modified|reduced|special) hours)\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", outside, re.I):
        raise _holiday_error("UCSF notice outside the calendar requires review", outside)
    paragraphs = re.findall(r'<p\b[^>]*>(.*?)</p>', bodies[0], flags=re.S)
    if _html_text(re.sub(r'<p\b[^>]*>.*?</p>', '', bodies[0], flags=re.S)):
        raise DirectSourceError("Unsupported UCSF schedule content outside its rows")
    rows = [_html_text(row) for row in paragraphs]
    header = re.fullmatch(r'UCSF Fitness and Recreation Centers are observing the (20\d{2}) holiday schedule listed below:', rows[0] if rows else '')
    if not header or len(rows) != 19:
        raise DirectSourceError("UCSF holiday schedule identity or row completeness changed")
    year = int(header[1])
    regular = [_html_text(part) for part in re.split(r'<br\s*/?>', paragraphs[1])]
    if len(regular) != 4 or regular[0] != 'Regular Hours':
        raise DirectSourceError("UCSF regular hours groups changed")
    expected = [('Monday-Friday', 'Bakar and Millberry'), ('Saturday-Sunday', 'Bakar'), ('Saturday-Sunday', 'Millberry')]
    hours = []
    for row, (days, scope) in zip(regular[1:], expected, strict=True):
        match = re.fullmatch(rf'{days} (.+) \({scope}\)', row)
        if not match:
            raise DirectSourceError("UCSF hours have missing days or conflicting facility scope")
        start, end = _hours(match[1])
        if start >= end:
            raise DirectSourceError("UCSF hours must end after opening")
        if facility in scope:
            selected = DAY_ORDER[:5] if days == 'Monday-Friday' else DAY_ORDER[5:]
            hours.extend(_access_hour(day, start, end, 'Facility hours', row) for day in selected)
    coverage_start, coverage_end = date(year, 1, 1), date(year + 1, 1, 1)
    if not coverage_start <= observed_on <= coverage_end:
        raise DirectSourceError("UCSF printed schedule does not cover the observation date")
    end = min(observed_on + timedelta(days=13), coverage_end)
    closures, exceptions, seen = [], [], set()
    previous = None
    for index, raw in enumerate(rows[2:]):
        row = raw.removesuffix(' Note: Schedule is subject to change.')
        match = re.fullmatch(r'([A-Z][a-z]+) (\d{1,2})(?:-(\d{1,2}))? \(([^()]+)\): (.+)', row)
        if not match:
            raise _holiday_error("Unsupported UCSF holiday row or scope", row)
        month, first, last, holiday, action = match.groups()
        printed = re.match(r'(20\d{2}) ', holiday)
        row_year = int(printed[1]) if printed else year
        try:
            month_number = list(calendar.month_name).index(month)
            first_date = date(row_year, month_number, int(first))
            last_date = date(row_year, month_number, int(last or first))
        except ValueError as error:
            raise _holiday_error("Invalid UCSF printed holiday date", row) from error
        if (first_date > last_date or first_date < coverage_start or last_date > coverage_end
                or previous is not None and first_date <= previous):
            raise _holiday_error("UCSF holiday dates duplicate, conflict, or exceed printed coverage", row)
        previous = last_date
        if index == 0 and first_date != coverage_start or index == 16 and last_date != coverage_end:
            raise DirectSourceError("UCSF calendar endpoints are missing")
        window = None
        if action not in {'Closed', 'Open Regular Hours'}:
            try:
                window = _hours(action)
            except DirectSourceError as error:
                raise _holiday_error(str(error), row) from error
            if window[0] >= window[1]:
                raise DirectSourceError("Invalid UCSF holiday opening range")
        for offset in range((last_date - first_date).days + 1):
            current = first_date + timedelta(days=offset)
            if current in seen:
                raise DirectSourceError("Duplicate UCSF holiday date")
            seen.add(current)
            if window:
                regular_hours = next(item for item in hours if item["day"] == DAY_ORDER[current.weekday()])
                if window[0] < regular_hours["start"] or window[1] > regular_hours["end"]:
                    raise _holiday_error("UCSF holiday hours exceed regular facility bounds", row)
            if not observed_on <= current <= end:
                continue
            if action == 'Closed':
                closures.append({'start': current.isoformat(), 'end': current.isoformat(),
                    'reason': row, 'reason_code': 'holiday', 'source_notices': [{'id': f'holiday-{index + 1}', 'text': row}]})
            elif window:
                exceptions.append({'date': current.isoformat(), 'start': window[0], 'end': window[1],
                    'label': 'Holiday facility hours', 'reason': row, 'evidence': row})
    return _payload('facility_hours', [], access_hours=hours, access_exceptions=exceptions, closures=closures) | {
        'effective_start': observed_on.isoformat(), 'effective_end': end.isoformat()}


def _extract_ucsf_fitness(html: str, observed_on: date) -> dict:
    return _extract_ucsf(html, 'Millberry', observed_on)


def _extract_ucsf_bakar(html: str, observed_on: date) -> dict:
    return _extract_ucsf(html, 'Bakar', observed_on)
