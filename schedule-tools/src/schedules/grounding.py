from __future__ import annotations

import re
import calendar
from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from ._time import printed_time_range
from .models import GroundingResult, SessionGrounding
from .schema import pool_label_payload
from .signals import DAY_TOKEN_RE, PdfSource, SourceCell, SourceNotice, TIME_RANGE_RE, CLOSURE_TOKEN_RE, program_types, north_beach_pool_identity
from .window_dates import parse_window_dates


@dataclass(frozen=True)
class SourceSlot:
    cell: SourceCell
    type: str
    start: str
    end: str
    pool: str | None

    @property
    def key(self) -> tuple:
        return self.cell.day, self.type, self.start, self.end, self.pool


def _cell_pool(cell: SourceCell, time_match) -> str | None:
    labels = [label.strip() for label in re.findall(r"\(([^()]*)\)", cell.text)]
    labels = [label for label in labels if not re.fullmatch(r"\d+\s*(?:lanes?)?", label, re.IGNORECASE)
              and not re.search(r"\b(?:closed|until)\b|\d+/\d+", label, re.IGNORECASE)]
    tail = cell.text[time_match.end():].strip()
    if re.fullmatch(r"[A-Z](?:/[A-Z])*", tail):
        labels.append(tail)
    normalized = {pool_label_payload({"sessions": [{"pool_label_raw": label}]})["sessions"][0].get("pool")
                  for label in labels}
    normalized.discard(None)
    if len(normalized) > 1:
        raise ValueError(f"{cell.id}:ambiguous_pool_allocation")
    return next(iter(normalized), None)


def source_slots(source: PdfSource) -> tuple[SourceSlot, ...]:
    slots = []
    for cell in source.cells:
        types = program_types(re.sub(r"\([^()]*\)", "", cell.text) if north_beach_pool_identity(source.text) else cell.text)
        if not types:
            continue
        ranges = list(TIME_RANGE_RE.finditer(cell.text))
        if len(ranges) != 1:
            raise ValueError(f"{cell.id}:ambiguous_program_times")
        time_match = ranges[0]
        start, end = printed_time_range(time_match["start"], time_match["end"])
        pool = _cell_pool(cell, time_match)
        for kind in types:
            override = re.search(r"\blap\s+(?:swim\s+)?until\s+(\d{1,2}(?::\d{2})?\s*[ap]m)", cell.text, re.IGNORECASE)
            slot_end = printed_time_range(time_match["start"], override[1])[1] if kind == "lap_swim" and override else end
            slots.append(SourceSlot(cell, kind, start, slot_end, pool))
    keys = [slot.key for slot in slots]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_source_slots")
    return tuple(slots)


def source_coverage(source: PdfSource, payload: dict, *, visual_pages: frozenset[int] = frozenset()) -> dict:
    issues = [issue for issue in source.issues
              if not (issue.endswith(":unbalanced_text") and
                      any(cell.id == issue.split(":")[0] and cell.page in visual_pages for cell in source.cells))]
    try:
        slots = source_slots(source)
    except ValueError as error:
        return {"ok": False, "issues": [*issues, str(error)], "expected_count": None, "session_cells": []}
    expected = Counter(slot.key for slot in slots)
    actual = Counter(tuple(session.get(field) for field in ("day", "type", "start", "end", "pool"))
                     for session in payload.get("sessions", []))
    if expected != actual:
        issues.append("source_session_mismatch")
    if not source.cells and payload.get("schedule_basis") != "temporarily_closed":
        issues.append("source_inventory_unavailable")
    indexed = {slot.key: slot.cell.id for slot in slots}
    return {"ok": not issues, "issues": issues, "expected_count": len(slots),
            "missing": [list(key) for key in (expected - actual).elements()],
            "extra": [list(key) for key in (actual - expected).elements()],
            "session_cells": [indexed.get(tuple(session.get(field) for field in ("day", "type", "start", "end", "pool")))
                              for session in payload.get("sessions", [])]}


def source_window(source: PdfSource) -> tuple[date, date] | None:
    header = []
    for line in source.text.split("\n\nPAGE 2\n", 1)[0].splitlines():
        if len({match[0].lower() for match in DAY_TOKEN_RE.finditer(line)}) >= 3:
            break
        header.append(line)
    return parse_window_dates(page_text="\n".join(header), anchor_text=None, filename=None, year_default=0)


def source_window_coverage(source: PdfSource, payload: dict) -> dict:
    window = source_window(source)
    expected = [day.isoformat() for day in window] if window else None
    actual = [payload.get("effective_start"), payload.get("effective_end")]
    return {"ok": expected is not None and expected == actual,
            "expected": expected, "actual": actual,
            "issues": [] if expected == actual else ["source_window_mismatch" if expected else "source_window_unavailable"]}


