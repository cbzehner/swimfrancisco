from __future__ import annotations

import httpx
import pytest
from pypdf import PdfWriter

from schedules.fetch import FetchError, fetch_pdf


def _make_pdf_bytes(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_path = tmp_path / "fixture.pdf"
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    return pdf_path.read_bytes()


def _fake_client_factory(pdf_bytes, counter):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def get(self, url):
            counter["count"] += 1
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
                request=request,
            )
    return FakeClient


def test_fetch_pdf_writes_to_per_review_dir_on_cache_miss(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    cache_root = tmp_path / "data"
    url = "http://example.test/schedule.pdf"
    result = fetch_pdf("test-pool", url, cache_root=cache_root)

    assert result.from_cache is False
    # path is data/test-pool/<date>-<prefix>/source.pdf
    assert result.path.name == "source.pdf"
    review_dir = result.path.parent
    assert review_dir.parent == cache_root / "test-pool"
    assert review_dir.name.endswith(f"-{result.sha256[:12]}")
    # Dir name is <YYYY-MM-DD>-<prefix>
    assert len(review_dir.name.split("-")) == 4  # YYYY MM DD prefix
    assert (review_dir / "source.sha256").read_text() == f"{result.sha256}\n"
    assert counter["count"] == 1


def test_fetch_pdf_cache_hit_short_circuits(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    cache_root = tmp_path / "data"
    url = "http://example.test/schedule.pdf"
    first = fetch_pdf("test-pool", url, cache_root=cache_root)
    second = fetch_pdf("test-pool", url, cache_root=cache_root)

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.sha256 == second.sha256
    assert first.path == second.path  # date-in-dirname is stable after first fetch
    assert (first.path.parent / "source.sha256").read_text() == f"{first.sha256}\n"
    assert counter["count"] == 2  # note: one extra GET per cache-hit compared to old index


def test_fetch_pdf_cache_hit_writes_missing_sha256(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    import hashlib

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    review_dir = tmp_path / "data" / "test-pool" / f"2026-04-17-{sha256[:12]}"
    review_dir.mkdir(parents=True)
    (review_dir / "source.pdf").write_bytes(pdf_bytes)

    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    result = fetch_pdf("test-pool", "http://example.test/schedule.pdf", cache_root=tmp_path / "data")

    assert result.from_cache is True
    assert (review_dir / "source.sha256").read_text() == f"{sha256}\n"


def test_fetch_pdf_raises_on_prefix_collision(tmp_path, monkeypatch):
    # Simulate: a file at the expected prefix location exists, but its sha differs.
    cache_root = tmp_path / "data"
    slug_dir = cache_root / "test-pool"
    slug_dir.mkdir(parents=True)

    pdf_bytes_a = _make_pdf_bytes(tmp_path)
    import hashlib
    prefix = hashlib.sha256(pdf_bytes_a).hexdigest()[:12]

    # Plant a DIFFERENT file with the same 12-char prefix.
    collision_dir = slug_dir / f"2026-04-17-{prefix}"
    collision_dir.mkdir()
    (collision_dir / "source.pdf").write_bytes(b"different content, same prefix by construction")

    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes_a, counter))

    with pytest.raises(FetchError, match="prefix collision"):
        fetch_pdf("test-pool", "http://example.test/x.pdf", cache_root=cache_root)
