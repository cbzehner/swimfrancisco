from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT

from ._time import pacific_today
from .models import MergeResult

DAY_ORDER = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def merge(
    pool_md_path: Path,
    extracted: dict[str, Any],
    *,
    last_verified_at: str | None = None,
    as_of_date: str | None = None,
) -> MergeResult:
    original_text = pool_md_path.read_text()
    frontmatter_text, body = _split_frontmatter(original_text)
    document = tomlkit.parse(frontmatter_text)
    extra = document.setdefault("extra", tomlkit.table())

    after = _normalized_schedule_payload(extracted)
    if as_of_date is None:
        as_of_date = pacific_today().isoformat()
    promoted = _promote_upcoming_schedule(extra, as_of_date)
    before = _schedule_from_table(extra)

    if _should_queue_upcoming(before, after):
        changed = _apply_queued_upcoming(extra, after, last_verified_at=last_verified_at, promoted=promoted)
    else:
        changed = _apply_current_schedule(extra, before, after, last_verified_at=last_verified_at, promoted=promoted)

    if not changed:
        return _merge_result(before, after, written=False)

    updated = tomlkit.dumps(document).rstrip("\n")
    pool_md_path.write_text(f"+++\n{updated}\n+++\n{body}")
    return _merge_result(before, after, written=True)


def _merge_result(before: dict[str, Any], after: dict[str, Any], *, written: bool) -> MergeResult:
    return MergeResult(
        prior_sessions_count=len(before["sessions"]),
        new_sessions_count=len(after["sessions"]),
        prior_closures_count=len(before["closures"]),
        new_closures_count=len(after["closures"]),
        written=written,
    )


def _apply_queued_upcoming(
    extra: Any,
    after: dict[str, Any],
    *,
    last_verified_at: str | None,
    promoted: bool,
) -> bool:
    existing = extra.get("upcoming_schedule")
    if _should_preserve_existing_upcoming(existing, after):
        return False
    existing_schedule = _schedule_from_table(existing) if existing else None
    existing_verified = existing.get("last_verified_at") if existing else None
    if not promoted and existing_schedule == after:
        if last_verified_at is None or existing_verified == last_verified_at:
            return False
    extra["upcoming_schedule"] = _build_schedule_table(after, last_verified_at=last_verified_at)
    return True


def _apply_current_schedule(
    extra: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    last_verified_at: str | None,
    promoted: bool,
) -> bool:
    if not promoted and before == after:
        if last_verified_at is None or extra.get("last_verified_at") == last_verified_at:
            return False
    _write_schedule_fields(extra, after, last_verified_at=last_verified_at)
    _drop_stale_upcoming(extra, after)
    return True


def read_schedule_snapshot(pool_md_path: Path) -> dict[str, Any]:
    frontmatter_text, _ = _split_frontmatter(pool_md_path.read_text())
    document = tomlkit.parse(frontmatter_text)
    extra = document.get("extra", {})
    return _schedule_from_table(extra)


def pick_active_schedule(extra: Any, today_iso: str) -> dict[str, Any]:
    """Display-time predicate: return the schedule that should be rendered
    for `today_iso`. Mirrors `resolveScheduleForDate` in static/js/helpers/
    board.mjs and the `active_extra` block in templates/spots/page.html —
    switches to the queued upcoming schedule once the current schedule has
    ended, so gap days surface the upcoming entry's pre-season closure copy.

    Distinct from `_promote_upcoming_schedule`, which writes upcoming over
    current in the frontmatter and uses a stricter predicate (only after
    today is inside the upcoming window).
    """
    current = _schedule_from_table(extra)
    upcoming_table = extra.get("upcoming_schedule")
    if not upcoming_table:
        return current
    upcoming = _schedule_from_table(upcoming_table)
    if _date_in_window(current, today_iso):
        return current
    current_end = current.get("effective_end")
    if isinstance(current_end, str) and current_end and today_iso > current_end:
        return upcoming
    return current


