from __future__ import annotations

import json
from pathlib import Path

from .envelope import EnvelopeValidationError, validate_envelope


def load_reviewed_snapshot_from_path(
    path: Path, *, expected_slug: str, expected_sha: str | None = None,
) -> dict:
    """Load and validate a reviewed-snapshot envelope from a known path.

    Pass ``expected_sha`` to additionally require the envelope's
    ``pdf_sha256`` to match the source currently being processed.
    """
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    try:
        validate_envelope(raw)
    except EnvelopeValidationError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if raw["slug"] != expected_slug:
        raise ValueError(
            f"{path} envelope slug={raw['slug']!r} does not match directory slug={expected_slug!r}"
        )
    if expected_sha is not None and raw["pdf_sha256"] != expected_sha:
        raise ValueError(f"{path} envelope pdf_sha256 does not match current source")
    return raw


_COMPARE_KEYS = {
    "sessions": ("day", "type", "start", "end", "pool"),
    "access_hours": ("day", "start", "end", "label"),
    "access_exceptions": ("date", "start", "end", "label", "reason"),
    "closures": ("start", "end", "reason", "start_time", "end_time"),
}


def _canonical_list(items: list, keys: tuple[str, ...]) -> list[dict]:
    projected = [{key: item[key] for key in keys if key in item} for item in items]
    projected.sort(key=lambda item: tuple(item.get(key, "") for key in keys))
    return projected


def canonicalize_payload(payload: dict) -> dict:
    """Return a comparison-stable form of an extracted payload.

    Sorts sessions and closures, and strips fields that legitimately vary
    between a reviewed snapshot and a fresh provider extraction (e.g.
    `evidence`, free-form `notes`).
    """
    lists = {
        name: _canonical_list(payload.get(name) or [], keys)
        for name, keys in _COMPARE_KEYS.items()
    }
    canonical: dict = {
        "effective_start": payload.get("effective_start"),
        "schedule_basis": payload.get("schedule_basis"),
        "sessions": lists["sessions"],
        "access_hours": lists["access_hours"],
        "access_exceptions": lists["access_exceptions"],
        "closures": lists["closures"],
    }
    if "effective_end" in payload and payload["effective_end"] is not None:
        canonical["effective_end"] = payload["effective_end"]
    return canonical


def payloads_equivalent(
    left: dict,
    right: dict,
    *,
    ignore: frozenset[str] = frozenset(),
) -> bool:
    first = canonicalize_payload(left)
    second = canonicalize_payload(right)
    for key in ignore:
        first.pop(key, None)
        second.pop(key, None)
    return first == second

