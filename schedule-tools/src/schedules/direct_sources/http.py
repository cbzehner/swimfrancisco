from __future__ import annotations

import hashlib
import re
import time
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from urllib.parse import urlsplit, urlunsplit

import httpx

from .._time import pacific_today
from ..paths import DATA_DIR
from .errors import DirectSourceError

BOT_USER_AGENT = "SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)"


@dataclass(frozen=True)
class DirectFetchResult:
    path: Path
    sha256: str
    from_cache: bool
    response_url: str


@dataclass(frozen=True)
class DirectTextResponse:
    text: str
    content: bytes
    response_url: str


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


def _http_failure(response: httpx.Response) -> str:
    headers = {
        key: re.sub(r"[^\x20-\x7e]", "", response.headers[key])[:120]
        for key in ("content-type", "server", "cf-mitigated")
        if key in response.headers
    }
    return f"HTTP {response.status_code} at {_safe_url(str(response.url))}; headers={headers}"


def fetch_text(
    url: str,
    *,
    timeout: float = 30.0,
    retries: int = 2,
) -> DirectTextResponse:
    if not 0 <= retries <= 5:
        raise ValueError("retries must be between 0 and 5")
    detail = "request failed"
    headers = {
        "User-Agent": BOT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for attempt in range(retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                return DirectTextResponse(response.text, response.content, str(response.url))
            except httpx.HTTPStatusError as exc:
                detail = _http_failure(exc.response)
                if exc.response.status_code not in {408, 429, 500, 502, 503, 504}:
                    break
            except httpx.TransportError as exc:
                detail = type(exc).__name__
            if attempt >= retries:
                break
            time.sleep(0.25 * (attempt + 1))
    raise DirectSourceError(f"Failed to fetch {_safe_url(url)}: {detail}") from None


def fetch_koret_workbook(slug: str, workbook_url: str, *, cache_root: Path = DATA_DIR) -> DirectFetchResult:
    sheet_id = _extract_google_sheet_id(workbook_url)
    headers = {
        "User-Agent": BOT_USER_AGENT,
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
            export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
            workbook_response = client.get(export_url, params={"format": "xlsx"})
            workbook_response.raise_for_status()
            pdf_response = client.get(export_url, params={
                "format": "pdf",
                "portrait": "false",
                "fitw": "true",
                "sheetnames": "true",
                "pagenumbers": "true",
                "gridlines": "false",
                "fzr": "true",
            })
            pdf_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DirectSourceError(f"Failed to fetch {slug} workbook: {_http_failure(exc.response)}") from None
    except httpx.TransportError as exc:
        raise DirectSourceError(f"Failed to fetch {slug} workbook: {type(exc).__name__}") from None

    workbook_bytes = workbook_response.content
    pdf_bytes = pdf_response.content
    try:
        with ZipFile(BytesIO(workbook_bytes)) as archive:
            if "xl/workbook.xml" not in archive.namelist():
                raise BadZipFile("missing workbook")
        sha256 = hashlib.sha256(workbook_bytes).hexdigest()
    except BadZipFile as exc:
        raise DirectSourceError(f"{slug} workbook export is not a valid XLSX (interstitial page?)") from exc
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    prefix = sha256[:12]
    matches = sorted(slug_dir.glob(f"*-{prefix}/source.xlsx"))
    if matches:
        path = matches[0]
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise DirectSourceError(f"prefix collision under {slug_dir}: {prefix}")
        from_cache = True
    else:
        review_dir = slug_dir / f"{pacific_today().isoformat()}-{prefix}"
        review_dir.mkdir(parents=True, exist_ok=True)
        path = review_dir / "source.xlsx"
        path.write_bytes(workbook_bytes)
        (review_dir / "source.sha256").write_text(f"{sha256}\n")
        from_cache = False
    pdf_path = path.parent / "source.pdf"
    if not pdf_path.exists() or not from_cache:
        pdf_path.write_bytes(pdf_bytes)
    return DirectFetchResult(
        path=path,
        sha256=sha256,
        from_cache=from_cache,
        response_url=str(workbook_response.url),
    )


def _cache_bytes(slug_dir: Path, sha256: str, extension: str, content: bytes) -> tuple[Path, bool]:
    if hashlib.sha256(content).hexdigest() != sha256:
        raise DirectSourceError("source bytes do not match source hash")
    prefix = sha256[:12]
    matches = sorted(slug_dir.glob(f"{pacific_today().isoformat()}-{prefix}/source.{extension}"))
    for existing in matches:
        if hashlib.sha256(existing.read_bytes()).hexdigest() != sha256:
            raise DirectSourceError(f"prefix collision under {slug_dir}: {prefix}")
        metadata = existing.parent / "source.sha256"
        if metadata.exists() and metadata.read_text().strip() != sha256:
            raise DirectSourceError(f"source hash metadata mismatch under {slug_dir}: {prefix}")
        if not metadata.exists():
            metadata.write_text(f"{sha256}\n")
        return existing, True

    review_dir = slug_dir / f"{pacific_today().isoformat()}-{prefix}"
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"source.{extension}"
    path.write_bytes(content)
    (review_dir / "source.sha256").write_text(f"{sha256}\n")
    return path, False


def _extract_google_sheet_id(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise DirectSourceError("Google Sheets URL does not include /spreadsheets/d/<id>")
    return match.group(1)
