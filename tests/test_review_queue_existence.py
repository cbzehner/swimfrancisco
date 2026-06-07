"""Queue semantics: `reviewed.json` existence gates visibility in the review queue.

No git repo needed — filesystem alone is the source of truth.
"""
from __future__ import annotations

import json
from pathlib import Path

from schedules.review import find_review_candidates


SLUG = "hamilton-pool"
PDF_SHA = "a" * 64
SHA12 = PDF_SHA[:12]
DATE = "2026-04-01"


def _review_dir(data_root: Path) -> Path:
    return data_root / SLUG / f"{DATE}-{SHA12}"


def _seed_provider_json(review_dir: Path) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "gemini-model.json").write_text(json.dumps({
        "provider": "gemini",
        "model": "model",
        "source_pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": PDF_SHA,
        "payload": {"effective_start": "2026-03-17", "sessions": [], "closures": []},
    }))


def _seed_reviewed_json(review_dir: Path) -> None:
    (review_dir / "reviewed.json").write_text(json.dumps({
        "slug": SLUG,
        "pdf_sha256": PDF_SHA,
        "reviewed_at": "2026-04-10",
        "source_pdf_url": "https://example.com/x.pdf",
        "payload": {},
    }))


def test_candidate_appears_when_reviewed_json_absent(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root)
    _seed_provider_json(review_dir)

    candidates = find_review_candidates(data_root=data_root)
    assert len(candidates) == 1
    assert candidates[0].slug == SLUG
    assert candidates[0].review_dir == review_dir


def test_candidate_disappears_once_reviewed_json_is_written(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root)
    _seed_provider_json(review_dir)

    # Before: visible.
    assert len(find_review_candidates(data_root=data_root)) == 1

    # After: hidden.
    _seed_reviewed_json(review_dir)
    assert find_review_candidates(data_root=data_root) == []
