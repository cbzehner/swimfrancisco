from __future__ import annotations

from datetime import date
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


def merge(pool_md_path: Path, extracted: dict[str, Any]) -> MergeResult:
    original_text = pool_md_path.read_text()
    frontmatter_text, body = _split_frontmatter(original_text)
    document = tomlkit.parse(frontmatter_text)
    extra = document.setdefault("extra", tomlkit.table())

    before = read_schedule_snapshot(pool_md_path)
    after = _normalized_schedule_payload(extracted)
    changed = before != after

    if not changed:
        return MergeResult(
            prior_sessions_count=len(before["sessions"]),
            new_sessions_count=len(after["sessions"]),
            prior_closures_count=len(before["closures"]),
            new_closures_count=len(after["closures"]),
            written=False,
        )

    extra["sessions"] = _build_sessions_value(after["sessions"])
    extra["closures"] = _build_closures_value(after["closures"])
    extra["schedule_effective"] = after["schedule_effective"]
    if after["schedule_effective_end"] is not None:
        extra["schedule_effective_end"] = after["schedule_effective_end"]
    elif "schedule_effective_end" in extra:
        del extra["schedule_effective_end"]
    extra["last_verified_at"] = date.today().isoformat()

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
        "closures": _normalize_closures(list(extra.get("closures", []))),
        "schedule_effective": extra.get("schedule_effective"),
        "schedule_effective_end": extra.get("schedule_effective_end"),
    }


def _normalized_schedule_payload(extracted: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessions": _normalize_sessions(extracted.get("sessions", [])),
        "closures": _normalize_closures(extracted.get("closures", [])),
        "schedule_effective": extracted.get("schedule_effective"),
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


def _normalize_closures(raw_closures: list[dict]) -> list[dict[str, str]]:
    # Closures are facility-wide, all-day, date-only per the v1 contract
    # (see docs/schedules.md).
    normalized = []
    for closure in raw_closures:
        item: dict[str, str] = {
            "start": str(closure["start"]),
            "end": str(closure["end"]),
            "reason": str(closure["reason"]),
        }
        normalized.append(item)
    return sorted(normalized, key=lambda item: (item["start"], item["end"], item["reason"]))


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


def _build_closures_value(closures: list[dict[str, str]]):
    if not closures:
        return tomlkit.array()
    aot: AoT = tomlkit.aot()
    for closure in closures:
        table = tomlkit.table()
        table["start"] = closure["start"]
        table["end"] = closure["end"]
        table["reason"] = closure["reason"]
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

