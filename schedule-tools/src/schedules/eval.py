"""Eval that diffs provider extractions against attested truth.

Reads existing artifacts under ``data/<slug>/<date>-<sha>/``; no API calls.
Run via ``just schedules-eval``.

Quality baseline is human Save or omitted ``attested_by`` (legacy). CI-attested
dirs are not same-dir truth. A latest CI dir may appear in a seasonal-delta
table against an older human envelope; never score CI vs CI.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ._time import PACIFIC_TZ
from .envelope import (
    AttestationAgentReference,
    AttestationCarried,
    AttestationCi,
    AttestationHuman,
    AttestationLegacy,
    parse_attestation,
)
from .paths import DATA_DIR, TMP_DIR


class EvaluationArtifactError(ValueError):
    """A JSON file that claims to be an eligible provider artifact is invalid."""


@dataclass(frozen=True)
class RowKey:
    day: str
    type: str
    start: str
    end: str
    pool: str
    physical_pool: str
    excluded_dates: tuple[str, ...]

    @classmethod
    def from_session(cls, session: dict) -> RowKey:
        return cls(
            day=str(session.get("day", "")),
            type=str(session.get("type", "")),
            start=str(session.get("start", "")),
            end=str(session.get("end", "")),
            pool=str(session.get("pool", "")),
            physical_pool=str(session.get("physical_pool", "")),
            excluded_dates=tuple(sorted(str(day) for day in session.get("excluded_dates", []))),
        )


def prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Precision/recall/F1 with the empty-denominator conventions used
    throughout the eval surfaces (no predictions → perfect precision)."""
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass(frozen=True)
class PoolEval:
    pool: str
    review_dir: Path
    provider_artifact: str
    provider: str
    truth_count: int
    extracted_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    extra_examples: list[dict]
    missing_examples: list[dict]
    fact_comparisons: list["FactComparison"]
    reference_origin: str
    artifact_origin: str
    table: str = "quality"  # "quality" | "seasonal_delta"

    @property
    def precision(self) -> float:
        return prf1(self.true_positives, self.false_positives, self.false_negatives)[0]

    @property
    def recall(self) -> float:
        return prf1(self.true_positives, self.false_positives, self.false_negatives)[1]

    @property
    def f1(self) -> float:
        return prf1(self.true_positives, self.false_positives, self.false_negatives)[2]


@dataclass(frozen=True)
class UnscoredArtifact:
    pool: str
    review_dir: Path
    provider_artifact: str
    reason: str
    table: str = "quality"


@dataclass(frozen=True)
class FactComparison:
    """A semantic comparison between one reference and provider dimension."""

    dimension: str
    reference_covered: bool
    matches: bool | None
    missing: tuple[object, ...] = ()
    extra: tuple[object, ...] = ()
    duplicate_reference: tuple[object, ...] = ()
    duplicate_extracted: tuple[object, ...] = ()


def _counter_difference(left: Counter, right: Counter) -> tuple[object, ...]:
    values: list[object] = []
    for item in sorted(left.keys(), key=repr):
        values.extend([item] * (left[item] - right[item]))
    return tuple(values)


def _compare_values(
    dimension: str,
    reference: object,
    extracted: object,
    *,
    reference_covered: bool = True,
    as_list: bool = False,
) -> FactComparison:
    if not reference_covered:
        return FactComparison(dimension, False, None)
    if as_list:
        reference_counter = Counter(reference)
        extracted_counter = Counter(extracted)
        missing = _counter_difference(reference_counter, extracted_counter)
        extra = _counter_difference(extracted_counter, reference_counter)
        duplicate_reference = tuple(
            item for item, count in sorted(reference_counter.items(), key=lambda pair: repr(pair[0]))
            if count > 1 for _ in range(count - 1)
        )
        duplicate_extracted = tuple(
            item for item, count in sorted(extracted_counter.items(), key=lambda pair: repr(pair[0]))
            if count > 1 for _ in range(count - 1)
        )
    else:
        missing = () if reference == extracted else (reference,)
        extra = () if reference == extracted else (extracted,)
        duplicate_reference = duplicate_extracted = ()
    return FactComparison(
        dimension=dimension,
        reference_covered=True,
        matches=not missing and not extra,
        missing=missing,
        extra=extra,
        duplicate_reference=duplicate_reference,
        duplicate_extracted=duplicate_extracted,
    )


