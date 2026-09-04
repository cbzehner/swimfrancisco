from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import tomlkit

from ._time import pacific_today
from .discover import view_id_from_url
from .fetch import fetch_pdf
from .merge import _split_frontmatter, read_schedule_snapshot
from .models import GroundingSummary, SourceStatus
from .paths import (
    CONTENT_SPOTS_DIR,
    DATA_DIR,
    PACKAGE_ROOT,
    TMP_DIR,
    all_review_dirs,
    parse_review_dir_name,
)
from .pipeline import GROUNDING_MIN_RATIO
from .registry import load_registry
from .review import (
    DecisionSet,
    FinalizeError,
    ReviewCandidate,
    _pick_provider_artifact,
    draft_envelope,
    finalize_draft,
    find_review_candidates,
    kept_grid_ids,
)
from .signals import analyze_page_texts, extract_page_texts
from .validate import validate
from .window_dates import parse_window_dates, windows_disjoint

QUARANTINE_PATH = PACKAGE_ROOT / "quarantine.toml"
_AUTO_PUBLISHABLE_BASES = frozenset({"swim_schedule", "temporarily_closed"})


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    code: str | None
    message: str = ""


class PublishRefuse(Exception):
    """Per-pool auto-publish refuse; command continues."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _ok() -> Eligibility:
    return Eligibility(ok=True, code=None)


def _refuse(code: str, message: str) -> Eligibility:
    return Eligibility(ok=False, code=code, message=message)


def load_quarantine(path: Path | None = None) -> frozenset[str]:
    path = QUARANTINE_PATH if path is None else path
    if not path.exists():
        return frozenset()
    data = tomllib.loads(path.read_text())
    shas: set[str] = set()
    for row in data.get("quarantine") or []:
        if not isinstance(row, dict):
            continue
        sha = row.get("pdf_sha256")
        if isinstance(sha, str) and sha:
            shas.add(sha)
    return frozenset(shas)


def auto_project_enabled() -> bool:
    return os.environ.get("SCHEDULES_AUTO_PROJECT") != "false"


def latest_effective_start(md_path: Path) -> str | None:
    starts = [
        start
        for table in _schedule_tables(md_path)
        if isinstance((start := table.get("effective_start")), str) and start
    ]
    return max(starts) if starts else None


def _schedule_tables(md_path: Path) -> list:
    if not md_path.exists():
        return []
    frontmatter, _ = _split_frontmatter(md_path.read_text())
    extra = tomlkit.parse(frontmatter).get("extra", {})
    schedules = extra.get("schedules")
    if schedules is None:
        return []
    return list(schedules)


_PAGER_EXCLUDED_REFUSE_CODES = frozenset(
    {"not_rec_park", "split_pdf", "discovery_flagged", "kill_switch"}
)


def pager_flagged_set(
    *,
    refused: list[dict],
    blocking: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """Operator pager rows. Omits not_rec_park and other out-of-scope refuses."""
    rows: set[tuple[str, str]] = set()
    for item in blocking or []:
        slug = item.get("slug")
        if not slug:
            continue
        rows.add((slug, str(item.get("reason") or item.get("code") or "flag")))
    for item in refused:
        if item.get("code") in _PAGER_EXCLUDED_REFUSE_CODES:
            continue
        slug = item.get("slug")
        if slug:
            rows.add((slug, str(item.get("code") or "")))
    return sorted(rows)


def pager_job_payload(tmp_dir: Path) -> dict:
    """Machine payload for the extract job's pager-outputs step."""
    decisions_path = tmp_dir / "discovery-decisions.json"
    publish_path = tmp_dir / "publish-pending.json"
    flagged_computed = decisions_path.is_file()
    decisions = DecisionSet.load(decisions_path)
    blocking = [item for item in decisions if item.get("blocking")]
    refused: list[dict] = []
    published: list[str] = []
    if publish_path.is_file():
        try:
            payload = json.loads(publish_path.read_text())
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            refused = [item for item in (payload.get("refused") or []) if isinstance(item, dict)]
            published = [
                slug for slug in (payload.get("published") or []) if isinstance(slug, str)
            ]
    rows = pager_flagged_set(refused=refused, blocking=blocking)
    return {
        "flagged_computed": flagged_computed,
        "flagged_set": [f"{slug}:{code}" for slug, code in rows],
        "published_slugs": published,
    }


