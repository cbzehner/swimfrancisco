from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from types import MappingProxyType

from ._time import pacific_today
from .discover import collapse_grid_candidates, view_id_from_url
from .envelope import EnvelopeValidationError, validate_envelope
from .reviewed_snapshots import payloads_equivalent
from .merge import read_schedule_snapshot
from .paths import (
    CONTENT_SPOTS_DIR,
    DATA_DIR,
    all_review_dirs,
    parse_review_dir_name,
    relative_to_repo,
    reviewed_path,
)
from .project import ProjectError, project
from .validate import validate


def parse_view_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def kept_grid_ids(decision: dict | None) -> set[int]:
    if not isinstance(decision, dict):
        return set()
    items = list(decision.get("candidates") or []) + list(
        decision.get("extra_candidates") or []
    )
    ids: set[int] = set()
    for item in collapse_grid_candidates(items):
        view_id = parse_view_id(item.get("view_id"))
        if view_id is not None:
            ids.add(view_id)
    return ids


@dataclass(frozen=True)
class DecisionSet:
    by_slug: Mapping[str, dict]

    @classmethod
    def from_items(cls, items: list[object]) -> DecisionSet:
        by_slug: dict[str, dict] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            if isinstance(slug, str) and slug and slug not in by_slug:
                by_slug[slug] = item
        return cls(by_slug=MappingProxyType(by_slug))

    @classmethod
    def load(cls, path: Path) -> DecisionSet:
        if not path.is_file():
            return cls.from_items([])
        try:
            data = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return cls.from_items([])
        if not isinstance(data, list):
            return cls.from_items([])
        return cls.from_items(data)

    def get(self, slug: str) -> dict | None:
        return self.by_slug.get(slug)

    def __iter__(self):
        return iter(self.by_slug.values())

    @property
    def sequential_slugs(self) -> tuple[str, ...]:
        return tuple(
            slug for slug, decision in self.by_slug.items() if len(kept_grid_ids(decision)) >= 2
        )

    @property
    def blocking_slugs(self) -> frozenset[str]:
        return frozenset(
            slug for slug, decision in self.by_slug.items() if decision.get("blocking")
        )


@dataclass(frozen=True)
class ReviewCandidate:
    slug: str
    pdf_sha256: str
    review_dir: Path
    source_path: Path
    fetch_date: str  # YYYY-MM-DD derived from the review-dir name prefix
    payload: Mapping[str, object] = field(default_factory=dict, compare=False)
    source_url: str = ""
    view_id: int | None = None


_PROVIDER_JSON_EXCLUDES = {"reviewed.json"}


def _provider_json_paths(review_dir: Path) -> list[Path]:
    return sorted(
        p for p in review_dir.glob("*.json") if p.name not in _PROVIDER_JSON_EXCLUDES
    )


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
            parsed = parse_review_dir_name(review_dir.name)
            if parsed is None:
                continue
            fetch_date, _ = parsed
            try:
                artifact = json.loads(_pick_provider_artifact(review_dir).read_text())
            except (OSError, json.JSONDecodeError, FileNotFoundError):
                continue
            if not isinstance(artifact, dict):
                continue
            full_sha = artifact.get("pdf_sha256")
            if not isinstance(full_sha, str) or len(full_sha) != 64:
                continue
            payload_raw = artifact.get("payload")
            payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
            source_url = artifact.get("source_pdf_url") or artifact.get("pdf_url") or ""
            if not isinstance(source_url, str):
                source_url = ""
            candidates.append(
                ReviewCandidate(
                    slug=slug,
                    pdf_sha256=full_sha,
                    review_dir=review_dir,
                    source_path=_source_path(review_dir),
                    fetch_date=fetch_date,
                    payload=MappingProxyType(payload),
                    source_url=source_url,
                    view_id=view_id_from_url(source_url) if source_url else None,
                )
            )
    candidates.sort(key=lambda c: (c.fetch_date, c.slug))
    return candidates