def _session_key(session: dict) -> tuple:
    return (
        str(session.get("day", "")),
        str(session.get("type", "")),
        str(session.get("start", "")),
        str(session.get("end", "")),
        str(session.get("pool", "")),
        str(session.get("physical_pool", "")),
        tuple(sorted(str(day) for day in session.get("excluded_dates", []))),
    )


def _closure_key(closure: dict) -> tuple:
    return tuple(closure.get(field) for field in ("start", "end", "start_time", "end_time", "physical_pool"))


def _access_hour_key(item: dict) -> tuple:
    return tuple(item.get(field) for field in ("day", "start", "end"))


def _access_exception_key(item: dict) -> tuple:
    # The date and interval define the exception. Labels and reasons are
    # explanatory prose and should not turn a semantically identical window
    # into a mismatch.
    return tuple(item.get(field) for field in ("date", "start", "end"))


def _session_dimension_covered(sessions: object, field: str) -> bool:
    """Return whether every referenced session explicitly carries a field."""
    return isinstance(sessions, list) and bool(sessions) and all(
        isinstance(session, dict) and field in session for session in sessions
    )


def _fact_comparisons(truth: dict, extracted: dict) -> list[FactComparison]:
    sessions_covered = "sessions" in truth
    truth_sessions = truth.get("sessions", [])
    extracted_sessions = extracted.get("sessions", [])
    truth_session_keys = [_session_key(session) for session in truth_sessions]
    extracted_session_keys = [_session_key(session) for session in extracted_sessions]
    truth_pools = sorted({key[5] for key in truth_session_keys if key[5]})
    extracted_pools = sorted({key[5] for key in extracted_session_keys if key[5]})
    truth_exclusions = sorted(
        (key[:6], date) for key in truth_session_keys for date in key[6]
    )
    extracted_exclusions = sorted(
        (key[:6], date) for key in extracted_session_keys for date in key[6]
    )
    physical_pools_covered = _session_dimension_covered(truth_sessions, "physical_pool")
    exclusions_covered = _session_dimension_covered(truth_sessions, "excluded_dates")

    comparisons = [
        _compare_values(
            "sessions", truth_session_keys, extracted_session_keys,
            reference_covered=sessions_covered, as_list=True,
        ),
        _compare_values(
            "physical_pools", truth_pools, extracted_pools,
            reference_covered=physical_pools_covered, as_list=True,
        ),
        _compare_values(
            "excluded_dates", truth_exclusions, extracted_exclusions,
            reference_covered=exclusions_covered, as_list=True,
        ),
        _compare_values(
            "effective_window",
            (truth.get("effective_start"), truth.get("effective_end")),
            (extracted.get("effective_start"), extracted.get("effective_end")),
            reference_covered="effective_start" in truth,
        ),
        _compare_values(
            "schedule_basis", truth.get("schedule_basis"), extracted.get("schedule_basis"),
            reference_covered="schedule_basis" in truth,
        ),
        _compare_values(
            "closures",
            [_closure_key(item) for item in truth.get("closures", [])],
            [_closure_key(item) for item in extracted.get("closures", [])],
            reference_covered="closures" in truth,
            as_list=True,
        ),
        _compare_values(
            "access_hours",
            [_access_hour_key(item) for item in truth.get("access_hours", [])],
            [_access_hour_key(item) for item in extracted.get("access_hours", [])],
            reference_covered="access_hours" in truth,
            as_list=True,
        ),
        _compare_values(
            "access_exceptions",
            [_access_exception_key(item) for item in truth.get("access_exceptions", [])],
            [_access_exception_key(item) for item in extracted.get("access_exceptions", [])],
            reference_covered="access_exceptions" in truth,
            as_list=True,
        ),
    ]
    return comparisons


