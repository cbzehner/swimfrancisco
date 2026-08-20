from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import tomlkit

from ._time import pacific_today
from .fetch import fetch_pdf
from .merge import _split_frontmatter, read_schedule_snapshot
from .models import GroundingResult, SourceStatus
from .paths import CONTENT_SPOTS_DIR, DATA_DIR, PACKAGE_ROOT, TMP_DIR
from .pipeline import GROUNDING_MIN_RATIO
from .registry import load_registry
from .review import (
    FinalizeError,
    ReviewCandidate,
    _pick_provider_artifact,
    draft_envelope,
    finalize_draft,
    find_review_candidates,
)
from .signals import analyze_page_texts, extract_page_texts
from .validate import validate

QUARANTINE_PATH = PACKAGE_ROOT / "quarantine.toml"
_AUTO_PUBLISHABLE_BASES = frozenset({"swim_schedule", "temporarily_closed"})
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_ALT = "|".join(_MONTHS)
_MD_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2})-(\d{1,2})_(\d{1,2})-(\d{1,2})(?:\s+(\d{4}))?"
)
_MONTH_TO_MONTH_RE = re.compile(
    rf"(?i)({_MONTH_ALT})\s+(\d{{1,2}})\s+to\s+({_MONTH_ALT})\s+(\d{{1,2}}),?\s*(\d{{4}})?"
)
_SAME_MONTH_RANGE_RE = re.compile(
    rf"(?i)({_MONTH_ALT})\s+(\d{{1,2}})\s*[–-]\s*(\d{{1,2}}),?\s*(\d{{4}})?"
)
_DIR_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{12})$")


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


def pager_flagged_set(
    *,
    refused: list[dict],
    blocking: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """Operator pager rows. Omits not_rec_park (out of scope, not Rec & Park FLAG)."""
    rows: set[tuple[str, str]] = set()
    for item in blocking or []:
        slug = item.get("slug")
        if not slug:
            continue
        rows.add((slug, str(item.get("reason") or item.get("code") or "flag")))
    for item in refused:
        if item.get("code") == "not_rec_park":
            continue
        slug = item.get("slug")
        if slug:
            rows.add((slug, str(item.get("code") or "")))
    return sorted(rows)


def parse_closure_dates(
    filename: str | None, anchor_text: str | None
) -> tuple[date, date] | None:
    for text in (anchor_text, filename):
        parsed = _parse_closure_text(text)
        if parsed is not None:
            return parsed
    return None


def _parse_closure_text(text: str | None) -> tuple[date, date] | None:
    if not text:
        return None
    year_default = pacific_today().year
    match = _MD_RANGE_RE.search(text)
    if match:
        start_month, start_day, end_month, end_day, year_token = match.groups()
        return _dates_or_none(
            year_token, year_default, start_month, start_day, end_month, end_day
        )
    match = _MONTH_TO_MONTH_RE.search(text)
    if match:
        start_month_name, start_day, end_month_name, end_day, year_token = match.groups()
        return _dates_or_none(
            year_token,
            year_default,
            _MONTHS[start_month_name.lower()],
            start_day,
            _MONTHS[end_month_name.lower()],
            end_day,
        )
    match = _SAME_MONTH_RANGE_RE.search(text)
    if match:
        month_name, start_day, end_day, year_token = match.groups()
        month = _MONTHS[month_name.lower()]
        return _dates_or_none(
            year_token, year_default, month, start_day, month, end_day
        )
    return None


def _dates_or_none(
    year_token: str | None,
    year_default: int,
    start_month: int | str,
    start_day: str,
    end_month: int | str,
    end_day: str,
) -> tuple[date, date] | None:
    year = int(year_token) if year_token else year_default
    try:
        start = date(year, int(start_month), int(start_day))
        end = date(year, int(end_month), int(end_day))
    except ValueError:
        return None
    return start, end


def publish_eligible(
    *,
    candidate: ReviewCandidate,
    payload: dict,
    grounding: GroundingResult | None,
    prior_sessions_count: int,
    latest_effective_start: str | None,
    source_kind: str,
    source_status: SourceStatus,
    blocking_slugs: frozenset[str],
    quarantined_shas: frozenset[str],
    has_prior_schedule_window: bool,
    source_pdf_path: Path | None,
    kill_switch: bool = False,
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


def _identity_gate(candidate: ReviewCandidate) -> Eligibility:
    match = _DIR_NAME_RE.fullmatch(candidate.review_dir.name)
    if match is None or match.group(2) != candidate.pdf_sha256[:12]:
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
    if end < start:
        raise PublishRefuse(
            "closure_dates_invalid",
            f"closure end {end.isoformat()} is before start {start.isoformat()}",
        )

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
            skipped="kill_switch",
        )
        return 0, report_path

    published: list[str] = []
    refused: list[dict] = []
    closure: list[str] = []
    decisions = _load_decisions(tmp_dir)
    blocking_slugs = frozenset(
        item["slug"]
        for item in decisions
        if isinstance(item, dict) and item.get("blocking") and item.get("slug")
    )
    quarantined_shas = load_quarantine()
    entries = {entry.slug: entry for entry in load_registry()}

    for candidate in find_review_candidates(data_root=data_root):
        try:
            _publish_unique_grid(
                candidate=candidate,
                entries=entries,
                blocking_slugs=blocking_slugs,
                quarantined_shas=quarantined_shas,
                content_spots_dir=content_spots_dir,
                attested_at=attested_at,
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

    for decision in decisions:
        if not isinstance(decision, dict):
            continue
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
) -> None:
    entry = entries.get(candidate.slug)
    if entry is None:
        raise PublishRefuse("not_rec_park", f"{candidate.slug} is not in the registry")

    try:
        artifact = json.loads(_pick_provider_artifact(candidate.review_dir).read_text())
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise PublishRefuse("identity_mismatch", "no provider JSON in review dir") from exc

    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
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
    )
    if not eligibility.ok:
        raise PublishRefuse(eligibility.code or "refused", eligibility.message)
    publish_candidate(
        candidate=candidate,
        content_spots_dir=content_spots_dir,
        attested_at=attested_at,
        eligibility=eligibility,
    )


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


def _grounding_from_artifact(artifact: dict) -> GroundingResult | None:
    if "grounding" not in artifact:
        return None
    raw = artifact.get("grounding")
    if not isinstance(raw, dict):
        return None
    return GroundingResult(
        sessions=[],
        grounded_count=int(raw.get("grounded_count") or 0),
        total=int(raw.get("total") or 0),
    )


def _load_decisions(tmp_dir: Path) -> list[dict]:
    path = tmp_dir / "discovery-decisions.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_reports(
    report_path: Path,
    json_path: Path,
    *,
    published: list[str],
    refused: list[dict],
    closure: list[str],
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