def parse_closure_dates(
    filename: str | None, anchor_text: str | None
) -> tuple[date, date] | None:
    return parse_window_dates(
        page_text=None,
        anchor_text=anchor_text,
        filename=filename,
        year_default=pacific_today().year,
    )


def publish_eligible(
    *,
    candidate: ReviewCandidate,
    payload: dict,
    grounding: GroundingSummary | None,
    prior_sessions_count: int,
    latest_effective_start: str | None,
    source_kind: str,
    source_status: SourceStatus,
    blocking_slugs: frozenset[str],
    quarantined_shas: frozenset[str],
    has_prior_schedule_window: bool,
    source_pdf_path: Path | None,
    kill_switch: bool = False,
    require_unique_pin: bool = False,
    require_grounding: bool = True,
    pin_url: str | None = None,
    source_pdf_url: str | None = None,
    decision: dict | None = None,
) -> Eligibility:
    if kill_switch:
        return _refuse("kill_switch", "SCHEDULES_AUTO_PROJECT=false")

    identity = _identity_gate(candidate)
    if not identity.ok:
        return identity

    if source_kind != "sfrecpark_pdf":
        return _refuse("not_rec_park", f"source_kind {source_kind!r} is not auto-published")

    if source_status == "missing_current_schedule":
        return _refuse("split_pdf", "source_status is missing_current_schedule")

    if candidate.slug in blocking_slugs:
        return _refuse("discovery_flagged", f"{candidate.slug} is discover-blocking")

    if require_unique_pin:
        unique = _unique_pin_gate(candidate, decision, pin_url, source_pdf_url)
        if not unique.ok:
            return unique

    if candidate.pdf_sha256 in quarantined_shas:
        return _refuse("quarantined", f"pdf_sha256 {candidate.pdf_sha256} is quarantined")

    if not has_prior_schedule_window:
        return _refuse("no_merge_baseline", f"no [[extra.schedules]] window for {candidate.slug}")

    result = validate(payload, prior_sessions_count=prior_sessions_count)
    if result.catastrophic:
        first = result.violations[0] if result.violations else None
        code = first.code if first else "sessions_dropped_to_zero"
        message = first.message if first else "catastrophic validation"
        return _refuse(code, message)
    if not result.ok:
        first = result.violations[0]
        return _refuse(first.code if first.code else "validate_failed", first.message)

    if require_grounding:
        if grounding is None:
            return _refuse("grounding_unavailable", "provider JSON is missing a grounding key")
        if grounding.ratio < GROUNDING_MIN_RATIO:
            return _refuse(
                "grounding_coverage_low",
                f"grounding ratio {grounding.ratio:.2f} is below {GROUNDING_MIN_RATIO}",
            )

    grid = _source_pdf_gate(source_pdf_path)
    if not grid.ok:
        return grid

    basis = payload.get("schedule_basis")
    if basis not in _AUTO_PUBLISHABLE_BASES:
        return _refuse("wrong_basis", f"schedule_basis {basis!r} is not auto-publishable")

    new_start = payload.get("effective_start")
    if (
        isinstance(latest_effective_start, str)
        and isinstance(new_start, str)
        and new_start < latest_effective_start
    ):
        return _refuse(
            "effective_start_regressed",
            f"effective_start {new_start} is before latest window {latest_effective_start}",
        )

    return _ok()


def _unique_pin_gate(
    candidate: ReviewCandidate,
    decision: dict | None,
    pin_url: str | None,
    source_pdf_url: str | None,
) -> Eligibility:
    kept = kept_grid_ids(decision)
    if len(kept) >= 2:
        return _refuse(
            "sibling_session_grids",
            f"{candidate.slug} has {len(kept)} session_grid windows",
        )
    candidate_id = view_id_from_url(source_pdf_url or "")
    pin_id = view_id_from_url(pin_url or "")
    if candidate_id is not None and pin_id is not None and candidate_id != pin_id:
        return _refuse(
            "not_current_pin",
            f"candidate View {candidate_id} is not pdf_url View {pin_id}",
        )
    return _ok()


