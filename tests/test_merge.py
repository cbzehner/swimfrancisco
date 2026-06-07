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


# ---- merge() queued-upcoming write paths ------------------------------------
#
# Earlier refactor split merge() into _apply_queued_upcoming /
# _apply_current_schedule / _promote_upcoming_schedule / _drop_stale_upcoming /
# _should_preserve_existing_upcoming. These integration tests exercise each
# branch through the public `merge()` API so regressions in the writer surface.

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
    """Copy a real pool's frontmatter so merge() has a real file to round-trip."""
    source = ROOT / "content" / "spots" / "hamilton-pool.md"
    target = tmp_path / source.name
    target.write_text(source.read_text())
    merge(target, _BASE_PAYLOAD)
    return target


def test_merge_queues_upcoming_when_incoming_starts_after_current_ends(tmp_path):
    target = _seed_pool(tmp_path)
    incoming = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "06:30", "end": "08:30"}],
        "closures": [],
        "effective_start": "2026-06-09",
        "effective_end": "2026-08-15",
    }
    result = merge(target, incoming, as_of_date="2026-04-15")

    assert result.written is True
    updated = target.read_text()
    assert "[extra.upcoming_schedule]" in updated
    assert 'effective_start = "2026-06-09"' in updated
    # Current schedule's effective_start must be preserved unchanged.
    assert 'effective_start = "2026-03-17"' in updated


def test_merge_preserves_closer_queued_upcoming_against_farther_one(tmp_path):
    target = _seed_pool(tmp_path)
    summer = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "06:30", "end": "08:30"}],
        "closures": [],
        "effective_start": "2026-06-09",
        "effective_end": "2026-08-15",
    }
    merge(target, summer, as_of_date="2026-04-15")

    # A farther-out schedule (fall) arrives next. The closer queued summer
    # must win — replacing it with fall would skip the summer transition
    # the user is about to live through.
    fall = {**summer, "effective_start": "2026-09-01", "effective_end": "2026-12-15"}
    result = merge(target, fall, as_of_date="2026-04-16")
    assert result.written is False
    assert 'effective_start = "2026-06-09"' in target.read_text()


def test_merge_promotes_upcoming_on_or_after_its_start_date(tmp_path):
    target = _seed_pool(tmp_path)
    summer = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "06:30", "end": "08:30"}],
        "closures": [],
        "effective_start": "2026-06-09",
        "effective_end": "2026-08-15",
    }
    merge(target, summer, as_of_date="2026-04-15")
    assert "[extra.upcoming_schedule]" in target.read_text()

    # The next merge sees as_of_date inside the upcoming window. Promotion
    # must overwrite current and delete the upcoming_schedule key entirely
    # (re-merging the same payload, since the source we'd normally re-fetch
    # produces the same data).
    result = merge(target, summer, as_of_date="2026-06-10")
    assert result.written is True
    updated = target.read_text()
    assert "[extra.upcoming_schedule]" not in updated
    assert 'effective_start = "2026-06-09"' in updated
    assert 'effective_end = "2026-08-15"' in updated


def test_merge_drops_stale_upcoming_when_current_overtakes_it(tmp_path):
    # Three-step setup so the final merge() hits _apply_current_schedule
    # (not the queuing branch) with an incoming start that overtakes the
    # queued upcoming — the narrow window where _drop_stale_upcoming fires.
    target = _seed_pool(tmp_path)

    # Step 1: queue summer (2026-06-09 → 2026-08-15).
    merge(target, {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "06:30", "end": "08:30"}],
        "closures": [],
        "effective_start": "2026-06-09",
        "effective_end": "2026-08-15",
    }, as_of_date="2026-04-15")
    assert "[extra.upcoming_schedule]" in target.read_text()

    # Step 2: extend current's effective_end to year-end so the next merge
    # doesn't trigger queuing. (`_should_queue_upcoming` only fires when
    # incoming.start > current.end.)
    merge(target, {
        **_BASE_PAYLOAD,
        "effective_end": "2026-12-31",
    }, as_of_date="2026-04-16")

    # Step 3: incoming current with effective_start past upcoming.start but
    # within current.end window. _drop_stale_upcoming must remove the
    # now-superseded upcoming so the next promote doesn't write obsolete data.
    merge(target, {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:30", "end": "09:00"}],
        "closures": [],
        "effective_start": "2026-07-01",
        "effective_end": "2026-12-31",
    }, as_of_date="2026-05-15")

    updated = target.read_text()
    assert "[extra.upcoming_schedule]" not in updated
    assert 'effective_start = "2026-07-01"' in updated


# ---- direct_sources year roll-forward ---------------------------------------


def test_resolve_yearless_date_keeps_same_year_for_near_future():
    from datetime import date
    from schedules.direct_sources import _resolve_yearless_date

    today = date(2026, 4, 1)
    # April 30 is in the future from April 1, same year.
    assert _resolve_yearless_date(4, 30, today=today) == date(2026, 4, 30)


def test_resolve_yearless_date_keeps_same_year_for_recent_past():
    from datetime import date
    from schedules.direct_sources import _resolve_yearless_date

    today = date(2026, 4, 20)
    # April 1 is 19 days in the past — within the 30-day grace window.
    assert _resolve_yearless_date(4, 1, today=today) == date(2026, 4, 1)


def test_resolve_yearless_date_rolls_forward_for_distant_past():
    from datetime import date
    from schedules.direct_sources import _resolve_yearless_date

    today = date(2026, 12, 20)
    # January 15 is 11 months in the past; assume the source meant next year.
    assert _resolve_yearless_date(1, 15, today=today) == date(2027, 1, 15)
