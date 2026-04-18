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
