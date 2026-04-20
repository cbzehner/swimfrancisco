import json
from pathlib import Path

import pytest

from schedules.review import ReviewCandidate, find_review_candidates


def _write_artifact(root: Path, slug: str, pdf_sha256: str, provider: str = "gemini") -> Path:
    artifact_dir = root / slug / pdf_sha256[:12]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    provider_path = artifact_dir / f"{provider}-model.json"
    provider_path.write_text(json.dumps({
        "slug": slug,
        "provider": provider,
        "model": "model",
        "pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))
    return provider_path


def _write_snapshot(root: Path, slug: str, pdf_sha256: str) -> Path:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"2026-04-10-{pdf_sha256[:12]}.json"
    path.write_text(json.dumps({"pdf_sha256": pdf_sha256, "slug": slug}))
    return path


def _write_pdf(root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"{date}-{pdf_sha256[:12]}.pdf"
    path.write_bytes(b"%PDF-fake")
    return path


def test_find_review_candidates_empty(tmp_path):
    result = find_review_candidates(
        artifacts_root=tmp_path / "artifacts",
        snapshots_root=tmp_path / "reviewed-snapshots",
        pdfs_root=tmp_path / "pdfs",
    )
    assert result == []


def test_find_review_candidates_returns_unreviewed(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)

    candidates = find_review_candidates(
        artifacts_root=artifacts, snapshots_root=snapshots, pdfs_root=pdfs,
    )
    assert len(candidates) == 1
    assert candidates[0].slug == "hamilton-pool"
    assert candidates[0].pdf_sha256 == "a" * 64


def test_find_review_candidates_skips_already_reviewed(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64)

    assert find_review_candidates(
        artifacts_root=artifacts, snapshots_root=snapshots, pdfs_root=pdfs,
    ) == []


def test_find_review_candidates_orders_by_pdf_date_then_slug(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "zulu-pool", "a" * 64)
    _write_artifact(artifacts, "alpha-pool", "b" * 64)
    _write_artifact(artifacts, "bravo-pool", "c" * 64)
    _write_pdf(pdfs, "zulu-pool", "2026-01-01", "a" * 64)
    _write_pdf(pdfs, "alpha-pool", "2026-03-01", "b" * 64)
    _write_pdf(pdfs, "bravo-pool", "2026-03-01", "c" * 64)

    candidates = find_review_candidates(
        artifacts_root=artifacts, snapshots_root=snapshots, pdfs_root=pdfs,
    )
    assert [c.slug for c in candidates] == ["zulu-pool", "alpha-pool", "bravo-pool"]


def test_find_review_candidates_filters_by_slug(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_artifact(artifacts, "balboa-pool", "b" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_pdf(pdfs, "balboa-pool", "2026-04-01", "b" * 64)

    candidates = find_review_candidates(
        artifacts_root=artifacts,
        snapshots_root=snapshots,
        pdfs_root=pdfs,
        only_slug="balboa-pool",
    )
    assert [c.slug for c in candidates] == ["balboa-pool"]
