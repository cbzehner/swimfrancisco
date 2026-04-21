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
    assert rendered.count("[[extra.sessions]]") == 5


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
