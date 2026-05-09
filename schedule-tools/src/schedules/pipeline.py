from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .artifacts import save_artifact_bundle, skip_if_fresh
from .delta import check_delta
from .envelope import EnvelopeValidationError, validate_envelope
from .fetch import FetchResult, fetch_pdf
from .grounding import grounding_from_text, normalize_pdf_text
from .merge import read_schedule_snapshot
from .models import Aborted, GroundingResult, PoolEntry, PoolResult, Proposed, Rejected, ReviewNote, Skipped, Unchanged, ValidationResult
from .paths import CONTENT_SPOTS_DIR, PROMPT_PATH, artifact_path, reviewed_path
from .providers import extract as extract_with_provider
from .providers.anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from .providers.gemini_provider import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from .registry import load_registry
from .diff import compare_payloads
from .report import write_report
from .schema import EXTRACTION_SCHEMA
from .signals import analyze_page_texts, extract_page_texts, source_notes_for_payload
from .validate import validate

_GROUNDING_MIN_RATIO = 0.9
_GROUNDING_EVIDENCE_SAMPLE = 5


def compute_exit_code(results: list[PoolResult]) -> int:
    """Non-zero when any pool failed. Partial failure must not exit 0."""
    return 1 if any(isinstance(result, (Rejected, Aborted)) for result in results) else 0


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
    if grounding.total == 0 or grounding.ratio >= _GROUNDING_MIN_RATIO:
        return []

    sample = []
    for entry in grounding.ungrounded[:_GROUNDING_EVIDENCE_SAMPLE]:
        session = entry.session
        sample.append(
            {
                "index": entry.index,
                "day": session.get("day"),
                "type": session.get("type"),
                "start": session.get("start"),
                "end": session.get("end"),
                "missing_evidence": entry.missing_evidence,
                "evidence_in_pdf": entry.evidence_in_pdf,
                "start_in_evidence": entry.start_in_evidence,
                "type_in_evidence": entry.type_in_evidence,
                "evidence": session.get("evidence"),
            }
        )

    ungrounded_total = grounding.total - grounding.grounded_count
    return [
        ReviewNote(
            kind="grounding_coverage_low",
            message=(
                f"{provider} grounding coverage is {grounding.ratio:.0%} "
                f"({grounding.grounded_count}/{grounding.total} sessions grounded; "
                f"{ungrounded_total} ungrounded)"
            ),
            evidence={
                "provider": provider,
                "ratio": round(grounding.ratio, 4),
                "grounded_count": grounding.grounded_count,
                "total": grounding.total,
                "sample_ungrounded": sample,
            },
        )
    ]


def _load_reviewed_envelope(path: Path, expected_slug: str, expected_sha: str) -> dict:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    try:
        validate_envelope(raw)
    except EnvelopeValidationError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if raw["slug"] != expected_slug:
        raise ValueError(f"{path} envelope slug does not match {expected_slug!r}")
    if raw["pdf_sha256"] != expected_sha:
        raise ValueError(f"{path} envelope pdf_sha256 does not match current PDF")
    return raw


@dataclass
class _Extraction:
    """In-flight state for a single pool while phases run.

    Built incrementally: extraction phase populates payload/model/etc;
    compare phase appends to review_notes & artifact_paths; finalize reads everything.
    """
    payload: dict
    model: str
    cost_estimate: str
    review_notes: list[ReviewNote]
    artifact_paths: dict[str, str]
    pdf_text_normalized: str


def _build_unchanged(entry: PoolEntry, fetch_result: FetchResult, reviewed_file: Path) -> Unchanged:
    envelope = _load_reviewed_envelope(reviewed_file, entry.slug, fetch_result.sha256)
    payload = envelope["payload"]
    return Unchanged(
        **_identity_kwargs(entry),
        provider="reviewed-snapshot",
        model="manual-review",
        pdf_sha256=fetch_result.sha256,
        page_count=fetch_result.page_count,
        sessions_count=len(payload.get("sessions") or []),
        closures_count=len(payload.get("closures") or []),
        schedule_effective=str(payload.get("schedule_effective") or ""),
        review_notes=[],
        artifact_paths={"reviewed-snapshot": str(reviewed_file)},
    )


def _extract_or_load(
    entry: PoolEntry,
    fetch_result: FetchResult,
    *,
    provider: str,
    prompt: str,
    force: bool,
    compare_with: str | None,
    prior_snapshot: dict,
) -> _Extraction:
    """Run the LLM extraction (or load the provider cache when fresh) and assemble base review notes."""
    date = fetch_result.path.parent.name[:10]
    page_texts = extract_page_texts(fetch_result.bytes)
    pdf_signals = analyze_page_texts(page_texts)
    pdf_text_normalized = normalize_pdf_text(page_texts)

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
        grounding = grounding_from_text(pdf_text_normalized, payload)
    else:
        primary = extract_with_provider(provider, fetch_result.bytes, prompt, EXTRACTION_SCHEMA)
        payload = primary.payload
        model = primary.model
        cost_estimate = primary.cost_estimate
        grounding = grounding_from_text(pdf_text_normalized, payload)
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
            usage=primary.usage,
            cost_estimate=cost_estimate,
            grounding=grounding,
        )

    review_notes: list[ReviewNote] = []
    review_notes.extend(source_notes_for_payload(pdf_signals, payload))
    review_notes.extend(_grounding_notes(provider, grounding))
    review_notes.extend(check_delta(payload, prior_snapshot))

    return _Extraction(
        payload=payload,
        model=model,
        cost_estimate=cost_estimate,
        review_notes=review_notes,
        artifact_paths=artifact_paths,
        pdf_text_normalized=pdf_text_normalized,
    )


