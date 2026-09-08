from __future__ import annotations

import re
import calendar
from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass, replace
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


def _cell_pool(cell: SourceCell, time_match, program_type: str) -> str | None:
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
        headings = list(re.finditer(r"\b(?:lap\s+swim|(?:rec(?:reation)?\s*/\s*)?family\s+swim|senior(?:\s*/\s*therapy)?\s+swim)\b", cell.text[:time_match.start()], re.IGNORECASE))
        if not headings or cell.text[:headings[0].start()].strip():
            raise ValueError(f"{cell.id}:ambiguous_pool_allocation")
        assigned = {}
        assigned_labels = []
        for index, heading in enumerate(headings):
            kinds = program_types(heading[0])
            end = headings[index + 1].start() if index + 1 < len(headings) else time_match.start()
            segment = cell.text[heading.end():end]
            allocations = re.findall(r"\(([^()]*)\)", segment)
            if (len(kinds) != 1 or kinds[0] in assigned or len(allocations) != 1
                    or re.sub(r"\([^()]*\)", "", segment).strip()):
                raise ValueError(f"{cell.id}:ambiguous_pool_allocation")
            assigned[kinds[0]] = pool_label_payload({"sessions": [{"pool_label_raw": allocations[0]}]})["sessions"][0].get("pool")
            assigned_labels.extend(label.strip() for label in allocations)
        if set(assigned) != set(program_types(cell.text)) or sorted(assigned_labels) != sorted(labels):
            raise ValueError(f"{cell.id}:ambiguous_pool_allocation")
        return assigned[program_type]
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
        start_minutes = int(start[:2]) * 60 + int(start[3:])
        end_minutes = int(end[:2]) * 60 + int(end[3:])
        if end_minutes - start_minutes > 12 * 60:
            raise ValueError(f"{cell.id}:unsupported_session_duration")
        for kind in types:
            pool = _cell_pool(cell, time_match, kind)
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
                            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?:\s+of\s+t\s*he\s+month)?\b", re.IGNORECASE)


