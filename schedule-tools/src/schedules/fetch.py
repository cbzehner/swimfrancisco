from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from ._time import pacific_today
from .artifacts import PrefixCollisionError, find_review_dir_for_sha
from .models import FetchResult
from .paths import DATA_DIR, review_dir as make_review_dir
from .signals import MAX_PDF_BYTES, MAX_PDF_PAGES, MAX_PAGE_POINTS


# Retried everywhere: a server that is busy, rate-limiting or briefly broken.
TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """Raised when a PDF cannot be fetched or validated."""


def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int | None = None,
    transient: frozenset[int] = TRANSIENT_STATUSES,
    retries: int = 2,
    sleep: Callable[[float], None] | None = None,
) -> httpx.Response:
    """GET with bounded retries on transient failures, raising for other statuses.

    The one HTTP retry loop: discover and the direct sources call it too.
    ``max_bytes`` streams the body and refuses anything larger, so an
    oversized or unbounded response never lands in memory.
    """
    if retries < 0:
        raise ValueError("retries must not be negative")
    last_error: httpx.HTTPError
    for attempt in range(retries + 1):
        try:
            return _get_once(client, url, max_bytes)
        except httpx.HTTPError as exc:
            last_error = exc
            retryable = isinstance(exc, httpx.TransportError) or (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in transient
            )
            if not retryable or attempt >= retries:
                break
            (sleep or time.sleep)(0.25 * (attempt + 1))
    raise last_error


def _get_once(client: httpx.Client, url: str, max_bytes: int | None) -> httpx.Response:
    if max_bytes is None:
        response = client.get(url)
        response.raise_for_status()
        return response
    with client.stream("GET", url) as response:
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise FetchError("PDF server returned an unsupported content encoding")
        length = response.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > max_bytes):
            raise FetchError("PDF exceeds the 25 MiB source limit or has an invalid length")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_raw(chunk_size=64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise FetchError("PDF exceeds the 25 MiB source limit")
            chunks.append(chunk)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=b"".join(chunks),
            request=response.request,
            extensions=response.extensions,
            history=response.history,
        )


def fetch_pdf(
    slug: str,
    url: str,
    *,
    cache_root: Path = DATA_DIR,
    timeout: float = 30.0,
    retries: int = 2,
) -> FetchResult:
    """Fetch a PDF, caching under data/<slug>/<date>-<prefix>/source.pdf."""
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True, max_redirects=5, timeout=timeout,
                      headers={"Accept-Encoding": "identity"}) as client:
        try:
            payload = get_with_retries(
                client, url, max_bytes=MAX_PDF_BYTES, retries=retries
            ).content
        except httpx.HTTPError as error:
            raise FetchError(f"Failed to fetch {slug} from {url}: {error}") from error

    sha256 = hashlib.sha256(payload).hexdigest()

    # A matching sha always reuses the existing review dir, even under `force`:
    # `--force` re-triggers provider extraction (see pipeline.py), not a fresh
    # dated directory for byte-identical PDFs.
    try:
        existing_dir = find_review_dir_for_sha(slug, sha256, root=cache_root)
    except PrefixCollisionError as exc:
        raise FetchError(str(exc)) from exc
    if existing_dir is not None:
        existing = existing_dir / "source.pdf"
        existing_bytes = existing.read_bytes()
        _write_source_sha256(existing_dir, sha256)
        return FetchResult(
            path=existing,
            sha256=sha256,
            bytes=existing_bytes,
            from_cache=True,
            page_count=_count_pdf_pages(existing_bytes),
        )

    # Cache miss — validate before creating a snapshot directory so
    # an unreadable HTTP 200 cannot leave a permanent junk file.
    page_count = _count_pdf_pages(payload)
    dest = make_review_dir(slug, pacific_today().isoformat(), sha256, root=cache_root)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "source.pdf"
    path.write_bytes(payload)
    _write_source_sha256(dest, sha256)
    return FetchResult(
        path=path,
        sha256=sha256,
        bytes=payload,
        from_cache=False,
        page_count=page_count,
    )


def _write_source_sha256(review_dir: Path, sha256: str) -> None:
    (review_dir / "source.sha256").write_text(f"{sha256}\n")


def _count_pdf_pages(payload: bytes) -> int:
    try:
        reader = PdfReader(BytesIO(payload))
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise FetchError("Downloaded file is not a readable PDF.") from exc

    if page_count <= 0:
        raise FetchError("Downloaded PDF contains zero pages.")
    if page_count > MAX_PDF_PAGES:
        raise FetchError("PDF exceeds the 12-page source limit")
    for page in reader.pages:
        if not (0 < page.mediabox.width <= MAX_PAGE_POINTS and 0 < page.mediabox.height <= MAX_PAGE_POINTS):
            raise FetchError("PDF page exceeds the supported dimensions")
    return page_count
