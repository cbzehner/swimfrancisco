from __future__ import annotations

import hashlib
import time
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from ._time import pacific_today
from .artifacts import PrefixCollisionError, find_review_dir_for_sha
from .models import FetchResult
from .paths import DATA_DIR, review_dir as make_review_dir


class FetchError(RuntimeError):
    """Raised when a PDF cannot be fetched or validated."""


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

    last_error: Exception | None = None
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for attempt in range(retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.content
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
                dest = make_review_dir(
                    slug, pacific_today().isoformat(), sha256, root=cache_root
                )
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
            except FetchError:
                raise  # don't retry prefix collisions
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(0.25 * (attempt + 1))

    raise FetchError(f"Failed to fetch {slug} from {url}: {last_error}") from last_error


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
    return page_count
