"""Render a PR body for auto-extract runs.

Leads with what published or was flagged (informational). Auto-merge PRs
do not include a ``just schedules-review`` checklist. That checklist is
debug-only when publish-pending did not succeed. Inputs come from
``git diff --staged`` (data/, registry.toml, content/spots/) plus
``tmp/discovery-decisions.json`` and ``tmp/publish-pending.json``.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date as _date
from pathlib import Path

from ._time import pacific_today
from .envelope import AttestationCarried, AttestationCi, parse_attestation
from .discover import view_id_from_url
from .eval import PoolEval, collect_pool_evals, prf1
from .paths import DATA_DIR, REPO_ROOT
from .registry import load_registry
from .review import DecisionSet, parse_view_id


_DATA_PATH_RE = re.compile(r"^data/([a-z0-9-]+)/([0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{12})/(.+)$")
_REVIEW_MIN_PER_POOL = 10
_REGISTRY_REL = "schedule-tools/src/schedules/registry.toml"
_LIVE_SITE_UPDATES = "The live site updates when this PR merges."
_DAILY_REFRESH = (
    "Daily extract will refresh this PR; closing it without merging will "
    "reopen on the next run that still sees a diff against `main`."
)
_AUTO_MERGE = "This PR auto-merges once checks pass."
_FLAGGED_ISSUE = "`schedules flagged`"
_SEQUENTIAL_REASONS = frozenset(
    {"sequential_windows", "overlapping_windows", "windows_unparsed"}
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


def _load_json_object(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _all_candidates(decision: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for bucket in ("candidates", "extra_candidates"):
        for item in decision.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            view_id = parse_view_id(item.get("view_id"))
            if view_id is None or view_id in seen:
                continue
            seen.add(view_id)
            rows.append(item)
    return rows


def _is_off_table(candidate: dict) -> bool:
    return candidate.get("source") in {"band", "persisted"}


def _kind_label(decision: dict) -> str:
    reason = str(decision.get("reason") or "")
    kind = str(decision.get("kind") or "")
    if reason in _SEQUENTIAL_REASONS:
        return reason
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


def _window_from_run(run_dir: Path) -> tuple[str | None, str | None, int | None]:
    if not run_dir.is_dir():
        return None, None, None
    paths = sorted(p for p in run_dir.glob("*.json") if p.name != "reviewed.json")
    reviewed = run_dir / "reviewed.json"
    if reviewed.is_file():
        paths.append(reviewed)
    best: tuple[str | None, str | None, int | None] = (None, None, None)
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
        source_url = envelope.get("source_pdf_url")
        view_id = view_id_from_url(source_url) if isinstance(source_url, str) else None
        if not (start_s or end_s):
            continue
        if view_id is not None:
            return start_s, end_s, view_id
        if best == (None, None, None):
            best = (start_s, end_s, None)
    return best


def _windows_from_artifacts(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    data_root: Path,
) -> tuple[dict[str, tuple[str | None, str | None]], dict[int, tuple[str | None, str | None]]]:
    windows: dict[str, tuple[str | None, str | None]] = {}
    by_view: dict[int, tuple[str | None, str | None]] = {}
    for slug, runs in changed.items():
        for run in sorted(runs, reverse=True):
            start, end, view_id = _window_from_run(data_root / slug / run)
            if view_id is not None and (start or end) and view_id not in by_view:
                by_view[view_id] = (start, end)
            if slug not in windows and (start or end):
                windows[slug] = (start, end)
    return windows, by_view


def _published_windows_by_view(publish_pending: dict | None) -> dict[int, tuple[str | None, str | None]]:
    if not isinstance(publish_pending, dict):
        return {}
    by_view: dict[int, tuple[str | None, str | None]] = {}
    for item in publish_pending.get("windows") or []:
        if not isinstance(item, dict):
            continue
        view_id = item.get("view_id")
        if not isinstance(view_id, int):
            continue
        start = item.get("effective_start")
        end = item.get("effective_end")
        start_s = start if isinstance(start, str) and start else None
        end_s = end if isinstance(end, str) and end else None
        if start_s or end_s:
            by_view[view_id] = (start_s, end_s)
    return by_view


def _format_range(start: str | None, end: str | None) -> str | None:
    if start and end:
        return f"{start}–{end}"
    return start or end


def _window_text_for_item(
    item: dict,
    *,
    by_view: dict[int, tuple[str | None, str | None]],
) -> str | None:
    view_id = parse_view_id(item.get("view_id"))
    if view_id is not None and view_id in by_view:
        return _format_range(*by_view[view_id])
    start = item.get("window_start")
    end = item.get("window_end")
    start_s = start if isinstance(start, str) and start else None
    end_s = end if isinstance(end, str) and end else None
    return _format_range(start_s, end_s)


def _format_decision_line(
    decision: dict,
    window: tuple[str | None, str | None] | None,
    *,
    windows_by_view: dict[int, tuple[str | None, str | None]] | None = None,
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
    by_view = windows_by_view or {}

    bits: list[str] = []
    mentioned: set[int] = set()
    attached_dates = False
    action = decision.get("action")
    if action == "adopt" and old_id is not None and new_id is not None and old_id != new_id:
        bits.append(f"{old_id} → {new_id}")
    elif old_id is not None:
        bits.append(f"{old_id} unchanged")

    def _mark(items: list[dict]) -> None:
        for item in items:
            view_id = parse_view_id(item.get("view_id"))
            if view_id is not None:
                mentioned.add(view_id)

    if table_flyers and off_grids:
        flyer = ", ".join(_id_and_name(item) for item in table_flyers)
        flagged = ", ".join(_id_and_name(item) for item in off_grids)
        bits.append(f"flyer {flyer}")
        bits.append(f"band-flagged {flagged}")
        _mark(table_flyers)
        _mark(off_grids)
    elif kind in _SEQUENTIAL_REASONS and grid_ids:
        labeled: list[str] = []
        for item in grid_ids:
            where = "off-table" if _is_off_table(item) else "table"
            piece = f"{where} {_id_and_name(item)}"
            dates = _window_text_for_item(item, by_view=by_view)
            if dates:
                piece = f"{piece} {dates}"
                attached_dates = True
            labeled.append(piece)
        bits.append(f"{kind} {' + '.join(labeled)}")
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
        parse_view_id(extra.get("view_id"))
        for extra in (decision.get("extra_candidates") or [])
        if isinstance(extra, dict) and extra.get("kind") != "session_grid"
    }
    extra_ids.discard(None)
    leftover_extra = [
        item
        for item in candidates
        if parse_view_id(item.get("view_id")) in extra_ids
        and parse_view_id(item.get("view_id")) not in mentioned
    ]
    if leftover_extra:
        bits.append("extra " + ", ".join(_id_and_name(item) for item in leftover_extra))

    if not attached_dates and window and (window[0] or window[1]):
        ranged = _format_range(window[0], window[1])
        if ranged:
            bits.append(ranged)

    return f"- `{slug}`: " + "; ".join(bits)


def _lead_pool_lines(
    pending_slugs: list[str],
    decisions: DecisionSet,
    windows: dict[str, tuple[str | None, str | None]],
    *,
    published_slugs: list[str] | None = None,
    carried_slugs: list[str] | None = None,
    windows_by_view: dict[int, tuple[str | None, str | None]] | None = None,
) -> list[str]:
    by_slug = dict(decisions.by_slug)
    slugs: list[str] = []
    seen: set[str] = set()
    for item in decisions:
        slug = item["slug"]
        if slug in seen:
            continue
        if (
            item.get("blocking")
            or item.get("action") == "adopt"
            or item.get("reason") in _SEQUENTIAL_REASONS
            or any(_is_off_table(candidate) for candidate in _all_candidates(item))
            or slug in pending_slugs
        ):
            seen.add(slug)
            slugs.append(slug)
    for slug in pending_slugs:
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    for slug in list(published_slugs or []) + list(carried_slugs or []):
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    published = set(published_slugs or [])
    carried = set(carried_slugs or [])
    lines: list[str] = []
    for slug in slugs:
        decision = by_slug.get(slug)
        if decision is not None:
            line = _format_decision_line(
                decision,
                windows.get(slug),
                windows_by_view=windows_by_view,
            )
        else:
            line = f"- `{slug}`: payload changed"
        if slug in published:
            line += "; auto"
        elif slug in carried:
            line += "; carried"
        lines.append(line)
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
    decisions = DecisionSet.load(repo_root / "tmp" / "discovery-decisions.json")
    publish_pending = _load_json_object(repo_root / "tmp" / "publish-pending.json")
    registry_staged = _registry_is_staged(repo_root)
    blocking_slugs = sorted(decisions.blocking_slugs)
    adopt_slugs = [item["slug"] for item in decisions if item.get("action") == "adopt"]

    if not changed and not registry_staged and not blocking_slugs and not adopt_slugs:
        return (
            "Nothing to review. Auto-extract found no diffs against `main` "
            "(every published pool's PDF, prompt, and schema sha matched the "
            "cached artifact). Close this PR.\n"
        )

    changed_slugs = sorted(s for s in changed if any(e.slug == s for e in registry))
    pending_slugs = sorted(s for s in changed_slugs if _has_pending_run(s, changed[s], data_root))
    auto_slugs, carried_slugs = _split_attested_slugs(changed, changed_slugs, pending_slugs, data_root)
    unchanged_n = len(published) - len(changed_slugs)
    windows, artifact_by_view = _windows_from_artifacts(changed, data_root)
    windows_by_view = {**artifact_by_view, **_published_windows_by_view(publish_pending)}
    branch = "auto/schedules-extract"
    published_slugs = _published_slugs(publish_pending, auto_slugs)
    show_checklist = _show_debug_checklist(publish_pending, pending_slugs)

    lines: list[str] = []
    lines.extend(
        _render_lead(
            changed,
            pending_slugs,
            carried_slugs,
            unchanged_n,
            decisions=decisions,
            windows=windows,
            windows_by_view=windows_by_view,
            registry_staged=registry_staged,
            published_slugs=published_slugs,
            blocking_slugs=blocking_slugs,
            show_checklist=show_checklist,
        )
    )
    lines.extend(
        _render_whats_here(changed, registry_staged=registry_staged, data_root=data_root)
    )
    lines.extend(_render_review(branch, pending_slugs, show_checklist=show_checklist))
    lines.extend(_render_eval_section(data_root=data_root, changed_artifacts=_changed_provider_artifacts(rows)))

    return "\n".join(lines).rstrip() + "\n"


def _has_pending_run(slug: str, runs: dict[str, list[tuple[str, str]]], data_root: Path) -> bool:
    """A slug still needs review when any of its changed run dirs lacks reviewed.json."""
    return any(not (data_root / slug / run / "reviewed.json").exists() for run in runs)


def _reviewed_envelope(data_root: Path, slug: str, run: str) -> dict | None:
    path = data_root / slug / run / "reviewed.json"
    return _load_json_object(path)


def _split_attested_slugs(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    changed_slugs: list[str],
    pending_slugs: list[str],
    data_root: Path,
) -> tuple[list[str], list[str]]:
    auto: list[str] = []
    carried: list[str] = []
    pending = set(pending_slugs)
    for slug in changed_slugs:
        if slug in pending:
            continue
        kind = "carried"
        for run in sorted(changed[slug], reverse=True):
            envelope = _reviewed_envelope(data_root, slug, run)
            if envelope is None:
                continue
            attestation = parse_attestation(envelope)
            if isinstance(attestation, AttestationCarried):
                kind = "carried"
            elif isinstance(attestation, AttestationCi):
                kind = "ci"
            break
        if kind == "ci":
            auto.append(slug)
        else:
            carried.append(slug)
    return auto, carried


def _published_slugs(publish_pending: dict | None, auto_slugs: list[str]) -> list[str]:
    if publish_pending is None:
        return auto_slugs
    listed = [slug for slug in (publish_pending.get("published") or []) if isinstance(slug, str)]
    return listed or auto_slugs


def _show_debug_checklist(publish_pending: dict | None, pending_slugs: list[str]) -> bool:
    if publish_pending is not None and publish_pending.get("skipped") == "kill_switch":
        return True
    return publish_pending is None and bool(pending_slugs)


def _render_lead(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    pending_slugs: list[str],
    carried_slugs: list[str],
    unchanged_n: int,
    *,
    decisions: DecisionSet | None = None,
    windows: dict[str, tuple[str | None, str | None]] | None = None,
    windows_by_view: dict[int, tuple[str | None, str | None]] | None = None,
    registry_staged: bool = False,
    review_slugs: list[str] | None = None,
    published_slugs: list[str] | None = None,
    blocking_slugs: list[str] | None = None,
    show_checklist: bool = False,
) -> list[str]:
    decisions = DecisionSet.from_items([]) if decisions is None else decisions
    windows = windows or {}
    windows_by_view = windows_by_view or {}
    published_slugs = published_slugs or []
    blocking_slugs = blocking_slugs or []
    if review_slugs is None:
        review_slugs = pending_slugs
    if published_slugs:
        n = len(published_slugs)
        noun = "pool" if n == 1 else "pools"
        action = (
            f"Published {n} Rec & Park {noun}. {_AUTO_MERGE} "
            f"{_LIVE_SITE_UPDATES}"
        )
    elif carried_slugs and not pending_slugs:
        action = (
            "No human review needed. Every changed pool extracted a payload "
            "identical to its last attested one, so the attestation was "
            "carried forward; this PR auto-merges once checks pass. "
            f"{_LIVE_SITE_UPDATES}"
        )
    elif blocking_slugs and not pending_slugs:
        n = len(blocking_slugs)
        noun = "pool" if n == 1 else "pools"
        action = (
            f"Discover flagged {n} Rec & Park {noun} (informational). "
            f"Operator signal is the rolling GitHub issue {_FLAGGED_ISSUE}. "
            f"{_AUTO_MERGE} {_LIVE_SITE_UPDATES}"
        )
    elif show_checklist and pending_slugs:
        action = (
            f"{_slug_list(pending_slugs)} still have no reviewed.json. "
            "publish-pending did not succeed. Debug with `just schedules-review`."
        )
    elif pending_slugs:
        action = (
            f"{_slug_list(pending_slugs)} remain on the rolling GitHub issue "
            f"{_FLAGGED_ISSUE}. {_AUTO_MERGE} {_LIVE_SITE_UPDATES}"
        )
    else:
        action = f"No human review needed. {_AUTO_MERGE} {_LIVE_SITE_UPDATES}"
    if carried_slugs and published_slugs:
        action += (
            f" {_slug_list(carried_slugs)} auto-verified: extraction matched "
            "the last attested payload, so the attestation carried forward."
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
    pool_lines = _lead_pool_lines(
        pending_slugs,
        decisions,
        windows,
        published_slugs=published_slugs,
        carried_slugs=carried_slugs,
        windows_by_view=windows_by_view,
    )
    extra_slugs = [
        slug
        for slug in published_slugs + carried_slugs
        if slug not in decisions.by_slug and slug not in pending_slugs
    ]
    for slug in extra_slugs:
        pool_lines.append(
            f"- `{slug}`: auto" if slug in published_slugs else f"- `{slug}`: carried"
        )
    if pool_lines:
        lines.extend(pool_lines)
        lines.append("")
    return lines


def _render_whats_here(
    changed: dict[str, dict[str, list[tuple[str, str]]]],
    *,
    registry_staged: bool = False,
    data_root: Path = DATA_DIR,
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
                    envelope = _reviewed_envelope(data_root, slug, run) or {}
                    attestation = parse_attestation(envelope)
                    if isinstance(attestation, AttestationCi):
                        phrase = "auto-published (`attested_by: ci`)."
                    else:
                        phrase = "attestation carried forward."
                    lines.append(f"`data/{slug}/{run}/{filename}` — {phrase}")
                    continue
                provider = _provider_word(filename)
                state = _change_word(change)
                lines.append(
                    f"`data/{slug}/{run}/{filename}` — {state} {provider} extraction."
                )
    lines.append("")
    return lines


def _render_review(
    branch: str, review_slugs: list[str], *, show_checklist: bool = False
) -> list[str]:
    if not show_checklist:
        return []
    minutes = max(_REVIEW_MIN_PER_POOL, max(len(review_slugs), 1) * _REVIEW_MIN_PER_POOL)

    return [
        f"## Debug (~{minutes} min)",
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
    historical_evals = [
        item for item in collect_pool_evals(data_root=data_root) if item.table != "seasonal_delta"
    ]
    changed_evals = [
        item
        for item in collect_pool_evals(data_root=data_root, all_dirs=True)
        if item.table != "seasonal_delta"
    ]

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
