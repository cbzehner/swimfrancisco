"""Bakeoff-style eval that diffs provider extractions against attested truth.

Reads existing artifacts under ``data/<slug>/<date>-<sha>/``; no API calls.
Run via ``just schedules-eval``.

Quality baseline is human Save or omitted ``attested_by`` (legacy). CI-attested
dirs are not same-dir truth. A latest CI dir may appear in a seasonal-delta
table against an older human envelope; never score CI vs CI.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import jsonschema

from ._time import PACIFIC_TZ
from .envelope import AttestationCarried, AttestationCi, parse_attestation
from .paths import DATA_DIR, TMP_DIR
from .schema import EXTRACTION_SCHEMA


@dataclass(frozen=True)
class RowKey:
    day: str
    type: str
    start: str
    end: str
    pool: str

    @classmethod
    def from_session(cls, session: dict) -> RowKey:
        return cls(
            day=str(session.get("day", "")),
            type=str(session.get("type", "")),
            start=str(session.get("start", "")),
            end=str(session.get("end", "")),
            pool=str(session.get("pool", "")),
        )


def prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Precision/recall/F1 with the empty-denominator conventions used
    throughout the eval surfaces (no predictions → perfect precision)."""
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def load_benchmark_reference(path: Path, reference_id: str, *, repo_root: Path) -> dict:
    references = json.loads(path.read_text())["documents"]
    matches = [item for item in references if item["id"] == reference_id]
    if len(matches) != 1:
        raise ValueError("Benchmark reference must identify exactly one document.")
    reference = matches[0]
    if reference["split"] != "development" or not reference.get("expected"):
        raise ValueError("This document is reserved or has no checked reference yet.")
    source = (repo_root / reference["source_pdf"]).resolve()
    if not source.is_relative_to(repo_root.resolve()):
        raise ValueError("Benchmark source must be inside the repository.")
    if hashlib.sha256(source.read_bytes()).hexdigest() != reference["source_sha256"]:
        raise ValueError("Benchmark source hash does not match the checked document.")
    expected = reference["expected"]
    try:
        jsonschema.validate(
            expected | {"closures": expected.get("closures", [])}, EXTRACTION_SCHEMA,
            format_checker=jsonschema.FormatChecker(),
        )
    except (jsonschema.ValidationError, TypeError, AttributeError) as exc:
        raise ValueError("Benchmark reference contains invalid expected schedule data.") from exc
    rows = [RowKey.from_session(row) for row in expected["sessions"]]
    if len(rows) != len(set(rows)):
        raise ValueError("Benchmark reference contains duplicate sessions.")
    if "as_of" in reference:
        date.fromisoformat(reference["as_of"])
    return reference


def _benchmark_rows(rows: list[dict], fields: tuple[str, ...]) -> Counter:
    return Counter(tuple(row.get(field, "") for field in fields) for row in rows)


def _benchmark_row_score(expected: list[dict], actual: list[dict], fields: tuple[str, ...]) -> dict:
    truth = _benchmark_rows(expected, fields)
    extracted = _benchmark_rows(actual, fields)
    matches = (truth & extracted).total()
    extras = extracted - truth
    missing = truth - extracted
    precision, recall, f1 = prf1(matches, extras.total(), missing.total())
    return {
        "precision": precision, "recall": recall, "f1": f1,
        "expected_count": truth.total(), "actual_count": extracted.total(),
        "extra": [dict(zip(fields, row)) for row in extras.elements()],
        "missing": [dict(zip(fields, row)) for row in missing.elements()],
    }


