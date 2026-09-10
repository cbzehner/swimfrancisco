from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import version
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models import PoolEntry
from ..paths import DATA_DIR
from .errors import DirectSourceError
from .http import (
    DirectFetchResult,
    _cache_bytes,
    fetch_koret_workbook,
    fetch_text,
)
from .providers.fitness_clubs import (
    _extract_24_hour_fitness,
    _extract_city_sports,
    _extract_equinox,
    _extract_bayclub_gateway,
    _extract_fitness_sf,
)
from .providers.koret import _extract_koret
from .providers.pomeroy import _extract_pomeroy
from .providers.ucsf import _extract_ucsf_bakar, _extract_ucsf_fitness

__all__ = [
    "DirectExtraction",
    "DirectFetchResult",
    "DirectSourceError",
    "extract_direct",
    "fetch_koret_workbook",
    "fetch_text",
]


@dataclass(frozen=True)
class DirectExtraction:
    fetch_result: DirectFetchResult
    payload: dict
    model: str
    notes: list[str]
    source: dict
    coverage: dict | None = None


def direct_configuration() -> dict:
    from ..schema import EXTRACTION_SCHEMA
    root = Path(__file__).parent
    files = sorted(root.rglob("*.py"))
    return {"source_identity": "original_bytes", "freshness_days": 14,
            "python": platform.python_version(),
            "libraries": {name: version(name) for name in ("httpx", "openpyxl")},
            "schema_sha256": hashlib.sha256(json.dumps(EXTRACTION_SCHEMA, sort_keys=True).encode()).hexdigest(),
            "parser_sha256": hashlib.sha256(b"".join(
                path.relative_to(root.parent).as_posix().encode() + b"\0" + path.read_bytes()
                for path in files + [root.parent / "_time.py", root.parent / "models.py"])).hexdigest()}


def _source_metadata(entry: PoolEntry, fetched: DirectFetchResult, observed_on: date) -> dict:
    return {"sha256": fetched.sha256, "url": fetched.response_url,
            "requested_url": entry.pdf_url, "observed_on": observed_on.isoformat(),
            "configuration": direct_configuration(), "freshness_days": 14}


def observation_window(payload: dict, observed_on: str) -> dict:
    if "effective_start" in payload:
        return payload
    observed = date.fromisoformat(observed_on)
    return payload | {"effective_start": observed.isoformat(),
                      "effective_end": (observed + timedelta(days=13)).isoformat()}


def verify_direct_artifact(artifact: dict, source_path: Path, *, today: date) -> dict:
    from .providers.pomeroy import verify_pomeroy
    if artifact.get("model") == "browser-html":
        return _verify_browser_artifact(artifact, source_path, today=today)
    if artifact.get("model") in {"ucsf-fitness-html-v1", "ucsf-bakar-html-v1", "fitness-sf-html-v1", "city-sports-html-v1", "equinox-html-v1", "bayclub-html"}:
        return _verify_access_artifact(artifact, source_path, today=today)
    source = artifact.get("details", {}).get("direct_source", {})
    if artifact.get("provider") != "direct" or artifact.get("model") != "pomeroy-html-v1":
        raise DirectSourceError("Only the approved Pomeroy parser can establish direct acceptance")
    official = "https://www.prrcsf.org/therapeutic-swim"
    if artifact.get("source_pdf_url") != official or source.get("requested_url") != official or source.get("url", "").rstrip("/") != official:
        raise DirectSourceError("Direct source differs from the approved operator URL")
    if source.get("configuration") != direct_configuration() or source.get("freshness_days") != 14:
        raise DirectSourceError("Direct extraction configuration changed")
    content = source_path.read_bytes()
    if source_path.suffix != ".html" or hashlib.sha256(content).hexdigest() != source.get("sha256") or source.get("sha256") != artifact.get("pdf_sha256"):
        raise DirectSourceError("Direct capture does not match its original-byte identity")
    observed = date.fromisoformat(source["observed_on"])
    if not observed <= today <= observed + timedelta(days=13):
        raise DirectSourceError("Direct observation is expired or in the future")
    payload = artifact["payload"]
    if (payload.get("effective_start"), payload.get("effective_end")) != (
        observed.isoformat(), (observed + timedelta(days=13)).isoformat()
    ):
        raise DirectSourceError("Undated source must use exactly the approved observation lifetime")
    return verify_pomeroy(content.decode("utf-8"), payload, observed)


