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
            "schedule_effective": "2026-03-17",
            "schedule_effective_end": "2026-06-06",
        },
    )

    updated = target.read_text()
    assert result.written is True
    assert 'title = "Hamilton Pool"' in updated
    assert 'website = "https://sfrecpark.org/facilities/facility/details/Hamilton-Pool-215"' in updated
    assert "Memorial Day" in updated
    assert "A heated indoor pool" in updated
