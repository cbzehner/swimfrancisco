from __future__ import annotations

import tomllib
from typing import get_args

from .models import CaptureMethod, PoolEntry, PoolSource, SourceKind, SourceStatus
from .paths import CONTENT_SPOTS_DIR, REGISTRY_PATH


_VALID_SOURCE_STATUSES = frozenset(get_args(SourceStatus))
_VALID_SOURCE_KINDS = frozenset(get_args(SourceKind))
_VALID_CAPTURE_METHODS = frozenset(get_args(CaptureMethod))
BROWSER_SOURCES = {
    "jccsf": ("jccsf_html", "https://www.jccsf.org/fitness/aquatics/"),
    "presidio-ymca-letterman": ("ymca_location_html", "https://www.ymcasf.org/location/presidio-community-ymca/letterman-pool-gym/"),
    "stonestown-ymca": ("ymca_location_html", "https://www.ymcasf.org/location/stonestown-family-ymca/"),
    "embarcadero-ymca": ("ymca_location_html", "https://www.ymcasf.org/location/embarcadero-ymca/"),
    "chinatown-ymca": ("ymca_location_html", "https://www.ymcasf.org/location/chinatown-ymca/"),
    "sfsu-mashouf": ("sfsu_aquatics_html", "https://campusrec.sfsu.edu/Aquatics"),
}
APPROVED_DIRECT_SOURCES = {
    "pomeroy-pool": ("pomeroy_html", "https://www.prrcsf.org/therapeutic-swim"),
    **BROWSER_SOURCES,
}
_ACCESS_SOURCES = {slug: BROWSER_SOURCES[slug] for slug in (
    "presidio-ymca-letterman", "stonestown-ymca", "embarcadero-ymca", "chinatown-ymca", "sfsu-mashouf",
)}


def allows_access_transition(slug: str, source_kind: str, source_url: str,
                             source_status: str, payload: dict) -> bool:
    return (
        _ACCESS_SOURCES.get(slug) == (source_kind, source_url)
        and source_status == "access_hours_only"
        and payload.get("schedule_basis") in {"pool_hours", "facility_hours"}
        and payload.get("sessions") == [] and bool(payload.get("access_hours"))
    )



def load_registry(path=REGISTRY_PATH) -> list[PoolEntry]:
    document = tomllib.loads(path.read_text())
    raw_entries = document.get("pool")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(f"{path} does not define any [[pool]] entries.")

    seen_slugs: set[str] = set()
    entries: list[PoolEntry] = []

    for index, raw_entry in enumerate(raw_entries, start=1):
        slug = _require_string(raw_entry, "slug", index)
        sources = raw_entry.get("pool_sources")
        if sources is not None:
            if slug != "north-beach-pool" or raw_entry.get("source_kind", "sfrecpark_pdf") != "sfrecpark_pdf":
                raise ValueError("Paired sources are supported only for North Beach")
            if "pdf_url" in raw_entry or not isinstance(sources, list) or len(sources) != 2:
                raise ValueError("Use exactly two pool_sources, without a single pdf_url")
            if any(not isinstance(item, dict) or set(item) != {"pool", "url"} for item in sources):
                raise ValueError("Each pool source requires pool and url")
            if {item["pool"] for item in sources} != {"cool", "warm"}:
                raise ValueError("North Beach requires one Cool and one Warm source")
            from .discover import view_id_from_url, absolute_view_url
            urls = [item["url"] for item in sources]
            if any(not isinstance(url, str) or not view_id_from_url(url) or url != absolute_view_url(view_id_from_url(url)) for url in urls) or len(set(urls)) != 2:
                raise ValueError("Pool sources require distinct official DocumentCenter URLs")
            pool_sources = tuple(PoolSource(**item) for item in sorted(sources, key=lambda item: item["pool"]))
            pdf_url = ""
        else:
            pdf_url = _require_string(raw_entry, "pdf_url", index)
            pool_sources = ()
        official_page_url = _require_string(raw_entry, "official_page_url", index)
        source_status = raw_entry.get("source_status", "published")
        source_kind = raw_entry.get("source_kind", "sfrecpark_pdf")
        notes = raw_entry.get("notes")
        capture_method = raw_entry.get("capture_method", "http")
        if not isinstance(capture_method, str) or capture_method not in _VALID_CAPTURE_METHODS:
            raise ValueError("capture_method must be http or cloudflare_browser")
        if capture_method == "cloudflare_browser" and BROWSER_SOURCES.get(slug) != (source_kind, pdf_url):
            raise ValueError("Cloudflare browser capture is limited to the six approved HTML sources and URLs")
        auto_publish = raw_entry.get("auto_publish", False)
        if not isinstance(auto_publish, bool) or (auto_publish and APPROVED_DIRECT_SOURCES.get(slug) != (source_kind, pdf_url)):
            raise ValueError("Direct automatic publication is limited to the seven approved source identities")

        if slug in seen_slugs:
            raise ValueError(f"Duplicate registry slug: {slug}")
        seen_slugs.add(slug)

        spot_path = CONTENT_SPOTS_DIR / f"{slug}.md"
        if not spot_path.exists():
            raise ValueError(f"Registry slug {slug!r} does not match an existing {spot_path}.")

        if notes is not None and not isinstance(notes, str):
            raise ValueError(f"notes for {slug!r} must be a string.")
        if source_status not in _VALID_SOURCE_STATUSES:
            valid = ", ".join(sorted(_VALID_SOURCE_STATUSES))
            raise ValueError(
                f"source_status for {slug!r} must be one of: {valid}. Got: {source_status!r}"
            )
        if source_kind not in _VALID_SOURCE_KINDS:
            valid = ", ".join(sorted(_VALID_SOURCE_KINDS))
            raise ValueError(
                f"source_kind for {slug!r} must be one of: {valid}. Got: {source_kind!r}"
            )

        entries.append(
            PoolEntry(
                slug=slug,
                pdf_url=pdf_url,
                official_page_url=official_page_url,
                source_status=source_status,
                source_kind=source_kind,
                auto_publish=auto_publish,
                capture_method=capture_method,
                notes=notes,
                pool_sources=pool_sources,
            )
        )

    return entries


def _require_string(raw_entry: dict, field: str, index: int) -> str:
    value = raw_entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Registry entry #{index} is missing required field {field!r}.")
    return value.strip()