def _apply_compare(
    extraction: _Extraction,
    *,
    entry: PoolEntry,
    fetch_result: FetchResult,
    primary_provider: str,
    compare_with: str,
    prompt: str,
) -> None:
    """Run the comparison provider; append diff/grounding notes and artifacts to extraction."""
    date = fetch_result.path.parent.name[:10]
    try:
        compare = extract_with_provider(compare_with, fetch_result.bytes, prompt, EXTRACTION_SCHEMA)
        compare_grounding = grounding_from_text(extraction.pdf_text_normalized, compare.payload)
        extraction.review_notes.extend(_grounding_notes(compare_with, compare_grounding))
        extraction.artifact_paths.update(
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
        extraction.review_notes.extend(
            compare_payloads(primary_provider, extraction.payload, compare_with, compare.payload)
        )
    except Exception as exc:  # noqa: BLE001
        extraction.review_notes.append(
            ReviewNote(
                kind="compare_provider_failed",
                message=f"{compare_with} comparison run failed: {exc}",
                severity="warning",
            )
        )


def _finalize(
    entry: PoolEntry,
    extraction: _Extraction,
    fetch_result: FetchResult,
    validation: ValidationResult,
    *,
    provider: str,
    prior_sessions_count: int,
) -> Rejected | Proposed:
    # The pipeline never writes content/spots/*.md directly. Whether the
    # extraction is clean or carries advisory violations, it lands as a
    # review candidate; `schedules review` is the only path that projects
    # an approved snapshot into content. Catastrophic validation still
    # routes to Rejected so the operator sees the refusal explicitly.
    if validation.catastrophic:
        return Rejected(
            **_identity_kwargs(entry),
            error="Validation refused the extracted payload.",
            provider=provider,
            model=extraction.model,
            pdf_sha256=fetch_result.sha256,
            page_count=fetch_result.page_count,
            sessions_count=validation.stats["sessions"],
            prior_sessions_count=prior_sessions_count,
            closures_count=validation.stats["closures"],
            schedule_effective=extraction.payload.get("schedule_effective"),
            violations=validation.violations,
            review_notes=extraction.review_notes,
            cost_estimate=extraction.cost_estimate,
            artifact_paths=extraction.artifact_paths,
        )
    return Proposed(
        **_identity_kwargs(entry),
        provider=provider,
        model=extraction.model,
        pdf_sha256=fetch_result.sha256,
        page_count=fetch_result.page_count,
        sessions_count=validation.stats["sessions"],
        prior_sessions_count=prior_sessions_count,
        closures_count=validation.stats["closures"],
        schedule_effective=extraction.payload.get("schedule_effective"),
        violations=validation.violations,
        review_notes=extraction.review_notes,
        cost_estimate=extraction.cost_estimate,
        artifact_paths=extraction.artifact_paths,
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

    if entry.source_status != "published":
        return Skipped(
            **_identity_kwargs(entry),
            reason="No current schedule PDF is available for this pool.",
            notes=entry.notes,
        )

    try:
        fetch_result = fetch_pdf(entry.slug, entry.pdf_url)
        date = fetch_result.path.parent.name[:10]
        reviewed_file = reviewed_path(entry.slug, date, fetch_result.sha256)

        # Fast-path: reviewed.json exists ⇒ the pool is locked to this PDF.
        if not force and not compare_with and reviewed_file.exists():
            return _build_unchanged(entry, fetch_result, reviewed_file)

        extraction = _extract_or_load(
            entry,
            fetch_result,
            provider=provider,
            prompt=prompt,
            force=force,
            compare_with=compare_with,
            prior_snapshot=prior_snapshot,
        )

        if compare_with:
            _apply_compare(
                extraction,
                entry=entry,
                fetch_result=fetch_result,
                primary_provider=provider,
                compare_with=compare_with,
                prompt=prompt,
            )

        validation = validate(
            extraction.payload,
            prior_sessions_count=len(prior_snapshot["sessions"]),
        )
        return _finalize(
            entry,
            extraction,
            fetch_result,
            validation,
            provider=provider,
            prior_sessions_count=len(prior_snapshot["sessions"]),
        )
    except Exception as exc:  # noqa: BLE001
        return Aborted(
            **_identity_kwargs(entry),
            error=str(exc),
            prior_sessions_count=len(prior_snapshot["sessions"]),
            prior_closures_count=len(prior_snapshot["closures"]),
            prior_schedule_effective=prior_snapshot["schedule_effective"],
        )


def run_pipeline(
    *,
    slugs: list[str] | None,
    provider: str,
    compare_with: str | None,
    force: bool,
) -> tuple[int, Path, list[PoolResult]]:
    registry = load_registry()
    selected = [entry for entry in registry if slugs is None or entry.slug in slugs]
    if slugs:
        missing = sorted(set(slugs) - {entry.slug for entry in selected})
        if missing:
            raise ValueError(f"Unknown registry slug(s): {', '.join(missing)}")

    prompt = PROMPT_PATH.read_text().strip()
    results = [
        _process_entry(
            entry,
            provider=provider,
            compare_with=compare_with,
            force=force,
            prompt=prompt,
        )
        for entry in selected
    ]
    report_path = write_report(results)
    return compute_exit_code(results), report_path, results
