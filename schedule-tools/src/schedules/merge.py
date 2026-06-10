from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT

from ._time import pacific_today
from .models import DAY_ORDER, MergeResult

_DAY_INDEX = {day: index for index, day in enumerate(DAY_ORDER)}


def merge(
    pool_md_path: Path,
    extracted: dict[str, Any],
    *,
    last_verified_at: str | None = None,
) -> MergeResult:
    """Merge an extracted schedule into a spot's [[extra.schedules]] array.

    Match-by-effective_start semantics:
      - Existing entry with the same effective_start → replace it
      - Otherwise → append a new entry

    Sort by effective_start after every change. No "current vs upcoming"
    split — the render-time predicate (`pick_active_schedule`) decides
    which array entry is active for any given date.
    """
    original_text = pool_md_path.read_text()
    frontmatter_text, body = _split_frontmatter(original_text)
    document = tomlkit.parse(frontmatter_text)
    extra = document.setdefault("extra", tomlkit.table())

    after = _normalized_schedule_payload(extracted)

    # Snapshot existing entries as dicts so we can mutate freely.
    existing_aot = extra.get("schedules")
    existing_entries: list[dict[str, Any]] = []
    if existing_aot is not None:
        for table in existing_aot:
            entry = _schedule_from_table(table)
            lva = table.get("last_verified_at")
            if isinstance(lva, str):
                entry["_last_verified_at"] = lva
            existing_entries.append(entry)

    target_start = after.get("effective_start")
    matching_index: int | None = None
    for i, entry in enumerate(existing_entries):
        if entry.get("effective_start") == target_start:
            matching_index = i
            break

    before = (
        {k: v for k, v in existing_entries[matching_index].items() if k != "_last_verified_at"}
        if matching_index is not None
        else _empty_schedule()
    )

    # Nothing to add and nothing to update.
    if matching_index is None and not target_start:
        return _merge_result(before, after, written=False)

    if matching_index is not None:
        existing_entry = existing_entries[matching_index]
        existing_verified = existing_entry.get("_last_verified_at")
        existing_payload = {k: v for k, v in existing_entry.items() if k != "_last_verified_at"}
        if existing_payload == after and (
            last_verified_at is None or existing_verified == last_verified_at
        ):
            return _merge_result(before, after, written=False)
        existing_entries[matching_index] = {
            **after,
            "_last_verified_at": last_verified_at if last_verified_at is not None else existing_verified,
        }
    else:
        existing_entries.append({
            **after,
            "_last_verified_at": last_verified_at,
        })

    existing_entries.sort(key=lambda s: s.get("effective_start") or "0000-00-00")

    new_aot = tomlkit.aot()
    for entry in existing_entries:
        verified = entry.get("_last_verified_at")
        payload = {k: v for k, v in entry.items() if k != "_last_verified_at"}
        new_aot.append(_build_schedule_table(payload, last_verified_at=verified))
    if "schedules" in extra:
        del extra["schedules"]
    extra["schedules"] = new_aot

    updated = tomlkit.dumps(document).rstrip("\n")
    pool_md_path.write_text(f"+++\n{updated}\n+++\n{body}")
    return _merge_result(before, after, written=True)


def _merge_result(before: dict[str, Any], after: dict[str, Any], *, written: bool) -> MergeResult:
    return MergeResult(
        prior_sessions_count=len(before.get("sessions") or []),
        new_sessions_count=len(after.get("sessions") or []),
        prior_closures_count=len(before.get("closures") or []),
        new_closures_count=len(after.get("closures") or []),
        written=written,
    )


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


def _normalize_sessions(raw_sessions: list[dict]) -> list[dict[str, str]]:
    normalized = []
    for session in raw_sessions:
        item: dict[str, str] = {
            "day": str(session["day"]),
            "type": str(session["type"]),
            "start": str(session["start"]),
            "end": str(session["end"]),
        }
        pool = session.get("pool")
        if isinstance(pool, str) and pool.strip():
            item["pool"] = pool.strip()
        notes = session.get("notes")
        if isinstance(notes, str) and notes.strip():
            item["notes"] = notes.strip()
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (
            _DAY_INDEX.get(item["day"], 99),
            item["start"],
            item["end"],
            item["type"],
            item.get("pool", ""),
        ),
    )


