import json
import shutil
from pathlib import Path

import pytest

from schedules.project import ProjectError, project


REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "version": 1,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "test",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _write_snapshot(root: Path, slug: str, pdf_sha256: str, envelope: dict) -> Path:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"2026-04-18-{pdf_sha256[:12]}.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"Hamilton Pool\"\n\n[extra]\n+++\nBody\n")
    return path


def test_project_writes_sessions_to_content_md(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-03-17\"" in rendered
    assert rendered.count("[[extra.sessions]]") == 5


def test_project_rejects_draft_path(tmp_path):
    drafts = tmp_path / "reviewed-snapshot-drafts"
    content = tmp_path / "content" / "spots"
    _write_snapshot(drafts, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(ProjectError, match="draft"):
        project(slug="hamilton-pool", snapshots_root=drafts, content_spots_dir=content)


def test_project_rejects_missing_slug(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    with pytest.raises(ProjectError, match="no reviewed snapshot"):
        project(slug="ghost-pool", snapshots_root=snapshots, content_spots_dir=content)


def test_project_is_idempotent(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)
    first = (content / "hamilton-pool.md").read_text()
    project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)
    second = (content / "hamilton-pool.md").read_text()
    assert first == second


def test_project_rejects_invalid_payload(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    envelope = _valid_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = envelope["payload"]["sessions"][:2]  # < 5
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64, envelope)
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(ProjectError, match="fewer than 5"):
        project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)
