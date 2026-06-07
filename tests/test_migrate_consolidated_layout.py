from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from migrate_consolidated_layout import main_fn  # noqa: E402


PDF_SHA = "a" * 64
PDF_SHA12 = PDF_SHA[:12]
SLUG = "hamilton-pool"
DATE = "2026-04-19"


def _seed_legacy_tree(data_root: Path) -> None:
    # PDF
    pdfs_dir = data_root / "pdfs" / SLUG
    pdfs_dir.mkdir(parents=True)
    (pdfs_dir / f"{DATE}-{PDF_SHA12}.pdf").write_bytes(b"%PDF-fake")

    # Artifacts (meta + two provider files)
    artifacts_dir = data_root / "artifacts" / SLUG / PDF_SHA12
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "meta.json").write_text(json.dumps({
        "slug": SLUG,
        "pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": PDF_SHA,
        "pdf_page_count": 1,
        "pdf_text_sha256": "deadbeef",
        "prompt_hash": "PROMPT_SHA",
        "schema_hash": "SCHEMA_SHA",
        "updated_at": "2026-04-18T00:00:00+00:00",
    }))
    (artifacts_dir / "gemini-model.json").write_text(json.dumps({
        "slug": SLUG,
        "provider": "gemini",
        "model": "model",
        "pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": PDF_SHA,
        "pdf_page_count": 1,
        "pdf_text_sha256": "deadbeef",
        "extracted_at": "2026-04-18T00:00:00+00:00",
        "payload": {
            "effective_start": "2026-03-17",
            "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}],
            "closures": [],
        },
    }))
    (artifacts_dir / "anthropic-claude.json").write_text(json.dumps({
        "slug": SLUG,
        "provider": "anthropic",
        "model": "claude",
        "pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": PDF_SHA,
        "payload": {"effective_start": "2026-03-17", "sessions": [], "closures": []},
    }))

    # Reviewed snapshot (with legacy fields)
    snap_dir = data_root / "reviewed-snapshots" / SLUG
    snap_dir.mkdir(parents=True)
    (snap_dir / f"{DATE}-{PDF_SHA12}.json").write_text(json.dumps({
        "slug": SLUG,
        "pdf_sha256": PDF_SHA,
        "reviewed_at": DATE,
        "source_pdf_url": "https://example.com/x.pdf",
        "version": 1,
        "reviewed_by": "Chris <c@example.com>",
        "reviewed_against": {"gemini": "sha"},
        "payload": {
            "effective_start": "2026-03-17",
            "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}],
            "closures": [],
        },
    }))

    # Legacy sidecar files
    (data_root / "extraction-state.json").write_text("{}")
    (data_root / "pdf-cache-index.json").write_text("{}")


def test_migrate_moves_pdf_and_builds_review_dir(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    _seed_legacy_tree(data_root)

    summary = main_fn(data_root, REPO_ROOT)

    review_dir = data_root / SLUG / f"{DATE}-{PDF_SHA12}"
    assert (review_dir / "source.pdf").exists()
    assert (review_dir / "reviewed.json").exists()
    assert (review_dir / "gemini-model.json").exists()
    assert (review_dir / "anthropic-claude.json").exists()
    assert not (review_dir / "meta.json").exists()
    assert summary.reviews_migrated == 1
    assert summary.providers_migrated == 2
    assert summary.pdfs_moved == 1
    assert summary.meta_files_deleted == 1


def test_migrate_strips_envelope_legacy_fields(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    _seed_legacy_tree(data_root)
    main_fn(data_root, REPO_ROOT)

    envelope = json.loads((data_root / SLUG / f"{DATE}-{PDF_SHA12}" / "reviewed.json").read_text())
    assert "version" not in envelope
    assert "reviewed_by" not in envelope
    assert "reviewed_against" not in envelope
    assert envelope["slug"] == SLUG
    assert envelope["source_pdf_url"] == "https://example.com/x.pdf"


def test_migrate_makes_provider_json_self_describing(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    _seed_legacy_tree(data_root)
    main_fn(data_root, REPO_ROOT)

    provider = json.loads((data_root / SLUG / f"{DATE}-{PDF_SHA12}" / "gemini-model.json").read_text())
    assert "slug" not in provider
    assert "pdf_page_count" not in provider
    assert "pdf_text_sha256" not in provider
    assert provider["source_pdf_url"] == "https://example.com/x.pdf"
    assert provider["pdf_sha256"] == PDF_SHA
    assert provider["prompt_sha256"] == "PROMPT_SHA"
    assert provider["schema_sha256"] == "SCHEMA_SHA"
    assert provider["extracted_at"] == "2026-04-18T00:00:00+00:00"


def test_migrate_removes_old_trees_and_sidecars(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    _seed_legacy_tree(data_root)
    main_fn(data_root, REPO_ROOT)

    assert not (data_root / "pdfs").exists()
    assert not (data_root / "artifacts").exists()
    assert not (data_root / "reviewed-snapshots").exists()
    assert not (data_root / "extraction-state.json").exists()
    assert not (data_root / "pdf-cache-index.json").exists()


def test_migrate_is_idempotent(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    _seed_legacy_tree(data_root)
    first = main_fn(data_root, REPO_ROOT)
    assert first.reviews_migrated == 1

    # Snapshot the post-migrate state
    before = {p.relative_to(data_root): p.read_bytes() for p in data_root.rglob("*") if p.is_file()}

    second = main_fn(data_root, REPO_ROOT)
    assert second.reviews_migrated == 0
    assert second.providers_migrated == 0

    after = {p.relative_to(data_root): p.read_bytes() for p in data_root.rglob("*") if p.is_file()}
    assert before == after
