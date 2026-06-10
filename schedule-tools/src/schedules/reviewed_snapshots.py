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
