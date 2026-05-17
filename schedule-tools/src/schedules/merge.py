from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT

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
) -> MergeResult:
    original_text = pool_md_path.read_text()
    frontmatter_text, body = _split_frontmatter(original_text)
    document = tomlkit.parse(frontmatter_text)
    extra = document.setdefault("extra", tomlkit.table())

    before = read_schedule_snapshot(pool_md_path)
    after = _normalized_schedule_payload(extracted)
    changed = before != after
    if last_verified_at is not None:
        changed = changed or extra.get("last_verified_at") != last_verified_at

    if not changed:
        return MergeResult(
            prior_sessions_count=len(before["sessions"]),
            new_sessions_count=len(after["sessions"]),
            prior_closures_count=len(before["closures"]),
            new_closures_count=len(after["closures"]),
            written=False,
        )

    extra["sessions"] = _build_sessions_value(after["sessions"])
    if after["access_hours"]:
        extra["access_hours"] = _build_access_hours_value(after["access_hours"])
    elif "access_hours" in extra:
        del extra["access_hours"]
    if after["access_exceptions"]:
        extra["access_exceptions"] = _build_access_exceptions_value(after["access_exceptions"])
    elif "access_exceptions" in extra:
        del extra["access_exceptions"]
    extra["closures"] = _build_closures_value(after["closures"])
    extra["schedule_effective"] = after["schedule_effective"]
    if after["schedule_basis"] is not None:
        extra["schedule_basis"] = after["schedule_basis"]
    elif "schedule_basis" in extra:
        del extra["schedule_basis"]
    if after["schedule_effective_end"] is not None:
        extra["schedule_effective_end"] = after["schedule_effective_end"]
    elif "schedule_effective_end" in extra:
        del extra["schedule_effective_end"]
    if last_verified_at is not None:
        extra["last_verified_at"] = last_verified_at

    updated = tomlkit.dumps(document).rstrip("\n")
    pool_md_path.write_text(f"+++\n{updated}\n+++\n{body}")
    return MergeResult(
        prior_sessions_count=len(before["sessions"]),
        new_sessions_count=len(after["sessions"]),
        prior_closures_count=len(before["closures"]),
        new_closures_count=len(after["closures"]),
        written=True,
    )


def read_schedule_snapshot(pool_md_path: Path) -> dict[str, Any]:
    frontmatter_text, _ = _split_frontmatter(pool_md_path.read_text())
    document = tomlkit.parse(frontmatter_text)
    extra = document.get("extra", {})
    return {
        "sessions": _normalize_sessions(list(extra.get("sessions", []))),
        "access_hours": _normalize_access_hours(list(extra.get("access_hours", []))),
        "access_exceptions": _normalize_access_exceptions(list(extra.get("access_exceptions", []))),
        "closures": _normalize_closures(list(extra.get("closures", []))),
        "schedule_effective": extra.get("schedule_effective"),
        "schedule_basis": extra.get("schedule_basis"),
        "schedule_effective_end": extra.get("schedule_effective_end"),
    }


def _normalized_schedule_payload(extracted: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessions": _normalize_sessions(extracted.get("sessions", [])),
        "access_hours": _normalize_access_hours(extracted.get("access_hours", [])),
        "access_exceptions": _normalize_access_exceptions(extracted.get("access_exceptions", [])),
        "closures": _normalize_closures(extracted.get("closures", [])),
        "schedule_effective": extracted.get("schedule_effective"),
        "schedule_basis": extracted.get("schedule_basis"),
        "schedule_effective_end": extracted.get("schedule_effective_end"),
    }


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
