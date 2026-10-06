"""Projecting a reviewed envelope into a spot's content file.

`project` validates the envelope's payload and hands it to `merge`, so
the append/replace/prune semantics of the schedules array are asserted
against `merge` directly in test_merge.py; what lives here is the
envelope-to-content path and the `schedules project` CLI wrapped around
it.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.project import ProjectError, project
from conftest import pin_publish_clock


def _valid_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "payload": {
            "effective_start": "2026-03-17",
            "schedule_basis": "swim_schedule",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00", "evidence": "Lap Swim 7-8am"}
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


def test_project_writes_sessions_to_content_md(tmp_path, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 4, 18))
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    reviewed = _write_reviewed_json(data, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)

    rendered = (content / "hamilton-pool.md").read_text()
    assert "effective_start = \"2026-03-17\"" in rendered
    assert "last_verified_at = \"2026-04-18\"" in rendered
    assert rendered.count("[[extra.schedules.sessions]]") == 5
    assert "[[extra.schedules]]" in rendered


def test_project_rejects_invalid_payload(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    envelope = _valid_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = envelope["payload"]["sessions"][:2]  # < 5
    reviewed = _write_reviewed_json(data, "hamilton-pool", "a" * 64, envelope)
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(ProjectError, match="fewer than 5"):
        project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)


def test_project_drops_long_expired_windows_but_keeps_the_recent_one(tmp_path, monkeypatch):
    """The publish path, not a separate cleanup, retires stale windows."""
    monkeypatch.setattr("schedules.merge.pacific_today", lambda: date(2026, 9, 11))
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_content_md(content, "hamilton-pool")
    for index, (sha, start, end) in enumerate(
        [
            ("a" * 64, "2026-01-05", "2026-07-13"),  # ended 60 days before publish
            ("b" * 64, "2026-07-14", "2026-08-31"),  # ended 11 days before publish
            ("c" * 64, "2026-09-01", "2026-12-12"),  # current
        ]
    ):
        envelope = _valid_envelope("hamilton-pool", sha)
        envelope["payload"]["effective_start"] = start
        envelope["payload"]["effective_end"] = end
        envelope["payload"]["sessions"][0]["start"] = f"0{index + 5}:00"
        reviewed = _write_reviewed_json(data, "hamilton-pool", sha, envelope)
        project(slug="hamilton-pool", reviewed_json_path=reviewed, content_spots_dir=content)

    rendered = (content / "hamilton-pool.md").read_text()
    assert rendered.count("[[extra.schedules]]") == 2
    assert 'effective_start = "2026-01-05"' not in rendered
    assert 'effective_start = "2026-07-14"' in rendered
    assert 'effective_start = "2026-09-01"' in rendered


# ---- the `schedules project` CLI wrapper ------------------------------------


def test_cli_project_happy_path(tmp_path, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 4, 18))
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _write_reviewed_json(data, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    monkeypatch.setattr("schedules.cli.DATA_DIR", data)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    result = CliRunner().invoke(cli, ["project", "hamilton-pool"])

    assert result.exit_code == 0, result.output
    assert "hamilton-pool.md" in result.output
    assert "[[extra.schedules.sessions]]" in (content / "hamilton-pool.md").read_text()


def test_cli_project_missing_slug_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules.cli.DATA_DIR", tmp_path / "data")
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", tmp_path / "content" / "spots")

    result = CliRunner().invoke(cli, ["project", "ghost-pool"])

    assert result.exit_code != 0
    assert "no review dir" in result.output
