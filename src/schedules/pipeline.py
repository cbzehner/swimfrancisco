from __future__ import annotations

from pathlib import Path

from .adjudications import load_adjudication
from .artifacts import save_artifact_bundle
from .delta import check_delta
from .fetch import fetch_pdf
from .grounding import compute_grounding
from .merge import merge, read_schedule_snapshot
from .models import DeltaResult, GroundingResult, PoolResult, ReviewFlag
from .paths import CONTENT_SPOTS_DIR, PROMPT_PATH
from .providers import extract as extract_with_provider
from .registry import load_registry
from .review import compare_payloads, string_flags
from .report import write_report
from .schema import EXTRACTION_SCHEMA
from .signals import analyze_pdf, source_flags_for_payload
from .state import build_state_entry, flags_for_entry, load_state, save_state
from .validate import validate

_GROUNDING_MIN_RATIO = 0.9
_GROUNDING_EVIDENCE_SAMPLE = 5


def _grounding_flags(provider: str, grounding: GroundingResult) -> list[ReviewFlag]:
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
        ReviewFlag(
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
                PoolResult(
                    slug=entry.slug,
                    status="skipped",
                    official_page_url=entry.official_page_url,
                    pdf_url=entry.pdf_url,
                    source_status=entry.source_status,
                    prior_sessions_count=len(prior_snapshot["sessions"]),
                    sessions_count=len(prior_snapshot["sessions"]),
                    closures_count=len(prior_snapshot["closures"]),
                    schedule_effective=prior_snapshot["schedule_effective"],
                    notes=entry.notes,
                    error="No current schedule PDF is available for this pool.",
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
                    PoolResult(
                        slug=entry.slug,
                        status="unchanged",
                        official_page_url=entry.official_page_url,
                        pdf_url=entry.pdf_url,
                        source_status=entry.source_status,
                        provider=prior_state.get("provider"),
                        model=prior_state.get("model"),
                        pdf_sha256=fetch_result.sha256,
                        page_count=fetch_result.page_count,
                        sessions_count=prior_state.get("sessions_count"),
                        prior_sessions_count=prior_state.get("sessions_count"),
                        closures_count=len(prior_snapshot["closures"]),
                        schedule_effective=prior_state.get("schedule_effective"),
                        invariants_passed=prior_state.get("invariants_passed"),
                        review_flags=flags_for_entry(prior_state),
                        cost_estimate="unchanged",
                        artifact_paths=dict(prior_state.get("artifact_paths") or {}),
                        pdf_text_sha256=prior_state.get("pdf_text_sha256"),
                    )
                )
                continue

            pdf_signals = analyze_pdf(fetch_result.bytes)
            if adjudication and not compare_with:
                payload = adjudication["payload"]
                model = "manual-review"
                usage = {}
                cost_estimate = "adjudicated"
                result_provider = "adjudicated"
                review_flags: list[ReviewFlag] = []
                artifact_paths = {"adjudicated": str(adjudication_path)}
                adjudication_notes = adjudication.get("summary")
            else:
                payload, model, usage, cost_estimate = extract_with_provider(
                    provider,
                    fetch_result.bytes,
                    prompt,
                    EXTRACTION_SCHEMA,
                )
                result_provider = provider
                review_flags = []
                review_flags.extend(source_flags_for_payload(pdf_signals, payload))
                primary_grounding = compute_grounding(fetch_result.bytes, payload)
                review_flags.extend(_grounding_flags(provider, primary_grounding))
                adjudication_notes = None
                review_flags.extend(string_flags(check_delta(payload, prior_state).flags))
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
            validation = validate(payload)
            delta = (
                DeltaResult(flags=[], hard_block=False)
                if adjudication and not compare_with
                else check_delta(payload, prior_state)
            )

            if compare_with:
                try:
                    compare_payload, compare_model, compare_usage, compare_cost_estimate = extract_with_provider(
                        compare_with,
                        fetch_result.bytes,
                        prompt,
                        EXTRACTION_SCHEMA,
                    )
                    compare_grounding = compute_grounding(fetch_result.bytes, compare_payload)
                    review_flags.extend(_grounding_flags(compare_with, compare_grounding))
                    artifact_paths.update(
                        save_artifact_bundle(
                            slug=entry.slug,
                            provider=compare_with,
                            model=compare_model,
                            pdf_url=entry.pdf_url,
                            pdf_sha256=fetch_result.sha256,
                            pdf_signals=pdf_signals,
                            prompt=prompt,
                            schema=EXTRACTION_SCHEMA,
                            payload=compare_payload,
                            usage=compare_usage,
                            cost_estimate=compare_cost_estimate,
                            grounding=compare_grounding,
                        )
                    )
                    review_flags.extend(compare_payloads(provider, payload, compare_with, compare_payload))
                except Exception as exc:  # noqa: BLE001
                    review_flags.append(
                        ReviewFlag(
                            kind="compare_provider_failed",
                            message=f"{compare_with} comparison run failed: {exc}",
                            severity="warning",
                        )
                    )

            if dry_run or delta.hard_block:
                merge_result = None
            else:
                merge_result = merge(CONTENT_SPOTS_DIR / f"{entry.slug}.md", payload)

            if not dry_run and not delta.hard_block:
                state[entry.slug] = build_state_entry(
                    pdf_url=entry.pdf_url,
                    pdf_sha256=fetch_result.sha256,
                    sessions_count=len(payload.get("sessions") or []),
                    session_types=[str(session.get("type")) for session in payload.get("sessions") or []],
                    schedule_effective=str(payload.get("schedule_effective")),
                    provider=result_provider,
                    model=model,
                    invariants_passed=validation.ok,
                    flags=review_flags,
                    artifact_paths=artifact_paths,
                    pdf_page_count=pdf_signals.page_count,
                    pdf_text_sha256=pdf_signals.text_sha256,
                    adjudication_sha256=adjudication_sha256,
                )
                state_dirty = True

            results.append(
                PoolResult(
                    slug=entry.slug,
                    status="failed" if delta.hard_block else "success",
                    official_page_url=entry.official_page_url,
                    pdf_url=entry.pdf_url,
                    source_status=entry.source_status,
                    provider=result_provider,
                    model=model,
                    pdf_sha256=fetch_result.sha256,
                    page_count=fetch_result.page_count,
                    sessions_count=validation.stats["sessions"],
                    prior_sessions_count=int(prior_state.get("sessions_count") or len(prior_snapshot["sessions"]))
                    if prior_state
                    else len(prior_snapshot["sessions"]),
                    closures_count=validation.stats["closures"],
                    schedule_effective=payload.get("schedule_effective"),
                    invariants_passed=validation.ok,
                    violations=validation.violations,
                    review_flags=review_flags,
                    hard_block=delta.hard_block,
                    cost_estimate=cost_estimate,
                    error="Semantic delta validation blocked merge." if delta.hard_block else None,
                    written=bool(merge_result and merge_result.written),
                    artifact_paths=artifact_paths,
                    pdf_text_sha256=pdf_signals.text_sha256,
                    notes=adjudication_notes,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                PoolResult(
                    slug=entry.slug,
                    status="failed",
                    official_page_url=entry.official_page_url,
                    pdf_url=entry.pdf_url,
                    source_status=entry.source_status,
                    prior_sessions_count=len(prior_snapshot["sessions"]),
                    sessions_count=len(prior_snapshot["sessions"]),
                    closures_count=len(prior_snapshot["closures"]),
                    schedule_effective=prior_snapshot["schedule_effective"],
                    error=str(exc),
                    review_flags=[],
                )
            )

    if state_dirty and not dry_run:
        save_state(state)

    report_path = write_report(results)
    exit_code = 0 if any(result.status in {"success", "unchanged"} for result in results) else 1
    return exit_code, report_path, results
