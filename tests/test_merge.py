from __future__ import annotations

from pathlib import Path

from schedules.merge import merge, read_schedule_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_merge_is_noop_when_schedule_matches_existing(tmp_path):
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())

    snapshot = read_schedule_snapshot(target)
    result = merge(target, snapshot)

    assert result.written is False
    assert target.read_text() == source.read_text()


def test_merge_updates_only_schedule_fields(tmp_path):
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())

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
            "effective_start": "2026-03-17",
            "effective_end": "2026-06-06",
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

    merge(
        target,
        {
            "sessions": read_schedule_snapshot(target)["sessions"],
            "closures": [
                {
                    "start": "2026-05-21",
                    "end": "2026-05-21",
                    "reason": "Staff training",
                    "start_time": "11:00",
                    "end_time": "15:00",
                }
            ],
            "effective_start": "2026-03-17",
            "effective_end": "2026-06-06",
        },
    )

    snapshot = read_schedule_snapshot(target)
    assert snapshot["closures"] == [
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


def _extra_with(current_start: str, current_end: str | None = None, upcoming_start: str | None = None, upcoming_end: str | None = None) -> dict:
    extra: dict = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}],
        "closures": [],
        "effective_start": current_start,
    }
    if current_end is not None:
        extra["effective_end"] = current_end
    if upcoming_start is not None:
        extra["upcoming_schedule"] = {
            "sessions": [{"day": "tuesday", "type": "lap_swim", "start": "09:00", "end": "10:00"}],
            "closures": [],
            "effective_start": upcoming_start,
        }
        if upcoming_end is not None:
            extra["upcoming_schedule"]["effective_end"] = upcoming_end
    return extra


def test_pick_active_schedule_returns_current_inside_window():
    from schedules.merge import pick_active_schedule

    extra = _extra_with("2026-03-17", "2026-06-06", "2026-06-09", "2026-08-15")
    active = pick_active_schedule(extra, "2026-05-01")
    assert active["effective_start"] == "2026-03-17"


def test_pick_active_schedule_returns_upcoming_after_current_ends():
    from schedules.merge import pick_active_schedule

    extra = _extra_with("2026-03-17", "2026-06-06", "2026-06-09", "2026-08-15")
    active = pick_active_schedule(extra, "2026-06-07")
    assert active["effective_start"] == "2026-06-09"


def test_pick_active_schedule_returns_upcoming_inside_upcoming_window():
    from schedules.merge import pick_active_schedule

    extra = _extra_with("2026-03-17", "2026-06-06", "2026-06-09", "2026-08-15")
    active = pick_active_schedule(extra, "2026-07-01")
    assert active["effective_start"] == "2026-06-09"


def test_pick_active_schedule_keeps_current_when_no_upcoming():
    from schedules.merge import pick_active_schedule

    extra = _extra_with("2026-03-17", "2026-06-06")
    active = pick_active_schedule(extra, "2026-07-01")
    assert active["effective_start"] == "2026-03-17"


def test_pick_active_schedule_keeps_current_before_its_start():
    from schedules.merge import pick_active_schedule

    extra = _extra_with("2026-03-17", "2026-06-06", "2026-06-09")
    active = pick_active_schedule(extra, "2026-02-01")
    assert active["effective_start"] == "2026-03-17"
