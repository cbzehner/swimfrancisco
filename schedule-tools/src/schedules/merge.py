from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import tomlkit

from ._time import pacific_today
from .models import DAY_ORDER

_DAY_INDEX = {day: index for index, day in enumerate(DAY_ORDER)}


def merge(
    pool_md_path: Path,
    extracted: dict[str, Any],
    *,
    last_verified_at: str | None = None,
) -> bool:
    """Merge an extracted schedule into a spot's [[extra.schedules]] array.

    Match-by-effective_start semantics:
      - Existing entry with the same effective_start → replace it
      - Otherwise → append a new entry

    Sort by effective_start after every change. No "current vs upcoming"
    split — the render-time predicate (`pick_active_schedule`) decides
    which array entry is active for any given date.

    Returns True when the content file was rewritten.
    """
    original_text = pool_md_path.read_text()
    frontmatter_text, body = _split_frontmatter(original_text)
    document = tomlkit.parse(frontmatter_text)
    extra = document.setdefault("extra", tomlkit.table())

    after = _normalized_schedule_payload(extracted)

    existing_aot = extra.get("schedules")
    stored = _index_schedules(existing_aot)

    target_start = after.get("effective_start")
    if not isinstance(target_start, str) or not target_start:
        return False

    existing = stored.get(target_start)
    if existing is not None:
        if existing.payload == after and (
            last_verified_at is None or existing.last_verified_at == last_verified_at
        ):
            return False
        stored[target_start] = _StoredSchedule(
            after,
            last_verified_at if last_verified_at is not None else existing.last_verified_at,
        )
    else:
        stored = _close_overlapping(stored, target_start)
        stored[target_start] = _StoredSchedule(after, last_verified_at)

    new_aot = tomlkit.aot()
    for start in sorted(stored):
        item = stored[start]
        new_aot.append(_build_schedule_table(item.payload, last_verified_at=item.last_verified_at))
    if "schedules" in extra:
        del extra["schedules"]
    extra["schedules"] = new_aot

    updated = tomlkit.dumps(document).rstrip("\n")
    pool_md_path.write_text(f"+++\n{updated}\n+++\n{body}")
    return True


def read_schedule_snapshot(pool_md_path: Path) -> dict[str, Any]:
    """Return the currently-active schedule for a spot, for diff baselines."""
    frontmatter_text, _ = _split_frontmatter(pool_md_path.read_text())
    document = tomlkit.parse(frontmatter_text)
    extra = document.get("extra", {})
    schedules = _schedules_list(extra)
    today_iso = pacific_today().isoformat()
    active = pick_active_schedule(schedules, today_iso)
    return active if active is not None else _empty_schedule()


def pick_active_schedule(schedules: list[Any], today_iso: str) -> dict[str, Any] | None:
    """Display-time predicate: pick the schedule to render for `today_iso`
    from a list of schedule entries.

    Selection order:
      1. In-window: effective_start <= today AND (no effective_end OR today
         <= effective_end). If multiple match (defensive — shouldn't happen
         with non-overlapping windows), prefer the latest effective_start.
      2. Upcoming: earliest entry with effective_start > today.
      3. Past: most recent entry with effective_end < today.
      4. None: no schedules at all.

    Both effective_start and effective_end are INCLUSIVE.

    Mirrors `resolveScheduleForDate` in static/js/helpers/board.mjs and the
    `active_schedule` block in templates/spots/page.html. The three impls
    must stay in sync — there's a golden table test in test_merge.py.
    """
    if not schedules:
        return None
    normalized = [_schedule_from_table(s) for s in schedules]
    in_window = [s for s in normalized if _date_in_window(s, today_iso)]
    if in_window:
        in_window.sort(key=lambda s: s.get("effective_start") or "", reverse=True)
        return in_window[0]
    upcoming = [
        s for s in normalized
        if isinstance(s.get("effective_start"), str) and s["effective_start"] > today_iso
    ]
    if upcoming:
        upcoming.sort(key=lambda s: s.get("effective_start") or "")
        return upcoming[0]
    past = [
        s for s in normalized
        if isinstance(s.get("effective_end"), str) and s["effective_end"] < today_iso
    ]
    if past:
        past.sort(key=lambda s: s.get("effective_end") or "", reverse=True)
        return past[0]
    return None