def extract_direct(entry: PoolEntry, *, cache_root: Path | None = None) -> DirectExtraction:
    from .._time import pacific_today
    fetch_kwargs = {"cache_root": cache_root} if cache_root is not None else {}
    if entry.source_kind == "koret_google_sheet":
        fetched = fetch_koret_workbook(entry.slug, entry.pdf_url, **fetch_kwargs)
        source = _source_metadata(entry, fetched, pacific_today())
        return DirectExtraction(
            fetch_result=fetched,
            payload=observation_window(_extract_koret(fetched.path), source["observed_on"]),
            model="koret-google-workbook-v1",
            notes=["Koret sessions represent official pool hours; the sheet still carries lane-level restrictions and team bookings."],
            source=source,
        )
    if entry.capture_method == "cloudflare_browser":
        return _extract_browser_entry(entry, cache_root=cache_root or DATA_DIR)
    spec = _HTML_EXTRACTORS.get(entry.source_kind or "")
    if spec is None:
        raise DirectSourceError(f"{entry.slug}: unsupported direct source kind {entry.source_kind!r}")
    extractor, model, note = spec
    cache_root = fetch_kwargs.get("cache_root") or DATA_DIR
    response = fetch_text(entry.pdf_url)
    observed_on = pacific_today()
    sha256 = hashlib.sha256(response.content).hexdigest()
    slug_dir = cache_root / entry.slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path, from_cache = _cache_bytes(slug_dir, sha256, "html", response.content)
    fetched = DirectFetchResult(
        path=path,
        sha256=sha256,
        from_cache=from_cache,
        response_url=response.response_url,
    )
    source = _source_metadata(entry, fetched, observed_on)
    from ..paths import relative_to_repo
    from .html_facts import HtmlClosureReviewRequired
    from .errors import CapturedClosureReviewRequired
    try:
        payload = extractor(response.text, observed_on=observed_on) if entry.source_kind in {"pomeroy_html", "ucsf_fitness_html", "ucsf_bakar_html"} else extractor(response.text)
    except HtmlClosureReviewRequired as error:
        raise CapturedClosureReviewRequired(slug=entry.slug, source_path=relative_to_repo(path),
            source_sha256=sha256, issues=error.issues, notices=error.notices) from error
    payload = observation_window(payload, source["observed_on"])
    from .providers.pomeroy import verify_pomeroy
    coverage = verify_pomeroy(response.text, payload, observed_on) if entry.source_kind == "pomeroy_html" else None
    if entry.source_kind in {"ucsf_fitness_html", "ucsf_bakar_html", "fitness_sf_html", "city_sports_html", "equinox_html", "bayclub_html"}:
        coverage = {"ok": True, "issues": []}
    return DirectExtraction(
        fetch_result=fetched,
        payload=payload,
        model=model,
        notes=[note],
        source=source,
        coverage=coverage,
    )


# HTML sources share fetch and original-byte capture. Adding a
# site is one registration here plus its extractor. Defined after the
# extractors so the references resolve at import time.
_HTML_EXTRACTORS: dict[str, tuple[Callable[[str], dict], str, str]] = {
    "twenty_four_hour_fitness_html": (
        _extract_24_hour_fitness,
        "twenty-four-hour-fitness-html-v1",
        "24 Hour Fitness exposes gym hours, not pool lane availability; these are access hours only.",
    ),
    "pomeroy_html": (
        _extract_pomeroy,
        "pomeroy-html-v1",
        "Pomeroy lap sessions are slow therapeutic lap swim, not vigorous lap training.",
    ),
    "city_sports_html": (
        _extract_city_sports,
        "city-sports-html-v1",
        "City Sports exposes club hours and lap-pool amenities, not lane availability; these are access hours only.",
    ),
    "bayclub_html": (
        _extract_bayclub_gateway,
        "bayclub-html",
        "Gateway publishes facility access hours, not lap-lane availability.",
    ),
    "equinox_html": (
        _extract_equinox,
        "equinox-html-v1",
        "Equinox exposes club hours and an indoor-pool amenity, not lane availability; these are access hours only.",
    ),
    "fitness_sf_html": (
        _extract_fitness_sf,
        "fitness-sf-html-v1",
        "FITNESS SF exposes club hours and pool policies, not lane availability; these are access hours only.",
    ),
    "ucsf_fitness_html": (
        _extract_ucsf_fitness,
        "ucsf-fitness-html-v1",
        "UCSF exposes facility hours and pool amenities, but not lane availability; these are access hours only.",
    ),
    "ucsf_bakar_html": (
        _extract_ucsf_bakar,
        "ucsf-bakar-html-v1",
        "UCSF Bakar exposes facility hours and pool amenities, but not pool lane availability; these are access hours only.",
    ),
}


def _extract_browser_entry(entry: PoolEntry, *, cache_root: Path) -> DirectExtraction:
    from ..paths import relative_to_repo
    from ..registry import BROWSER_SOURCES
    from .browser import read_browser_capture
    from .errors import CapturedClosureReviewRequired
    from .html_facts import (
        HtmlClosureReviewRequired, inspect_html_source, html_source_payload,
    )
    if BROWSER_SOURCES.get(entry.slug) != (entry.source_kind, entry.pdf_url):
        raise DirectSourceError("HTML extraction requires an approved source identity")
    response, capture = read_browser_capture(entry)
    observed = datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00")).astimezone(
        ZoneInfo("America/Los_Angeles")).date()
    sha256 = hashlib.sha256(response.content).hexdigest()
    directory = cache_root / entry.slug
    directory.mkdir(parents=True, exist_ok=True)
    path, from_cache = _cache_bytes(directory, sha256, "html", response.content)
    fetched = DirectFetchResult(path, sha256, from_cache, response.response_url)
    try:
        inventory = inspect_html_source(entry.slug, response.text)
        payload = html_source_payload(inventory, observed)
    except HtmlClosureReviewRequired as error:
        raise CapturedClosureReviewRequired(slug=entry.slug, source_path=relative_to_repo(path),
            source_sha256=sha256, issues=error.issues, notices=error.notices) from error
    source = {"sha256": sha256, "url": response.response_url, "requested_url": entry.pdf_url,
              "observed_on": observed.isoformat(), "freshness_days": 14,
              "configuration": direct_configuration() | {"capture": capture}}
    notes = (["These are pool or facility access hours; they do not establish lap-swim availability."]
             if payload.get("schedule_basis") in {"pool_hours", "facility_hours"} else [])
    return DirectExtraction(fetched, payload, "browser-html", notes, source, {"ok": True, "issues": []})


