from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import (
    ARTIFACTS_DIR,
    PDF_CACHE_DIR,
    REVIEWED_SNAPSHOTS_DIR,
)


@dataclass(frozen=True)
class ReviewCandidate:
    slug: str
    pdf_sha256: str
    artifact_dir: Path
    pdf_path: Path | None
    pdf_date: str  # YYYY-MM-DD extracted from PDF filename; empty string if no PDF


_PDF_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{12})\.pdf$")


def _reviewed_sha256s_for_slug(snapshots_root: Path, slug: str) -> set[str]:
    slug_dir = snapshots_root / slug
    if not slug_dir.is_dir():
        return set()
    out: set[str] = set()
    for path in slug_dir.glob("*.json"):
        try:
            envelope = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sha = envelope.get("pdf_sha256")
        if isinstance(sha, str):
            out.add(sha)
    return out


def _full_sha_from_artifact(artifact_dir: Path) -> str | None:
    """Recover the full pdf_sha256 from any provider payload in the dir."""
    for provider_path in sorted(artifact_dir.glob("*.json")):
        if provider_path.name == "meta.json":
            continue
        try:
            payload = json.loads(provider_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sha = payload.get("pdf_sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    # Fall back to meta.json, which also carries pdf_sha256.
    meta_path = artifact_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        sha = meta.get("pdf_sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    return None


def _pdf_date_for(pdfs_root: Path, slug: str, pdf_sha256: str) -> tuple[str, Path | None]:
    slug_dir = pdfs_root / slug
    if not slug_dir.is_dir():
        return "", None
    prefix = pdf_sha256[:12]
    for path in sorted(slug_dir.glob(f"*-{prefix}.pdf")):
        m = _PDF_NAME.match(path.name)
        if m:
            return m.group(1), path
    return "", None


def find_review_candidates(
    *,
    artifacts_root: Path = ARTIFACTS_DIR,
    snapshots_root: Path = REVIEWED_SNAPSHOTS_DIR,
    pdfs_root: Path = PDF_CACHE_DIR,
    only_slug: str | None = None,
) -> list[ReviewCandidate]:
    """Return review candidates ordered by PDF publication date, then slug."""
    if not artifacts_root.is_dir():
        return []

    candidates: list[ReviewCandidate] = []
    for slug_dir in sorted(artifacts_root.iterdir()):
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        if only_slug is not None and slug != only_slug:
            continue
        reviewed = _reviewed_sha256s_for_slug(snapshots_root, slug)
        for hash_dir in sorted(slug_dir.iterdir()):
            if not hash_dir.is_dir():
                continue
            full_sha = _full_sha_from_artifact(hash_dir)
            if full_sha is None or full_sha in reviewed:
                continue
            pdf_date, pdf_path = _pdf_date_for(pdfs_root, slug, full_sha)
            candidates.append(
                ReviewCandidate(
                    slug=slug,
                    pdf_sha256=full_sha,
                    artifact_dir=hash_dir,
                    pdf_path=pdf_path,
                    pdf_date=pdf_date,
                )
            )
    candidates.sort(key=lambda c: (c.pdf_date, c.slug))
    return candidates
