import json
from pathlib import Path

from schedules.review import find_review_candidates


def _write_provider_json(review_dir: Path, pdf_sha256: str, provider: str = "gemini") -> Path:
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"{provider}-model.json"
    path.write_text(json.dumps({
        "provider": provider,
        "model": "model",
        "source_pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "effective_start": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))
    return path


def _write_reviewed(review_dir: Path, slug: str, pdf_sha256: str) -> Path:
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / "reviewed.json"
    path.write_text(json.dumps({
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-10",
        "source_pdf_url": "https://example.com/x.pdf",
        "payload": {},
    }))
    return path


def _review_dir(data_root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    return data_root / slug / f"{date}-{pdf_sha256[:12]}"


def test_find_review_candidates_empty(tmp_path):
    assert find_review_candidates(data_root=tmp_path / "data") == []


def test_find_review_candidates_returns_unreviewed(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_provider_json(review_dir, "a" * 64)

    candidates = find_review_candidates(data_root=data_root)
    assert len(candidates) == 1
    assert candidates[0].slug == "hamilton-pool"
    assert candidates[0].pdf_sha256 == "a" * 64
    assert candidates[0].fetch_date == "2026-04-01"
    assert candidates[0].review_dir == review_dir
    assert candidates[0].source_path == review_dir / "source.pdf"


def test_find_review_candidates_uses_csv_source_when_pdf_missing(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "koret-center", "2026-04-01", "a" * 64)
    _write_provider_json(review_dir, "a" * 64, provider="direct")
    (review_dir / "source.csv").write_text("Monday Hours: 7am-7pm\n")

    candidates = find_review_candidates(data_root=data_root)
    assert len(candidates) == 1
    assert candidates[0].source_path == review_dir / "source.csv"


def test_find_review_candidates_skips_already_reviewed(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_provider_json(review_dir, "a" * 64)
    _write_reviewed(review_dir, "hamilton-pool", "a" * 64)

    assert find_review_candidates(data_root=data_root) == []


def test_find_review_candidates_orders_by_date_then_slug(tmp_path):
    data_root = tmp_path / "data"
    _write_provider_json(_review_dir(data_root, "zulu-pool", "2026-01-01", "a" * 64), "a" * 64)
    _write_provider_json(_review_dir(data_root, "alpha-pool", "2026-03-01", "b" * 64), "b" * 64)
    _write_provider_json(_review_dir(data_root, "bravo-pool", "2026-03-01", "c" * 64), "c" * 64)

    candidates = find_review_candidates(data_root=data_root)
    assert [c.slug for c in candidates] == ["zulu-pool", "alpha-pool", "bravo-pool"]


def test_find_review_candidates_filters_by_slug(tmp_path):
    data_root = tmp_path / "data"
    _write_provider_json(_review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64), "a" * 64)
    _write_provider_json(_review_dir(data_root, "balboa-pool", "2026-04-01", "b" * 64), "b" * 64)

    candidates = find_review_candidates(data_root=data_root, only_slug="balboa-pool")
    assert [c.slug for c in candidates] == ["balboa-pool"]


def test_find_review_candidates_skips_review_dir_without_provider_json(tmp_path):
    # A review dir that only has source.pdf (no provider JSON, no reviewed.json)
    # is mid-state and should not surface in the queue.
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64)
    review_dir.mkdir(parents=True)
    (review_dir / "source.pdf").write_bytes(b"%PDF-fake")

    assert find_review_candidates(data_root=data_root) == []