def _notice_closures(notice: SourceNotice, window: tuple[date, date], *, paired: bool = False, full_day_closures: tuple = ()) -> list[tuple]:
    if not notice.facility:
        raise ValueError("unresolved_closure_scope")
    text = " ".join(notice.text.split())
    # Expand only an adjacent day which explicitly inherits a preceding month.
    inherited = re.compile(r"(?P<prefix>(?P<month>" + "|".join(_MONTH_NUMBERS) + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?|(?P<numeric>\d{1,2})/\d{1,2})(?P<join>\s*(?:and|&|[-–])\s*)(?P<day>\d{1,2})(?:st|nd|rd|th)?(?![\d/:])\b", re.IGNORECASE)
    text = inherited.sub(lambda match: match["prefix"] + match["join"] + (match["month"] + " " if match["month"] else match["numeric"] + "/") + match["day"], text)
    if not re.search(r"\b(?:will be closed|pool(?:s)? closed|closed for (?:annual maintenance|in-service)|(?:holiday|training) closures)\b", text, re.IGNORECASE):
        raise ValueError("unresolved_closure_notice")
    scope_text = re.sub(r"\b" + notice.physical_pool + r" pool\b", "pool", text, flags=re.IGNORECASE) if paired and notice.physical_pool else text
    if re.search(r"\b(?:small|main|warm|cool|therapy)\s+pool\b|\b(?:may|might|possibly|except|unless)\b", scope_text, re.IGNORECASE):
        raise ValueError("unresolved_closure_scope")
    text = re.split(r"\breopen\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    recurrence = _RECURRENCE_RE.search(text)
    if recurrence:
        text = text[:recurrence.start()] + " " * len(recurrence[0]) + text[recurrence.end():]
    matches = list(_NOTICE_DATE_RE.finditer(text))
    clock_text = _NOTICE_DATE_RE.sub("", text)
    if len(list(TIME_RANGE_RE.finditer(clock_text))) > 1:
        if recurrence or len(matches) < 2:
            raise ValueError("ambiguous_closure_times")
        prefix = text[:matches[0].start()]
        clauses = [text[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
                   for index, match in enumerate(matches)]
        if any(len(list(TIME_RANGE_RE.finditer(_NOTICE_DATE_RE.sub("", clause)))) != 1 for clause in clauses):
            raise ValueError("ambiguous_closure_times")
        return [interval for clause in clauses
                for interval in _notice_closures(replace(notice, text=prefix + clause), window, paired=paired)]
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
    if times and clock[0] < clock[1] <= "12:00" and clock[0] < "12:00":
        text = re.sub(r"\b(?:the\s+)?morning\s+of\b", "", text, flags=re.IGNORECASE)
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
        intervals = _reconcile_recurring_dates(occurrences, intervals, full_day_closures)
    if not intervals:
        raise ValueError("closure_dates_unavailable")
    if times and any(start != end for start, end in intervals):
        raise ValueError("unsupported_multiday_closure_times")
    return [(start.isoformat(), end.isoformat(), *clock) for start, end in intervals]


def _reconcile_recurring_dates(occurrences: list[tuple], listed: list[tuple], full_day_closures: tuple) -> list[tuple]:
    if not listed:
        return occurrences
    if len(set(listed)) != len(listed) or set(listed) - set(occurrences):
        raise ValueError("conflicting_recurring_closure_dates")
    missing = set(occurrences) - set(listed)
    if any(not any(start <= day <= end for start, end in full_day_closures) for day, _ in missing):
        raise ValueError("conflicting_recurring_closure_dates")
    return sorted(listed)


def _independent_full_day_closures(source: PdfSource, window: tuple[date, date]) -> tuple:
    intervals = []
    for notice in source.notices:
        if not notice.facility or notice.session_cell or notice.physical_pool or _RECURRENCE_RE.search(notice.text):
            continue
        text = " ".join(notice.text.split())
        if (not re.match(r"(?:All(?: city)? pools will be closed|Pool (?:will be closed|closed))\b", text, re.IGNORECASE)
                or re.search(r"\b(?:reopen\w*|may|might|possibly|except|unless|if|not|only)\b|\b(?:lap|deep|shallow|small|main|warm|cool|therapy)\s+pool\b", text, re.IGNORECASE)):
            continue
        try:
            parsed = _notice_closures(notice, window)
        except ValueError:
            continue
        intervals.extend((date.fromisoformat(start), date.fromisoformat(end))
                         for start, end, start_time, end_time in parsed if start_time is None and end_time is None)
    return tuple(intervals)


def source_closure_inventory(source: PdfSource) -> list[dict]:
    window = source_window(source)
    if window is None:
        raise ValueError("source_window_unavailable")
    source_excluded_dates(source)
    closures = []
    paired = bool(north_beach_pool_identity(source.text))
    for notice in source.notices:
        if notice.session_cell:
            continue
        try:
            intervals = _notice_closures(notice, window, paired=paired, full_day_closures=_independent_full_day_closures(source, window))
        except ValueError as error:
            raise ValueError(f"{notice.id}:{error}") from error
        categories = [code for code, pattern in (
            ("holiday", r"\b(?:holidays?|thanksgiving|veterans?\s+day|labor\s+day|indigenous)\b"),
            ("staff_training", r"\b(?:trainings?|in-service)\b"),
            ("maintenance", r"\b(?:maintenance|maintence)\b"),
        ) if re.search(pattern, notice.text, re.IGNORECASE)]
        if len(categories) > 1:
            raise ValueError(f"{notice.id}:ambiguous_closure_reason")
        for interval in intervals:
            closure = dict(zip(("start", "end", "start_time", "end_time"), interval))
            closure.update(reason_code=categories[0] if categories else "other",
                           source_notices=[{"id": notice.id, "text": notice.text}])
            if paired and notice.physical_pool:
                closure["physical_pool"] = notice.physical_pool
            closures.append(closure)
    return closures


def source_closure_coverage(source: PdfSource, payload: dict) -> dict:
    window = source_window(source)
    issues = []
    expected = []
    if window is None:
        issues.append("source_window_unavailable")
    else:
        for notice in source.notices:
            if notice.session_cell:
                continue
            try:
                parsed = _notice_closures(notice, window, paired=bool(north_beach_pool_identity(source.text)), full_day_closures=_independent_full_day_closures(source, window))
                expected.extend([(*item, notice.physical_pool) for item in parsed] if north_beach_pool_identity(source.text) else parsed)
            except ValueError as error:
                issues.append(f"{notice.id}:{error}")
    try:
        source_excluded_dates(source)
    except ValueError as error:
        issues.append(str(error))
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
        cell = next(cell for cell in source.cells if cell.id == notice.session_cell)
        if not window or len(re.findall(r"\bclosed\b", notice.text, re.IGNORECASE)) != 1 or re.search(r"\b(?:may|might|unless|except|before|after)\b", notice.text, re.IGNORECASE):
            raise ValueError(f"{notice.id}:unresolved_session_exclusion")
        recurrence = _RECURRENCE_RE.search(notice.text)
        if recurrence:
            remainder = re.split(r"\bclosed\b", notice.text, flags=re.IGNORECASE)[1]
            remainder = TIME_RANGE_RE.sub("", _RECURRENCE_RE.sub("", remainder)).strip()
            listed_matches = list(_NOTICE_DATE_RE.finditer(remainder))
            residue = _NOTICE_DATE_RE.sub("", remainder)
            if not re.fullmatch(r"(?:for\s+(?:staff\s+)?training)?[\s,&]*", residue, re.IGNORECASE):
                raise ValueError(f"{notice.id}:conflicting_session_recurrence")
            weekday = list(day.lower() for day in calendar.day_name).index(recurrence[2].lower())
            values = [window[0] + timedelta(days=offset) for offset in range((window[1] - window[0]).days + 1)]
            occurrences = [(day, day) for day in values if day.weekday() == weekday and (day.day - 1) // 7 + 1 == int(recurrence[1])]
            if recurrence[2].lower() != cell.day or (listed_matches and window[0].year != window[1].year):
                raise ValueError(f"{notice.id}:conflicting_session_recurrence")
            if any(match["month"] is None or match["year"] is not None for match in listed_matches):
                raise ValueError(f"{notice.id}:conflicting_session_recurrence")
            listed = [(date(window[0].year, int(match["month"]), int(match["day"])),) * 2 for match in listed_matches]
            reconciled = _reconcile_recurring_dates(occurrences, listed, _independent_full_day_closures(source, window))
            excluded[notice.session_cell] = [day.isoformat() for day, _ in reconciled]
            continue
        match = re.search(r"(?:\(CLOSED\s*-?\s*|CLOSED\s*\()(\d{1,2}/\d{1,2}(?:\s*[&,]\s*\d{1,2}/\d{1,2})*)\)", notice.text, re.IGNORECASE)
        if not match or len(CLOSURE_TOKEN_RE.findall(notice.text)) != 1:
            raise ValueError(f"{notice.id}:unresolved_session_exclusion")
        dates = []
        for part in re.split(r"\s*[&,]\s*", match[1]):
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
        if len(set(dates)) != len(dates):
            raise ValueError(f"{notice.id}:duplicate_exclusion_date")
        excluded[notice.session_cell] = sorted(dates)
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
