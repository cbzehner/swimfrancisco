"""Render a PR body for auto-extract runs.

Designed for a human reviewer landing on a freshly-opened PR cold. Leads
with the action ("X needs a human review"), then a short list of what
artifacts changed, then a 5-step checklist with rough time estimate.
The eval baseline is collapsed; reviewers who care about the F1 number
can expand it. Inputs come from ``git diff --staged`` and the registry,
so the workflow's plumbing is just "git add data/" → run this command.
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
_REVIEW_MIN_PER_POOL = 10


def _staged_data_changes(repo_root: Path = REPO_ROOT) -> list[tuple[str, str, str, str]]:
    """Return staged changes under ``data/`` as ``(slug, run, filename, change)`` tuples."""
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
        change = parts[0][0]  # A/M/D
        path = parts[-1]
        m = _DATA_PATH_RE.match(path)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3), change))
    return rows


def _changed_slugs_with_runs(rows: list[tuple[str, str, str, str]]) -> dict[str, dict[str, list[tuple[str, str]]]]:
    out: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for slug, run, filename, change in rows:
        out.setdefault(slug, {}).setdefault(run, []).append((filename, change))
    return out


def _change_word(change: str) -> str:
    return {"A": "new", "M": "updated", "D": "deleted"}.get(change, "changed")


def _provider_word(filename: str) -> str:
    if filename.startswith("anthropic"):
        return "Anthropic"
    if filename.startswith("gemini"):
        return "Gemini"
    return filename.split("-", 1)[0].capitalize()


def _slug_list(slugs: list[str]) -> str:
    if not slugs:
        return ""
    if len(slugs) == 1:
        return f"`{slugs[0]}`"
    if len(slugs) == 2:
        return f"`{slugs[0]}` and `{slugs[1]}`"
    return ", ".join(f"`{s}`" for s in slugs[:-1]) + f", and `{slugs[-1]}`"


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
    published = [e for e in registry if e.source_status == "published"]

    if not changed:
        return (
            "Nothing to review. Auto-extract found no diffs against `main` "
            "(every published pool's PDF, prompt, and schema sha matched the "
            "cached artifact). Close this PR.\n"
        )

    changed_slugs = sorted(s for s in changed if any(e.slug == s for e in registry))
    unchanged_n = len(published) - len(changed_slugs)
    branch = f"auto/schedules-extract-{today.isoformat()}"

    lines: list[str] = []
    lines.extend(_render_lead(changed, changed_slugs, unchanged_n))
    lines.extend(_render_whats_here(changed))
    lines.extend(_render_review(branch, changed_slugs))
    lines.extend(_render_eval_section(data_root=data_root, changed_slugs=set(changed_slugs)))

    return "\n".join(lines).rstrip() + "\n"


def _render_lead(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    changed_slugs: list[str],
    unchanged_n: int,
) -> list[str]:
    if len(changed_slugs) == 1:
        slug = changed_slugs[0]
        action = (
            f"`{slug}` needs a human review. "
            "The published page is running on an unverified projection until that happens."
        )
    else:
        action = (
            f"{_slug_list(changed_slugs)} need human review this week. "
            "Their published pages run on unverified projections until that happens."
        )

    files = [
        (filename, change)
        for runs in changed.values()
        for files in runs.values()
        for filename, change in files
    ]
    new_files = [f for f, c in files if c == "A"]
    updated_files = [f for f, c in files if c == "M"]

    seed_phrases = []
    if new_files:
        providers = sorted({_provider_word(f) for f in new_files})
        seed_phrases.append(f"seeded fresh {', '.join(providers)} JSON")
    if updated_files:
        providers = sorted({_provider_word(f) for f in updated_files})
        seed_phrases.append(f"refreshed {', '.join(providers)} JSON")
    seed = " and ".join(seed_phrases) if seed_phrases else "wrote provider artifacts"

    if unchanged_n == 1:
        tail = "; the other published pool cache-hit, nothing else changed."
    elif unchanged_n > 1:
        tail = f"; the other {unchanged_n} published pools cache-hit, nothing else changed."
    else:
        tail = "."

    return [f"{action} Auto-extract {seed} to start from{tail}", ""]


def _render_whats_here(changed: dict[str, dict[str, list[tuple[str, str]]]]) -> list[str]:
    lines = ["## What's here", ""]
    for slug in sorted(changed):
        for run in sorted(changed[slug]):
            for filename, change in sorted(changed[slug][run]):
                provider = _provider_word(filename)
                state = _change_word(change)
                lines.append(
                    f"`data/{slug}/{run}/{filename}` — {state} {provider} extraction."
                )
    lines.append("")
    return lines


def _render_review(branch: str, changed_slugs: list[str]) -> list[str]:
    minutes = max(_REVIEW_MIN_PER_POOL, len(changed_slugs) * _REVIEW_MIN_PER_POOL)
    if len(changed_slugs) == 1:
        slug = changed_slugs[0]
        review_step = (
            f"`just schedules-review --slug {slug}` — opens the PDF and a seeded JSON in `$EDITOR`"
        )
    else:
        first = changed_slugs[0]
        review_step = (
            f"For each pool, `just schedules-review --slug <slug>` — opens its PDF and a seeded JSON in `$EDITOR` "
            f"(start with `{first}`)"
        )

    return [
        f"## Review (~{minutes} min)",
        "",
        f"- [ ] `git fetch origin && git checkout {branch}`",
        f"- [ ] {review_step}",
        "- [ ] Read each session row against the PDF cell it claims to come from. Drop invented or misclassified rows, fix wrong days/times, leave correct rows alone.",
        "- [ ] Save and quit. The CLI projects the verified payload into `content/spots/<slug>.md`.",
        "- [ ] Commit `reviewed.json` and the projected MD, push, merge.",
        "",
        "Skip this week → close the PR. Next Monday will produce another.",
        "",
    ]


def _eval_aggregate_row(provider: str, items: list[PoolEval]) -> str:
    tp = sum(i.true_positives for i in items)
    fp = sum(i.false_positives for i in items)
    fn = sum(i.false_negatives for i in items)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return f"| {provider} | {f1:.2f} |"


def _render_eval_section(*, data_root: Path, changed_slugs: set[str]) -> list[str]:
    evals = collect_pool_evals(data_root=data_root)
    if not evals:
        return []

    by_provider: dict[str, list[PoolEval]] = {}
    for e in evals:
        by_provider.setdefault(e.provider, []).append(e)

    relevant = [e for e in evals if e.pool in changed_slugs]

    if relevant:
        summary = "Eval baseline (changed pools detailed below)"
    else:
        summary = "Eval baseline (changed pools excluded — that's the point of this PR)"

    lines = [f"<details><summary>{summary}</summary>", ""]

    distinct_pools = len({e.pool for e in evals})
    lines.append(f"| Provider | F1 across {distinct_pools} reviewed pools |")
    lines.append("|---|---:|")
    for provider in sorted(by_provider):
        lines.append(_eval_aggregate_row(provider, by_provider[provider]))
    lines.append("")
    lines.append(
        "Per-codebase F1 on `(day, type, start, end)` row identity. "
        "Run `just schedules-eval --stdout` for the full per-pool breakdown."
    )
    lines.append("")

    if relevant:
        lines.append("**Changed pools, per artifact:**")
        lines.append("")
        lines.append("| Pool | Artifact | Truth | Extracted | F1 |")
        lines.append("|---|---|---:|---:|---:|")
        for e in sorted(relevant, key=lambda x: (x.pool, x.provider)):
            lines.append(
                f"| {e.pool} | {e.provider_artifact} | {e.truth_count} | {e.extracted_count} | {e.f1:.2f} |"
            )
        lines.append("")
        for e in sorted(relevant, key=lambda x: (x.pool, x.provider)):
            if not (e.extra_examples or e.missing_examples):
                continue
            lines.append(f"_{e.pool} — {e.provider_artifact}:_")
            if e.extra_examples:
                lines.append("- Extra (extracted but not in truth):")
                for ex in e.extra_examples:
                    lines.append(f"  - {ex['day']} {ex['type']} {ex['start']}-{ex['end']}  `{ex['evidence']}`")
            if e.missing_examples:
                lines.append("- Missing (in truth but not extracted):")
                for ex in e.missing_examples:
                    lines.append(f"  - {ex['day']} {ex['type']} {ex['start']}-{ex['end']}  `{ex['evidence']}`")
            lines.append("")

    lines.append("</details>")
    lines.append("")
    return lines
