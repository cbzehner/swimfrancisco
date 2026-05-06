from __future__ import annotations

import tomllib
from typing import get_args

from .models import PoolEntry, SourceStatus
from .paths import CONTENT_SPOTS_DIR, REGISTRY_PATH


_VALID_SOURCE_STATUSES = frozenset(get_args(SourceStatus))


def load_registry(path=REGISTRY_PATH) -> list[PoolEntry]:
    document = tomllib.loads(path.read_text())
    raw_entries = document.get("pool")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(f"{path} does not define any [[pool]] entries.")

    seen_slugs: set[str] = set()
    entries: list[PoolEntry] = []

    for index, raw_entry in enumerate(raw_entries, start=1):
        slug = _require_string(raw_entry, "slug", index)
        pdf_url = _require_string(raw_entry, "pdf_url", index)
        official_page_url = _require_string(raw_entry, "official_page_url", index)
        source_status = raw_entry.get("source_status", "published")
        notes = raw_entry.get("notes")

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

        entries.append(
            PoolEntry(
                slug=slug,
                pdf_url=pdf_url,
                official_page_url=official_page_url,
                source_status=source_status,
                notes=notes,
            )
        )

    return entries


def _require_string(raw_entry: dict, field: str, index: int) -> str:
    value = raw_entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Registry entry #{index} is missing required field {field!r}.")
    return value.strip()

