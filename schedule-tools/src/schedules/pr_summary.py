"""Render a PR body optimized for human reviewers of auto-extract runs.

The verbose ``tmp/extraction-report.md`` is useful when running the pipeline
locally. For a GitHub PR, that level of detail buries the signal under
seven unchanged-pool blocks. This module produces a tight summary that:

  - Highlights pools whose artifact files actually changed in this run.
  - One-liners every other pool (unchanged or skipped) so the reviewer
    knows nothing was forgotten.
  - Appends the eval scorecard as-is (it's already concise).

Inputs are derived from the filesystem and ``git`` — no in-memory pipeline
results required, which keeps the workflow plumbing simple.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date as _date
from pathlib import Path

from .eval import PoolEval, collect_pool_evals
from .paths import DATA_DIR, REPO_ROOT
from .registry import load_registry


_DATA_PATH_RE = re.compile(r"^data/([a-z0-9-]+)/([0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{12})/(.+)$")


def _staged_data_changes(repo_root: Path = REPO_ROOT) -> list[tuple[str, str, str, str]]:
    """Return staged changes under ``data/`` as ``(slug, run, filename, change)`` tuples.

    ``change`` is one of: ``A`` (added), ``M`` (modified), ``D`` (deleted).
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--staged", "--name-status", "--", "data/"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    rows: list[tuple[str, str, str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        change = parts[0][0]  # A/M/D/...
        path = parts[-1]
        m = _DATA_PATH_RE.match(path)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3), change))
    return rows


def _changed_slugs_with_runs(rows: list[tuple[str, str, str, str]]) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """Group changes by slug → run → list of (filename, change-marker)."""
    out: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for slug, run, filename, change in rows:
        out.setdefault(slug, {}).setdefault(run, []).append((filename, change))
    return out


def _change_marker(change: str) -> str:
    return {"A": "🆕", "M": "✏️", "D": "🗑️"}.get(change, "•")


def _has_reviewed(slug: str, run: str, data_root: Path = DATA_DIR) -> bool:
    return (data_root / slug / run / "reviewed.json").exists()


def _render_changed_pool(slug: str, runs: dict[str, list[tuple[str, str]]], data_root: Path = DATA_DIR) -> list[str]:
    lines = [f"### `{slug}`"]
    for run, files in sorted(runs.items()):
        reviewed = _has_reviewed(slug, run, data_root)
        attestation = (
            "✅ has `reviewed.json` (human-verified)"
            if reviewed
            else "⚠️ **no `reviewed.json` — run `just schedules-review --slug "
            f"{slug}` to verify**"
        )
        lines.append(f"- run `{run}` — {attestation}")
        for filename, change in sorted(files):
            lines.append(f"  - {_change_marker(change)} `{filename}`")
    lines.append("")
    return lines


def render_pr_body(
    *,
    repo_root: Path = REPO_ROOT,
    data_root: Path = DATA_DIR,
    today: _date | None = None,
) -> str:
    today = today or _date.today()
    rows = _staged_data_changes(repo_root)
    changed = _changed_slugs_with_runs(rows)
    registry = load_registry()
    registry_slugs = {entry.slug for entry in registry}

    lines: list[str] = []
    lines.append(f"## Auto-extract {today.isoformat()}")
    lines.append("")
    lines.append("Opened by the weekly `schedules-extract` workflow. Provider artifacts under `data/`")
    lines.append("are regenerated when the cache misses (new PDF, prompt edit, schema edit, or no")
    lines.append("prior artifact). `content/spots/` and `reviewed.json` are never modified by the")
    lines.append("workflow — humans always review.")
    lines.append("")

    if changed:
        n_pools = len({s for s in changed.keys() if s in registry_slugs})
        n_files = sum(len(files) for runs in changed.values() for files in runs.values())
        lines.append(f"### Changed in this run — {n_pools} pool(s), {n_files} file(s)")
        lines.append("")
        for slug in sorted(changed.keys()):
            lines.extend(_render_changed_pool(slug, changed[slug], data_root))

    unchanged_published = sorted(
        e.slug for e in registry
        if e.source_status == "published" and e.slug not in changed
    )
    skipped = [e for e in registry if e.source_status != "published"]

    if unchanged_published:
        lines.append("### Unchanged (cache fresh, no diff)")
        lines.append("")
        lines.append(", ".join(f"`{slug}`" for slug in unchanged_published))
        lines.append("")

    if skipped:
        lines.append("### Skipped")
        lines.append("")
        for entry in skipped:
            note = entry.notes or "no published schedule"
            lines.append(f"- `{entry.slug}` — {note}")
        lines.append("")

    lines.append("### Reviewer next steps")
    lines.append("")
    if changed:
        first_changed = sorted(changed.keys())[0]
        lines.append(f"1. `git fetch origin && git checkout auto/schedules-extract-{today.isoformat()}`")
        lines.append(f"2. `just schedules-review --slug {first_changed}` (repeat per changed pool)")
        lines.append("3. Verify each row against the source PDF in `$EDITOR`; save `reviewed.json`.")
        lines.append("4. Commit `reviewed.json` and the auto-projected `content/spots/<slug>.md`, push, merge.")
    else:
        lines.append("Nothing changed — this PR is empty and can be closed.")
    lines.append("")

    lines.extend(_render_eval_section(data_root=data_root, changed_slugs=set(changed.keys())))

    return "\n".join(lines).rstrip() + "\n"