def _identity_gate(candidate: ReviewCandidate) -> Eligibility:
    parsed = parse_review_dir_name(candidate.review_dir.name)
    if parsed is None or parsed[1] != candidate.pdf_sha256[:12]:
        return _refuse(
            "identity_mismatch",
            f"review dir {candidate.review_dir.name} does not match sha {candidate.pdf_sha256[:12]}",
        )
    try:
        artifact = json.loads(_pick_provider_artifact(candidate.review_dir).read_text())
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return _refuse("identity_mismatch", "no provider JSON in review dir")
    provider_sha = artifact.get("pdf_sha256")
    if provider_sha != candidate.pdf_sha256:
        return _refuse(
            "identity_mismatch",
            "provider pdf_sha256 does not match candidate",
        )
    return _ok()


def _source_pdf_gate(source_pdf_path: Path | None) -> Eligibility:
    if source_pdf_path is None or not source_pdf_path.exists():
        return _refuse("source_pdf_missing", "source.pdf is missing")
    try:
        page_texts = extract_page_texts(source_pdf_path.read_bytes())
    except Exception:  # noqa: BLE001
        return _refuse("source_pdf_missing", "source.pdf could not be read")
    grid_pages = analyze_page_texts(page_texts)
    if len(grid_pages) >= 2:
        return _refuse(
            "multi_grid_suspected",
            f"source.pdf has {len(grid_pages)} day-grid pages",
        )
    return _ok()


