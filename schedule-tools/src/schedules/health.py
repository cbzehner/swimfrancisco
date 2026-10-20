"""Read-only checks of the schedule coverage the site actually publishes."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tomllib

from ._time import pacific_today
from .paths import CONTENT_SPOTS_DIR


def coverage_gap(schedules: list[dict], today: date, *, days: int = 7) -> dict | None:
    """Find the first uncovered date through the inclusive warning horizon.

    Coverage means published schedule knowledge, including explicit closures
    and facility access hours. It does not mean the pool is open for swimming.
    Adjacent windows cover a transition; a later successor cannot hide a gap.
    """
    if days < 0:
        raise ValueError("Warning horizon cannot be negative")
    windows = sorted(
        (date.fromisoformat(str(item["effective_start"])),
         date.fromisoformat(str(item["effective_end"])) if item.get("effective_end") else date.max)
        for item in schedules
    )
    cursor = today
    horizon = today + timedelta(days=days)
    for start, end in windows:
        if end < start:
            raise ValueError("Schedule ends before it starts")
        if end < cursor:
            continue
        if start > cursor:
            return {"gap_start": cursor.isoformat(), "next_start": start.isoformat()}
        if end >= horizon:
            return None
        cursor = end + timedelta(days=1)
    return {"gap_start": cursor.isoformat(), "next_start": None}


def coverage_report(*, content_dir: Path = CONTENT_SPOTS_DIR, today: date | None = None,
                    days: int = 7) -> dict:
    today = today or pacific_today()
    alerts = []
    checked = 0
    for path in sorted(content_dir.glob("*.md")):
        if "." in path.stem or path.stem.startswith("_"):
            continue
        parts = path.read_text().split("+++", 2)
        if len(parts) != 3:
            raise ValueError(f"Missing TOML frontmatter: {path.name}")
        page = tomllib.loads(parts[1])
        extra = page.get("extra", {})
        if extra.get("type") != "pool":
            continue
        checked += 1
        gap = coverage_gap(extra.get("schedules", []), today, days=days)
        if gap:
            alerts.append({"slug": path.stem, "title": page.get("title", path.stem), **gap})
    if not checked:
        raise ValueError("No canonical pool schedules found")
    return {"checked_at": today.isoformat(), "horizon_days": days, "checked_pools": checked, "alerts": alerts}