_MONTH_NUMBERS = {name.lower(): number for number in range(1, 13)
                  for name in (calendar.month_name[number], calendar.month_abbr[number])} | {"sept": 9}
_NOTICE_DATE_RE = re.compile(
    r"(?<![\d/])(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>20\d{2}|\d{2}))?(?![\d/])|"
    r"\b(?P<name>" + "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True)) + r")\.?\s+"
    r"(?P<named_day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<named_year>20\d{2}))?\b", re.IGNORECASE,
)
_RECURRENCE_RE = re.compile(r"\bevery\s+([1-5])(?:st|nd|rd|th)\s+"
                            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+of\s+the\s+month\b", re.IGNORECASE)


def _notice_closures(notice: SourceNotice, window: tuple[date, date], *, paired: bool = False) -> list[tuple]:
    if not notice.facility:
        raise ValueError("unresolved_closure_scope")
    text = " ".join(notice.text.split())
    if paired:
        text = re.sub(r"\b(" + "|".join(_MONTH_NUMBERS) + r")\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(?![\d:])\b",
                      lambda match: f"{match[1]} {match[2]} - {match[1]} {match[3]}", text, flags=re.IGNORECASE)
    if not re.search(r"\b(?:will be closed|pool(?:s)? closed|(?:holiday|training) closures)\b", text, re.IGNORECASE):
        raise ValueError("unresolved_closure_notice")
    scope_text = re.sub(r"\b" + notice.physical_pool + r" pool\b", "pool", text, flags=re.IGNORECASE) if paired and notice.physical_pool else text
    if re.search(r"\b(?:small|main|warm|cool|therapy)\s+pool\b|\b(?:may|might|possibly|except|unless)\b", scope_text, re.IGNORECASE):
        raise ValueError("unresolved_closure_scope")
    text = re.split(r"\breopen\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    recurrence = _RECURRENCE_RE.search(text)
    if recurrence:
        text = text[:recurrence.start()] + " " * len(recurrence[0]) + text[recurrence.end():]
    matches = list(_NOTICE_DATE_RE.finditer(text))
    days = []
    for match in matches:
        explicit_year = match["year"] or match["named_year"]
        if explicit_year is None and window[0].year != window[1].year:
            raise ValueError("ambiguous_closure_year")
        year = int(explicit_year) if explicit_year else window[0].year
        if year < 100:
            year += 2000
        month = int(match["month"]) if match["month"] else _MONTH_NUMBERS[match["name"].lower()]
        days.append(date(year, month, int(match["day"] or match["named_day"])))
    intervals = []
    index = 0
    while index < len(days):
        end_index = index
        if index + 1 < len(days) and re.fullmatch(r"\s*(?:to|[-–—])\s*", text[matches[index].end():matches[index + 1].start()], re.IGNORECASE):
            end_index += 1
        if days[end_index] < days[index]:
            raise ValueError("reversed_closure_dates")
        intervals.append((days[index], days[end_index]))
        index = end_index + 1
    for match in reversed(matches):
        text = text[:match.start()] + " " * len(match[0]) + text[match.end():]
    text = re.sub(r"(?<=\d)([ap])\b", r"\1m", text, flags=re.IGNORECASE)
    times = list(TIME_RANGE_RE.finditer(text))
    if len(times) > 1:
        raise ValueError("ambiguous_closure_times")
    clock = printed_time_range(times[0]["start"], times[0]["end"]) if times else (None, None)
    if times:
        text = text[:times[0].start()] + text[times[0].end():]
    if re.search(r"\d|\b(?:every|until|through|morning|afternoon|evening|night|early|late|before|after)\b", text, re.IGNORECASE):
        raise ValueError("unparsed_closure_condition")
    if recurrence:
        if not times or (window[1] - window[0]).days > 370:
            raise ValueError("unresolved_recurring_closure")
        weekday = [day.lower() for day in calendar.day_name].index(recurrence[2].lower())
        occurrences = []
        current = window[0]
        while current <= window[1]:
            if current.weekday() == weekday and (current.day - 1) // 7 + 1 == int(recurrence[1]):
                occurrences.append((current, current))
            current += timedelta(days=1)
        if intervals and intervals != occurrences:
            raise ValueError("conflicting_recurring_closure_dates")
        intervals = occurrences
    if not intervals:
        raise ValueError("closure_dates_unavailable")
    if times and any(start != end for start, end in intervals):
        raise ValueError("unsupported_multiday_closure_times")
    return [(start.isoformat(), end.isoformat(), *clock) for start, end in intervals]


def source_closure_coverage(source: PdfSource, payload: dict) -> dict:
    window = source_window(source)
    issues = []
    expected = []
    if window is None:
        issues.append("source_window_unavailable")
    else:
        for notice in source.notices:
            if notice.session_cell and north_beach_pool_identity(source.text):
                continue
            try:
                parsed = _notice_closures(notice, window, paired=bool(north_beach_pool_identity(source.text)))
                expected.extend([(*item, notice.physical_pool) for item in parsed] if north_beach_pool_identity(source.text) else parsed)
            except ValueError as error:
                issues.append(f"{notice.id}:{error}")
    if not north_beach_pool_identity(source.text) and any(closure.get("physical_pool") for closure in payload.get("closures", [])):
        issues.append("unsupported_pool_closure")
    expected_counts = Counter(expected)
    fields = ("start", "end", "start_time", "end_time") + (("physical_pool",) if north_beach_pool_identity(source.text) else ())
    actual = Counter(tuple(closure.get(field) for field in fields)
                     for closure in payload.get("closures", []))
    if expected_counts != actual:
        issues.append("source_closure_mismatch")
    return {"ok": not issues, "issues": issues, "expected": [list(item) for item in expected],
            "missing": [list(item) for item in (expected_counts - actual).elements()],
            "extra": [list(item) for item in (actual - expected_counts).elements()]}


def source_publication_coverage(source: PdfSource, payload: dict, *, visual_pages: frozenset[int] = frozenset()) -> dict:
    sessions = source_coverage(source, payload, visual_pages=visual_pages)
    window = source_window_coverage(source, payload)
    closures = source_closure_coverage(source, payload)
    exclusions = source_exclusion_coverage(source, payload)
    return sessions | {"ok": sessions["ok"] and window["ok"] and closures["ok"] and exclusions["ok"],
                       "window": window, "closures": closures, "exclusions": exclusions}

TYPE_TOKENS: dict[str, tuple[str, ...]] = {
    "lap_swim": ("lap",),
    "family_swim": ("family", "rec", "recreation"),
    "senior_swim": ("senior", "55+", "50+"),
}

# Substrings that, if present in evidence, mean the row is from an ignore-list
# program — even if the surrounding text shares a token with an allowed type
# (e.g. "SENIOR/SELF GUIDED EXERCISE" contains "senior" but is exercise, not
# senior swim; "MASTER'S SWIM TEAM" might be adjacent to lap-swim cells but
# is a private team booking). Each token is matched against normalized
# (lowercased, period-stripped) evidence.
IGNORE_LIST_TOKENS: tuple[str, ...] = (
    "lessons",
    "learn to swim",
    "tiny tots",
    "aerobics",
    "exercise",
    "master",
    "synchro",
    "hockey",
    "water polo",
    "piranhas",
    "sfusd",
    "self guided",
    "parent/child",
)

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9:/]+")
_EVIDENCE_WINDOW_CHARS = 250


def normalize_pdf_text(page_texts: Iterable[str]) -> str:
    return _normalize("\n".join(page_texts))


def _evidence_locally_grounded(evidence: str, pdf_text: str) -> bool:
    """True if evidence is grounded in pdf_text, tolerating cross-line layouts.

    A row in a calendar PDF often serializes through pypdf as program label and
    time range on different lines, with intervening cells from other days.
    The literal substring check fails in those cases. This check accepts an
    extraction iff the evidence's significant tokens appear *in order* within
    a single window of pdf_text. Paraphrased evidence (tokens not present in
    the PDF, or out of order) is still rejected.
    """
    if not evidence or not pdf_text:
        return False
    if evidence in pdf_text:
        return True
    e_tokens = _TOKEN_RE.findall(evidence)
    if not e_tokens:
        return False
    first_token = e_tokens[0]
    for match in re.finditer(re.escape(first_token), pdf_text):
        win_start = match.start()
        win_end = min(len(pdf_text), win_start + _EVIDENCE_WINDOW_CHARS)
        cursor = match.end()
        ok = True
        for tok in e_tokens[1:]:
            i = pdf_text.find(tok, cursor, win_end)
            if i == -1:
                ok = False
                break
            cursor = i + len(tok)
        if ok:
            return True
    return False


def grounding_from_text(pdf_text_normalized: str, payload: dict) -> GroundingResult:
    sessions_out: list[SessionGrounding] = []

    for index, session in enumerate(payload.get("sessions") or []):
        evidence_raw = session.get("evidence")
        evidence = _normalize(evidence_raw) if isinstance(evidence_raw, str) else ""
        typ = session.get("type") if isinstance(session.get("type"), str) else ""
        tokens = TYPE_TOKENS.get(typ, ())
        type_in_pdf_text = bool(tokens) and any(token in pdf_text_normalized for token in tokens)

        if not evidence:
            sessions_out.append(
                SessionGrounding(
                    index=index,
                    grounded=False,
                    missing_evidence=True,
                    evidence_in_pdf=False,
                    start_in_evidence=False,
                    type_in_evidence=False,
                    type_in_pdf_text=type_in_pdf_text,
                    session=session,
                )
            )
            continue

        evidence_in_pdf = _evidence_locally_grounded(evidence, pdf_text_normalized)

        start = session.get("start") if isinstance(session.get("start"), str) else ""
        start_in_evidence = bool(start) and any(
            variant in evidence for variant in _start_variants(start)
        )

        type_in_evidence = bool(tokens) and any(token in evidence for token in tokens)
        ignore_token_in_evidence = any(token in evidence for token in IGNORE_LIST_TOKENS)

        # Multi-program cells (e.g. "LAP SWIM (4) SELF GUIDED EXERCISE (2)")
        # legitimately contain both a kept-type token and an ignore-list token.
        # Only block when the evidence has an ignore-list token AND no kept-type
        # token, which signals the model classified an ignore-list program as
        # a kept type.
        ignore_only = ignore_token_in_evidence and not type_in_evidence

        ok = all(
            (
                evidence_in_pdf,
                type_in_evidence,
                start_in_evidence,
                type_in_pdf_text,
                not ignore_only,
            )
        )

        sessions_out.append(
            SessionGrounding(
                index=index,
                grounded=ok,
                missing_evidence=False,
                evidence_in_pdf=evidence_in_pdf,
                start_in_evidence=start_in_evidence,
                type_in_evidence=type_in_evidence,
                type_in_pdf_text=type_in_pdf_text,
                session=session,
            )
        )

    return GroundingResult(sessions=sessions_out)


def _normalize(text: str) -> str:
    value = text.lower().replace(".", "")
    value = _WS_RE.sub(" ", value)
    return value.strip()


def _start_variants(start: str) -> list[str]:
    try:
        hour_str, minute_str = start.split(":")
        hour_24 = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        return []

    hour_12 = hour_24 % 12 or 12
    meridiem = "am" if hour_24 < 12 else "pm"
    minute_txt = f"{minute:02d}"
    variants = [
        start,
        f"{hour_12}:{minute_txt}",
        f"{hour_12}:{minute_txt}{meridiem}",
        f"{hour_12}:{minute_txt} {meridiem}",
    ]
    if minute == 0:
        variants.extend([f"{hour_12}{meridiem}", f"{hour_12} {meridiem}"])
    return variants


def source_excluded_dates(source: PdfSource) -> dict[str, list[str]]:
    window = source_window(source)
    excluded = {}
    for notice in source.notices:
        if not notice.session_cell:
            continue
        match = re.search(r"\(CLOSED\s+(\d{1,2}/\d{1,2}(?:\s*&\s*\d{1,2}/\d{1,2})*)\)", notice.text, re.IGNORECASE)
        if not match or not window or len(CLOSURE_TOKEN_RE.findall(notice.text)) != 1:
            raise ValueError(f"{notice.id}:unresolved_session_exclusion")
        dates = []
        for part in re.split(r"\s*&\s*", match[1]):
            month, day = map(int, part.split("/"))
            candidates = []
            for year in range(window[0].year, window[1].year + 1):
                try:
                    value = date(year, month, day)
                except ValueError:
                    continue
                if window[0] <= value <= window[1]:
                    candidates.append(value)
            cell = next(cell for cell in source.cells if cell.id == notice.session_cell)
            if len(candidates) != 1 or candidates[0].strftime("%A").lower() != cell.day:
                raise ValueError(f"{notice.id}:ambiguous_exclusion_date")
            dates.append(candidates[0].isoformat())
        excluded[notice.session_cell] = sorted(set(dates))
    return excluded


def source_exclusion_coverage(source: PdfSource, payload: dict) -> dict:
    try:
        excluded = source_excluded_dates(source)
        slots = {slot.key: slot.cell.id for slot in source_slots(source)}
        issues = []
        for session in payload.get("sessions", []):
            key = tuple(session.get(field) for field in ("day", "type", "start", "end", "pool"))
            expected = excluded.get(slots.get(key), [])
            if session.get("excluded_dates", []) != expected:
                issues.append("source_exclusion_mismatch")
        return {"ok": not issues, "issues": issues, "expected": excluded}
    except ValueError as error:
        return {"ok": False, "issues": [str(error)]}