def _normalize_access_hours(raw_access_hours: list[dict]) -> list[dict[str, str]]:
    normalized = []
    for access_hour in raw_access_hours:
        item: dict[str, str] = {
            "day": str(access_hour["day"]),
            "start": str(access_hour["start"]),
            "end": str(access_hour["end"]),
            "label": str(access_hour["label"]),
        }
        notes = access_hour.get("notes")
        if isinstance(notes, str) and notes.strip():
            item["notes"] = notes.strip()
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (
            _DAY_INDEX.get(item["day"], 99),
            item["start"],
            item["end"],
            item["label"],
        ),
    )


def _normalize_access_exceptions(raw_access_exceptions: list[dict]) -> list[dict[str, str]]:
    normalized = []
    for access_exception in raw_access_exceptions:
        item: dict[str, str] = {
            "date": str(access_exception["date"]),
            "start": str(access_exception["start"]),
            "end": str(access_exception["end"]),
            "label": str(access_exception["label"]),
            "reason": str(access_exception["reason"]),
        }
        notes = access_exception.get("notes")
        if isinstance(notes, str) and notes.strip():
            item["notes"] = notes.strip()
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (
            item["date"],
            item["start"],
            item["end"],
            item["label"],
            item["reason"],
        ),
    )


def _normalize_closures(raw_closures: list[dict]) -> list[dict[str, str]]:
    normalized = []
    for closure in raw_closures:
        item: dict[str, str] = {
            "start": str(closure["start"]),
            "end": str(closure["end"]),
            "reason": str(closure["reason"]),
        }
        start_time = closure.get("start_time")
        end_time = closure.get("end_time")
        if isinstance(start_time, str) and start_time.strip():
            item["start_time"] = start_time.strip()
        if isinstance(end_time, str) and end_time.strip():
            item["end_time"] = end_time.strip()
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (
            item["start"],
            item["end"],
            item.get("start_time", ""),
            item.get("end_time", ""),
            item["reason"],
        ),
    )


def _build_sessions_value(sessions: list[dict[str, str]]):
    if not sessions:
        return tomlkit.array()
    aot = tomlkit.aot()
    for session in sessions:
        table = tomlkit.table()
        table["day"] = session["day"]
        table["type"] = session["type"]
        table["start"] = session["start"]
        table["end"] = session["end"]
        if "pool" in session:
            table["pool"] = session["pool"]
        if "notes" in session:
            table["notes"] = session["notes"]
        aot.append(table)
    return aot


def _build_access_hours_value(access_hours: list[dict[str, str]]):
    if not access_hours:
        return tomlkit.array()
    aot = tomlkit.aot()
    for access_hour in access_hours:
        table = tomlkit.table()
        table["day"] = access_hour["day"]
        table["start"] = access_hour["start"]
        table["end"] = access_hour["end"]
        table["label"] = access_hour["label"]
        if "notes" in access_hour:
            table["notes"] = access_hour["notes"]
        aot.append(table)
    return aot


def _build_access_exceptions_value(access_exceptions: list[dict[str, str]]):
    if not access_exceptions:
        return tomlkit.array()
    aot = tomlkit.aot()
    for access_exception in access_exceptions:
        table = tomlkit.table()
        table["date"] = access_exception["date"]
        table["start"] = access_exception["start"]
        table["end"] = access_exception["end"]
        table["label"] = access_exception["label"]
        table["reason"] = access_exception["reason"]
        if "notes" in access_exception:
            table["notes"] = access_exception["notes"]
        aot.append(table)
    return aot


def _build_closures_value(closures: list[dict[str, str]]):
    if not closures:
        return tomlkit.array()
    aot: AoT = tomlkit.aot()
    for closure in closures:
        table = tomlkit.table()
        table["start"] = closure["start"]
        table["end"] = closure["end"]
        table["reason"] = closure["reason"]
        if "start_time" in closure:
            table["start_time"] = closure["start_time"]
        if "end_time" in closure:
            table["end_time"] = closure["end_time"]
        aot.append(table)
    return aot


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
