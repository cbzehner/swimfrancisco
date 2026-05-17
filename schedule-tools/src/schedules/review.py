from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as _date, datetime as _datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .envelope import EnvelopeValidationError, validate_envelope
from .paths import CONTENT_SPOTS_DIR, DATA_DIR, all_review_dirs, reviewed_path
from .project import ProjectError, project
from .validate import validate


@dataclass(frozen=True)
class ReviewCandidate:
    slug: str
    pdf_sha256: str
    review_dir: Path
    pdf_path: Path
    fetch_date: str  # YYYY-MM-DD derived from the review-dir name prefix


_PROVIDER_JSON_EXCLUDES = {"reviewed.json"}


def _provider_json_paths(review_dir: Path) -> list[Path]:
    return sorted(
        p for p in review_dir.glob("*.json") if p.name not in _PROVIDER_JSON_EXCLUDES
    )


def _full_sha_from_provider_jsons(review_dir: Path) -> str | None:
    """Recover the full pdf_sha256 from any provider payload in the review dir."""
    for provider_path in _provider_json_paths(review_dir):
        try:
            payload = json.loads(provider_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sha = payload.get("pdf_sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    return None


def find_review_candidates(
    *,
    data_root: Path = DATA_DIR,
    only_slug: str | None = None,
) -> list[ReviewCandidate]:
    """Return review candidates ordered by fetch date (oldest first), then slug.

    A candidate is a review dir under ``data/<slug>/`` where at least one
    ``<provider>-<model>.json`` exists AND ``reviewed.json`` does not.
    """
    if not data_root.is_dir():
        return []

    candidates: list[ReviewCandidate] = []
    for slug_dir in sorted(data_root.iterdir()):
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        if only_slug is not None and slug != only_slug:
            continue
        for review_dir in all_review_dirs(slug, root=data_root):
            if (review_dir / "reviewed.json").exists():
                continue
            if not _provider_json_paths(review_dir):
                continue
            full_sha = _full_sha_from_provider_jsons(review_dir)
            if full_sha is None:
                continue
            fetch_date = review_dir.name[:10]
            candidates.append(
                ReviewCandidate(
                    slug=slug,
                    pdf_sha256=full_sha,
                    review_dir=review_dir,
                    pdf_path=review_dir / "source.pdf",
                    fetch_date=fetch_date,
                )
            )
    candidates.sort(key=lambda c: (c.fetch_date, c.slug))
    return candidates


_PROVIDER_PREFERENCE = ("gemini", "anthropic")
_PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def _pacific_today() -> _date:
    return _datetime.now(_PACIFIC_TZ).date()


def _pick_provider_artifact(review_dir: Path) -> Path:
    """Return the provider artifact to seed from. gemini → anthropic → newest mtime."""
    provider_paths: dict[str, list[Path]] = {}
    for path in _provider_json_paths(review_dir):
        provider = path.name.split("-", 1)[0]
        provider_paths.setdefault(provider, []).append(path)

    for preferred in _PROVIDER_PREFERENCE:
        if preferred in provider_paths:
            return sorted(provider_paths[preferred], key=lambda p: p.stat().st_mtime)[-1]

    all_paths = [p for paths in provider_paths.values() for p in paths]
    if not all_paths:
        raise FileNotFoundError(f"No provider artifacts found in {review_dir}")
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

    provider_path = _pick_provider_artifact(candidate.review_dir)
    provider_payload = json.loads(provider_path.read_text())
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
    target.write_text(json.dumps(envelope, indent=2) + "\n")
    return target


class FinalizeError(RuntimeError):
    """Raised when finalizing a draft fails; message is reviewer-facing."""


def _canonical_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _payload_matches_any_provider(payload: dict, review_dir: Path) -> str | None:
    """Return the provider artifact name whose payload byte-equals this one.

    Used to detect "the reviewer didn't actually edit anything" — a bypass of
    the human review contract. A re-export of the same PDF that yields a
    legitimately correct LLM payload still requires the reviewer to make an
    explicit attestation edit (a notes field, a reorder, anything).
    """
    target = _canonical_payload(payload)
    for provider_path in _provider_json_paths(review_dir):
        try:
            provider = json.loads(provider_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if provider.get("provider") == "direct":
            continue
        if _canonical_payload(provider.get("payload", {})) == target:
            return provider_path.name
    return None


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
        raw = json.loads(reviewed_json_path.read_text())
    except json.JSONDecodeError as exc:
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
        raise FinalizeError("; ".join(v.message for v in result.violations))

    matched = _payload_matches_any_provider(raw.get("payload", {}), reviewed_json_path.parent)
    if matched is not None:
        raise FinalizeError(
            f"reviewed payload is byte-identical to {matched} — "
            "no human edits detected. Re-open the file, verify each row "
            "against the source PDF, and make at least one explicit change "
            "(a notes field, a reorder, an evidence edit) before saving."
        )

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