def _date_in_window(schedule: dict[str, Any], date_iso: str) -> bool:
    start = schedule.get("effective_start")
    end = schedule.get("effective_end")
    if isinstance(start, str) and start and date_iso < start:
        return False
    if isinstance(end, str) and end and date_iso > end:
        return False
    return True


def _schedules_list(extra: Any) -> list[Any]:
    """Return the schedules array on an extra table, defaulting to []."""
    schedules = extra.get("schedules")
    if schedules is None:
        return []
    return list(schedules)


def _empty_schedule() -> dict[str, Any]:
    return {
        "sessions": [],
        "access_hours": [],
        "access_exceptions": [],
        "closures": [],
        "effective_start": None,
        "schedule_basis": None,
        "effective_end": None,
    }


class _StoredSchedule(NamedTuple):
    payload: dict[str, Any]
    last_verified_at: str | None


def _index_schedules(existing_aot: Any) -> dict[str, _StoredSchedule]:
    indexed: dict[str, _StoredSchedule] = {}
    if existing_aot is None:
        return indexed
    for table in existing_aot:
        entry = _schedule_from_table(table)
        start = entry.get("effective_start")
        if not isinstance(start, str) or not start:
            raise ValueError("schedule entry is missing effective_start")
        if start in indexed:
            raise ValueError(f"duplicate schedule effective_start {start}")
        verified = table.get("last_verified_at")
        indexed[start] = _StoredSchedule(
            entry,
            verified if isinstance(verified, str) else None,
        )
    return indexed


def _close_overlapping(
    stored: dict[str, _StoredSchedule],
    new_start: str,
) -> dict[str, _StoredSchedule]:
    prior_end = _day_before(new_start)
    closed: dict[str, _StoredSchedule] = {}
    for start, item in stored.items():
        payload = dict(item.payload)
        end = payload.get("effective_end")
        overlaps = start < new_start and (not isinstance(end, str) or not end or end >= new_start)
        if overlaps:
            payload["effective_end"] = prior_end
            closed[start] = _StoredSchedule(payload, item.last_verified_at)
        else:
            closed[start] = item
    return closed


