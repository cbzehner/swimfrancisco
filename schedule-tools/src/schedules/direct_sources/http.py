from __future__ import annotations

import hashlib
import json
import re
import time
from io import BytesIO
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import httpx

from .._time import pacific_today
from ..paths import DATA_DIR
from .errors import DirectSourceError


@dataclass(frozen=True)
class DirectFetchResult:
    path: Path
    sha256: str
    text: str
    from_cache: bool
    response_url: str


def fetch_text(
    slug: str,
    url: str,
    *,
    extension: str,
    cache_root: Path = DATA_DIR,
    timeout: float = 30.0,
    retries: int = 2,
    fingerprint: Callable[[str], str] | None = None,
) -> DirectFetchResult:
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    headers = {
        "User-Agent": "SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for attempt in range(retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                text = response.text
                fingerprint_text = fingerprint(text) if fingerprint is not None else text
                sha256 = hashlib.sha256(fingerprint_text.encode("utf-8")).hexdigest()
                path, from_cache = _cache_text(slug_dir, sha256, extension, text)
                return DirectFetchResult(
                    path=path,
                    sha256=sha256,
                    text=path.read_text(),
                    from_cache=from_cache,
                    response_url=str(response.url),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(0.25 * (attempt + 1))
    raise DirectSourceError(f"Failed to fetch {slug} from {url}: {last_error}") from last_error


def fetch_koret_workbook(slug: str, workbook_url: str, *, cache_root: Path = DATA_DIR) -> DirectFetchResult:
    sheet_id = _extract_google_sheet_id(workbook_url)
    headers = {
        "User-Agent": "SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)",
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
    except httpx.HTTPError as exc:
        raise DirectSourceError(f"Failed to fetch {slug} workbook: {exc}") from exc

    workbook_bytes = workbook_response.content
    pdf_bytes = pdf_response.content
    try:
        sha256 = _xlsx_content_sha256(workbook_bytes)
    except BadZipFile as exc:
        raise DirectSourceError(f"{slug} workbook export is not a valid XLSX (interstitial page?)") from exc
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    prefix = sha256[:12]
    matches = sorted(slug_dir.glob(f"*-{prefix}/source.xlsx"))
    if matches:
        path = matches[0]
        if _xlsx_content_sha256(path.read_bytes()) != sha256:
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
        text="",
        from_cache=from_cache,
        response_url=workbook_url,
    )


def _cache_text(slug_dir: Path, sha256: str, extension: str, text: str) -> tuple[Path, bool]:
    prefix = sha256[:12]
    matches = sorted(slug_dir.glob(f"*-{prefix}/source.{extension}"))
    for existing in matches:
        metadata = existing.parent / "source.sha256"
        if metadata.exists() and metadata.read_text().strip() == sha256:
            return existing, True
        if not metadata.exists() and hashlib.sha256(existing.read_bytes()).hexdigest() == sha256:
            metadata.write_text(f"{sha256}\n")
            return existing, True
        raise DirectSourceError(f"prefix collision under {slug_dir}: {prefix}")

    review_dir = slug_dir / f"{pacific_today().isoformat()}-{prefix}"
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"source.{extension}"
    path.write_text(text)
    (review_dir / "source.sha256").write_text(f"{sha256}\n")
    return path, False


def _xlsx_content_sha256(payload: bytes) -> str:
    digest = hashlib.sha256()
    with ZipFile(BytesIO(payload)) as archive:
        for name in sorted(archive.namelist()):
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(archive.read(name))
            digest.update(b"\0")
    return digest.hexdigest()


def _payload_fingerprint(extractor: Callable[[str], dict]) -> Callable[[str], str]:
    def fingerprint(text: str) -> str:
        payload = dict(extractor(text))
        payload.pop("effective_start", None)
        # Closure starts can be anchored to the scrape date (e.g. "closed until
        # <reopen>"), which would mint a new review dir every calendar day; the
        # end date carries the actual signal.
        payload["closures"] = [
            {key: value for key, value in closure.items() if key != "start"}
            for closure in payload.get("closures", [])
        ]
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    return fingerprint


def _extract_google_sheet_id(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise DirectSourceError("Google Sheets URL does not include /spreadsheets/d/<id>")
    return match.group(1)
