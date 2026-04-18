from __future__ import annotations

import hashlib
import json
import time
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from .models import FetchResult
from .paths import PDF_CACHE_DIR, PDF_CACHE_INDEX_PATH


class FetchError(RuntimeError):
    """Raised when a PDF cannot be fetched or validated."""


def fetch_pdf(
    slug: str,
    url: str,
    *,
    cache_dir: Path = PDF_CACHE_DIR,
    index_path: Path = PDF_CACHE_INDEX_PATH,
    force: bool = False,
    timeout: float = 30.0,
    retries: int = 2,
) -> FetchResult:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_index = _load_cache_index(index_path)
    cache_key = f"{slug}|{url}"

    if not force:
        cached_name = cache_index.get(cache_key)
        if isinstance(cached_name, str):
            cached_path = cache_dir / cached_name
            try:
                payload = cached_path.read_bytes()
            except FileNotFoundError:
                payload = None
            if payload is not None:
                sha256 = hashlib.sha256(payload).hexdigest()
                return FetchResult(
                    path=cached_path,
                    sha256=sha256,
                    bytes=payload,
                    from_cache=True,
                    page_count=_count_pdf_pages(payload),
                    response_url=url,
                )

    last_error: Exception | None = None
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for attempt in range(retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.content
                sha256 = hashlib.sha256(payload).hexdigest()
                filename = f"{slug}-{sha256[:12]}.pdf"
                path = cache_dir / filename
                path.write_bytes(payload)
                cache_index[cache_key] = filename
                _save_cache_index(index_path, cache_index)
                return FetchResult(
                    path=path,
                    sha256=sha256,
                    bytes=payload,
                    from_cache=False,
                    page_count=_count_pdf_pages(payload),
                    response_url=str(response.url),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(0.25 * (attempt + 1))

    raise FetchError(f"Failed to fetch {slug} from {url}: {last_error}") from last_error


def _count_pdf_pages(payload: bytes) -> int:
    try:
        reader = PdfReader(BytesIO(payload))
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise FetchError("Downloaded file is not a readable PDF.") from exc

    if page_count <= 0:
        raise FetchError("Downloaded PDF contains zero pages.")
    return page_count


def _load_cache_index(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise FetchError(f"Cache index at {path} is not a JSON object.")
    return {str(key): str(value) for key, value in raw.items()}


def _save_cache_index(path: Path, index: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")

