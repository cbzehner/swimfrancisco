from __future__ import annotations

import httpx
import pytest
from io import BytesIO
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
    client = httpx.Client

    def handler(request):
        counter["count"] += 1
        return httpx.Response(200, stream=httpx.ByteStream(pdf_bytes), headers={"Content-Type": "application/pdf"})

    return lambda *args, **kwargs: client(*args, transport=httpx.MockTransport(handler), **kwargs)


def test_fetch_pdf_does_not_write_unreadable_payload(tmp_path, monkeypatch):
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(b"not a pdf", counter))
    cache_root = tmp_path / "data"
    with pytest.raises(FetchError, match="not a readable PDF"):
        fetch_pdf("test-pool", "http://example.test/schedule.pdf", cache_root=cache_root)
    slug_dir = cache_root / "test-pool"
    assert not any(slug_dir.glob("*/source.pdf")) if slug_dir.exists() else True


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


def test_fetch_pdf_collision_regardless_of_sort_order(tmp_path, monkeypatch):
    import hashlib

    from schedules.artifacts import PrefixCollisionError, find_review_dir_for_sha

    pdf_bytes = _make_pdf_bytes(tmp_path)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    prefix = sha256[:12]
    slug_dir = tmp_path / "test-pool"
    slug_dir.mkdir()
    match_dir = slug_dir / f"2026-04-17-{prefix}"
    collide_dir = slug_dir / f"2026-04-18-{prefix}"
    match_dir.mkdir()
    collide_dir.mkdir()
    (match_dir / "source.pdf").write_bytes(pdf_bytes)
    (match_dir / "source.sha256").write_text(f"{sha256}\n")
    (collide_dir / "source.pdf").write_bytes(b"different content, same prefix by construction")
    (collide_dir / "source.sha256").write_text(f"{'b' * 64}\n")

    with pytest.raises(PrefixCollisionError, match="prefix collision"):
        find_review_dir_for_sha("test-pool", sha256, root=tmp_path)

    later_match = slug_dir / f"2026-04-19-{prefix}"
    later_match.mkdir()
    (later_match / "source.sha256").write_text(f"{sha256}\n")
    (later_match / "source.pdf").write_bytes(pdf_bytes)
    collide_dir.rename(slug_dir / f"2026-04-16-{prefix}")

    with pytest.raises(PrefixCollisionError, match="prefix collision"):
        find_review_dir_for_sha("test-pool", sha256, root=tmp_path)

    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))
    with pytest.raises(FetchError, match="prefix collision"):
        fetch_pdf("test-pool", "http://example.test/x.pdf", cache_root=tmp_path)


@pytest.mark.parametrize("status, expected_calls", [(404, 1), (403, 1), (429, 1), (500, 3), (503, 3)])
def test_fetch_retries_only_transient_http_errors(tmp_path, monkeypatch, status, expected_calls):
    client = httpx.Client
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    monkeypatch.setattr("schedules.fetch.httpx.Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr("schedules.fetch.time.sleep", lambda _: None)
    with pytest.raises(FetchError):
        fetch_pdf("test-pool", "https://example.test/source.pdf", cache_root=tmp_path)
    assert len(calls) == expected_calls
    assert not list(tmp_path.glob("**/source.pdf"))


@pytest.mark.parametrize("headers", [{"content-length": "1000"}, {"content-length": "1"}, {}, {"content-encoding": "gzip"}])
def test_fetch_bounds_actual_bytes_as_well_as_declared_size(tmp_path, monkeypatch, headers):
    client = httpx.Client
    monkeypatch.setattr("schedules.fetch.MAX_PDF_BYTES", 100)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=httpx.ByteStream(b"x" * 200), headers=headers)

    monkeypatch.setattr("schedules.fetch.httpx.Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(FetchError, match="source limit|content encoding"):
        fetch_pdf("test-pool", "https://example.test/source.pdf", cache_root=tmp_path)
    assert len(calls) == 1
    assert not list(tmp_path.glob("**/source.pdf"))


@pytest.mark.parametrize("pages,width,height", [(13, 72, 72), (1, 2001, 72), (1, 72, 2001)])
def test_oversized_pdf_is_rejected_before_caching(tmp_path, monkeypatch, pages, width, height):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=height)
    stream = BytesIO()
    writer.write(stream)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(stream.getvalue(), counter))
    with pytest.raises(FetchError, match="source limit|dimensions"):
        fetch_pdf("test-pool", "https://example.test/source.pdf", cache_root=tmp_path)
    assert counter["count"] == 1
    assert not list(tmp_path.glob("**/source.pdf"))
