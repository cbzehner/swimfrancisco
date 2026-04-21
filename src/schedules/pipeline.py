from __future__ import annotations

import json
import os
from pathlib import Path

from .artifacts import save_artifact_bundle, skip_if_fresh
from .delta import check_delta
from .envelope import EnvelopeValidationError, validate_envelope
from .fetch import fetch_pdf
from .grounding import grounding_from_text, normalize_pdf_text
from .merge import merge, read_schedule_snapshot
from .models import Failed, GroundingResult, PoolEntry, PoolResult, Proposed, ReviewNote, Skipped, Unchanged
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


def should_write(*, dry_run: bool, compare_with: str | None, catastrophic: bool) -> bool:
    """Return True iff the pipeline may mutate content or state.

    Gating invariants (all must be False for a write to happen):
    - dry_run: operator asked for a no-write pass
    - compare_with: bakeoff mode is observational by default
    - catastrophic: validation refused the new payload (e.g. sessions dropped to 0)
    """
    return not (dry_run or compare_with is not None or catastrophic)


def compute_exit_code(results: list[PoolResult]) -> int:
    """Non-zero when any pool failed. Partial failure must not exit 0."""
    return 1 if any(isinstance(result, Failed) for result in results) else 0


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


def run_pipeline(
    *,
    slugs: list[str] | None,
    provider: str,
    compare_with: str | None,
    force: bool,
    dry_run: bool,
) -> tuple[int, Path, list[PoolResult]]:
    registry = load_registry()
    selected = [entry for entry in registry if slugs is None or entry.slug in slugs]
    if slugs:
        missing = sorted(set(slugs) - {entry.slug for entry in selected})
        if missing:
            raise ValueError(f"Unknown registry slug(s): {', '.join(missing)}")

    prompt = PROMPT_PATH.read_text().strip()
    results: list[PoolResult] = []

    for entry in selected:
        prior_snapshot = read_schedule_snapshot(CONTENT_SPOTS_DIR / f"{entry.slug}.md")

        if entry.source_status != "published":
            results.append(
                Skipped(
                    **_identity_kwargs(entry),
                    reason="No current schedule PDF is available for this pool.",
                    notes=entry.notes,
                )
            )
            continue

        try:
            fetch_result = fetch_pdf(entry.slug, entry.pdf_url)
            date = fetch_result.path.parent.name[:10]
            reviewed_file = reviewed_path(entry.slug, date, fetch_result.sha256)

            # Fast-path: reviewed.json exists ⇒ the pool is locked to this PDF.
            if not force and not compare_with and reviewed_file.exists():
                envelope = _load_reviewed_envelope(reviewed_file, entry.slug, fetch_result.sha256)
                payload = envelope["payload"]
                results.append(
                    Unchanged(
                        **_identity_kwargs(entry),
                        provider="reviewed-snapshot",
                        model="manual-review",
                        pdf_sha256=fetch_result.sha256,
                        page_count=fetch_result.page_count,
                        sessions_count=len(payload.get("sessions") or []),
                        closures_count=len(payload.get("closures") or []),
                        schedule_effective=str(payload.get("schedule_effective") or ""),
                        invariants_passed=True,
                        review_notes=[],
                        artifact_paths={"reviewed-snapshot": str(reviewed_file)},
                    )
                )
                continue

            page_texts = extract_page_texts(fetch_result.bytes)
            pdf_signals = analyze_page_texts(page_texts)
            pdf_text_normalized = normalize_pdf_text(page_texts)
            prior_sessions_count = len(prior_snapshot["sessions"])

            # Extract-skip: provider cache matches current prompt+schema hashes.
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
                cached_path = artifact_path(
                    entry.slug, date, fetch_result.sha256, provider, default_model
                )
                cached = json.loads(cached_path.read_text())
                payload = cached["payload"]
                model = cached.get("model", default_model)
                usage = cached.get("usage") or {}
                cost_estimate = cached.get("cost_estimate", "cached")
                result_provider = provider
                review_notes: list[ReviewNote] = []
                review_notes.extend(source_notes_for_payload(pdf_signals, payload))
                cached_grounding = grounding_from_text(pdf_text_normalized, payload)
                review_notes.extend(_grounding_notes(provider, cached_grounding))
                review_notes.extend(check_delta(payload, prior_snapshot))
                artifact_paths = {provider: str(cached_path)}
            else:
                primary = extract_with_provider(provider, fetch_result.bytes, prompt, EXTRACTION_SCHEMA)
                payload = primary.payload
                model = primary.model
                usage = primary.usage
                cost_estimate = primary.cost_estimate
                result_provider = provider
                review_notes = []
                review_notes.extend(source_notes_for_payload(pdf_signals, payload))
                primary_grounding = grounding_from_text(pdf_text_normalized, payload)
                review_notes.extend(_grounding_notes(provider, primary_grounding))
                review_notes.extend(check_delta(payload, prior_snapshot))
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
                    usage=usage,
                    cost_estimate=cost_estimate,
                    grounding=primary_grounding,
                )

            validation = validate(payload, prior_sessions_count=prior_sessions_count)

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

            write_allowed = should_write(
                dry_run=dry_run,
                compare_with=compare_with,
                catastrophic=validation.catastrophic,
            )

            if write_allowed:
                merge_result = merge(CONTENT_SPOTS_DIR / f"{entry.slug}.md", payload)
            else:
                merge_result = None

            result_prior_sessions = len(prior_snapshot["sessions"])
            if validation.catastrophic:
                results.append(
                    Failed(
                        **_identity_kwargs(entry),
                        error="Validation refused the extracted payload.",
                        provider=result_provider,
                        model=model,
                        pdf_sha256=fetch_result.sha256,
                        page_count=fetch_result.page_count,
                        sessions_count=validation.stats["sessions"],
                        prior_sessions_count=result_prior_sessions,
                        closures_count=validation.stats["closures"],
                        schedule_effective=payload.get("schedule_effective"),
                        violations=validation.violations,
                        review_notes=review_notes,
                        cost_estimate=cost_estimate,
                        artifact_paths=artifact_paths,
                    )
                )
            else:
                results.append(
                    Proposed(
                        **_identity_kwargs(entry),
                        provider=result_provider,
                        model=model,
                        pdf_sha256=fetch_result.sha256,
                        page_count=fetch_result.page_count,
                        sessions_count=validation.stats["sessions"],
                        prior_sessions_count=result_prior_sessions,
                        closures_count=validation.stats["closures"],
                        schedule_effective=payload.get("schedule_effective"),
                        invariants_passed=validation.ok,
                        violations=validation.violations,
                        review_notes=review_notes,
                        cost_estimate=cost_estimate,
                        written=bool(merge_result and merge_result.written),
                        artifact_paths=artifact_paths,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            prior_count = len(prior_snapshot["sessions"])
            results.append(
                Failed(
                    **_identity_kwargs(entry),
                    error=str(exc),
                    prior_sessions_count=prior_count,
                    sessions_count=prior_count,
                    closures_count=len(prior_snapshot["closures"]),
                    schedule_effective=prior_snapshot["schedule_effective"],
                )
            )

    report_path = write_report(results)
    return compute_exit_code(results), report_path, results
