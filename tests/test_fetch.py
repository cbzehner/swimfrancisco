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


def test_fetch_pdf_writes_to_per_slug_dir_on_cache_miss(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    cache_root = tmp_path / "pdfs"
    url = "http://example.test/schedule.pdf"
    result = fetch_pdf("test-pool", url, cache_root=cache_root)

    assert result.from_cache is False
    assert result.path.parent == cache_root / "test-pool"
    assert result.path.name.endswith(f"-{result.sha256[:12]}.pdf")
    # Filename is <YYYY-MM-DD>-<prefix>.pdf
    assert len(result.path.stem.split("-")) == 4  # YYYY MM DD prefix
    assert counter["count"] == 1


def test_fetch_pdf_cache_hit_short_circuits(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    cache_root = tmp_path / "pdfs"
    url = "http://example.test/schedule.pdf"
    first = fetch_pdf("test-pool", url, cache_root=cache_root)
    second = fetch_pdf("test-pool", url, cache_root=cache_root)

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.sha256 == second.sha256
    assert first.path == second.path  # date-in-filename is stable after first fetch
    assert counter["count"] == 2  # note: one extra GET per cache-hit compared to old index


def test_fetch_pdf_raises_on_prefix_collision(tmp_path, monkeypatch):
    # Simulate: a file at the expected prefix location exists, but its sha differs.
    cache_root = tmp_path / "pdfs"
    slug_dir = cache_root / "test-pool"
    slug_dir.mkdir(parents=True)

    pdf_bytes_a = _make_pdf_bytes(tmp_path)
    import hashlib
    prefix = hashlib.sha256(pdf_bytes_a).hexdigest()[:12]

    # Plant a DIFFERENT file with the same 12-char prefix (contrived by writing bytes at that path).
    collision_path = slug_dir / f"2026-04-17-{prefix}.pdf"
    collision_path.write_bytes(b"different content, same prefix by construction")

    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes_a, counter))

    with pytest.raises(FetchError, match="prefix collision"):
        fetch_pdf("test-pool", "http://example.test/x.pdf", cache_root=cache_root)
