from __future__ import annotations

from pathlib import Path

from schedules.merge import merge, pick_active_schedule, read_schedule_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_merge_is_noop_when_schedule_matches_existing(tmp_path):
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())

    snapshot = read_schedule_snapshot(target)
    snapshot.pop("_last_verified_at", None)
    result = merge(target, snapshot)

    assert result.written is False
    assert target.read_text() == source.read_text()


def test_merge_updates_only_schedule_fields(tmp_path):
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())

    snapshot = read_schedule_snapshot(target)
    result = merge(
        target,
        {
            "sessions": [
                {"day": "monday", "type": "lap_swim", "start": "06:00", "end": "08:00"},
                {"day": "tuesday", "type": "family_swim", "start": "12:00", "end": "14:00"},
                {"day": "wednesday", "type": "lap_swim", "start": "06:00", "end": "08:00"},
                {"day": "thursday", "type": "lap_swim", "start": "06:00", "end": "08:00"},
                {"day": "friday", "type": "lap_swim", "start": "06:00", "end": "08:00"},
            ],
            "closures": [{"start": "2026-05-25", "end": "2026-05-25", "reason": "Memorial Day"}],
            "effective_start": snapshot["effective_start"],
            "effective_end": snapshot.get("effective_end"),
        },
    )

    updated = target.read_text()
    assert result.written is True
    assert 'title = "Hamilton Pool"' in updated
    assert 'website = "https://sfrecpark.org/facilities/facility/details/Hamilton-Pool-215"' in updated
    assert "Memorial Day" in updated
    assert "A heated indoor pool" in updated


def test_merge_preserves_partial_day_closure_fields(tmp_path):
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())

    snapshot = read_schedule_snapshot(target)
    merge(
        target,
        {
            "sessions": snapshot["sessions"],
            "closures": [
                {
                    "start": "2026-05-21",
                    "end": "2026-05-21",
                    "reason": "Staff training",
                    "start_time": "11:00",
                    "end_time": "15:00",
                }
            ],
            "effective_start": snapshot["effective_start"],
            "effective_end": snapshot.get("effective_end"),
        },
    )

    snapshot_after = read_schedule_snapshot(target)
    assert snapshot_after["closures"] == [
        {
            "start": "2026-05-21",
            "end": "2026-05-21",
            "reason": "Staff training",
            "start_time": "11:00",
            "end_time": "15:00",
        }
    ]
    updated = target.read_text()
    assert 'start_time = "11:00"' in updated
    assert 'end_time = "15:00"' in updated


# ---- pick_active_schedule (the unified render-time predicate) --------------
#
# The new API takes a list of schedule dicts and a today_iso. It mirrors the
# Tera template's active_schedule block and JS's resolveScheduleForDate.

def _sched(effective_start: str, effective_end: str | None = None) -> dict:
    s = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}],
        "closures": [],
        "effective_start": effective_start,
    }
    if effective_end is not None:
        s["effective_end"] = effective_end
    return s


def test_pick_active_schedule_returns_in_window_entry():
    current = _sched("2026-03-17", "2026-06-06")
    upcoming = _sched("2026-06-09", "2026-08-15")
    active = pick_active_schedule([current, upcoming], "2026-05-01")
    assert active["effective_start"] == "2026-03-17"


def test_pick_active_schedule_picks_earliest_upcoming_on_gap_day():
    current = _sched("2026-03-17", "2026-06-06")
    upcoming = _sched("2026-06-09", "2026-08-15")
    active = pick_active_schedule([current, upcoming], "2026-06-07")
    assert active["effective_start"] == "2026-06-09"


def test_pick_active_schedule_returns_in_window_upcoming_once_it_starts():
    current = _sched("2026-03-17", "2026-06-06")
    upcoming = _sched("2026-06-09", "2026-08-15")
    active = pick_active_schedule([current, upcoming], "2026-07-01")
    assert active["effective_start"] == "2026-06-09"


def test_pick_active_schedule_falls_back_to_most_recent_past_when_no_in_window():
    expired = _sched("2026-03-17", "2026-06-06")
    active = pick_active_schedule([expired], "2026-07-01")
    assert active["effective_start"] == "2026-03-17"


def test_pick_active_schedule_picks_earliest_upcoming_before_any_starts():
    upcoming = _sched("2026-03-17", "2026-06-06")
    active = pick_active_schedule([upcoming], "2026-02-01")
    assert active["effective_start"] == "2026-03-17"


