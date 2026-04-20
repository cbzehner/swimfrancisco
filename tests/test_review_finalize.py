import json
from pathlib import Path

import pytest

from schedules.review import FinalizeError, finalize_draft


def _valid_draft_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "version": 1,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-19",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "reviewer edits",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _write_draft(drafts_root: Path, slug: str, pdf_sha256: str, envelope: dict) -> Path:
    slug_dir = drafts_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"2026-04-19-{pdf_sha256[:12]}.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")
    return path


def test_finalize_happy_path(tmp_path):
    drafts = tmp_path / "drafts"
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, _valid_draft_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    result = finalize_draft(
        draft_path=draft,
        snapshots_root=snapshots,
        content_spots_dir=content,
    )

    assert result.is_relative_to(snapshots)
    assert not draft.exists()
    assert (snapshots / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json").exists()
    assert "[[extra.sessions]]" in (content / "hamilton-pool.md").read_text()


def test_finalize_rejects_malformed_json(tmp_path):
    drafts = tmp_path / "drafts"
    (drafts / "hamilton-pool").mkdir(parents=True)
    draft = drafts / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json"
    draft.write_text("{ bogus")

    with pytest.raises(FinalizeError, match="invalid JSON"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=tmp_path / "reviewed-snapshots",
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert draft.exists()


def test_finalize_rejects_schema_invalid(tmp_path):
    drafts = tmp_path / "drafts"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    del envelope["summary"]  # violates required
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, envelope)

    with pytest.raises(FinalizeError, match="summary"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=tmp_path / "reviewed-snapshots",
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert draft.exists()


def test_finalize_rejects_validate_failure(tmp_path):
    drafts = tmp_path / "drafts"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = envelope["payload"]["sessions"][:2]
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, envelope)

    with pytest.raises(FinalizeError, match="fewer than 5"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=tmp_path / "reviewed-snapshots",
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert draft.exists()


def test_finalize_aborts_on_destination_conflict(tmp_path):
    drafts = tmp_path / "drafts"
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, _valid_draft_envelope("hamilton-pool", "a" * 64))
    (snapshots / "hamilton-pool").mkdir(parents=True)
    (snapshots / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json").write_text("{}")
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(FinalizeError, match="already exists"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=snapshots,
            content_spots_dir=content,
        )
    assert draft.exists()