def carry_forward_review(
    *,
    slug: str,
    review_dir: Path,
    pdf_sha256: str,
    payload: dict,
    ignore_effective_start: bool,
    data_root: Path = DATA_DIR,
) -> Path | None:
    """Re-use an existing attestation for an identical payload.

    When a new source capture extracts a payload byte-equal to the pool's
    most recent attested payload, a prior attestor has already signed this
    exact schedule — the source merely churned. Write ``reviewed.json`` into
    the new capture dir (same envelope, new source sha, ``carried_from``
    provenance) so the pool never enters the review queue. Copies the prior
    ``attested_by`` (or omits it on legacy files). Any payload difference
    returns None and review proceeds as usual.

    ``ignore_effective_start`` is for direct extractors, which stamp
    ``payload.effective_start`` with the fetch date; the field is
    clock-derived there, not source-derived, so it must not block a carry.
    """
    prior = _latest_reviewed_snapshot(slug, exclude_dir=review_dir, data_root=data_root)
    if prior is None:
        return None
    prior_path, prior_envelope = prior

    ignore = frozenset({"effective_start"}) if ignore_effective_start else frozenset()
    if not payloads_equivalent(payload, prior_envelope.get("payload", {}), ignore=ignore):
        return None

    envelope = {
        **prior_envelope,
        "pdf_sha256": pdf_sha256,
        "carried_from": relative_to_repo(prior_path),
    }
    validate_envelope(envelope)

    target = review_dir / "reviewed.json"
    target.write_text(json.dumps(envelope, indent=2) + "\n")
    return target


def _latest_reviewed_snapshot(
    slug: str, *, exclude_dir: Path, data_root: Path
) -> tuple[Path, dict] | None:
    for review_dir in reversed(all_review_dirs(slug, root=data_root)):
        if review_dir.resolve() == exclude_dir.resolve():
            continue
        reviewed_file = review_dir / "reviewed.json"
        if not reviewed_file.exists():
            continue
        try:
            envelope = json.loads(reviewed_file.read_text())
            validate_envelope(envelope)
        except (OSError, json.JSONDecodeError, EnvelopeValidationError):
            continue
        return reviewed_file, envelope
    return None


def _source_path(review_dir: Path) -> Path:
    for name in ("source.pdf", "source.csv", "source.html"):
        path = review_dir / name
        if path.exists():
            return path
    return review_dir / "source.pdf"


_PROVIDER_PREFERENCE = ("gemini", "anthropic")


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
    today = today or pacific_today()
    target = reviewed_path(candidate.slug, candidate.fetch_date, candidate.pdf_sha256, root=data_root)
    if target.exists():
        return target

    envelope = draft_envelope(candidate=candidate, today=today)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(envelope, indent=2) + "\n")
    return target


def draft_envelope(
    *,
    candidate: ReviewCandidate,
    today: _date | None = None,
    attested_by: str = "human",
) -> dict:
    """Build an unsaved reviewed-snapshot envelope from a provider artifact."""
    today = today or pacific_today()
    provider_path = _pick_provider_artifact(candidate.review_dir)
    provider_payload = json.loads(provider_path.read_text())
    source_pdf_url = (
        provider_payload.get("source_pdf_url")
        or provider_payload.get("pdf_url")
        or ""
    )
    payload = provider_payload.get("payload", {})

    return {
        "slug": candidate.slug,
        "pdf_sha256": candidate.pdf_sha256,
        "reviewed_at": today.isoformat(),
        "attested_by": attested_by,
        "source_pdf_url": source_pdf_url,
        "payload": payload,
    }



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

    slug = raw["slug"]
    prior_sessions_count = 0
    md_path = content_spots_dir / f"{slug}.md"
    if md_path.exists():
        snapshot = read_schedule_snapshot(md_path)
        prior_sessions_count = len(snapshot.get("sessions") or [])

    result = validate(raw.get("payload", {}), prior_sessions_count=prior_sessions_count)
    if not result.ok:
        raise FinalizeError("; ".join(v.message for v in result.violations))

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