def score_benchmark_run(reference: dict, run: dict) -> dict:
    """Score a recorded attempt without calling a model or publishing data."""
    for field in ("model", "transport", "source_sha256"):
        if not isinstance(run.get(field), str) or not run[field].strip():
            raise ValueError(f"Benchmark attempt requires {field}.")
    if run["source_sha256"] != reference["source_sha256"]:
        raise ValueError("Attempt and reference must use the same source bytes.")
    if not isinstance(run.get("timed_out"), bool):
        raise ValueError("Benchmark attempt requires a boolean timed_out.")
    exit_code = run.get("exit_code")
    if not run["timed_out"] and type(exit_code) is not int:
        raise ValueError("Completed benchmark attempt requires an integer exit_code.")
    result = {
        "reference": reference["id"], "model": run["model"], "transport": run["transport"],
        "reference_review": reference["review"], "unresolved": reference["unresolved"],
        "status": "timeout" if run["timed_out"] else "execution_error",
    }
    if run["timed_out"] or exit_code != 0:
        return result
    payload = run.get("payload")
    errors = list(jsonschema.Draft202012Validator(
        EXTRACTION_SCHEMA, format_checker=jsonschema.FormatChecker(),
    ).iter_errors(payload))
    if errors:
        return result | {"status": "schema_invalid", "schema_error_paths": [
            "/".join(map(str, error.absolute_path)) or "<root>" for error in errors
        ]}
    expected = reference["expected"]
    scores = {}
    for field in ("effective_start", "effective_end", "schedule_basis"):
        if field in expected:
            scores[field] = {"expected": expected[field], "actual": payload.get(field),
                             "match": expected[field] == payload.get(field)}
    if "as_of" in reference:
        expected_status = benchmark_window_status(expected, reference["as_of"])
        actual_status = benchmark_window_status(payload, reference["as_of"])
        scores["window_status"] = {
            "as_of": reference["as_of"], "expected": expected_status,
            "actual": actual_status, "match": expected_status == actual_status,
        }
    fields_by_rows = {
        "sessions": ("day", "type", "start", "end", "pool"),
        "closures": ("start", "end", "start_time", "end_time"),
    }
    for field, row_fields in fields_by_rows.items():
        if field in expected:
            scores[field] = _benchmark_row_score(expected[field], payload[field], row_fields)
    return result | {
        "status": "scored", "scores": scores,
        "unscored_fields": sorted(set(fields_by_rows) - expected.keys()),
        "checked_fields_match": all(
            score.get("match", not score.get("extra") and not score.get("missing"))
            for score in scores.values()
        ),
    }


def benchmark_window_status(payload: dict, as_of: str) -> str:
    """Classify extracted dates, not whether the facility itself is open."""
    today = date.fromisoformat(as_of)
    if date.fromisoformat(payload["effective_start"]) > today:
        return "future"
    end = payload.get("effective_end")
    if end is None:
        return "unknown_end"
    return "expired" if date.fromisoformat(end) < today else "within_window"


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


def _diff_payloads(truth: dict, extracted: dict, sample_n: int = 3) -> tuple[set[RowKey], set[RowKey], int, list[dict], list[dict]]:
    truth_keys = {RowKey.from_session(s) for s in truth.get("sessions", [])}
    extracted_sessions = extracted.get("sessions", [])
    extracted_keys = {RowKey.from_session(s) for s in extracted_sessions}

    extras = extracted_keys - truth_keys
    missings = truth_keys - extracted_keys
    # Count from key sets, not row counts: duplicate session keys in truth
    # would otherwise inflate true positives.
    tp = len(truth_keys & extracted_keys)

    extra_samples = []
    for s in extracted_sessions:
        if RowKey.from_session(s) in extras and len(extra_samples) < sample_n:
            extra_samples.append({
                "day": s.get("day"), "type": s.get("type"),
                "start": s.get("start"), "end": s.get("end"),
                "pool": s.get("pool", ""),
                "evidence": s.get("evidence", "")[:120],
            })
    missing_samples = []
    for s in truth.get("sessions", []):
        if RowKey.from_session(s) in missings and len(missing_samples) < sample_n:
            missing_samples.append({
                "day": s.get("day"), "type": s.get("type"),
                "start": s.get("start"), "end": s.get("end"),
                "pool": s.get("pool", ""),
                "evidence": s.get("evidence", "")[:120],
            })

    return extras, missings, tp, extra_samples, missing_samples


def _load_envelope(path: Path) -> dict | None:
    try:
        envelope = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return envelope if isinstance(envelope, dict) else None


def _is_ci_attestation(envelope: dict) -> bool:
    kind = parse_attestation(envelope)
    return isinstance(kind.origin if isinstance(kind, AttestationCarried) else kind, AttestationCi)