def _date_in_window(schedule: dict[str, Any], date_iso: str) -> bool:
    start = schedule.get("effective_start")
    end = schedule.get("effective_end")
    if isinstance(start, str) and start and date_iso < start:
        return False
    if isinstance(end, str) and end and date_iso > end:
        return False
    return True


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


def _should_queue_upcoming(current: dict[str, Any], incoming: dict[str, Any]) -> bool:
    current_end = current.get("effective_end")
    incoming_start = incoming.get("effective_start")
    return (
        isinstance(current_end, str)
        and isinstance(incoming_start, str)
        and incoming_start > current_end
    )


def _should_preserve_existing_upcoming(upcoming: Any, incoming: dict[str, Any]) -> bool:
    if not upcoming:
        return False
    upcoming_start = upcoming.get("effective_start")
    incoming_start = incoming.get("effective_start")
    return (
        isinstance(upcoming_start, str)
        and isinstance(incoming_start, str)
        and incoming_start > upcoming_start
    )


def _promote_upcoming_schedule(extra: Any, as_of_date: str) -> bool:
    # Promotion (writing upcoming over current in the frontmatter) is a
    # different concept from render-time selection. Promote only once we're
    # definitely INSIDE the upcoming window — i.e. as_of_date >= upcoming.start.
    # Render-time selection (templates/spots/page.html + static/js/helpers/board.mjs
    # resolveScheduleForDate) switches as soon as the current schedule has
    # ENDED, so during a gap day visitors see "Schedule starts <date>" sourced
    # from the still-queued upcoming entry.
    upcoming = extra.get("upcoming_schedule")
    if not upcoming:
        return False
    upcoming_start = upcoming.get("effective_start")
    if not isinstance(upcoming_start, str) or as_of_date < upcoming_start:
        return False
    schedule = _schedule_from_table(upcoming)
    last_verified_at = upcoming.get("last_verified_at")
    current_end = extra.get("effective_end")
    print(
        f"[merge] promoting upcoming_schedule: "
        f"as_of={as_of_date} current_end={current_end} "
        f"upcoming_start={upcoming_start} upcoming_end={upcoming.get('effective_end')}"
    )
    del extra["upcoming_schedule"]
    _write_schedule_fields(
        extra,
        schedule,
        last_verified_at=last_verified_at if isinstance(last_verified_at, str) else None,
    )
    return True


def _write_schedule_fields(
    target: Any,
    schedule: dict[str, Any],
    *,
    last_verified_at: str | None = None,
) -> None:
    target["sessions"] = _build_sessions_value(schedule["sessions"])
    if schedule["access_hours"]:
        target["access_hours"] = _build_access_hours_value(schedule["access_hours"])
    elif "access_hours" in target:
        del target["access_hours"]
    if schedule["access_exceptions"]:
        target["access_exceptions"] = _build_access_exceptions_value(schedule["access_exceptions"])
    elif "access_exceptions" in target:
        del target["access_exceptions"]
    target["closures"] = _build_closures_value(schedule["closures"])
    target["effective_start"] = schedule["effective_start"]
    if schedule["schedule_basis"] is not None:
        target["schedule_basis"] = schedule["schedule_basis"]
    elif "schedule_basis" in target:
        del target["schedule_basis"]
    if schedule["effective_end"] is not None:
        target["effective_end"] = schedule["effective_end"]
    elif "effective_end" in target:
        del target["effective_end"]
    if last_verified_at is not None:
        target["last_verified_at"] = last_verified_at


def _build_schedule_table(
    schedule: dict[str, Any],
    *,
    last_verified_at: str | None = None,
):
    table = tomlkit.table()
    _write_schedule_fields(table, schedule, last_verified_at=last_verified_at)
    return table


def _drop_stale_upcoming(target: Any, current: dict[str, Any]) -> None:
    upcoming = target.get("upcoming_schedule")
    if not upcoming:
        return
    upcoming_start = upcoming.get("effective_start")
    current_start = current.get("effective_start")
    if isinstance(upcoming_start, str) and isinstance(current_start, str) and upcoming_start <= current_start:
        del target["upcoming_schedule"]


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
            DAY_ORDER.get(item["day"], 99),
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
            DAY_ORDER.get(item["day"], 99),
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