def _diff_payloads(truth: dict, extracted: dict, sample_n: int = 3) -> tuple[Counter[RowKey], Counter[RowKey], int, list[dict], list[dict]]:
    truth_keys = Counter(RowKey.from_session(s) for s in truth.get("sessions", []))
    extracted_sessions = extracted.get("sessions", [])
    extracted_keys = Counter(RowKey.from_session(s) for s in extracted_sessions)

    extras = extracted_keys - truth_keys
    missings = truth_keys - extracted_keys
    tp = sum((truth_keys & extracted_keys).values())

    extra_samples = []
    for s in extracted_sessions:
        if RowKey.from_session(s) in extras and len(extra_samples) < sample_n:
            extra_samples.append({
                "day": s.get("day"), "type": s.get("type"),
                "start": s.get("start"), "end": s.get("end"),
                "pool": s.get("pool", ""),
                "evidence": s.get("evidence", "")[:120],
                "physical_pool": s.get("physical_pool", ""),
                "excluded_dates": s.get("excluded_dates", []),
            })
    missing_samples = []
    for s in truth.get("sessions", []):
        if RowKey.from_session(s) in missings and len(missing_samples) < sample_n:
            missing_samples.append({
                "day": s.get("day"), "type": s.get("type"),
                "start": s.get("start"), "end": s.get("end"),
                "pool": s.get("pool", ""),
                "evidence": s.get("evidence", "")[:120],
                "physical_pool": s.get("physical_pool", ""),
                "excluded_dates": s.get("excluded_dates", []),
            })

    return extras, missings, tp, extra_samples, missing_samples


def _validate_eval_payload(payload: dict, path: Path) -> None:
    sessions = payload.get("sessions", [])
    if not isinstance(sessions, list):
        raise EvaluationArtifactError(f"{path}: payload.sessions must be a JSON array")
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise EvaluationArtifactError(
                f"{path}: payload.sessions[{index}] must be a JSON object"
            )
        if "evidence" in session and not isinstance(session["evidence"], str):
            raise EvaluationArtifactError(
                f"{path}: payload.sessions[{index}].evidence must be a string"
            )
        if "excluded_dates" in session and (
            not isinstance(session["excluded_dates"], list)
            or not all(isinstance(day, str) for day in session["excluded_dates"])
        ):
            raise EvaluationArtifactError(
                f"{path}: payload.sessions[{index}].excluded_dates must be an array of strings"
            )
    fact_fields = {
        "closures": ("start", "end", "start_time", "end_time", "physical_pool"),
        "access_hours": ("day", "start", "end", "label"),
        "access_exceptions": ("date", "start", "end", "label", "reason"),
    }
    for field, consumed_fields in fact_fields.items():
        if field not in payload:
            continue
        values = payload[field]
        if not isinstance(values, list):
            raise EvaluationArtifactError(f"{path}: payload.{field} must be a JSON array")
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                raise EvaluationArtifactError(
                    f"{path}: payload.{field}[{index}] must be a JSON object"
                )
            for consumed_field in consumed_fields:
                if consumed_field in value and not isinstance(value[consumed_field], (str, type(None))):
                    raise EvaluationArtifactError(
                        f"{path}: payload.{field}[{index}].{consumed_field} must be a string or null"
                    )


def _load_envelope(path: Path) -> dict | None:
    try:
        envelope = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return envelope if isinstance(envelope, dict) else None


def _is_human_or_omitted(envelope: dict) -> bool:
    kind = parse_attestation(envelope)
    origin = kind.origin if isinstance(kind, AttestationCarried) else kind
    return isinstance(origin, (AttestationLegacy, AttestationHuman))


