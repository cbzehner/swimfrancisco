"""Bakeoff-style eval that diffs provider extractions against human-reviewed
ground truth. Reads existing artifacts under ``data/<slug>/<date>-<sha>/``;
no API calls. Run via ``just schedules-eval``.

Trustworthy ground truth comes from ``reviewed.json`` files. Only review dirs
with a committed ``reviewed.json`` participate — this enforces the napkin's
contract that the human signed off on those payloads against the source PDF.
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

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _provider_stem_to_provider(stem: str) -> str:
    if stem.startswith("gemini"):
        return "gemini"
    if stem.startswith("anthropic"):
        return "anthropic"
    return stem.split("-", 1)[0]


def _diff_payloads(truth: dict, extracted: dict, sample_n: int = 3) -> tuple[set[RowKey], set[RowKey], list[dict], list[dict]]:
    truth_keys = {RowKey.from_session(s) for s in truth.get("sessions", [])}
    extracted_sessions = extracted.get("sessions", [])
    extracted_keys = {RowKey.from_session(s) for s in extracted_sessions}

    extras = extracted_keys - truth_keys
    missings = truth_keys - extracted_keys

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

    return extras, missings, extra_samples, missing_samples


def collect_pool_evals(*, data_root: Path = DATA_DIR, all_dirs: bool = False) -> list[PoolEval]:
    """Walk data/ and emit one PoolEval per (review_dir, provider artifact) where
    a reviewed.json exists.

    By default, only the latest review dir per pool is included — that is the
    snapshot in production. Pass ``all_dirs=True`` to include older review dirs
    as historical baselines.
    """
    results: list[PoolEval] = []
    if not data_root.is_dir():
        return results
    for pool_dir in sorted(data_root.iterdir()):
        if not pool_dir.is_dir():
            continue
        review_dirs = [d for d in sorted(pool_dir.iterdir()) if d.is_dir() and (d / "reviewed.json").exists()]
        if not review_dirs:
            continue
        if not all_dirs:
            review_dirs = review_dirs[-1:]
        for review_dir in review_dirs:
            reviewed_file = review_dir / "reviewed.json"
            try:
                truth = json.loads(reviewed_file.read_text()).get("payload", {})
            except (OSError, json.JSONDecodeError):
                continue
            for art_path in sorted(review_dir.glob("*.json")):
                if art_path.name == "reviewed.json":
                    continue
                try:
                    art = json.loads(art_path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                extracted = art.get("payload") or {}
                extras, missings, extra_ex, missing_ex = _diff_payloads(truth, extracted)
                truth_count = len(truth.get("sessions", []))
                extracted_count = len(extracted.get("sessions", []))
                tp = truth_count - len(missings)
                results.append(
                    PoolEval(
                        pool=pool_dir.name,
                        review_dir=review_dir,
                        provider_artifact=art_path.name,
                        provider=_provider_stem_to_provider(art_path.stem),
                        truth_count=truth_count,
                        extracted_count=extracted_count,
                        true_positives=tp,
                        false_positives=len(extras),
                        false_negatives=len(missings),
                        extra_examples=extra_ex,
                        missing_examples=missing_ex,
                    )
                )
    return results


def render_report(evals: Iterable[PoolEval]) -> str:
    evals = list(evals)
    if not evals:
        return "# Schedule extraction eval\n\nNo (review_dir, provider) pairs found.\n"

    lines: list[str] = []
    lines.append("# Schedule extraction eval")
    lines.append("")
    lines.append(f"_Generated {datetime.now(PACIFIC_TZ).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append("Diffs each provider artifact against the human-reviewed `reviewed.json`")
    lines.append("payload in the same review dir. Row identity is `(day, type, start, end, pool)`.")
    lines.append("")

    # Per-provider rollup
    by_provider: dict[str, list[PoolEval]] = {}
    for e in evals:
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
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        lines.append(
            f"| {provider} | {len(items)} | {truth} | {extracted} | {tp} | {fp} | {fn} | "
            f"{precision:.0%} | {recall:.0%} | {f1:.2f} |"
        )
    lines.append("")

    lines.append("## Per pool / artifact")
    lines.append("")
    lines.append("| Pool | Artifact | Truth | Extr | TP | FP | FN | P | R | F1 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for e in sorted(evals, key=lambda x: (x.pool, x.provider)):
        lines.append(
            f"| {e.pool} | {e.provider_artifact} | {e.truth_count} | {e.extracted_count} | "
            f"{e.true_positives} | {e.false_positives} | {e.false_negatives} | "
            f"{e.precision:.0%} | {e.recall:.0%} | {e.f1:.2f} |"
        )
    lines.append("")

    lines.append("## Disagreements (samples)")
    lines.append("")
    for e in sorted(evals, key=lambda x: (x.pool, x.provider)):
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
