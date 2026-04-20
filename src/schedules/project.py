from __future__ import annotations

from pathlib import Path

from .merge import merge
from .paths import CONTENT_SPOTS_DIR, REVIEWED_SNAPSHOTS_DIR, REVIEWED_SNAPSHOT_DRAFTS_DIR
from .reviewed_snapshots import (
    canonicalize_payload,
    load_reviewed_snapshot_from_path,
)
from .validate import validate


class ProjectError(RuntimeError):
    """Raised when projection fails; message is reviewer-facing."""


def _latest_snapshot_path(snapshots_root: Path, slug: str) -> Path | None:
    slug_dir = snapshots_root / slug
    if not slug_dir.is_dir():
        return None
    candidates = sorted(slug_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def project(
    *,
    slug: str,
    snapshots_root: Path = REVIEWED_SNAPSHOTS_DIR,
    content_spots_dir: Path = CONTENT_SPOTS_DIR,
) -> Path:
    """Project the latest reviewed snapshot for `slug` into content/spots/<slug>.md.

    Raises ProjectError with a reviewer-facing message on any failure.
    Returns the path to the written MD. Idempotent.
    """
    # Explicit draft-tree guard: spec contract.
    if snapshots_root.name == REVIEWED_SNAPSHOT_DRAFTS_DIR.name:
        raise ProjectError(
            f"refusing to project from draft tree {snapshots_root}; "
            "drafts must be finalized into reviewed-snapshots first"
        )

    snapshot_path = _latest_snapshot_path(snapshots_root, slug)
    if snapshot_path is None:
        raise ProjectError(f"no reviewed snapshot found for slug={slug!r}")

    envelope, _, _ = load_reviewed_snapshot_from_path(snapshot_path, expected_slug=slug)
    canonical = canonicalize_payload(envelope["payload"])

    result = validate(canonical)
    if not result.ok:
        raise ProjectError("; ".join(result.violations))

    md_path = content_spots_dir / f"{slug}.md"
    if not md_path.exists():
        raise ProjectError(f"content file missing: {md_path}")

    merge(md_path, canonical)
    return md_path
