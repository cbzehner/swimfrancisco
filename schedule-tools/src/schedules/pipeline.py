from __future__ import annotations

import json
import os
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Literal

from .artifacts import save_artifact_bundle, skip_if_fresh
from .delta import check_delta
from .direct_sources import extract_direct
from .discover import (
    absolute_view_url,
    collapse_grid_candidates,
    discover_all,
    rec_park_entries,
)
from .fetch import fetch_pdf
from .grounding import grounding_from_text, normalize_pdf_text
from .merge import read_schedule_snapshot
from .models import Aborted, Extracted, GroundingResult, PoolEntry, PoolResult, ReviewNote, Skipped, Unchanged
from .paths import CONTENT_SPOTS_DIR, PROMPT_PATH, REPORT_PATHS, TMP_DIR, artifact_path, reviewed_path
from .providers import extract as extract_with_provider
from .providers.anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from .providers.gemini_provider import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from .registry import load_registry
from .review import carry_forward_review
from .reviewed_snapshots import load_reviewed_snapshot_from_path
from .diff import compare_payloads
from .report import discovery_notes_from_decisions, write_report
from .schema import EXTRACTION_SCHEMA
from .signals import analyze_page_texts, extract_page_texts, source_notes_for_signals
from .validate import validate

GROUNDING_MIN_RATIO = 0.9
SourceMode = Literal["direct", "gemini", "anthropic"]
ProviderMode = Literal["gemini", "anthropic"]


def parse_provider(value: str) -> ProviderMode:
    if value == "gemini" or value == "anthropic":
        return value
    raise ValueError(f"Unsupported provider {value!r}; expected 'gemini' or 'anthropic'.")


def parse_source_mode(value: str) -> SourceMode:
    if value == "direct":
        return value
    return parse_provider(value)


def compute_exit_code(results: list[PoolResult]) -> int:
    """Non-zero when any pool failed. Partial failure must not exit 0."""
    return 1 if any(_failed(result) for result in results) else 0


def _failed(result: PoolResult) -> bool:
    """A pool counts as failed if the run aborted or validation refused."""
    if isinstance(result, Aborted):
        return True
    if isinstance(result, Extracted):
        return result.catastrophic
    return False


def _identity_kwargs(entry: PoolEntry) -> dict:
    return {
        "slug": entry.slug,
        "official_page_url": entry.official_page_url,
        "pdf_url": entry.pdf_url,
        "source_status": entry.source_status,
    }


