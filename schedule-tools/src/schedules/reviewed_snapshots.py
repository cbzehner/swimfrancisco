from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .envelope import EnvelopeValidationError, validate_envelope
from .paths import relative_to_repo


def load_reviewed_snapshot_from_path(
    path: Path, *, expected_slug: str,
) -> tuple[dict, str, str]:
    """Load a snapshot when the on-disk path is already known.

    Does not require the caller to know the envelope's ``pdf_sha256`` in
    advance — it extracts it from the file and validates.
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
    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    return raw, fingerprint, relative_to_repo(path)


_SESSION_COMPARE_KEYS = ("day", "type", "start", "end", "pool")
_ACCESS_HOUR_COMPARE_KEYS = ("day", "start", "end", "label")
_ACCESS_EXCEPTION_COMPARE_KEYS = ("date", "start", "end", "label", "reason")
_CLOSURE_COMPARE_KEYS = ("start", "end", "reason", "start_time", "end_time")


def _project(source: dict, keys: tuple[str, ...]) -> dict:
    return {key: source[key] for key in keys if key in source}


def canonicalize_payload(payload: dict) -> dict:
    """Return a comparison-stable form of an extracted payload.

    Sorts sessions and closures, and strips fields that legitimately vary
    between a reviewed snapshot and a fresh provider extraction (e.g.
    `evidence`, free-form `notes`).
    """
    sessions = [_project(session, _SESSION_COMPARE_KEYS) for session in payload.get("sessions") or []]
    sessions.sort(key=lambda s: tuple(s.get(key, "") for key in _SESSION_COMPARE_KEYS))

    closures = [_project(closure, _CLOSURE_COMPARE_KEYS) for closure in payload.get("closures") or []]
    closures.sort(key=lambda c: tuple(c.get(key, "") for key in _CLOSURE_COMPARE_KEYS))

    access_hours = [
        _project(access_hour, _ACCESS_HOUR_COMPARE_KEYS)
        for access_hour in payload.get("access_hours") or []
    ]
    access_hours.sort(key=lambda a: tuple(a.get(key, "") for key in _ACCESS_HOUR_COMPARE_KEYS))

    access_exceptions = [
        _project(access_exception, _ACCESS_EXCEPTION_COMPARE_KEYS)
        for access_exception in payload.get("access_exceptions") or []
    ]
    access_exceptions.sort(key=lambda a: tuple(a.get(key, "") for key in _ACCESS_EXCEPTION_COMPARE_KEYS))

    canonical: dict = {
        "effective_start": payload.get("effective_start"),
        "schedule_basis": payload.get("schedule_basis"),
        "sessions": sessions,
        "access_hours": access_hours,
        "access_exceptions": access_exceptions,
        "closures": closures,
    }
    if "effective_end" in payload and payload["effective_end"] is not None:
        canonical["effective_end"] = payload["effective_end"]
    return canonical