def _reference_origin(envelope: dict) -> str:
    kind = parse_attestation(envelope)
    if isinstance(kind, AttestationCarried):
        origin = kind.origin
        prefix = "carried "
    else:
        origin = kind
        prefix = ""
    if isinstance(origin, AttestationCi):
        return prefix + "ci"
    if isinstance(origin, AttestationHuman):
        return prefix + "human"
    if isinstance(origin, AttestationAgentReference):
        return prefix + "agent-reference"
    return prefix + "legacy"


def _evals_for_dir(
    *,
    pool: str,
    review_dir: Path,
    truth: dict,
    table: str,
    reference_origin: str,
    artifact_origin: str,
) -> list[PoolEval | UnscoredArtifact]:
    _validate_eval_payload(truth, review_dir / "reviewed.json")
    results: list[PoolEval | UnscoredArtifact] = []
    for art_path in sorted(review_dir.glob("*.json")):
        if art_path.name in {"reviewed.json", "source-bundle.json"}:
            continue
        try:
            art = json.loads(art_path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvaluationArtifactError(f"{art_path}: invalid JSON ({exc})") from exc
        if not isinstance(art, dict):
            raise EvaluationArtifactError(
                f"{art_path}: eligible provider artifact must be a JSON object"
            )

        status = art.get("status")
        if status not in (None, "completed"):
            results.append(
                UnscoredArtifact(
                    pool=pool,
                    review_dir=review_dir,
                    provider_artifact=art_path.name,
                    reason=f"recorded provider failure ({status})",
                    table=table,
                )
            )
            continue
        if "payload" not in art:
            if status == "completed":
                raise EvaluationArtifactError(
                    f"{art_path}: completed provider artifact is missing payload"
                )
            results.append(
                UnscoredArtifact(
                    pool=pool,
                    review_dir=review_dir,
                    provider_artifact=art_path.name,
                    reason="unsupported historical artifact: no payload",
                    table=table,
                )
            )
            continue
        extracted = art["payload"]
        if not isinstance(extracted, dict):
            raise EvaluationArtifactError(
                f"{art_path}: successful provider payload must be a JSON object"
            )
        if "sessions" not in extracted:
            results.append(
                UnscoredArtifact(
                    pool=pool,
                    review_dir=review_dir,
                    provider_artifact=art_path.name,
                    reason="unsupported historical artifact: payload has no sessions",
                    table=table,
                )
            )
            continue
        _validate_eval_payload(extracted, art_path)
        extras, missings, tp, extra_ex, missing_ex = _diff_payloads(truth, extracted)
        results.append(
            PoolEval(
                pool=pool,
                review_dir=review_dir,
                provider_artifact=art_path.name,
                provider=art_path.stem.split("-", 1)[0],
                truth_count=len(truth.get("sessions", [])),
                extracted_count=len(extracted.get("sessions", [])),
                true_positives=tp,
                false_positives=sum(extras.values()),
                false_negatives=sum(missings.values()),
                extra_examples=extra_ex,
                missing_examples=missing_ex,
                fact_comparisons=_fact_comparisons(truth, extracted),
                reference_origin=reference_origin,
                artifact_origin=artifact_origin,
                table=table,
            )
        )
    return results


def collect_pool_evals(*, data_root: Path = DATA_DIR, all_dirs: bool = False) -> list[PoolEval | UnscoredArtifact]:
    """Walk data/ and emit one PoolEval per (review_dir, provider artifact).

    Quality rows use same-dir truth only when ``attested_by`` is ``human`` or
    omitted, including carries of those origins. CI and agent-reference dirs
    are never same-dir truth; look back for a human/omitted envelope and emit
    a seasonal-delta row against the latest provider JSON. Never score one
    non-independent reference against another.
    """
    results: list[PoolEval | UnscoredArtifact] = []
    if not data_root.is_dir():
        return results
    for pool_dir in sorted(data_root.iterdir()):
        if not pool_dir.is_dir():
            continue
        review_dirs = [
            d for d in sorted(pool_dir.iterdir()) if d.is_dir() and (d / "reviewed.json").exists()
        ]
        if not review_dirs:
            continue
        envelopes: list[tuple[Path, dict]] = []
        for review_dir in review_dirs:
            envelope = _load_envelope(review_dir / "reviewed.json")
            if envelope is None:
                continue
            envelopes.append((review_dir, envelope))
        if not envelopes:
            continue

        quality_dirs = envelopes if all_dirs else envelopes[-1:]
        for review_dir, envelope in quality_dirs:
            if not _is_human_or_omitted(envelope):
                continue
            truth = envelope.get("payload") or {}
            results.extend(
                _evals_for_dir(
                    pool=pool_dir.name,
                    review_dir=review_dir,
                    truth=truth,
                    table="quality",
                    reference_origin=_reference_origin(envelope),
                    artifact_origin=_reference_origin(envelope),
                )
            )

        latest_dir, latest_env = envelopes[-1]
        if not _is_human_or_omitted(latest_env):
            human_payload = None
            for _older_dir, older_env in reversed(envelopes[:-1]):
                if _is_human_or_omitted(older_env):
                    human_payload = older_env.get("payload") or {}
                    break
            if human_payload is not None:
                results.extend(
                    _evals_for_dir(
                        pool=pool_dir.name,
                        review_dir=latest_dir,
                        truth=human_payload,
                        table="seasonal_delta",
                        reference_origin=_reference_origin(older_env),
                        artifact_origin=_reference_origin(latest_env),
                    )
                )
    return results


def render_report(evals: Iterable[PoolEval | UnscoredArtifact]) -> str:
    evals = list(evals)
    unscored = [item for item in evals if isinstance(item, UnscoredArtifact)]
    scored = [item for item in evals if isinstance(item, PoolEval)]
    quality = [item for item in scored if item.table != "seasonal_delta"]
    seasonal = [item for item in scored if item.table == "seasonal_delta"]
    if not quality and not seasonal and not unscored:
        return "# Schedule extraction eval\n\nNo (review_dir, provider) pairs found.\n"

    lines: list[str] = []
    lines.append("# Schedule extraction eval")
    lines.append("")
    lines.append(f"_Generated {datetime.now(PACIFIC_TZ).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append("Quality baseline diffs each provider artifact against a human or omitted")
    lines.append("`attested_by` envelope in the same review dir. CI and agent-reference dirs are not")
    lines.append("same-dir truth. Session F1 is session-only; row identity includes day, type, time, allocation, physical pool, and exclusions.")
    lines.append("")

    if unscored:
        lines.append("## Unscored artifacts")
        lines.append("")
        lines.append("These recorded failures or unsupported historical artifacts were not treated as zero-session predictions.")
        lines.append("")
        lines.append("| Pool | Review dir | Artifact | Table | Reason |")
        lines.append("|---|---|---|---|---|")
        for item in sorted(unscored, key=lambda x: (x.pool, x.provider_artifact, x.table)):
            lines.append(
                f"| {item.pool} | {item.review_dir} | {item.provider_artifact} | "
                f"{item.table} | {item.reason} |"
            )
        lines.append("")

    # Per-provider rollup (quality only — seasonal-delta must not gate quality)
    by_provider: dict[str, list[PoolEval]] = {}
    for e in quality:
        by_provider.setdefault(e.provider, []).append(e)

    lines.append("## Aggregate by provider")
    lines.append("")
    lines.append("| Provider | Pools | Truth rows | Extracted | TP | FP | FN | Precision | Recall | F1 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for provider, items in sorted(by_provider.items()):
        truth = sum(i.truth_count for i in items)
        extracted = sum(i.extracted_count for i in items)
        tp = sum(i.true_positives for i in items)
        fp = sum(i.false_positives for i in items)
        fn = sum(i.false_negatives for i in items)
        precision, recall, f1 = prf1(tp, fp, fn)
        lines.append(
            f"| {provider} | {len(items)} | {truth} | {extracted} | {tp} | {fp} | {fn} | "
            f"{precision:.0%} | {recall:.0%} | {f1:.2f} |"
        )
    lines.append("")

    lines.append("## Per pool / artifact")
    lines.append("")
    lines.append("| Pool | Artifact | Reference | Truth | Extr | TP | FP | FN | P | R | F1 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for e in sorted(quality, key=lambda x: (x.pool, x.provider)):
        lines.append(
            f"| {e.pool} | {e.provider_artifact} | {e.reference_origin} | {e.truth_count} | {e.extracted_count} | "
            f"{e.true_positives} | {e.false_positives} | {e.false_negatives} | "
            f"{e.precision:.0%} | {e.recall:.0%} | {e.f1:.2f} |"
        )
    lines.append("")

    lines.append("## Semantic dimensions")
    lines.append("")
    lines.append("Session F1 is session-only. Semantic dimensions compare available reference facts; omitted optional reference fields are unknown/unmeasured. Agent references remain distinguishable and are not human approval.")
    lines.append("")
    lines.append("| Table | Pool | Artifact | Reference | Snapshot | Dimension | Status | Missing | Extra | Duplicate reference | Duplicate extracted |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for e in sorted(scored, key=lambda x: (x.table, x.pool, x.provider_artifact)):
        for comparison in e.fact_comparisons:
            if not comparison.reference_covered:
                status = "unknown/unmeasured"
            elif comparison.matches:
                status = "match"
            else:
                status = "mismatch"
            display = lambda values: ", ".join(repr(value) for value in values[:3]) or "—"
            lines.append(
                f"| {e.table} | {e.pool} | {e.provider_artifact} | {e.reference_origin} | {e.artifact_origin} | {comparison.dimension} | {status} | "
                f"{display(comparison.missing)} | {display(comparison.extra)} | "
                f"{display(comparison.duplicate_reference)} | {display(comparison.duplicate_extracted)} |"
            )
    lines.append("")

    if seasonal:
        lines.append("## Seasonal delta (not quality baseline)")
        lines.append("")
        lines.append("Latest CI or agent-reference provider JSON vs an older human/omitted envelope.")
        lines.append("Seasonal change, not model regression. Not in the quality aggregate.")
        lines.append("")
        lines.append("| Pool | Artifact | Reference | Snapshot | Truth | Extr | TP | FP | FN | P | R | F1 |")
        lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for e in sorted(seasonal, key=lambda x: (x.pool, x.provider)):
            lines.append(
                f"| {e.pool} | {e.provider_artifact} | {e.reference_origin} | {e.artifact_origin} | {e.truth_count} | {e.extracted_count} | "
                f"{e.true_positives} | {e.false_positives} | {e.false_negatives} | "
                f"{e.precision:.0%} | {e.recall:.0%} | {e.f1:.2f} |"
            )
        lines.append("")

    lines.append("## Disagreements (samples)")
    lines.append("")
    for e in sorted(quality, key=lambda x: (x.pool, x.provider)):
        if not (e.extra_examples or e.missing_examples):
            continue
        lines.append(f"### {e.pool} — {e.provider_artifact}")
        if e.extra_examples:
            lines.append("**Extra (extracted but not in truth):**")
            for ex in e.extra_examples:
                lines.append(f"- {ex['day']} {ex['type']} {ex['start']}-{ex['end']} physical_pool={ex.get('physical_pool', '')}  `{ex['evidence']}`")
        if e.missing_examples:
            lines.append("**Missing (in truth but not extracted):**")
            for ex in e.missing_examples:
                lines.append(f"- {ex['day']} {ex['type']} {ex['start']}-{ex['end']} physical_pool={ex.get('physical_pool', '')}  `{ex['evidence']}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_report(evals: Iterable[PoolEval | UnscoredArtifact], *, tmp_dir: Path = TMP_DIR) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(PACIFIC_TZ).strftime("%Y%m%dT%H%M%S")
    path = tmp_dir / f"eval-{timestamp}.md"
    path.write_text(render_report(evals))
    return path
