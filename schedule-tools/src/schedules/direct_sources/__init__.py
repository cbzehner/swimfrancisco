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
    _extract_fitness_sf,
    _extract_sfsu_aquatics,
)
from .providers.jccsf import _extract_jccsf
from .providers.koret import _extract_koret
from .providers.pomeroy import _extract_pomeroy
from .providers.ucsf import _extract_ucsf_bakar, _extract_ucsf_fitness
from .providers.ymca import _extract_ymca_location

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
    spec = _HTML_EXTRACTORS.get(entry.source_kind or "")
    if spec is None:
        raise DirectSourceError(f"{entry.slug}: unsupported direct source kind {entry.source_kind!r}")
    extractor, model, note = spec
    cache_root = fetch_kwargs.get("cache_root") or DATA_DIR
    capture = None
    if entry.capture_method == "cloudflare_browser":
        from .browser import read_browser_capture
        response, capture = read_browser_capture(entry)
    else:
        response = fetch_text(entry.pdf_url)
    observed_on = (datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00"))
                   .astimezone(ZoneInfo("America/Los_Angeles")).date()) if capture else pacific_today()
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
    if capture is not None:
        source["configuration"] = source["configuration"] | {"capture": capture}
    payload = _extract_pomeroy(response.text, observed_on=observed_on) if entry.source_kind == "pomeroy_html" else extractor(response.text)
    payload = observation_window(payload, source["observed_on"])
    from .providers.pomeroy import verify_pomeroy
    coverage = verify_pomeroy(response.text, payload, observed_on) if entry.source_kind == "pomeroy_html" else None
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
    "jccsf_html": (
        _extract_jccsf,
        "jccsf-html-v1",
        "JCCSF lap swim is modeled from Aquatics Center hours; lane-count breakdown remains linked on the official page.",
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
    "sfsu_aquatics_html": (
        _extract_sfsu_aquatics,
        "sfsu-aquatics-html-v1",
        "SFSU exposes natatorium hours, not public lane availability; these are access hours only.",
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
    "ymca_location_html": (
        _extract_ymca_location,
        "ymca-location-html-v1",
        "YMCA location pages expose facility hours and link to a separate pool schedule; these are access hours only.",
    ),
}
