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

from .paths import DATA_DIR, REPO_ROOT, TMP_DIR
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
    tmp_dir: Path = TMP_DIR,
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

    eval_path = tmp_dir / "eval.md"
    if eval_path.exists():
        eval_text = eval_path.read_text().strip()
        if eval_text:
            lines.append("### Eval (vs current `reviewed.json` ground truth)")
            lines.append("")
            lines.append(eval_text)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
