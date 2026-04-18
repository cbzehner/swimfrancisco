from __future__ import annotations

import httpx
from pypdf import PdfWriter

from schedules.fetch import fetch_pdf


def test_fetch_pdf_caches_local_fixture(tmp_path, monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_path = tmp_path / "fixture.pdf"
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    pdf_bytes = pdf_path.read_bytes()
    requests = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            requests["count"] += 1
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
                request=request,
            )

    monkeypatch.setattr("schedules.fetch.httpx.Client", FakeClient)

    url = "http://example.test/schedule.pdf"
    first = fetch_pdf(
        "test-pool",
        url,
        cache_dir=tmp_path / "cache",
        index_path=tmp_path / "pdf-cache-index.json",
    )
    second = fetch_pdf(
        "test-pool",
        url,
        cache_dir=tmp_path / "cache",
        index_path=tmp_path / "pdf-cache-index.json",
    )

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.sha256 == second.sha256
    assert requests["count"] == 1