def _default_model(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("SCHEDULES_GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
    if provider == "anthropic":
        return os.getenv("SCHEDULES_ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
    raise ValueError(f"Unsupported provider {provider!r}.")


def _grounding_notes(provider: str, grounding: GroundingResult) -> list[ReviewNote]:
    if grounding.total == 0 or grounding.ratio >= GROUNDING_MIN_RATIO:
        return []

    ungrounded_total = grounding.total - grounding.grounded_count
    return [
        ReviewNote(
            kind="grounding_coverage_low",
            message=(
                f"{provider} grounding coverage is {grounding.ratio:.0%} "
                f"({grounding.grounded_count}/{grounding.total} sessions grounded; "
                f"{ungrounded_total} ungrounded)"
            ),
        )
    ]


def _build_unchanged(entry: PoolEntry, *, pdf_sha256: str, page_count: int, reviewed_file: Path) -> Unchanged:
    envelope = load_reviewed_snapshot_from_path(
        reviewed_file, expected_slug=entry.slug, expected_sha=pdf_sha256
    )
    payload = envelope["payload"]
    review_notes = []
    if envelope.get("carried_from"):
        review_notes.append(
            ReviewNote(
                kind="review_carried_forward",
                message=f"attestation carried forward from {envelope['carried_from']}",
                severity="info",
            )
        )
    return Unchanged(
        **_identity_kwargs(entry),
        provider="reviewed-snapshot",
        model="manual-review",
        pdf_sha256=pdf_sha256,
        page_count=page_count,
        sessions_count=len(payload.get("sessions") or []),
        closures_count=len(payload.get("closures") or []),
        effective_start=str(payload.get("effective_start") or ""),
        schedule_basis=payload.get("schedule_basis"),
        review_notes=review_notes,
        artifact_paths={"reviewed-snapshot": str(reviewed_file)},
    )


def _process_entry(
    entry: PoolEntry,
    *,
    provider: str,
    compare_with: str | None,
    force: bool,
    prompt: str,
) -> PoolResult:
    prior_snapshot = read_schedule_snapshot(CONTENT_SPOTS_DIR / f"{entry.slug}.md")

    # FLAG is a write policy, not a fetch policy: still GET a published pointer.
    can_extract_access_hours = entry.source_status == "access_hours_only" and entry.source_kind != "sfrecpark_pdf"
    if entry.source_status != "published" and not can_extract_access_hours:
        return Skipped(
            **_identity_kwargs(entry),
            reason="No current schedule PDF is available for this pool.",
            notes=entry.notes,
        )

    try:
        if entry.source_kind != "sfrecpark_pdf":
            return _process_direct_entry(entry, prior_snapshot)

        # PDF fetch + path setup
        fetch_result = fetch_pdf(entry.slug, entry.pdf_url)
        date = fetch_result.path.parent.name[:10]
        reviewed_file = reviewed_path(entry.slug, date, fetch_result.sha256)

        # Reviewed-snapshot fast path: SHA matches a hand-approved snapshot.
        if not force and not compare_with and reviewed_file.exists():
            return _build_unchanged(
                entry,
                pdf_sha256=fetch_result.sha256,
                page_count=fetch_result.page_count,
                reviewed_file=reviewed_file,
            )

        # PDF text + signals (reused for grounding both providers if bakeoff).
        page_texts = extract_page_texts(fetch_result.bytes)
        pdf_signals = analyze_page_texts(page_texts)
        pdf_text_normalized = normalize_pdf_text(page_texts)

        # Primary extraction (LLM call or cached artifact).
        default_model = _default_model(provider)
        use_cached = (
            not force
            and not compare_with
            and skip_if_fresh(
                slug=entry.slug,
                date=date,
                pdf_sha256=fetch_result.sha256,
                provider=provider,
                model=default_model,
                prompt=prompt,
                schema=EXTRACTION_SCHEMA,
            )
        )

        if use_cached:
            cached_path = artifact_path(entry.slug, date, fetch_result.sha256, provider, default_model)
            cached = json.loads(cached_path.read_text())
            payload = cached["payload"]
            model = cached.get("model", default_model)
            cost_estimate = cached.get("cost_estimate", "cached")
            artifact_paths = {provider: str(cached_path)}
            primary_usage: dict | None = None
        else:
            primary = extract_with_provider(provider, fetch_result.bytes, prompt, EXTRACTION_SCHEMA)
            payload = primary.payload
            model = primary.model
            cost_estimate = primary.cost_estimate
            artifact_paths = {}  # filled in once grounding is computed
            primary_usage = primary.usage

        # Compute grounding once, used for both the artifact bundle (when fresh)
        # and the review-note assembly. Cached artifacts already have their
        # grounding section persisted; no need to re-save the bundle.
        grounding = grounding_from_text(pdf_text_normalized, payload)

        if not use_cached:
            artifact_paths = save_artifact_bundle(
                slug=entry.slug,
                date=date,
                provider=provider,
                model=model,
                source_pdf_url=entry.pdf_url,
                pdf_sha256=fetch_result.sha256,
                prompt=prompt,
                schema=EXTRACTION_SCHEMA,
                payload=payload,
                usage=primary_usage or {},
                cost_estimate=cost_estimate,
                grounding=grounding,
            )

        # A payload identical to the last human-reviewed one needs no new
        # review — carry the attestation to this capture. Bakeoff runs
        # (--compare-with) always produce a full Extracted result.
        if not compare_with:
            carried = carry_forward_review(
                slug=entry.slug,
                review_dir=reviewed_file.parent,
                pdf_sha256=fetch_result.sha256,
                payload=payload,
                ignore_effective_start=False,
            )
            if carried is not None:
                return _build_unchanged(
                    entry,
                    pdf_sha256=fetch_result.sha256,
                    page_count=fetch_result.page_count,
                    reviewed_file=carried,
                )

        # Review notes from three sources: PDF signals, grounding, prior-vs-current delta.
        review_notes: list[ReviewNote] = [
            *source_notes_for_signals(pdf_signals),
            *_grounding_notes(provider, grounding),
            *check_delta(payload, prior_snapshot),
        ]

        # Optional bakeoff against a second provider.
        if compare_with:
            try:
                compare = extract_with_provider(compare_with, fetch_result.bytes, prompt, EXTRACTION_SCHEMA)
                compare_grounding = grounding_from_text(pdf_text_normalized, compare.payload)
                review_notes.extend(_grounding_notes(compare_with, compare_grounding))
                artifact_paths.update(
                    save_artifact_bundle(
                        slug=entry.slug,
                        date=date,
                        provider=compare_with,
                        model=compare.model,
                        source_pdf_url=entry.pdf_url,
                        pdf_sha256=fetch_result.sha256,
                        prompt=prompt,
                        schema=EXTRACTION_SCHEMA,
                        payload=compare.payload,
                        usage=compare.usage,
                        cost_estimate=compare.cost_estimate,
                        grounding=compare_grounding,
                    )
                )
                review_notes.extend(compare_payloads(provider, payload, compare_with, compare.payload))
            except Exception as exc:  # noqa: BLE001
                review_notes.append(
                    ReviewNote(
                        kind="compare_provider_failed",
                        message=f"{compare_with} comparison run failed: {exc}",
                        severity="warning",
                    )
                )

        # Catastrophic validation routes to a non-zero exit (Extracted with
        # catastrophic=True); advisory violations land on the result for the
        # operator to weigh during review.
        validation = validate(payload, prior_sessions_count=len(prior_snapshot["sessions"]))

        return Extracted(
            **_identity_kwargs(entry),
            provider=provider,
            model=model,
            pdf_sha256=fetch_result.sha256,
            page_count=fetch_result.page_count,
            sessions_count=validation.stats["sessions"],
            prior_sessions_count=len(prior_snapshot["sessions"]),
            closures_count=validation.stats["closures"],
            effective_start=payload.get("effective_start"),
            schedule_basis=payload.get("schedule_basis"),
            cost_estimate=cost_estimate,
            catastrophic=validation.catastrophic,
            violations=validation.violations,
            review_notes=review_notes,
            artifact_paths=artifact_paths,
        )
    except Exception as exc:  # noqa: BLE001
        return Aborted(
            **_identity_kwargs(entry),
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            prior_sessions_count=len(prior_snapshot["sessions"]),
            prior_closures_count=len(prior_snapshot["closures"]),
            prior_schedule_effective=prior_snapshot["effective_start"],
        )


# Runs inside _process_entry's try/except, which wraps any failure in the
# same Aborted result — no separate error handling needed here.
def _process_direct_entry(entry: PoolEntry, prior_snapshot: dict) -> PoolResult:
    extracted = extract_direct(entry)
    fetch_result = extracted.fetch_result
    date = fetch_result.path.parent.name[:10]
    reviewed_file = reviewed_path(entry.slug, date, fetch_result.sha256)

    if reviewed_file.exists():
        return _build_unchanged(
            entry,
            pdf_sha256=fetch_result.sha256,
            page_count=0,
            reviewed_file=reviewed_file,
        )

    payload = extracted.payload

    # Direct extractors stamp payload.effective_start with the fetch date, so
    # the carry comparison ignores that one clock-derived field.
    carried = carry_forward_review(
        slug=entry.slug,
        review_dir=fetch_result.path.parent,
        pdf_sha256=fetch_result.sha256,
        payload=payload,
        ignore_effective_start=True,
    )
    if carried is not None:
        return _build_unchanged(
            entry,
            pdf_sha256=fetch_result.sha256,
            page_count=0,
            reviewed_file=carried,
        )

    review_notes = [
        ReviewNote(
            kind="direct_extractor_note",
            message=note,
            severity="info",
        )
        for note in extracted.notes
    ]
    review_notes.extend(check_delta(payload, prior_snapshot))
    validation = validate(payload, prior_sessions_count=len(prior_snapshot["sessions"]))
    artifact_paths = save_artifact_bundle(
        slug=entry.slug,
        date=date,
        provider="direct",
        model=extracted.model,
        source_pdf_url=entry.pdf_url,
        pdf_sha256=fetch_result.sha256,
        prompt=f"direct:{entry.source_kind}",
        schema=EXTRACTION_SCHEMA,
        payload=payload,
        usage={},
        cost_estimate="deterministic",
        grounding=None,
    )
    return Extracted(
        **_identity_kwargs(entry),
        provider="direct",
        model=extracted.model,
        pdf_sha256=fetch_result.sha256,
        page_count=0,
        sessions_count=validation.stats["sessions"],
        prior_sessions_count=len(prior_snapshot["sessions"]),
        closures_count=validation.stats["closures"],
        effective_start=payload.get("effective_start"),
        schedule_basis=payload.get("schedule_basis"),
        cost_estimate="deterministic",
        catastrophic=validation.catastrophic,
        violations=validation.violations,
        review_notes=review_notes,
        artifact_paths=artifact_paths,
    )


def select_registry_entries(
    registry: list[PoolEntry],
    *,
    source_mode: SourceMode,
    slugs: list[str] | None,
) -> list[PoolEntry]:
    if source_mode == "direct":
        candidates = [entry for entry in registry if entry.source_kind != "sfrecpark_pdf"]
    else:
        candidates = [entry for entry in registry if entry.source_kind == "sfrecpark_pdf"]

    selected = [entry for entry in candidates if slugs is None or entry.slug in slugs]
    if slugs:
        missing = sorted(set(slugs) - {entry.slug for entry in selected})
        if missing:
            raise ValueError(
                f"Unknown or mismatched registry slug(s) for {source_mode} mode: {', '.join(missing)}"
            )
    return selected


def _attach_discovery_notes(
    result: PoolResult, notes_by_slug: dict[str, list[ReviewNote]]
) -> PoolResult:
    extra = notes_by_slug.get(result.slug)
    if not extra:
        return result
    return replace(result, review_notes=[*result.review_notes, *extra])


def _session_grid_hrefs(entry: PoolEntry, decisions: list[dict]) -> list[str]:
    """One href per [window_start, window_end]. Table id wins ties.
    Equal-range copies are omitted. pdf_url is always included."""
    decision = next(
        (
            item
            for item in decisions
            if isinstance(item, dict) and item.get("slug") == entry.slug
        ),
        None,
    )
    hrefs: list[str] = []
    seen: set[str] = set()

    def add(href: str) -> None:
        if href and href not in seen:
            seen.add(href)
            hrefs.append(href)

    if decision is not None:
        raw = list(decision.get("candidates") or [])
        extra = list(decision.get("extra_candidates") or [])
        for item in collapse_grid_candidates(raw + extra):
            href = item.get("href")
            if isinstance(href, str) and href:
                add(href)
                continue
            view_id = item.get("view_id")
            if isinstance(view_id, int):
                add(absolute_view_url(view_id))
            elif isinstance(view_id, str) and view_id.isdigit():
                add(absolute_view_url(int(view_id)))
    add(entry.pdf_url)
    return hrefs


def _load_discovery_decisions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def run_pipeline(
    *,
    slugs: list[str] | None,
    source_mode: SourceMode,
    compare_with: str | None,
    force: bool,
    apply_discover: bool = False,
    override_url: str | None = None,
) -> tuple[int, Path, list[PoolResult]]:
    source_mode = parse_source_mode(source_mode)
    if source_mode == "direct" or compare_with is not None or override_url is not None:
        apply_discover = False
    if override_url is not None and (slugs is None or len(slugs) != 1):
        raise ValueError("--url requires exactly one --only slug")

    registry = load_registry()
    selected = select_registry_entries(registry, source_mode=source_mode, slugs=slugs)

    if apply_discover:
        rec_park = rec_park_entries(registry)
        apply_slugs: list[str] | None = None
        if slugs is not None:
            rec_slugs = {entry.slug for entry in rec_park}
            apply_slugs = [slug for slug in slugs if slug in rec_slugs]
            if not apply_slugs:
                rec_park = []
        if rec_park:
            # Full Rec & Park set for max_id / band; slugs limits apply.
            discover_all(rec_park, slugs=apply_slugs)
        registry = load_registry()
        selected = select_registry_entries(registry, source_mode=source_mode, slugs=slugs)

    if override_url is not None:
        assert slugs is not None
        target = slugs[0]
        selected = [
            replace(entry, pdf_url=override_url) if entry.slug == target else entry
            for entry in selected
        ]

    prompt = PROMPT_PATH.read_text().strip()
    decisions = _load_discovery_decisions(TMP_DIR / "discovery-decisions.json")
    results: list[PoolResult] = []
    for entry in selected:
        hrefs = [entry.pdf_url]
        if (
            override_url is None
            and entry.source_kind == "sfrecpark_pdf"
            and entry.source_status == "published"
        ):
            hrefs = _session_grid_hrefs(entry, decisions)
        for href in hrefs:
            work = entry if href == entry.pdf_url else replace(entry, pdf_url=href)
            results.append(
                _process_entry(
                    work,
                    provider=source_mode,
                    compare_with=compare_with,
                    force=force,
                    prompt=prompt,
                )
            )
    notes_by_slug = discovery_notes_from_decisions(TMP_DIR / "discovery-decisions.json")
    results = [_attach_discovery_notes(result, notes_by_slug) for result in results]
    report_path = write_report(results, path=REPORT_PATHS[source_mode])
    return compute_exit_code(results), report_path, results
