from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .._time import pacific_today
from ..models import PoolEntry
from ..paths import DATA_DIR
from .errors import DirectSourceError
from .http import (
    DirectFetchResult,
    _cache_text,
    _xlsx_content_sha256,
    fetch_koret_workbook,
    fetch_text,
)
from .parsing import _resolve_yearless_date, _stable_payload_key
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
    "_xlsx_content_sha256",
]


@dataclass(frozen=True)
class DirectExtraction:
    fetch_result: DirectFetchResult
    payload: dict
    model: str
    notes: list[str]


def extract_direct(entry: PoolEntry, *, cache_root: Path | None = None) -> DirectExtraction:
    fetch_kwargs = {"cache_root": cache_root} if cache_root is not None else {}
    if entry.source_kind == "koret_google_sheet":
        fetched = fetch_koret_workbook(entry.slug, entry.pdf_url, **fetch_kwargs)
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_koret(fetched.path),
            model="koret-google-workbook-v1",
            notes=["Koret sessions represent official pool hours; the sheet still carries lane-level restrictions and team bookings."],
        )
    spec = _HTML_EXTRACTORS.get(entry.source_kind or "")
    if spec is None:
        raise DirectSourceError(f"{entry.slug}: unsupported direct source kind {entry.source_kind!r}")
    extractor, model, note = spec
    cache_root = fetch_kwargs.get("cache_root") or DATA_DIR
    text, response_url = fetch_text(entry.pdf_url)
    payload = extractor(text)
    sha256 = hashlib.sha256(_stable_payload_key(payload).encode("utf-8")).hexdigest()
    slug_dir = cache_root / entry.slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path, from_cache = _cache_text(slug_dir, sha256, "html", text)
    fetched = DirectFetchResult(
        path=path,
        sha256=sha256,
        from_cache=from_cache,
        response_url=response_url,
    )
    return DirectExtraction(
        fetch_result=fetched,
        payload=payload,
        model=model,
        notes=[note],
    )


# HTML sources share fetch + one extract + a payload cache key. Adding a
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
