from __future__ import annotations

import hashlib
import time
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from ._time import pacific_today
from .models import FetchResult
from .paths import DATA_DIR


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
                prefix = sha256[:12]

                # Glob by prefix under per-review dirs to detect cache hit or collision.
                # A matching sha always reuses the existing review dir, even under `force`:
                # `--force` re-triggers provider extraction (see pipeline.py), not a fresh
                # dated directory for byte-identical PDFs.
                matches = sorted(slug_dir.glob(f"*-{prefix}/source.pdf"))
                if matches:
                    for existing in matches:
                        existing_bytes = existing.read_bytes()
                        existing_sha = hashlib.sha256(existing_bytes).hexdigest()
                        if existing_sha == sha256:
                            _write_source_sha256(existing.parent, sha256)
                            return FetchResult(
                                path=existing,
                                sha256=sha256,
                                bytes=existing_bytes,
                                from_cache=True,
                                page_count=_count_pdf_pages(existing_bytes),
                            )
                        # Same 12-char prefix, different full hash — collision.
                        raise FetchError(
                            f"prefix collision in {slug}: existing={existing_sha} new={sha256}"
                        )

                # Cache miss — validate before creating a snapshot directory so
                # an unreadable HTTP 200 cannot leave a permanent junk file.
                page_count = _count_pdf_pages(payload)
                review_dir = slug_dir / f"{pacific_today().isoformat()}-{prefix}"
                review_dir.mkdir(parents=True, exist_ok=True)
                path = review_dir / "source.pdf"
                path.write_bytes(payload)
                _write_source_sha256(review_dir, sha256)
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
