from datetime import date
from pathlib import Path

import pytest

from schedules.health import coverage_gap, coverage_report

TODAY = date(2026, 10, 19)


def window(start, end=None):
    return {"effective_start": start, **({"effective_end": end} if end else {})}


def test_adjacent_successor_covers_expiring_schedule():
    assert coverage_gap([window("2026-10-01", "2026-10-20"), window("2026-10-21", "2026-11-01")], TODAY) is None


def test_successor_does_not_hide_gap():
    assert coverage_gap([window("2026-10-01", "2026-10-20"), window("2026-10-22")], TODAY) == {
        "gap_start": "2026-10-21", "next_start": "2026-10-22",
    }


def test_expiry_is_inclusive_and_warning_horizon_is_bounded():
    assert coverage_gap([window("2026-10-01", "2026-10-26")], TODAY) is None
    assert coverage_gap([window("2026-10-01", "2026-10-25")], TODAY) == {
        "gap_start": "2026-10-26", "next_start": None,
    }


def test_empty_and_expired_schedules_are_missing_today():
    expected = {"gap_start": "2026-10-19", "next_start": None}
    assert coverage_gap([], TODAY) == expected
    assert coverage_gap([window("2026-08-01", "2026-10-17")], TODAY) == expected


def test_open_ended_and_overlapping_windows_remain_covered():
    assert coverage_gap([window("2026-10-01")], TODAY) is None
    assert coverage_gap([window("2026-10-20"), window("2026-10-01", "2026-10-22")], TODAY) is None


def test_bad_date_ranges_fail_instead_of_claiming_coverage():
    with pytest.raises(ValueError):
        coverage_gap([window("2026-10-20", "2026-10-01")], TODAY)


def test_report_uses_canonical_pools_and_preserves_content(tmp_path):
    canonical = '+++\ntitle = "Pool"\n[extra]\ntype = "pool"\n+++\n'
    (tmp_path / "pool.md").write_text(canonical)
    (tmp_path / "pool.es.md").write_text("generated page")
    (tmp_path / "beach.md").write_text('+++\n[extra]\ntype = "open_water"\n+++\n')
    report = coverage_report(content_dir=tmp_path, today=TODAY)
    assert report["checked_pools"] == 1
    assert report["alerts"] == [{"slug": "pool", "title": "Pool", "gap_start": "2026-10-19", "next_start": None}]
    assert (tmp_path / "pool.md").read_text() == canonical


def test_coverage_job_remains_enabled_when_publication_is_disabled():
    workflow = (Path(__file__).parents[1] / ".github/workflows/schedules-extract.yml").read_text()
    job = workflow.split("\n  coverage:", 1)[1]
    assert "SCHEDULES_AUTOMATION_ENABLED" not in job
    assert "contents: read" in job
    assert "contents: write" not in job
    assert "schedules coverage" in job
    assert "issue?.body?.includes(fingerprint)" in job