def _day_before(iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return (date(year, month, day) - timedelta(days=1)).isoformat()


def _normalized_schedule_payload(extracted: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessions": _normalize_sessions(extracted.get("sessions", [])),
        "access_hours": _normalize_access_hours(extracted.get("access_hours", [])),
        "access_exceptions": _normalize_access_exceptions(extracted.get("access_exceptions", [])),
        "closures": _normalize_closures(extracted.get("closures", [])),
        "effective_start": extracted.get("effective_start"),
        "schedule_basis": extracted.get("schedule_basis"),
        "effective_end": extracted.get("effective_end"),
    }


def _schedule_from_table(table: Any) -> dict[str, Any]:
    return {
        "sessions": _normalize_sessions(list(table.get("sessions", []))),
        "access_hours": _normalize_access_hours(list(table.get("access_hours", []))),
        "access_exceptions": _normalize_access_exceptions(list(table.get("access_exceptions", []))),
        "closures": _normalize_closures(list(table.get("closures", []))),
        "effective_start": table.get("effective_start"),
        "schedule_basis": table.get("schedule_basis"),
        "effective_end": table.get("effective_end"),
    }


def _build_schedule_table(
    schedule: dict[str, Any],
    *,
    last_verified_at: str | None = None,
):
    table = tomlkit.table()
    table["sessions"] = _build_sessions_value(schedule["sessions"])
    if schedule["access_hours"]:
        table["access_hours"] = _build_access_hours_value(schedule["access_hours"])
    if schedule["access_exceptions"]:
        table["access_exceptions"] = _build_access_exceptions_value(schedule["access_exceptions"])
    table["closures"] = _build_closures_value(schedule["closures"])
    table["effective_start"] = schedule["effective_start"]
    if schedule["schedule_basis"] is not None:
        table["schedule_basis"] = schedule["schedule_basis"]
    if schedule["effective_end"] is not None:
        table["effective_end"] = schedule["effective_end"]
    if last_verified_at is not None:
        table["last_verified_at"] = last_verified_at
    return table


class _RecordSpec(NamedTuple):
    """Declarative shape for one record type in the schedule payload.

    `required` and `optional` together define both the field set validated
    during normalization and the exact key order written to TOML tables.
    `sort_key` mirrors the original per-type sort tuple exactly.
    """

    required: tuple[str, ...]
    optional: tuple[str, ...]
    sort_key: Any


_SESSION_SPEC = _RecordSpec(
    required=("day", "type", "start", "end"),
    optional=("pool", "notes"),
    sort_key=lambda item: (
        _DAY_INDEX.get(item["day"], 99),
        item["start"],
        item["end"],
        item["type"],
        item.get("pool", ""),
    ),
)

_ACCESS_HOUR_SPEC = _RecordSpec(
    required=("day", "start", "end", "label"),
    optional=("notes",),
    sort_key=lambda item: (
        _DAY_INDEX.get(item["day"], 99),
        item["start"],
        item["end"],
        item["label"],
    ),
)

_ACCESS_EXCEPTION_SPEC = _RecordSpec(
    required=("date", "start", "end", "label", "reason"),
    optional=("notes",),
    sort_key=lambda item: (
        item["date"],
        item["start"],
        item["end"],
        item["label"],
        item["reason"],
    ),
)

_CLOSURE_SPEC = _RecordSpec(
    required=("start", "end", "reason"),
    optional=("start_time", "end_time"),
    sort_key=lambda item: (
        item["start"],
        item["end"],
        item.get("start_time", ""),
        item.get("end_time", ""),
        item["reason"],
    ),
)


def _normalize_records(raw_records: list[dict], spec: _RecordSpec) -> list[dict[str, str]]:
    normalized = []
    for record in raw_records:
        item: dict[str, str] = {field: str(record[field]) for field in spec.required}
        for field in spec.optional:
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                item[field] = value.strip()
        normalized.append(item)
    return sorted(normalized, key=spec.sort_key)


def _normalize_sessions(raw_sessions: list[dict]) -> list[dict[str, str]]:
    return _normalize_records(raw_sessions, _SESSION_SPEC)


def _normalize_access_hours(raw_access_hours: list[dict]) -> list[dict[str, str]]:
    return _normalize_records(raw_access_hours, _ACCESS_HOUR_SPEC)


def _normalize_access_exceptions(raw_access_exceptions: list[dict]) -> list[dict[str, str]]:
    return _normalize_records(raw_access_exceptions, _ACCESS_EXCEPTION_SPEC)


def _normalize_closures(raw_closures: list[dict]) -> list[dict[str, str]]:
    return _normalize_records(raw_closures, _CLOSURE_SPEC)


def _build_records_value(records: list[dict[str, str]], spec: _RecordSpec):
    if not records:
        return tomlkit.array()
    aot: AoT = tomlkit.aot()
    for record in records:
        table = tomlkit.table()
        for field in spec.required:
            table[field] = record[field]
        for field in spec.optional:
            if field in record:
                table[field] = record[field]
        aot.append(table)
    return aot


def _build_sessions_value(sessions: list[dict[str, str]]):
    return _build_records_value(sessions, _SESSION_SPEC)


def _build_access_hours_value(access_hours: list[dict[str, str]]):
    return _build_records_value(access_hours, _ACCESS_HOUR_SPEC)


def _build_access_exceptions_value(access_exceptions: list[dict[str, str]]):
    return _build_records_value(access_exceptions, _ACCESS_EXCEPTION_SPEC)


def _build_closures_value(closures: list[dict[str, str]]):
    return _build_records_value(closures, _CLOSURE_SPEC)


def _split_frontmatter(text: str) -> tuple[str, str]:
    marker = "+++\n"
    if not text.startswith(marker):
        raise ValueError("Content file is missing TOML frontmatter.")
    remainder = text[len(marker) :]
    closing = "\n+++\n"
    boundary = remainder.find(closing)
    if boundary < 0:
        raise ValueError("Content file frontmatter is not properly closed.")
    return remainder[:boundary], remainder[boundary + len(closing) :]
