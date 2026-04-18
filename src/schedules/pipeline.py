from __future__ import annotations

from pathlib import Path

from .adjudications import load_adjudication
from .artifacts import save_artifact_bundle
from .delta import check_delta
from .fetch import fetch_pdf
from .grounding import grounding_from_text, normalize_pdf_text
from .merge import merge, read_schedule_snapshot
from .models import Failed, GroundingResult, PoolEntry, PoolResult, Proposed, ReviewNote, Skipped, Unchanged
from .paths import CONTENT_SPOTS_DIR, PROMPT_PATH
from .providers import extract as extract_with_provider
from .registry import load_registry
from .review import compare_payloads
from .report import write_report
from .schema import EXTRACTION_SCHEMA
from .signals import analyze_page_texts, extract_page_texts, source_notes_for_payload
from .state import build_state_entry, load_state, notes_for_entry, save_state
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
    state = load_state()
    results: list[PoolResult] = []
    state_dirty = False

    for entry in selected:
        prior_state = state.get(entry.slug)
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
            fetch_result = fetch_pdf(entry.slug, entry.pdf_url, force=force)
            adjudication, adjudication_sha256, adjudication_path = load_adjudication(entry.slug, fetch_result.sha256)
            if (
                not force
                and not compare_with
                and prior_state
                and prior_state.get("pdf_sha256") == fetch_result.sha256
                and prior_state.get("adjudication_sha256") == adjudication_sha256
            ):
                results.append(
                    Unchanged(
                        **_identity_kwargs(entry),
                        provider=str(prior_state.get("provider")),
                        model=str(prior_state.get("model")),
                        pdf_sha256=fetch_result.sha256,
                        page_count=fetch_result.page_count,
                        sessions_count=int(prior_state.get("sessions_count") or 0),
                        closures_count=len(prior_snapshot["closures"]),
                        schedule_effective=str(prior_state.get("schedule_effective")),
                        invariants_passed=bool(prior_state.get("invariants_passed")),
                        review_notes=notes_for_entry(prior_state),
                        artifact_paths=dict(prior_state.get("artifact_paths") or {}),
                        pdf_text_sha256=prior_state.get("pdf_text_sha256"),
                    )
                )
                continue

            page_texts = extract_page_texts(fetch_result.bytes)
            pdf_signals = analyze_page_texts(page_texts)
            pdf_text_normalized = normalize_pdf_text(page_texts)
            prior_sessions_count = (
                int(prior_state.get("sessions_count") or 0) if prior_state else 0
            )
            if adjudication and not compare_with:
                payload = adjudication["payload"]
                model = "manual-review"
                usage = {}
                cost_estimate = "adjudicated"
                result_provider = "adjudicated"
                review_notes: list[ReviewNote] = []
                artifact_paths = {"adjudicated": str(adjudication_path)}
                adjudication_notes = adjudication.get("summary")
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
                adjudication_notes = None
                review_notes.extend(check_delta(payload, prior_state))
                artifact_paths = save_artifact_bundle(
                    slug=entry.slug,
                    provider=provider,
                    model=model,
                    pdf_url=entry.pdf_url,
                    pdf_sha256=fetch_result.sha256,
                    pdf_signals=pdf_signals,
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
                            provider=compare_with,
                            model=compare.model,
                            pdf_url=entry.pdf_url,
                            pdf_sha256=fetch_result.sha256,
                            pdf_signals=pdf_signals,
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

            if write_allowed:
                state[entry.slug] = build_state_entry(
                    pdf_url=entry.pdf_url,
                    pdf_sha256=fetch_result.sha256,
                    sessions_count=len(payload.get("sessions") or []),
                    session_types=[str(session.get("type")) for session in payload.get("sessions") or []],
                    schedule_effective=str(payload.get("schedule_effective")),
                    provider=result_provider,
                    model=model,
                    invariants_passed=validation.ok,
                    notes=review_notes,
                    artifact_paths=artifact_paths,
                    pdf_page_count=pdf_signals.page_count,
                    pdf_text_sha256=pdf_signals.text_sha256,
                    adjudication_sha256=adjudication_sha256,
                )
                state_dirty = True

            result_prior_sessions = (
                int(prior_state.get("sessions_count") or len(prior_snapshot["sessions"]))
                if prior_state
                else len(prior_snapshot["sessions"])
            )
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
                        pdf_text_sha256=pdf_signals.text_sha256,
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
                        pdf_text_sha256=pdf_signals.text_sha256,
                        adjudication_notes=adjudication_notes,
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

    if state_dirty and not dry_run and compare_with is None:
        save_state(state)

    report_path = write_report(results)
    return compute_exit_code(results), report_path, results