def publish_candidate(
    *,
    candidate: ReviewCandidate,
    content_spots_dir: Path,
    attested_at: date,
    eligibility: Eligibility,
) -> Path:
    """Write reviewed.json (attested_by=ci) and finalize_draft. Unlink on failure."""
    if not eligibility.ok:
        raise PublishRefuse(eligibility.code or "refused", eligibility.message)
    envelope = draft_envelope(
        candidate=candidate, today=attested_at, attested_by="ci"
    )
    target = candidate.review_dir / "reviewed.json"
    target.write_text(json.dumps(envelope, indent=2) + "\n")
    try:
        finalize_draft(
            reviewed_json_path=target,
            content_spots_dir=content_spots_dir,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def publish_closure_notice(
    *,
    slug: str,
    flyer: dict,
    content_spots_dir: Path,
    attested_at: date,
    quarantined_shas: frozenset[str],
    data_root: Path = DATA_DIR,
) -> Path | None:
    """Fetch flyer URL, parse dates, project temporarily_closed. No registry write."""
    parsed = parse_closure_dates(flyer.get("filename"), flyer.get("anchor_text"))
    if parsed is None:
        raise PublishRefuse("closure_dates_unparsed", "could not parse closure dates")
    start, end = parsed

    md_path = content_spots_dir / f"{slug}.md"
    if not md_path.exists() or not _schedule_tables(md_path):
        raise PublishRefuse("no_merge_baseline", f"no [[extra.schedules]] window for {slug}")
    for table in _schedule_tables(md_path):
        if table.get("effective_start") == start.isoformat():
            return None

    href = flyer.get("href")
    if not isinstance(href, str) or not href:
        raise PublishRefuse("closure_notice_missing", "flyer href is missing")

    fetched = fetch_pdf(slug, href, cache_root=data_root)
    if fetched.sha256 in quarantined_shas:
        raise PublishRefuse("quarantined", f"flyer sha {fetched.sha256} is quarantined")

    title = (flyer.get("anchor_text") or flyer.get("filename") or "").strip()
    payload = {
        "schedule_basis": "temporarily_closed",
        "effective_start": start.isoformat(),
        "effective_end": end.isoformat(),
        "sessions": [],
        "closures": [
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "reason": title or "Maintenance closure",
            }
        ],
    }
    if payload["sessions"]:
        raise PublishRefuse("flyer_emitted_sessions", "closure payload has sessions")

    envelope = {
        "slug": slug,
        "pdf_sha256": fetched.sha256,
        "reviewed_at": attested_at.isoformat(),
        "attested_by": "ci",
        "source_pdf_url": href,
        "payload": payload,
    }
    target = fetched.path.parent / "reviewed.json"
    target.write_text(json.dumps(envelope, indent=2) + "\n")
    try:
        finalize_draft(
            reviewed_json_path=target,
            content_spots_dir=content_spots_dir,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def publish_pending_all(
    *,
    data_root: Path | None = None,
    content_spots_dir: Path | None = None,
    today: date | None = None,
) -> tuple[int, Path]:
    """Returns (published_count, report_path). Writes tmp/publish-pending-report.md
    and tmp/publish-pending.json."""
    data_root = DATA_DIR if data_root is None else data_root
    content_spots_dir = CONTENT_SPOTS_DIR if content_spots_dir is None else content_spots_dir
    attested_at = today or pacific_today()
    tmp_dir = TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    report_path = tmp_dir / "publish-pending-report.md"
    json_path = tmp_dir / "publish-pending.json"

    if not auto_project_enabled():
        _write_reports(
            report_path,
            json_path,
            published=[],
            refused=[],
            closure=[],
            windows=[],
            skipped="kill_switch",
        )
        return 0, report_path

    published: list[str] = []
    refused: list[dict] = []
    closure: list[str] = []
    windows: list[dict] = []
    decisions = DecisionSet.load(tmp_dir / "discovery-decisions.json")
    sequential_slugs = decisions.sequential_slugs
    blocking_slugs = decisions.blocking_slugs
    quarantined_shas = load_quarantine()
    entries = {entry.slug: entry for entry in load_registry()}
    candidates = find_review_candidates(data_root=data_root)

    for candidate in candidates:
        if candidate.slug in sequential_slugs:
            continue
        try:
            _publish_unique_grid(
                candidate=candidate,
                entries=entries,
                blocking_slugs=blocking_slugs,
                quarantined_shas=quarantined_shas,
                content_spots_dir=content_spots_dir,
                attested_at=attested_at,
                decisions=decisions,
            )
        except PublishRefuse as exc:
            refused.append(
                {"slug": candidate.slug, "code": exc.code, "message": exc.message}
            )
        except FinalizeError as exc:
            refused.append(
                {
                    "slug": candidate.slug,
                    "code": "finalize_failed",
                    "message": str(exc),
                }
            )
        else:
            published.append(candidate.slug)

    for slug in sequential_slugs:
        decision = decisions.get(slug)
        if decision is None:
            continue
        try:
            sitting_windows = publish_sequential_slug(
                slug=slug,
                decision=decision,
                candidates=[item for item in candidates if item.slug == slug],
                content_spots_dir=content_spots_dir,
                attested_at=attested_at,
                quarantined_shas=quarantined_shas,
                entries=entries,
                data_root=data_root,
                blocking_slugs=blocking_slugs,
            )
        except PublishRefuse as exc:
            refused.append({"slug": slug, "code": exc.code, "message": exc.message})
        except FinalizeError as exc:
            refused.append({"slug": slug, "code": "finalize_failed", "message": str(exc)})
        else:
            if sitting_windows:
                published.append(slug)
                windows.extend(sitting_windows)

    for decision in decisions:
        slug = decision.get("slug")
        if not isinstance(slug, str):
            continue
        try:
            written = _publish_closure_for_decision(
                decision=decision,
                content_spots_dir=content_spots_dir,
                attested_at=attested_at,
                quarantined_shas=quarantined_shas,
                data_root=data_root,
            )
        except PublishRefuse as exc:
            refused.append({"slug": slug, "code": exc.code, "message": exc.message})
            continue
        except FinalizeError as exc:
            refused.append(
                {"slug": slug, "code": "finalize_failed", "message": str(exc)}
            )
            continue
        if written is not None:
            published.append(slug)
            closure.append(slug)

    _write_reports(
        report_path,
        json_path,
        published=published,
        refused=refused,
        closure=closure,
        windows=windows,
        skipped=None,
    )
    return len(published), report_path


def _publish_unique_grid(
    *,
    candidate: ReviewCandidate,
    entries: dict,
    blocking_slugs: frozenset[str],
    quarantined_shas: frozenset[str],
    content_spots_dir: Path,
    attested_at: date,
    decisions: DecisionSet,
) -> None:
    entry = entries.get(candidate.slug)
    if entry is None:
        raise PublishRefuse("not_rec_park", f"{candidate.slug} is not in the registry")

    try:
        artifact = json.loads(_pick_provider_artifact(candidate.review_dir).read_text())
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise PublishRefuse("identity_mismatch", "no provider JSON in review dir") from exc

    decision = decisions.get(candidate.slug)
    source_pdf_url = candidate.source_url or None
    payload = dict(candidate.payload)
    grounding = _grounding_from_artifact(artifact)
    md_path = content_spots_dir / f"{candidate.slug}.md"
    tables = _schedule_tables(md_path)
    prior_sessions_count = 0
    if md_path.exists():
        snapshot = read_schedule_snapshot(md_path)
        prior_sessions_count = len(snapshot.get("sessions") or [])
    source_pdf_path = candidate.source_path if candidate.source_path.exists() else None

    eligibility = publish_eligible(
        candidate=candidate,
        payload=payload,
        grounding=grounding,
        prior_sessions_count=prior_sessions_count,
        latest_effective_start=latest_effective_start(md_path),
        source_kind=entry.source_kind,
        source_status=entry.source_status,
        blocking_slugs=blocking_slugs,
        quarantined_shas=quarantined_shas,
        has_prior_schedule_window=len(tables) > 0,
        source_pdf_path=source_pdf_path,
        require_unique_pin=True,
        pin_url=entry.pdf_url,
        source_pdf_url=source_pdf_url,
        decision=decision,
    )
    if not eligibility.ok:
        raise PublishRefuse(eligibility.code or "refused", eligibility.message)
    publish_candidate(
        candidate=candidate,
        content_spots_dir=content_spots_dir,
        attested_at=attested_at,
        eligibility=eligibility,
    )


def publish_sequential_slug(
    *,
    slug: str,
    decision: dict,
    candidates: list[ReviewCandidate],
    content_spots_dir: Path,
    attested_at: date,
    quarantined_shas: frozenset[str],
    entries: dict,
    attested_by: str = "ci",
    require_grounding: bool = True,
    envelopes: dict[str, dict] | None = None,
    data_root: Path | None = None,
    blocking_slugs: frozenset[str] = frozenset(),
) -> list[dict]:
    """All-or-nothing project of unpublished date-disjoint windows.

    Restores content markdown and unlinks reviewed.json on failure.
    Calls publish_eligible(..., require_unique_pin=False).
    """
    data_root = DATA_DIR if data_root is None else data_root
    entry = entries.get(slug)
    if entry is None:
        raise PublishRefuse("not_rec_park", f"{slug} is not in the registry")

    kept_ids = kept_grid_ids(decision)
    if len(kept_ids) < 2:
        raise PublishRefuse(
            "sequential_incomplete",
            f"{slug} has {len(kept_ids)} kept session_grid windows",
        )

    unpublished = _unpublished_kept_windows(candidates, kept_ids)
    attested = _attested_view_ids(slug, data_root, kept_ids)
    covered = set(unpublished) | attested
    missing = kept_ids - covered
    if missing or (not attested and len(unpublished) < 2):
        raise PublishRefuse(
            "sequential_incomplete",
            f"{slug} unpublished={sorted(unpublished)} attested={sorted(attested)} "
            f"missing={sorted(missing)}",
        )

    ordered = _order_unpublished(unpublished)
    payload_ranges: list[tuple[date, date]] = []
    for candidate in ordered:
        if envelopes is not None:
            posted = envelopes.get(candidate.pdf_sha256[:12])
            payload = (
                posted.get("payload")
                if isinstance(posted, dict) and isinstance(posted.get("payload"), dict)
                else {}
            )
        else:
            payload = dict(candidate.payload)
        parsed = _payload_window(payload)
        if parsed is None:
            continue
        payload_ranges.append(parsed)
    for index, left in enumerate(payload_ranges):
        for right in payload_ranges[index + 1 :]:
            if not windows_disjoint(left, right):
                raise PublishRefuse(
                    "overlapping_windows",
                    f"{slug} payload windows overlap",
                )

    md_path = content_spots_dir / f"{slug}.md"
    tables = _schedule_tables(md_path)
    prior_sessions_count = 0
    if md_path.exists():
        snapshot = read_schedule_snapshot(md_path)
        prior_sessions_count = len(snapshot.get("sessions") or [])
    frozen_latest = latest_effective_start(md_path)
    backup = md_path.read_text() if md_path.exists() else None

    prepared: list[tuple[ReviewCandidate, dict, Eligibility]] = []
    for candidate in ordered:
        try:
            artifact = json.loads(_pick_provider_artifact(candidate.review_dir).read_text())
        except (OSError, json.JSONDecodeError, FileNotFoundError):
            artifact = {}
        payload = dict(candidate.payload)
        source_pdf_url = candidate.source_url or None
        source_pdf_path = candidate.source_path if candidate.source_path.exists() else None
        eligibility = publish_eligible(
            candidate=candidate,
            payload=payload,
            grounding=_grounding_from_artifact(artifact),
            prior_sessions_count=prior_sessions_count,
            latest_effective_start=frozen_latest,
            source_kind=entry.source_kind,
            source_status=entry.source_status,
            blocking_slugs=blocking_slugs,
            quarantined_shas=quarantined_shas,
            has_prior_schedule_window=len(tables) > 0,
            source_pdf_path=source_pdf_path,
            require_unique_pin=False,
            require_grounding=require_grounding,
            pin_url=entry.pdf_url,
            source_pdf_url=source_pdf_url,
            decision=decision,
        )
        prepared.append((candidate, payload, eligibility))

    failed = next((item for item in prepared if not item[2].ok), None)
    if failed is not None:
        raise PublishRefuse("sequential_partial", failed[2].code or "refused")

    written: list[Path] = []
    windows: list[dict] = []
    try:
        for candidate, payload, eligibility in prepared:
            if envelopes is not None:
                sha12 = candidate.pdf_sha256[:12]
                envelope = envelopes.get(sha12)
                if envelope is None:
                    raise PublishRefuse(
                        "sequential_incomplete",
                        f"{slug} missing posted envelope for {sha12}",
                    )
                path = _write_posted_envelope(
                    candidate=candidate,
                    envelope=envelope,
                    attested_at=attested_at,
                    attested_by=attested_by,
                    content_spots_dir=content_spots_dir,
                )
            else:
                path = publish_candidate(
                    candidate=candidate,
                    content_spots_dir=content_spots_dir,
                    attested_at=attested_at,
                    eligibility=eligibility,
                )
            written.append(path)
            windows.append(
                {
                    "slug": slug,
                    "effective_start": payload.get("effective_start"),
                    "effective_end": payload.get("effective_end"),
                    "view_id": candidate.view_id,
                }
            )
    except Exception as exc:
        if backup is not None:
            md_path.write_text(backup)
        for path in written:
            path.unlink(missing_ok=True)
        raise PublishRefuse("sequential_partial", str(exc)) from exc
    return windows


def _write_posted_envelope(
    *,
    candidate: ReviewCandidate,
    envelope: dict,
    attested_at: date,
    attested_by: str,
    content_spots_dir: Path,
) -> Path:
    target = candidate.review_dir / "reviewed.json"
    payload = dict(envelope)
    payload["slug"] = candidate.slug
    payload["pdf_sha256"] = candidate.pdf_sha256
    payload["reviewed_at"] = attested_at.isoformat()
    payload["attested_by"] = attested_by
    target.write_text(json.dumps(payload, indent=2) + "\n")
    try:
        finalize_draft(
            reviewed_json_path=target,
            content_spots_dir=content_spots_dir,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def _publish_closure_for_decision(
    *,
    decision: dict,
    content_spots_dir: Path,
    attested_at: date,
    quarantined_shas: frozenset[str],
    data_root: Path,
) -> Path | None:
    if decision.get("action") != "flag" or not decision.get("blocking"):
        return None
    candidates = decision.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    table_grids = [
        item
        for item in candidates
        if isinstance(item, dict)
        and item.get("kind") == "session_grid"
        and item.get("source") == "table"
    ]
    if table_grids:
        return None
    table_notices = [
        item
        for item in candidates
        if isinstance(item, dict)
        and item.get("kind") == "closure_notice"
        and item.get("source") == "table"
    ]
    kind = decision.get("kind")
    reason = decision.get("reason")
    if not table_notices and kind != "closure_notice" and reason != "closure_notice":
        return None
    if len(table_notices) == 0:
        raise PublishRefuse("closure_notice_missing", "no table closure_notice")
    if len(table_notices) > 1:
        raise PublishRefuse(
            "closure_notice_not_unique",
            f"{len(table_notices)} table closure_notice files",
        )
    return publish_closure_notice(
        slug=decision["slug"],
        flyer=table_notices[0],
        content_spots_dir=content_spots_dir,
        attested_at=attested_at,
        quarantined_shas=quarantined_shas,
        data_root=data_root,
    )


def _grounding_from_artifact(artifact: dict) -> GroundingSummary | None:
    if "grounding" not in artifact:
        return None
    raw = artifact.get("grounding")
    if not isinstance(raw, dict):
        return None
    return GroundingSummary(
        grounded_count=int(raw.get("grounded_count") or 0),
        total=int(raw.get("total") or 0),
    )


def _payload_window(payload: dict) -> tuple[date, date] | None:
    start, end = payload.get("effective_start"), payload.get("effective_end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        return date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return None


def _unpublished_kept_windows(
    candidates: list[ReviewCandidate], kept_ids: set[int]
) -> dict[int, ReviewCandidate]:
    by_id: dict[int, ReviewCandidate] = {}
    for candidate in candidates:
        view_id = candidate.view_id
        if view_id is None or view_id not in kept_ids:
            continue
        previous = by_id.get(view_id)
        if previous is None or candidate.fetch_date >= previous.fetch_date:
            by_id[view_id] = candidate
    return by_id


def _attested_view_ids(slug: str, data_root: Path, kept_ids: set[int]) -> set[int]:
    found: set[int] = set()
    for review_dir in all_review_dirs(slug, root=data_root):
        path = review_dir / "reviewed.json"
        if not path.exists():
            continue
        try:
            envelope = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
        url = envelope.get("source_pdf_url")
        view_id = view_id_from_url(url) if isinstance(url, str) else None
        if view_id in kept_ids:
            found.add(view_id)
    return found


def _order_unpublished(
    unpublished: dict[int, ReviewCandidate],
) -> list[ReviewCandidate]:
    def sort_key(candidate: ReviewCandidate) -> tuple[str, str]:
        start = candidate.payload.get("effective_start")
        start_s = start if isinstance(start, str) else ""
        return (start_s, candidate.fetch_date)

    return sorted(unpublished.values(), key=sort_key)


def _write_reports(
    report_path: Path,
    json_path: Path,
    *,
    published: list[str],
    refused: list[dict],
    closure: list[str],
    windows: list[dict],
    skipped: str | None,
) -> None:
    json_path.write_text(
        json.dumps(
            {
                "published": published,
                "refused": [
                    {"slug": item["slug"], "code": item["code"]} for item in refused
                ],
                "closure": closure,
                "windows": windows,
                **({"skipped": skipped} if skipped else {}),
            },
            indent=2,
        )
        + "\n"
    )
    lines = [
        "# publish-pending",
        "",
        f"{len(published)} published, {len(refused)} refused",
        "",
    ]
    if skipped:
        lines.extend([f"skipped: {skipped}", ""])
    lines.append("## Published")
    if published:
        lines.extend(f"- {slug}" for slug in published)
    else:
        lines.append("- none")
    lines.extend(["", "## Refused"])
    if refused:
        lines.extend(
            f"- {item['slug']}: {item['code']} — {item.get('message', '')}"
            for item in refused
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Closure"])
    if closure:
        lines.extend(f"- {slug}" for slug in closure)
    else:
        lines.append("- none")
    lines.append("")
    report_path.write_text("\n".join(lines))