def test_pick_active_schedule_open_ended_treated_as_in_window():
    open_ended = _sched("2026-05-17")  # no effective_end
    active = pick_active_schedule([open_ended], "2027-12-31")
    assert active["effective_start"] == "2026-05-17"


def test_pick_active_schedule_prefers_latest_start_among_overlapping_in_window():
    older = _sched("2026-01-01", "2026-12-31")
    newer = _sched("2026-06-01", "2026-12-31")
    active = pick_active_schedule([older, newer], "2026-08-01")
    assert active["effective_start"] == "2026-06-01"


def test_pick_active_schedule_returns_none_for_empty_list():
    assert pick_active_schedule([], "2026-06-07") is None


# ---- merge() append-or-replace semantics ------------------------------------
#
# The merge function now matches existing schedules by effective_start and
# either replaces the matching entry or appends a new one. No queue/promote
# distinction — that concept is eliminated by the array shape.

_BASE_PAYLOAD = {
    "sessions": [
        {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
    ],
    "closures": [],
    "effective_start": "2026-03-17",
    "effective_end": "2026-06-06",
}


def _seed_pool(tmp_path: Path) -> Path:
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())
    merge(target, _BASE_PAYLOAD)
    return target


def test_merge_appends_new_schedule_with_different_effective_start(tmp_path):
    target = _seed_pool(tmp_path)
    incoming = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "06:30", "end": "08:30"}],
        "closures": [],
        "effective_start": "2026-06-09",
        "effective_end": "2026-08-15",
    }
    result = merge(target, incoming)

    assert result.written is True
    updated = target.read_text()
    # Both the base and the new schedule must coexist in the array.
    assert 'effective_start = "2026-03-17"' in updated
    assert 'effective_start = "2026-06-09"' in updated
    # Old upcoming_schedule key must NOT appear — that's the obsolete shape.
    assert "[extra.upcoming_schedule]" not in updated


def _read_schedules_array(target: Path) -> list[dict]:
    """Read the [[extra.schedules]] entries directly from a spot's frontmatter."""
    import tomllib
    text = target.read_text()
    frontmatter = text.split("+++", 2)[1]
    return tomllib.loads(frontmatter)["extra"].get("schedules", [])


def test_merge_replaces_existing_schedule_with_matching_effective_start(tmp_path):
    target = _seed_pool(tmp_path)
    updated_payload = {
        **_BASE_PAYLOAD,
        "sessions": [{"day": "wednesday", "type": "family_swim", "start": "10:00", "end": "12:00"}],
    }
    result = merge(target, updated_payload)

    assert result.written is True
    schedules = _read_schedules_array(target)
    matching = next(s for s in schedules if s["effective_start"] == "2026-03-17")
    assert matching["sessions"] == [
        {"day": "wednesday", "type": "family_swim", "start": "10:00", "end": "12:00"}
    ]


def test_merge_no_op_when_appending_an_entry_already_present(tmp_path):
    target = _seed_pool(tmp_path)
    result = merge(target, _BASE_PAYLOAD)
    assert result.written is False


def test_merge_sorts_schedules_by_effective_start(tmp_path):
    target = _seed_pool(tmp_path)
    # Add a future schedule first, then an even-later one — both should sort
    # into chronological order in the file.
    merge(target, {**_BASE_PAYLOAD, "effective_start": "2026-09-01", "effective_end": "2026-12-31"})
    merge(target, {**_BASE_PAYLOAD, "effective_start": "2026-06-09", "effective_end": "2026-08-15"})

    text = target.read_text()
    pos_base = text.index('effective_start = "2026-03-17"')
    pos_summer = text.index('effective_start = "2026-06-09"')
    pos_fall = text.index('effective_start = "2026-09-01"')
    assert pos_base < pos_summer < pos_fall


# ---- direct_sources year roll-forward ---------------------------------------


def test_resolve_yearless_date_keeps_same_year_for_near_future():
    from datetime import date
    from schedules.direct_sources import _resolve_yearless_date

    today = date(2026, 4, 1)
    assert _resolve_yearless_date(4, 30, today=today) == date(2026, 4, 30)


def test_resolve_yearless_date_keeps_same_year_for_recent_past():
    from datetime import date
    from schedules.direct_sources import _resolve_yearless_date

    today = date(2026, 4, 20)
    assert _resolve_yearless_date(4, 1, today=today) == date(2026, 4, 1)


def test_resolve_yearless_date_rolls_forward_for_distant_past():
    from datetime import date
    from schedules.direct_sources import _resolve_yearless_date

    today = date(2026, 12, 20)
    assert _resolve_yearless_date(1, 15, today=today) == date(2027, 1, 15)
