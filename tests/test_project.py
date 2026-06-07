import json
from pathlib import Path

import pytest

from schedules.project import ProjectError, project


def _valid_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _write_reviewed_json(data_root: Path, slug: str, pdf_sha256: str, envelope: dict) -> Path:
    review_dir = data_root / slug / f"2026-04-18-{pdf_sha256[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / "reviewed.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"Hamilton Pool\"\n\n[extra]\n+++\nBody\n")
    return path


def test_project_writes_sessions_to_content_md(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    reviewed = _write_reviewed_json(data, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-03-17\"" in rendered
    assert "last_verified_at = \"2026-04-18\"" in rendered
    assert rendered.count("[[extra.sessions]]") == 5


def test_project_queues_future_schedule_when_current_schedule_has_not_ended(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    current = _valid_envelope("hamilton-pool", "a" * 64)
    current["payload"]["schedule_effective_end"] = "2026-06-06"
    reviewed_current = _write_reviewed_json(data, "hamilton-pool", "a" * 64, current)
    _seed_content_md(content, "hamilton-pool")
    project(slug="hamilton-pool", reviewed_json_path=reviewed_current, content_spots_dir=content, as_of_date="2026-06-06")

    future = _valid_envelope("hamilton-pool", "b" * 64)
    future["reviewed_at"] = "2026-06-06"
    future["payload"]["schedule_effective"] = "2026-06-09"
    future["payload"]["schedule_effective_end"] = "2026-08-15"
    future["payload"]["sessions"][0]["start"] = "06:30"
    reviewed_future = _write_reviewed_json(data, "hamilton-pool", "b" * 64, future)
    project(slug="hamilton-pool", reviewed_json_path=reviewed_future, content_spots_dir=content, as_of_date="2026-06-06")

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-03-17\"" in rendered
    assert "schedule_effective_end = \"2026-06-06\"" in rendered
    assert "[extra.upcoming_schedule]" in rendered
    assert "last_verified_at = \"2026-06-06\"" in rendered
    assert "[[extra.upcoming_schedule.sessions]]" in rendered
    assert "start = \"06:30\"" in rendered


def test_project_promotes_queued_schedule_on_its_start_date(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    current = _valid_envelope("hamilton-pool", "a" * 64)
    current["payload"]["schedule_effective_end"] = "2026-06-06"
    reviewed_current = _write_reviewed_json(data, "hamilton-pool", "a" * 64, current)
    _seed_content_md(content, "hamilton-pool")
    project(slug="hamilton-pool", reviewed_json_path=reviewed_current, content_spots_dir=content, as_of_date="2026-06-06")

    future = _valid_envelope("hamilton-pool", "b" * 64)
    future["reviewed_at"] = "2026-06-06"
    future["payload"]["schedule_effective"] = "2026-06-09"
    future["payload"]["schedule_effective_end"] = "2026-08-15"
    future["payload"]["sessions"][0]["start"] = "06:30"
    reviewed_future = _write_reviewed_json(data, "hamilton-pool", "b" * 64, future)
    project(slug="hamilton-pool", reviewed_json_path=reviewed_future, content_spots_dir=content, as_of_date="2026-06-06")
    project(slug="hamilton-pool", reviewed_json_path=reviewed_future, content_spots_dir=content, as_of_date="2026-06-09")

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-06-09\"" in rendered
    assert "schedule_effective_end = \"2026-08-15\"" in rendered
    assert "[extra.upcoming_schedule]" not in rendered
    assert "start = \"06:30\"" in rendered


def test_project_preserves_next_queued_schedule_when_later_schedule_arrives_early(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    current = _valid_envelope("hamilton-pool", "a" * 64)
    current["payload"]["schedule_effective_end"] = "2026-06-06"
    reviewed_current = _write_reviewed_json(data, "hamilton-pool", "a" * 64, current)
    _seed_content_md(content, "hamilton-pool")
    project(slug="hamilton-pool", reviewed_json_path=reviewed_current, content_spots_dir=content, as_of_date="2026-06-06")

    summer = _valid_envelope("hamilton-pool", "b" * 64)
    summer["reviewed_at"] = "2026-06-06"
    summer["payload"]["schedule_effective"] = "2026-06-09"
    summer["payload"]["schedule_effective_end"] = "2026-08-15"
    summer["payload"]["sessions"][0]["start"] = "06:30"
    reviewed_summer = _write_reviewed_json(data, "hamilton-pool", "b" * 64, summer)
    project(slug="hamilton-pool", reviewed_json_path=reviewed_summer, content_spots_dir=content, as_of_date="2026-06-06")

    fall = _valid_envelope("hamilton-pool", "c" * 64)
    fall["reviewed_at"] = "2026-06-07"
    fall["payload"]["schedule_effective"] = "2026-08-18"
    fall["payload"]["schedule_effective_end"] = "2026-11-15"
    fall["payload"]["sessions"][0]["start"] = "07:30"
    reviewed_fall = _write_reviewed_json(data, "hamilton-pool", "c" * 64, fall)
    project(slug="hamilton-pool", reviewed_json_path=reviewed_fall, content_spots_dir=content, as_of_date="2026-06-07")

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-03-17\"" in rendered
    assert "[extra.upcoming_schedule]" in rendered
    assert "schedule_effective = \"2026-06-09\"" in rendered
    assert "schedule_effective_end = \"2026-08-15\"" in rendered
    assert "start = \"06:30\"" in rendered
    assert "2026-08-18" not in rendered
    assert "2026-11-15" not in rendered
    assert "start = \"07:30\"" not in rendered


def test_project_promotes_active_queued_schedule_before_queueing_later_schedule(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    current = _valid_envelope("hamilton-pool", "a" * 64)
    current["payload"]["schedule_effective_end"] = "2026-06-06"
    reviewed_current = _write_reviewed_json(data, "hamilton-pool", "a" * 64, current)
    _seed_content_md(content, "hamilton-pool")
    project(slug="hamilton-pool", reviewed_json_path=reviewed_current, content_spots_dir=content, as_of_date="2026-06-06")

    summer = _valid_envelope("hamilton-pool", "b" * 64)
    summer["reviewed_at"] = "2026-06-06"
    summer["payload"]["schedule_effective"] = "2026-06-09"
    summer["payload"]["schedule_effective_end"] = "2026-08-15"
    summer["payload"]["sessions"][0]["start"] = "06:30"
    reviewed_summer = _write_reviewed_json(data, "hamilton-pool", "b" * 64, summer)
    project(slug="hamilton-pool", reviewed_json_path=reviewed_summer, content_spots_dir=content, as_of_date="2026-06-06")

    fall = _valid_envelope("hamilton-pool", "c" * 64)
    fall["reviewed_at"] = "2026-08-01"
    fall["payload"]["schedule_effective"] = "2026-08-18"
    fall["payload"]["schedule_effective_end"] = "2026-11-15"
    fall["payload"]["sessions"][0]["start"] = "07:30"
    reviewed_fall = _write_reviewed_json(data, "hamilton-pool", "c" * 64, fall)
    project(slug="hamilton-pool", reviewed_json_path=reviewed_fall, content_spots_dir=content, as_of_date="2026-08-01")

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-06-09\"" in rendered
    assert "schedule_effective_end = \"2026-08-15\"" in rendered
    assert "[extra.upcoming_schedule]" in rendered
    assert "schedule_effective = \"2026-08-18\"" in rendered
    assert "schedule_effective_end = \"2026-11-15\"" in rendered


def test_project_preserves_timed_closures(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    envelope = _valid_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["closures"] = [
        {
            "start": "2026-05-21",
            "end": "2026-05-21",
            "reason": "Staff training",
            "start_time": "11:00",
            "end_time": "15:00",
        }
    ]
    reviewed = _write_reviewed_json(data, "hamilton-pool", "a" * 64, envelope)
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)

    rendered = (content / "hamilton-pool.md").read_text()
    assert "reason = \"Staff training\"" in rendered
    assert "start_time = \"11:00\"" in rendered
    assert "end_time = \"15:00\"" in rendered


def test_project_is_idempotent(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    reviewed = _write_reviewed_json(data, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)
    first = (content / "hamilton-pool.md").read_text()
    project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)
    second = (content / "hamilton-pool.md").read_text()
    assert first == second


def test_project_rejects_invalid_payload(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    envelope = _valid_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = envelope["payload"]["sessions"][:2]  # < 5
    reviewed = _write_reviewed_json(data, "hamilton-pool", "a" * 64, envelope)
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(ProjectError, match="fewer than 5"):
        project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)
