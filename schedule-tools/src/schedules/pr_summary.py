"""Render a PR body for auto-extract runs.

Designed for a human reviewer landing on a freshly-opened PR cold. Leads
with the action ("X needs a human review"), then a short list of what
artifacts changed, then a 5-step checklist with rough time estimate.
The eval baseline is collapsed; reviewers who care about the F1 number
can expand it. Inputs come from ``git diff --staged`` (data/ and
registry.toml) plus ``tmp/discovery-decisions.json`` when present.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date as _date
from pathlib import Path

from ._time import pacific_today
from .discover import view_id_from_url
from .eval import PoolEval, collect_pool_evals, prf1
from .paths import DATA_DIR, REPO_ROOT
from .registry import load_registry


_DATA_PATH_RE = re.compile(r"^data/([a-z0-9-]+)/([0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{12})/(.+)$")
_REVIEW_MIN_PER_POOL = 10
_REGISTRY_REL = "schedule-tools/src/schedules/registry.toml"
_LIVE_SITE_UNTIL_MERGE = (
    "The live site stays on the last reviewed window until this PR merges."
)
_DAILY_REFRESH = (
    "Daily extract will refresh this PR; closing it without merging will "
    "reopen on the next run that still sees a diff against `main`."
)


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


def staged_data_has_meaningful_changes(repo_root: Path = REPO_ROOT) -> bool:
    """Return true when staged data changes should open a review PR.

    Provider JSON can churn when a deterministic direct extractor refreshes
    `extracted_at` and rolls `payload.effective_start` forward even though the
    modeled schedule did not change. Those diffs do not need a PR. Everything
    else stays conservative: added/deleted files, source files, unparseable JSON,
    and semantic payload changes all count as meaningful.
    """
    for change, path in _staged_name_status(repo_root):
        if change != "M":
            return True
        if not path.endswith(".json"):
            return True
        if not _staged_json_change_is_metadata_only(repo_root, path):
            return True
    return False


def _staged_name_status(repo_root: Path) -> list[tuple[str, str]]:
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

    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rows.append((parts[0][0], parts[-1]))
    return rows


def _staged_json_change_is_metadata_only(repo_root: Path, path: str) -> bool:
    before = _git_blob(repo_root, f"HEAD:{path}")
    after = _git_blob(repo_root, f":{path}")
    if before is None or after is None:
        return False
    try:
        before_json = json.loads(before)
        after_json = json.loads(after)
    except json.JSONDecodeError:
        return False
    return _semantic_provider_json(before_json) == _semantic_provider_json(after_json)


def _git_blob(repo_root: Path, ref: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "show", ref],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _semantic_provider_json(value: object) -> object:
    if not isinstance(value, dict):
        return value
    cleaned = dict(value)
    cleaned.pop("extracted_at", None)
    payload = cleaned.get("payload")
    if isinstance(payload, dict):
        cleaned["payload"] = {
            key: val
            for key, val in payload.items()
            if key != "effective_start"
        }
    return cleaned


def _changed_slugs_with_runs(rows: list[tuple[str, str, str, str]]) -> dict[str, dict[str, list[tuple[str, str]]]]:
    out: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for slug, run, filename, change in rows:
        out.setdefault(slug, {}).setdefault(run, []).append((filename, change))
    return out


def _change_word(change: str) -> str:
    return {"A": "new", "M": "updated", "D": "deleted"}.get(change, "changed")


def _provider_word(filename: str) -> str:
    return filename.split("-", 1)[0].capitalize()


def _slug_list(slugs: list[str]) -> str:
    if not slugs:
        return ""
    if len(slugs) == 1:
        return f"`{slugs[0]}`"
    if len(slugs) == 2:
        return f"`{slugs[0]}` and `{slugs[1]}`"
    return ", ".join(f"`{s}`" for s in slugs[:-1]) + f", and `{slugs[-1]}`"


def _registry_is_staged(repo_root: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "diff", "--staged", "--name-only", "--", _REGISTRY_REL],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return any(line.strip().endswith("registry.toml") for line in out.splitlines())


def _load_discovery_decisions(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        item
        for item in payload
        if isinstance(item, dict) and isinstance(item.get("slug"), str) and item["slug"]
    ]


def _all_candidates(decision: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for bucket in ("candidates", "extra_candidates"):
        for item in decision.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            view_id = item.get("view_id")
            if not isinstance(view_id, int) or view_id in seen:
                continue
            seen.add(view_id)
            rows.append(item)
    return rows


def _is_off_table(candidate: dict) -> bool:
    return candidate.get("source") in {"band", "persisted"}


def _kind_label(decision: dict) -> str:
    reason = str(decision.get("reason") or "")
    kind = str(decision.get("kind") or "")
    if reason == "multiple_windows":
        return "multiple_windows"
    if reason in {"band_session_grid", "band_flag"}:
        return "band_flag"
    if reason == "split_part" or kind == "split_part":
        return "split_pdfs"
    if reason == "closure_notice" or kind == "closure_notice":
        return "closure_notice"
    if kind:
        return kind
    if reason:
        return reason
    return "session_grid"


def _id_and_name(candidate: dict) -> str:
    view_id = candidate.get("view_id")
    name = candidate.get("filename")
    if isinstance(name, str) and name.strip():
        return f"{view_id} `{name.strip()}`"
    return str(view_id)


def _preferred_filename(decision: dict, view_id: int | None) -> str | None:
    if view_id is None:
        return None
    for candidate in _all_candidates(decision):
        if candidate.get("view_id") != view_id:
            continue
        name = candidate.get("filename")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _window_from_run(run_dir: Path) -> tuple[str | None, str | None]:
    if not run_dir.is_dir():
        return None, None
    paths = sorted(p for p in run_dir.glob("*.json") if p.name != "reviewed.json")
    reviewed = run_dir / "reviewed.json"
    if reviewed.is_file():
        paths.append(reviewed)
    for path in paths:
        try:
            envelope = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            continue
        start = payload.get("effective_start")
        end = payload.get("effective_end")
        start_s = start if isinstance(start, str) and start else None
        end_s = end if isinstance(end, str) and end else None
        if start_s or end_s:
            return start_s, end_s
    return None, None


def _windows_from_artifacts(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    data_root: Path,
) -> dict[str, tuple[str | None, str | None]]:
    windows: dict[str, tuple[str | None, str | None]] = {}
    for slug, runs in changed.items():
        for run in sorted(runs, reverse=True):
            window = _window_from_run(data_root / slug / run)
            if window != (None, None):
                windows[slug] = window
                break
    return windows


def _format_decision_line(
    decision: dict,
    window: tuple[str | None, str | None] | None,
) -> str:
    slug = decision["slug"]
    kind = _kind_label(decision)
    old_id = view_id_from_url(str(decision.get("old_url") or ""))
    new_id = view_id_from_url(str(decision.get("new_url") or ""))
    candidates = _all_candidates(decision)
    off_table = [item for item in candidates if _is_off_table(item)]
    table_flyers = [
        item
        for item in candidates
        if item.get("source") == "table" and item.get("kind") == "closure_notice"
    ]
    off_grids = [item for item in off_table if item.get("kind") == "session_grid"]
    grid_ids = [item for item in candidates if item.get("kind") == "session_grid"]

    bits: list[str] = []
    mentioned: set[int] = set()
    action = decision.get("action")
    if action == "adopt" and old_id is not None and new_id is not None and old_id != new_id:
        bits.append(f"{old_id} → {new_id}")
    elif old_id is not None:
        bits.append(f"{old_id} unchanged")

    def _mark(items: list[dict]) -> None:
        for item in items:
            view_id = item.get("view_id")
            if isinstance(view_id, int):
                mentioned.add(view_id)

    if table_flyers and off_grids:
        flyer = ", ".join(_id_and_name(item) for item in table_flyers)
        flagged = ", ".join(_id_and_name(item) for item in off_grids)
        bits.append(f"flyer {flyer}")
        bits.append(f"band-flagged {flagged}")
        _mark(table_flyers)
        _mark(off_grids)
    elif kind == "multiple_windows" and grid_ids:
        labeled: list[str] = []
        for item in grid_ids:
            where = "off-table" if _is_off_table(item) else "table"
            labeled.append(f"{where} {_id_and_name(item)}")
        bits.append(f"multiple_windows {' + '.join(labeled)}")
        _mark(grid_ids)
    else:
        filename = _preferred_filename(decision, new_id or old_id)
        if filename:
            bits.append(f"`{filename}`")
        bits.append(kind)
        if off_table:
            bits.append("off-table " + ", ".join(_id_and_name(item) for item in off_table))
            _mark(off_table)

    extra_ids = {
        extra.get("view_id")
        for extra in (decision.get("extra_candidates") or [])
        if isinstance(extra, dict) and extra.get("kind") != "session_grid"
    }
    leftover_extra = [
        item
        for item in candidates
        if item.get("view_id") in extra_ids and item.get("view_id") not in mentioned
    ]
    if leftover_extra:
        bits.append("extra " + ", ".join(_id_and_name(item) for item in leftover_extra))

    if window and (window[0] or window[1]):
        start, end = window
        if start and end:
            bits.append(f"{start}–{end}")
        elif start:
            bits.append(start)
        elif end:
            bits.append(end)

    return f"- `{slug}`: " + "; ".join(bits)


def _lead_pool_lines(
    pending_slugs: list[str],
    decisions: list[dict],
    windows: dict[str, tuple[str | None, str | None]],
) -> list[str]:
    by_slug = {item["slug"]: item for item in decisions}
    slugs: list[str] = []
    seen: set[str] = set()
    for item in decisions:
        slug = item["slug"]
        if slug in seen:
            continue
        if (
            item.get("blocking")
            or item.get("action") == "adopt"
            or any(_is_off_table(candidate) for candidate in _all_candidates(item))
            or slug in pending_slugs
        ):
            seen.add(slug)
            slugs.append(slug)
    for slug in pending_slugs:
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    lines: list[str] = []
    for slug in slugs:
        decision = by_slug.get(slug)
        if decision is not None:
            lines.append(_format_decision_line(decision, windows.get(slug)))
        else:
            lines.append(f"- `{slug}`: payload changed, needs review")
    return lines


def render_pr_body(
    *,
    repo_root: Path = REPO_ROOT,
    data_root: Path = DATA_DIR,
    today: _date | None = None,
) -> str:
    today = today or pacific_today()
    rows = _staged_data_changes(repo_root)
    changed = _changed_slugs_with_runs(rows)
    registry = load_registry()
    published = [e for e in registry if e.source_status == "published"]
    decisions = _load_discovery_decisions(repo_root / "tmp" / "discovery-decisions.json")
    registry_staged = _registry_is_staged(repo_root)
    blocking_slugs = sorted(
        {item["slug"] for item in decisions if item.get("blocking")}
    )
    adopt_slugs = [item["slug"] for item in decisions if item.get("action") == "adopt"]

    if not changed and not registry_staged and not blocking_slugs and not adopt_slugs:
        return (
            "Nothing to review. Auto-extract found no diffs against `main` "
            "(every published pool's PDF, prompt, and schema sha matched the "
            "cached artifact). Close this PR.\n"
        )

    changed_slugs = sorted(s for s in changed if any(e.slug == s for e in registry))
    pending_slugs = sorted(s for s in changed_slugs if _has_pending_run(s, changed[s], data_root))
    carried_slugs = [s for s in changed_slugs if s not in pending_slugs]
    unchanged_n = len(published) - len(changed_slugs)
    windows = _windows_from_artifacts(changed, data_root)
    branch = "auto/schedules-extract"
    review_slugs = sorted(set(pending_slugs) | set(blocking_slugs))

    lines: list[str] = []
    lines.extend(
        _render_lead(
            changed,
            pending_slugs,
            carried_slugs,
            unchanged_n,
            decisions=decisions,
            windows=windows,
            registry_staged=registry_staged,
            review_slugs=review_slugs,
        )
    )
    lines.extend(_render_whats_here(changed, registry_staged=registry_staged))
    lines.extend(_render_review(branch, review_slugs))
    lines.extend(_render_eval_section(data_root=data_root, changed_artifacts=_changed_provider_artifacts(rows)))

    return "\n".join(lines).rstrip() + "\n"


def _has_pending_run(slug: str, runs: dict[str, list[tuple[str, str]]], data_root: Path) -> bool:
    """A slug still needs review when any of its changed run dirs lacks reviewed.json."""
    return any(not (data_root / slug / run / "reviewed.json").exists() for run in runs)


def _render_lead(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    pending_slugs: list[str],
    carried_slugs: list[str],
    unchanged_n: int,
    *,
    decisions: list[dict] | None = None,
    windows: dict[str, tuple[str | None, str | None]] | None = None,
    registry_staged: bool = False,
    review_slugs: list[str] | None = None,
) -> list[str]:
    decisions = decisions or []
    windows = windows or {}
    review_slugs = pending_slugs if review_slugs is None else review_slugs
    minutes = len(review_slugs) * _REVIEW_MIN_PER_POOL
    if not review_slugs:
        action = (
            "No human review needed. Every changed pool extracted a payload "
            "identical to its last human-reviewed one, so the attestation was "
            "carried forward; this PR auto-merges once checks pass."
        )
    elif len(review_slugs) == 1:
        action = (
            f"`{review_slugs[0]}` needs a human review (~{minutes} min). "
            f"{_LIVE_SITE_UNTIL_MERGE}"
        )
    else:
        rec_park = [item["slug"] for item in decisions if item["slug"] in review_slugs]
        if rec_park and set(rec_park) == set(review_slugs):
            action = (
                f"{len(review_slugs)} Rec & Park pools need human review "
                f"(~{minutes} min). {_LIVE_SITE_UNTIL_MERGE}"
            )
        else:
            action = (
                f"{_slug_list(review_slugs)} need human review (~{minutes} min). "
                f"{_LIVE_SITE_UNTIL_MERGE}"
            )
    if review_slugs and carried_slugs:
        action += (
            f" {_slug_list(carried_slugs)} auto-verified: extraction matched "
            "the last human-reviewed payload, so the attestation carried forward."
        )

    files = [
        (filename, change)
        for runs in changed.values()
        for files in runs.values()
        for filename, change in files
        if filename != "reviewed.json"
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
    if registry_staged:
        seed_phrases.append("updated Rec & Park registry pins or discover notes")
    seed = " and ".join(seed_phrases) if seed_phrases else "wrote provider artifacts"

    if unchanged_n == 1:
        tail = "; the other published pool cache-hit, nothing else changed."
    elif unchanged_n > 1:
        tail = f"; the other {unchanged_n} published pools cache-hit, nothing else changed."
    else:
        tail = "."

    lines = [f"{action} Auto-extract {seed} to start from{tail}", ""]
    pool_lines = _lead_pool_lines(pending_slugs, decisions, windows)
    if pool_lines:
        lines.extend(pool_lines)
        lines.append("")
    return lines


def _render_whats_here(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    *,
    registry_staged: bool = False,
) -> list[str]:
    if not changed and not registry_staged:
        return []
    lines = ["## What's here", ""]
    if registry_staged:
        lines.append(
            f"`{_REGISTRY_REL}` — Rec & Park `pdf_url` and discover notes."
        )
    for slug in sorted(changed):
        for run in sorted(changed[slug]):
            for filename, change in sorted(changed[slug][run]):
                if filename == "reviewed.json":
                    lines.append(
                        f"`data/{slug}/{run}/{filename}` — attestation carried forward."
                    )
                    continue
                provider = _provider_word(filename)
                state = _change_word(change)
                lines.append(
                    f"`data/{slug}/{run}/{filename}` — {state} {provider} extraction."
                )
    lines.append("")
    return lines


def _render_review(branch: str, review_slugs: list[str]) -> list[str]:
    if not review_slugs:
        return []
    minutes = max(_REVIEW_MIN_PER_POOL, len(review_slugs) * _REVIEW_MIN_PER_POOL)

    return [
        f"## Review (~{minutes} min)",
        "",
        f"- [ ] git fetch origin && git checkout {branch}",
        "- [ ] just schedules-review  (work the queue)",
        "- [ ] just release           (bulletin only if reviewed payloads changed)",
        "- [ ] commit content/spots, data, registry.toml",
        "- [ ] merge this PR; do not open a second one",
        "",
        _DAILY_REFRESH,
        "",
    ]


def _eval_aggregate_row(provider: str, items: list[PoolEval]) -> str:
    tp = sum(i.true_positives for i in items)
    fp = sum(i.false_positives for i in items)
    fn = sum(i.false_negatives for i in items)
    _, _, f1 = prf1(tp, fp, fn)
    return f"| {provider} | {f1:.2f} |"


def _changed_provider_artifacts(
    rows: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str]]:
    return [
        (slug, run, filename)
        for slug, run, filename, _change in rows
        if filename != "reviewed.json" and filename.endswith(".json")
    ]


def _render_eval_section(
    *,
    data_root: Path,
    changed_artifacts: list[tuple[str, str, str]],
) -> list[str]:
    historical_evals = collect_pool_evals(data_root=data_root)
    changed_evals = collect_pool_evals(data_root=data_root, all_dirs=True)

    lines = _render_changed_artifacts(changed_artifacts, changed_evals)
    if not historical_evals:
        return lines

    by_provider: dict[str, list[PoolEval]] = {}
    for e in historical_evals:
        by_provider.setdefault(e.provider, []).append(e)

    lines.extend([
        "<details><summary>Historical reviewed baseline</summary>",
        "",
        "This is the aggregate from committed reviewed artifacts, not a score "
        "for unreviewed changed artifacts.",
        "",
    ])

    distinct_pools = len({e.pool for e in historical_evals})
    lines.append(f"| Provider | F1 across {distinct_pools} reviewed pools |")
    lines.append("|---|---:|")
    for provider in sorted(by_provider):
        lines.append(_eval_aggregate_row(provider, by_provider[provider]))
    lines.append("")
    lines.append(
        "Per-codebase F1 on `(day, type, start, end, pool)` row identity. "
        "Run `just schedules-eval --stdout` for the full per-pool breakdown."
    )
    lines.append("")

    lines.append("</details>")
    lines.append("")
    return lines


def _render_changed_artifacts(
    changed_artifacts: list[tuple[str, str, str]],
    evaluations: list[PoolEval],
) -> list[str]:
    if not changed_artifacts:
        return []

    evaluations_by_identity = {
        (evaluation.pool, evaluation.review_dir.name, evaluation.provider_artifact): evaluation
        for evaluation in evaluations
    }
    lines = [
        "## Changed artifacts",
        "",
        "| Artifact | Evaluation | Truth | Extracted | F1 |",
        "|---|---|---:|---:|---:|",
    ]
    disagreements: list[tuple[str, PoolEval]] = []
    for slug, run, filename in sorted(changed_artifacts):
        path = f"data/{slug}/{run}/{filename}"
        evaluation = evaluations_by_identity.get((slug, run, filename))
        if evaluation is None:
            lines.append(f"| `{path}` | unscored — human review required | | | |")
            continue
        lines.append(
            f"| `{path}` | scored | {evaluation.truth_count} | "
            f"{evaluation.extracted_count} | {evaluation.f1:.2f} |"
        )
        if evaluation.extra_examples or evaluation.missing_examples:
            disagreements.append((path, evaluation))
    lines.append("")
    for path, evaluation in disagreements:
        lines.append(f"_{path}:_")
        if evaluation.extra_examples:
            lines.append("- Extra (extracted but not in truth):")
            for example in evaluation.extra_examples:
                lines.append(
                    f"  - {example['day']} {example['type']} {example['start']}-{example['end']}  "
                    f"`{example['evidence']}`"
                )
        if evaluation.missing_examples:
            lines.append("- Missing (in truth but not extracted):")
            for example in evaluation.missing_examples:
                lines.append(
                    f"  - {example['day']} {example['type']} {example['start']}-{example['end']}  "
                    f"`{example['evidence']}`"
                )
    lines.append("")
    return lines
