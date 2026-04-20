from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import (
    ARTIFACTS_DIR,
    DATA_DIR,
    PDF_CACHE_DIR,
    REVIEWED_SNAPSHOTS_DIR,
    reviewed_path,
)


@dataclass(frozen=True)
class ReviewCandidate:
    slug: str
    pdf_sha256: str
    artifact_dir: Path
    pdf_path: Path | None
    fetch_date: str  # YYYY-MM-DD; first-seen date (from PDF filename or today)


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
                    fetch_date=pdf_date,
                )
            )
    candidates.sort(key=lambda c: (c.fetch_date, c.slug))
    return candidates


import json as _json
from datetime import date as _date, datetime as _datetime
from zoneinfo import ZoneInfo


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


def seed_draft(
    *,
    candidate: ReviewCandidate,
    data_root: Path = DATA_DIR,
    today: _date | None = None,
) -> Path:
    """Write `reviewed.json` under the per-review dir if it does not exist.

    Returns the target path regardless of whether a write happened. Reviewers
    who want to discard WIP use `git restore`; to start over from raw
    extraction, remove the file and re-run `schedules review`.
    """
    today = today or _pacific_today()
    target = reviewed_path(candidate.slug, candidate.fetch_date, candidate.pdf_sha256, root=data_root)
    if target.exists():
        return target

    provider_path = _pick_provider_artifact(candidate.artifact_dir)
    provider_payload = _json.loads(provider_path.read_text())
    source_pdf_url = (
        provider_payload.get("source_pdf_url")
        or provider_payload.get("pdf_url")
        or ""
    )
    payload = provider_payload.get("payload", {})

    envelope = {
        "slug": candidate.slug,
        "pdf_sha256": candidate.pdf_sha256,
        "reviewed_at": today.isoformat(),
        "source_pdf_url": source_pdf_url,
        "payload": payload,
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_json.dumps(envelope, indent=2) + "\n")
    return target


from .envelope import EnvelopeValidationError, validate_envelope
from .paths import CONTENT_SPOTS_DIR
from .project import ProjectError, project
from .validate import validate


class FinalizeError(RuntimeError):
    """Raised when finalizing a draft fails; message is reviewer-facing."""


def finalize_draft(
    *,
    reviewed_json_path: Path,
    content_spots_dir: Path = CONTENT_SPOTS_DIR,
) -> Path:
    """Validate `reviewed.json` in place and project it into content/spots/<slug>.md.

    No rename: `reviewed.json` IS the final file. Returns the reviewed.json
    path on success. On any failure, raises FinalizeError and leaves the
    file unchanged on disk.
    """
    try:
        raw = _json.loads(reviewed_json_path.read_text())
    except _json.JSONDecodeError as exc:
        raise FinalizeError(f"{reviewed_json_path}: invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    except OSError as exc:
        raise FinalizeError(f"{reviewed_json_path}: cannot read: {exc}") from exc

    if not isinstance(raw, dict):
        raise FinalizeError(f"{reviewed_json_path}: envelope must be a JSON object")

    try:
        validate_envelope(raw)
    except EnvelopeValidationError as exc:
        raise FinalizeError(f"schema: {exc}") from exc

    result = validate(raw.get("payload", {}))
    if not result.ok:
        raise FinalizeError("; ".join(result.violations))

    slug = raw["slug"]
    try:
        project(
            slug=slug,
            reviewed_json_path=reviewed_json_path,
            content_spots_dir=content_spots_dir,
        )
    except ProjectError as exc:
        raise FinalizeError(
            f"reviewed.json at {reviewed_json_path} validated, but projection failed: {exc}. "
            f"Re-run `schedules project {slug}` to finish."
        ) from exc

    return reviewed_json_path
