"""Bakeoff-style eval that diffs provider extractions against attested truth.

Reads existing artifacts under ``data/<slug>/<date>-<sha>/``; no API calls.
Run via ``just schedules-eval``.

Quality baseline is human Save or omitted ``attested_by`` (legacy). CI-attested
dirs are not same-dir truth. A latest CI dir may appear in a seasonal-delta
table against an older human envelope; never score CI vs CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ._time import PACIFIC_TZ
from .paths import DATA_DIR, TMP_DIR


@dataclass(frozen=True)
class RowKey:
    day: str
    type: str
    start: str
    end: str
    pool: str

    @classmethod
    def from_session(cls, session: dict) -> "RowKey":
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
    return envelope.get("attested_by") == "ci" and not envelope.get("carried_from")


def _is_human_or_omitted(envelope: dict) -> bool:
    attested = envelope.get("attested_by")
    return attested != "ci"


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
    omitted, or when ``carried_from`` is set. A latest CI dir (no carry) is
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