def _is_human_or_omitted(envelope: dict) -> bool:
    kind = parse_attestation(envelope)
    if isinstance(kind, AttestationCarried):
        return not isinstance(kind.origin, AttestationCi)
    return not isinstance(kind, AttestationCi)


def _evals_for_dir(
    *,
    pool: str,
    review_dir: Path,
    truth: dict,
    table: str,
) -> list[PoolEval]:
    results: list[PoolEval] = []
    for art_path in sorted(review_dir.glob("*.json")):
        if art_path.name == "reviewed.json":
            continue
        try:
            art = json.loads(art_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        extracted = art.get("payload") or {}
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
                false_positives=len(extras),
                false_negatives=len(missings),
                extra_examples=extra_ex,
                missing_examples=missing_ex,
                table=table,
            )
        )
    return results


def collect_pool_evals(*, data_root: Path = DATA_DIR, all_dirs: bool = False) -> list[PoolEval]:
    """Walk data/ and emit one PoolEval per (review_dir, provider artifact).

    Quality rows use same-dir truth only when ``attested_by`` is ``human`` or
    omitted, including carries of those origins. A latest CI dir is
    never same-dir truth; look back for a human/omitted envelope and emit a
    seasonal-delta row against the latest provider JSON. Never score CI vs CI.
    """
    results: list[PoolEval] = []
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
            if _is_ci_attestation(envelope):
                continue
            truth = envelope.get("payload") or {}
            results.extend(
                _evals_for_dir(
                    pool=pool_dir.name,
                    review_dir=review_dir,
                    truth=truth,
                    table="quality",
                )
            )

        latest_dir, latest_env = envelopes[-1]
        if _is_ci_attestation(latest_env):
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
                    )
                )
    return results


def render_report(evals: Iterable[PoolEval]) -> str:
    evals = list(evals)
    quality = [item for item in evals if item.table != "seasonal_delta"]
    seasonal = [item for item in evals if item.table == "seasonal_delta"]
    if not quality and not seasonal:
        return "# Schedule extraction eval\n\nNo (review_dir, provider) pairs found.\n"

    lines: list[str] = []
    lines.append("# Schedule extraction eval")
    lines.append("")
    lines.append(f"_Generated {datetime.now(PACIFIC_TZ).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append("Quality baseline diffs each provider artifact against a human or omitted")
    lines.append("`attested_by` envelope in the same review dir. CI-attested dirs are not")
    lines.append("same-dir truth. Row identity is `(day, type, start, end, pool)`.")
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
    lines.append("| Pool | Artifact | Truth | Extr | TP | FP | FN | P | R | F1 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for e in sorted(quality, key=lambda x: (x.pool, x.provider)):
        lines.append(
            f"| {e.pool} | {e.provider_artifact} | {e.truth_count} | {e.extracted_count} | "
            f"{e.true_positives} | {e.false_positives} | {e.false_negatives} | "
            f"{e.precision:.0%} | {e.recall:.0%} | {e.f1:.2f} |"
        )
    lines.append("")

    if seasonal:
        lines.append("## Seasonal delta (not quality baseline)")
        lines.append("")
        lines.append("Latest CI provider JSON vs an older human/omitted envelope.")
        lines.append("Seasonal change, not model regression. Not in the quality aggregate.")
        lines.append("")
        lines.append("| Pool | Artifact | Truth | Extr | TP | FP | FN | P | R | F1 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for e in sorted(seasonal, key=lambda x: (x.pool, x.provider)):
            lines.append(
                f"| {e.pool} | {e.provider_artifact} | {e.truth_count} | {e.extracted_count} | "
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
                lines.append(f"- {ex['day']} {ex['type']} {ex['start']}-{ex['end']}  `{ex['evidence']}`")
        if e.missing_examples:
            lines.append("**Missing (in truth but not extracted):**")
            for ex in e.missing_examples:
                lines.append(f"- {ex['day']} {ex['type']} {ex['start']}-{ex['end']}  `{ex['evidence']}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_report(evals: Iterable[PoolEval], *, tmp_dir: Path = TMP_DIR) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(PACIFIC_TZ).strftime("%Y%m%dT%H%M%S")
    path = tmp_dir / f"eval-{timestamp}.md"
    path.write_text(render_report(evals))
    return path
