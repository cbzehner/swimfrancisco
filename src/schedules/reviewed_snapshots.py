from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .paths import REVIEWED_SNAPSHOTS_DIR, relative_to_repo


REVIEWED_SNAPSHOT_VERSION = 1
_REQUIRED_ENVELOPE_FIELDS = (
    "version",
    "slug",
    "pdf_sha256",
    "reviewed_at",
    "source_pdf_url",
    "reviewed_against",
    "payload",
)


def reviewed_snapshot_path(slug: str, pdf_sha256: str, root: Path = REVIEWED_SNAPSHOTS_DIR) -> Path:
    return root / slug / f"{pdf_sha256}.json"


def _validate_envelope(raw: dict, path: Path, *, expected_slug: str, expected_pdf_sha256: str) -> None:
    missing = [field for field in _REQUIRED_ENVELOPE_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{path} is missing required field(s): {', '.join(missing)}")
    if raw["version"] != REVIEWED_SNAPSHOT_VERSION:
        raise ValueError(
            f"{path} has version={raw['version']!r}, expected {REVIEWED_SNAPSHOT_VERSION}"
        )
    if raw["slug"] != expected_slug:
        raise ValueError(
            f"{path} envelope slug={raw['slug']!r} does not match directory slug={expected_slug!r}"
        )
    if raw["pdf_sha256"] != expected_pdf_sha256:
        raise ValueError(
            f"{path} envelope pdf_sha256 does not match filename sha256"
        )
    if not isinstance(raw["payload"], dict):
        raise ValueError(f"{path} payload must be an object")
    if not isinstance(raw["reviewed_against"], list):
        raise ValueError(f"{path} reviewed_against must be a list")


def load_reviewed_snapshot(
    slug: str,
    pdf_sha256: str,
    *,
    root: Path = REVIEWED_SNAPSHOTS_DIR,
) -> tuple[dict | None, str | None, str | None]:
    path = reviewed_snapshot_path(slug, pdf_sha256, root)
    if not path.exists():
        return None, None, None

    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    _validate_envelope(raw, path, expected_slug=slug, expected_pdf_sha256=pdf_sha256)

    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    return raw, fingerprint, relative_to_repo(path)


_SESSION_COMPARE_KEYS = ("day", "type", "start", "end", "pool")
_CLOSURE_COMPARE_KEYS = ("start", "end", "reason")


def _project(source: dict, keys: tuple[str, ...]) -> dict:
    return {key: source[key] for key in keys if key in source}


def canonicalize_payload(payload: dict) -> dict:
    """Return a comparison-stable form of an extracted payload.

    Sorts sessions and closures, and strips fields that legitimately vary
    between a reviewed snapshot and a fresh provider extraction (e.g.
    `evidence`, free-form `notes`). Used by the ratification check: two
    payloads with identical canonical forms represent the same schedule.
    """
    sessions = [_project(session, _SESSION_COMPARE_KEYS) for session in payload.get("sessions") or []]
    sessions.sort(key=lambda s: tuple(s.get(key, "") for key in _SESSION_COMPARE_KEYS))

    closures = [_project(closure, _CLOSURE_COMPARE_KEYS) for closure in payload.get("closures") or []]
    closures.sort(key=lambda c: tuple(c.get(key, "") for key in _CLOSURE_COMPARE_KEYS))

    canonical: dict = {
        "schedule_effective": payload.get("schedule_effective"),
        "sessions": sessions,
        "closures": closures,
    }
    if "schedule_effective_end" in payload and payload["schedule_effective_end"] is not None:
        canonical["schedule_effective_end"] = payload["schedule_effective_end"]
    return canonical
