from __future__ import annotations

from pathlib import Path

from .merge import merge
from .paths import CONTENT_SPOTS_DIR
from .reviewed_snapshots import (
    canonicalize_payload,
    load_reviewed_snapshot_from_path,
)
from .validate import validate


class ProjectError(RuntimeError):
    """Raised when projection fails; message is reviewer-facing."""


def project(
    *,
    slug: str,
    reviewed_json_path: Path,
    content_spots_dir: Path = CONTENT_SPOTS_DIR,
) -> Path:
    """Project `reviewed_json_path` into content/spots/<slug>.md.

    Raises ProjectError with a reviewer-facing message on any failure.
    Returns the path to the written MD. Idempotent.
    """
    envelope, _, _ = load_reviewed_snapshot_from_path(reviewed_json_path, expected_slug=slug)
    canonical = canonicalize_payload(envelope["payload"])

    result = validate(canonical)
    if not result.ok:
        raise ProjectError("; ".join(v.message for v in result.violations))

    md_path = content_spots_dir / f"{slug}.md"
    if not md_path.exists():
        raise ProjectError(f"content file missing: {md_path}")

    merge(md_path, canonical, last_verified_at=envelope["reviewed_at"])
    return md_path