def _verify_browser_artifact(artifact: dict, source_path: Path, *, today: date) -> dict:
    from ..models import PoolEntry
    from ..registry import BROWSER_SOURCES
    from .browser import read_browser_capture
    from .html_facts import inspect_html_source, html_source_payload
    if artifact.get("provider") != "direct" or artifact.get("model") != "browser-html":
        raise DirectSourceError("HTML artifact must use the approved direct parser")
    source = artifact["details"]["direct_source"]
    slug = source_path.parent.parent.name
    approved = BROWSER_SOURCES.get(slug)
    if not approved:
        raise DirectSourceError("HTML artifact is outside the approved sources")
    kind, url = approved
    if (artifact.get("source_pdf_url") != url or source.get("requested_url") != url
            or source.get("url", "").rstrip("/") != url.rstrip("/")):
        raise DirectSourceError("HTML source URL changed")
    if source_path.name != "source.html" or source_path.is_symlink() or source_path.parent.is_symlink():
        raise DirectSourceError("HTML source is not an original capture file")
    content = source_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != artifact.get("pdf_sha256") or source.get("sha256") != artifact.get("pdf_sha256"):
        raise DirectSourceError("HTML original bytes do not match the source identity")
    entry = PoolEntry(slug=slug, official_page_url=url, pdf_url=url, source_kind=kind,
                      capture_method="cloudflare_browser")
    response, receipt = read_browser_capture(entry)
    if response.content != content or source.get("configuration") != direct_configuration() | {"capture": receipt}:
        raise DirectSourceError("HTML artifact does not match the current capture and configuration")
    observed = datetime.fromisoformat(receipt["captured_at"].replace("Z", "+00:00")).astimezone(
        ZoneInfo("America/Los_Angeles")).date()
    if (source.get("observed_on") != observed.isoformat() or source.get("freshness_days") != 14
            or not observed <= today <= observed + timedelta(days=13)):
        raise DirectSourceError("HTML observation is expired or future-dated")
    inventory = inspect_html_source(slug, content.decode("utf-8"))
    payload = html_source_payload(inventory, observed)
    if payload != artifact.get("payload"):
        raise DirectSourceError("Published HTML payload differs from verified source facts")
    if not payload["effective_start"] <= today.isoformat() <= payload["effective_end"]:
        raise DirectSourceError("Verified HTML schedule window is expired or future-dated")
    return {"ok": True, "issues": []}


def _verify_access_artifact(artifact: dict, source_path: Path, *, today: date) -> dict:
    from ..registry import HTTP_ACCESS_SOURCES
    slug = source_path.parent.parent.name
    approved = HTTP_ACCESS_SOURCES.get(slug)
    if not approved:
        raise DirectSourceError("HTTP access artifact has an unapproved facility identity")
    kind, url = approved
    extractor, model, _ = _HTML_EXTRACTORS[kind]
    source = artifact.get("details", {}).get("direct_source", {})
    if (artifact.get("provider") != "direct" or artifact.get("model") != model
            or artifact.get("source_pdf_url") != url or source.get("requested_url") != url
            or source.get("url") != url):
        raise DirectSourceError("HTTP access source identity differs from the approved facility and calendar")
    if (source_path.name != "source.html" or source_path.is_symlink() or source_path.parent.is_symlink()
            or source.get("configuration") != direct_configuration() or source.get("freshness_days") != 14):
        raise DirectSourceError("HTTP access source configuration or original file changed")
    content = source_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != source.get("sha256") or source.get("sha256") != artifact.get("pdf_sha256"):
        raise DirectSourceError("HTTP access original bytes do not match their identity")
    observed = date.fromisoformat(source["observed_on"])
    if not observed <= today <= observed + timedelta(days=13):
        raise DirectSourceError("HTTP access observation is expired or future-dated")
    payload = (extractor(content.decode("utf-8"), observed_on=observed)
               if kind in {"ucsf_fitness_html", "ucsf_bakar_html"} else extractor(content.decode("utf-8")))
    payload = observation_window(payload, observed.isoformat())
    if payload != artifact.get("payload"):
        raise DirectSourceError("HTTP access payload differs from the complete official source")
    if not payload["effective_start"] <= today.isoformat() <= payload["effective_end"]:
        raise DirectSourceError("HTTP access printed schedule coverage is expired")
    return {"ok": True, "issues": []}
