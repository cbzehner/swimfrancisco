"""One-shot migration: collapse [extra] (current schedule) + [extra.upcoming_schedule]
into a single [[extra.schedules]] array per spot file.

Run via: `uv --project schedule-tools run python scripts/migrate-schedules-to-array.py`

Idempotent: skips spots that have already been migrated (already have
[[extra.schedules]] and no schedule fields at root).
"""

from __future__ import annotations

from pathlib import Path

import tomlkit

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_SPOTS = REPO_ROOT / "content" / "spots"

# Fields that belong to a single schedule entry (move into [[extra.schedules]]).
SCHEDULE_FIELDS = [
    "effective_start",
    "effective_end",
    "last_verified_at",
    "schedule_basis",
    "sessions",
    "access_hours",
    "access_exceptions",
    "closures",
]

FRONTMATTER_DELIM = "+++"


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith(FRONTMATTER_DELIM + "\n"):
        raise ValueError("expected +++ frontmatter")
    end = text.find("\n" + FRONTMATTER_DELIM + "\n", len(FRONTMATTER_DELIM) + 1)
    if end == -1:
        raise ValueError("frontmatter not closed")
    return text[len(FRONTMATTER_DELIM) + 1 : end], text[end + len(FRONTMATTER_DELIM) + 2 :]


def schedule_entry_has_data(entry: dict) -> bool:
    return any(entry.get(k) for k in SCHEDULE_FIELDS)


def migrate_one(md_path: Path) -> str:
    """Returns one of: 'migrated', 'already-migrated', 'no-schedule', 'skipped'."""
    text = md_path.read_text()
    frontmatter, body = split_frontmatter(text)
    document = tomlkit.parse(frontmatter)
    extra = document.get("extra")
    if extra is None:
        return "skipped"

    if "schedules" in extra and not any(field in extra for field in SCHEDULE_FIELDS):
        return "already-migrated"

    # Collect the current schedule from root [extra].
    current_entry = {}
    for field in SCHEDULE_FIELDS:
        if field in extra:
            current_entry[field] = extra[field]

    # Collect the upcoming schedule.
    upcoming_table = extra.get("upcoming_schedule")
    upcoming_entry = {}
    if upcoming_table is not None:
        for field in SCHEDULE_FIELDS:
            if field in upcoming_table:
                upcoming_entry[field] = upcoming_table[field]

    if not schedule_entry_has_data(current_entry) and not schedule_entry_has_data(upcoming_entry):
        return "no-schedule"

    # Build the new array. Sort by effective_start so iteration is predictable.
    entries = []
    if schedule_entry_has_data(current_entry):
        entries.append(current_entry)
    if schedule_entry_has_data(upcoming_entry):
        entries.append(upcoming_entry)
    entries.sort(key=lambda e: e.get("effective_start") or "0000-00-00")

    # Strip the old shape from [extra] before adding the new one.
    for field in SCHEDULE_FIELDS:
        if field in extra:
            del extra[field]
    if "upcoming_schedule" in extra:
        del extra["upcoming_schedule"]

    # Build the new [[extra.schedules]] array of tables. Use array-of-tables
    # form so sessions/closures etc. remain readable (one block per session).
    schedules_aot = tomlkit.aot()
    for entry in entries:
        sched_table = tomlkit.table()
        # Scalar fields first, then array-of-tables fields (sessions etc.).
        for k in ("effective_start", "effective_end", "last_verified_at", "schedule_basis"):
            if k in entry:
                sched_table[k] = entry[k]
        for k in ("sessions", "access_hours", "access_exceptions", "closures"):
            if k in entry:
                value = entry[k]
                # Convert tomlkit AoT (preserve nesting) — these are arrays
                # of tables in the source, so reattach as AoT under the
                # schedule.
                if hasattr(value, "_body"):
                    sched_table[k] = value
                else:
                    sched_table[k] = value
        schedules_aot.append(sched_table)
    extra["schedules"] = schedules_aot

    updated = tomlkit.dumps(document).rstrip("\n")
    md_path.write_text(f"+++\n{updated}\n+++\n{body}")
    return "migrated"


def main() -> None:
    counts = {"migrated": 0, "already-migrated": 0, "no-schedule": 0, "skipped": 0}
    for md in sorted(CONTENT_SPOTS.glob("*.md")):
        if md.stem == "_index" or "." in md.stem:
            continue
        result = migrate_one(md)
        counts[result] += 1
        if result == "migrated":
            print(f"✓ {md.stem}")
        elif result == "no-schedule":
            print(f"– {md.stem} (no schedule fields)")
    print()
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