def _eval_aggregate_row(provider: str, items: list[PoolEval]) -> str:
    truth = sum(i.truth_count for i in items)
    extracted = sum(i.extracted_count for i in items)
    tp = sum(i.true_positives for i in items)
    fp = sum(i.false_positives for i in items)
    fn = sum(i.false_negatives for i in items)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return (
        f"| {provider} | {len(items)} | {truth} | {extracted} | {tp} | {fp} | {fn} | "
        f"{precision:.0%} | {recall:.0%} | {f1:.2f} |"
    )


def _render_eval_section(*, data_root: Path, changed_slugs: set[str]) -> list[str]:
    evals = collect_pool_evals(data_root=data_root)
    if not evals:
        return []

    lines = ["### Eval (vs current `reviewed.json` ground truth)", ""]

    by_provider: dict[str, list[PoolEval]] = {}
    for e in evals:
        by_provider.setdefault(e.provider, []).append(e)

    lines.append("| Provider | Pools | Truth | Extr | TP | FP | FN | P | R | F1 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for provider in sorted(by_provider):
        lines.append(_eval_aggregate_row(provider, by_provider[provider]))
    lines.append("")
    lines.append("<details><summary>Column definitions</summary>")
    lines.append("")
    lines.append("- **Pools** — number of (pool, review-dir) pairs the provider was scored against.")
    lines.append("- **Truth** — total session rows in the human-reviewed `reviewed.json` payloads.")
    lines.append("- **Extr** — total session rows the provider extracted.")
    lines.append("- **TP** (true positive) — extracted rows that match a truth row on `(day, type, start, end)`.")
    lines.append("- **FP** (false positive) — extracted rows the truth does not have. Precision-loss.")
    lines.append("- **FN** (false negative) — truth rows the provider missed. Recall-loss.")
    lines.append("- **P** — precision = TP / (TP + FP). Of what we emit, how much is correct.")
    lines.append("- **R** — recall = TP / (TP + FN). Of what truth has, how much we caught.")
    lines.append("- **F1** — harmonic mean of P and R: `2·P·R / (P+R)`. Single number for overall fit.")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    relevant = [e for e in evals if e.pool in changed_slugs]
    if not relevant:
        unchanged = sorted({e.pool for e in evals})
        lines.append(
            f"_No reviewed pools changed in this run; per-pool detail omitted "
            f"({len(unchanged)} pool(s) tracked: {', '.join(unchanged)})._"
        )
        lines.append("")
        return lines

    lines.append("**Per pool / artifact (changed only):**")
    lines.append("")
    lines.append("| Pool | Artifact | Truth | Extr | TP | FP | FN | P | R | F1 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for e in sorted(relevant, key=lambda x: (x.pool, x.provider)):
        lines.append(
            f"| {e.pool} | {e.provider_artifact} | {e.truth_count} | {e.extracted_count} | "
            f"{e.true_positives} | {e.false_positives} | {e.false_negatives} | "
            f"{e.precision:.0%} | {e.recall:.0%} | {e.f1:.2f} |"
        )
    lines.append("")

    for e in sorted(relevant, key=lambda x: (x.pool, x.provider)):
        if not (e.extra_examples or e.missing_examples):
            continue
        lines.append(f"**{e.pool} — {e.provider_artifact}:**")
        if e.extra_examples:
            lines.append("- Extra (extracted but not in truth):")
            for ex in e.extra_examples:
                lines.append(f"  - {ex['day']} {ex['type']} {ex['start']}-{ex['end']}  `{ex['evidence']}`")
        if e.missing_examples:
            lines.append("- Missing (in truth but not extracted):")
            for ex in e.missing_examples:
                lines.append(f"  - {ex['day']} {ex['type']} {ex['start']}-{ex['end']}  `{ex['evidence']}`")
        lines.append("")

    return lines
