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


import json as _json
from datetime import date as _date, datetime as _datetime
from zoneinfo import ZoneInfo
from .paths import REVIEWED_SNAPSHOT_DRAFTS_DIR


_PROVIDER_PREFERENCE = ("gemini", "anthropic")
_PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def _pacific_today() -> _date:
    return _datetime.now(_PACIFIC_TZ).date()


def _pick_provider_artifact(artifact_dir: Path) -> Path:
    """Return the provider artifact to seed from. gemini → anthropic → newest mtime."""
    provider_paths: dict[str, list[Path]] = {}
    for path in artifact_dir.glob("*.json"):
        if path.name == "meta.json":
            continue
        provider = path.name.split("-", 1)[0]
        provider_paths.setdefault(provider, []).append(path)

    for preferred in _PROVIDER_PREFERENCE:
        if preferred in provider_paths:
            return sorted(provider_paths[preferred], key=lambda p: p.stat().st_mtime)[-1]

    all_paths = [p for paths in provider_paths.values() for p in paths]
    if not all_paths:
        raise FileNotFoundError(f"No provider artifacts found in {artifact_dir}")
    return max(all_paths, key=lambda p: p.stat().st_mtime)


def _all_provider_descriptors(artifact_dir: Path, primary_provider: str) -> list[dict]:
    # artifact_dir = <artifacts_root>/<slug>/<hash_prefix>; use <slug>/<hash>/<file>.
    artifacts_root = artifact_dir.parent.parent
    descriptors: list[dict] = []
    for path in sorted(artifact_dir.glob("*.json")):
        if path.name == "meta.json":
            continue
        try:
            payload = _json.loads(path.read_text())
        except (OSError, _json.JSONDecodeError):
            continue
        provider = payload.get("provider")
        model = payload.get("model")
        if isinstance(provider, str) and isinstance(model, str):
            try:
                relpath = str(path.relative_to(artifacts_root))
            except ValueError:
                relpath = str(path)
            descriptors.append({
                "provider": provider,
                "model": model,
                "artifact_relpath": relpath,
            })

    # The provider actually seeded into payload leads; remaining sorted by
    # preference order then provider name.
    def _rank(d: dict) -> tuple[int, int, str]:
        is_primary = 0 if d["provider"] == primary_provider else 1
        try:
            idx = _PROVIDER_PREFERENCE.index(d["provider"])
        except ValueError:
            idx = len(_PROVIDER_PREFERENCE)
        return (is_primary, idx, d["provider"])
    descriptors.sort(key=_rank)
    return descriptors


def draft_path_for(slug: str, pdf_sha256: str, today: _date, root: Path = REVIEWED_SNAPSHOT_DRAFTS_DIR) -> Path:
    return root / slug / f"{today.isoformat()}-{pdf_sha256[:12]}.json"


def seed_draft(
    *,
    candidate: ReviewCandidate,
    drafts_root: Path = REVIEWED_SNAPSHOT_DRAFTS_DIR,
    today: _date | None = None,
) -> Path:
    """Seed a draft envelope in the drafts tree. Returns its path.

    If a draft for this (slug, pdf_sha256) already exists, returns it
    unchanged — resuming work is idempotent.
    """
    today = today or _pacific_today()

    # Idempotent on re-entry: any prior draft for this (slug, pdf_sha256) wins,
    # regardless of the date in its filename.
    slug_drafts = drafts_root / candidate.slug
    prefix = candidate.pdf_sha256[:12]
    if slug_drafts.is_dir():
        for existing in sorted(slug_drafts.glob(f"*-{prefix}.json")):
            return existing

    path = draft_path_for(candidate.slug, candidate.pdf_sha256, today, root=drafts_root)

    provider_path = _pick_provider_artifact(candidate.artifact_dir)
    provider_payload = _json.loads(provider_path.read_text())
    source_pdf_url = provider_payload.get("pdf_url", "")
    payload = provider_payload.get("payload", {})

    envelope = {
        "slug": candidate.slug,
        "pdf_sha256": candidate.pdf_sha256,
        "reviewed_at": today.isoformat(),
        "source_pdf_url": source_pdf_url,
        "payload": payload,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(envelope, indent=2) + "\n")
    return path


from .envelope import EnvelopeValidationError, validate_envelope
from .paths import CONTENT_SPOTS_DIR
from .project import ProjectError, project
from .validate import validate


class FinalizeError(RuntimeError):
    """Raised when finalizing a draft fails; message is reviewer-facing."""


def finalize_draft(
    *,
    draft_path: Path,
    snapshots_root: Path = REVIEWED_SNAPSHOTS_DIR,
    content_spots_dir: Path = CONTENT_SPOTS_DIR,
) -> Path:
    """Finalize a draft envelope into a reviewed snapshot and project its MD.

    Returns the final snapshot path on success. Leaves the draft in place
    on any failure. Commit point is the os.rename; project() runs after.
    """
    try:
        raw = _json.loads(draft_path.read_text())
    except _json.JSONDecodeError as exc:
        raise FinalizeError(f"{draft_path}: invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    except OSError as exc:
        raise FinalizeError(f"{draft_path}: cannot read: {exc}") from exc

    if not isinstance(raw, dict):
        raise FinalizeError(f"{draft_path}: envelope must be a JSON object")

    try:
        validate_envelope(raw)
    except EnvelopeValidationError as exc:
        raise FinalizeError(f"schema: {exc}") from exc

    result = validate(raw.get("payload", {}))
    if not result.ok:
        raise FinalizeError("; ".join(result.violations))

    slug = raw["slug"]
    pdf_sha256 = raw["pdf_sha256"]
    reviewed_at = raw["reviewed_at"]
    destination = snapshots_root / slug / f"{reviewed_at}-{pdf_sha256[:12]}.json"

    if destination.exists():
        raise FinalizeError(
            f"destination {destination} already exists; resolve by deleting either "
            "the existing snapshot or the draft, then retry"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    import os as _os
    _os.rename(draft_path, destination)

    try:
        project(slug=slug, snapshots_root=snapshots_root, content_spots_dir=content_spots_dir)
    except ProjectError as exc:
        raise FinalizeError(
            f"snapshot committed at {destination}, but projection failed: {exc}. "
            f"Re-run `schedules project {slug}` to finish."
        ) from exc

    return destination
