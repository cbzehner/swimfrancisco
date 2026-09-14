"""Retention for captured schedule snapshots.

Per slug, keep a snapshot dir if ANY of: (a) it is the newest dir containing
``reviewed.json``; (b) it lacks ``reviewed.json`` and either (i) it contains a
provider or direct artifact and no reviewed dir of the slug is dated after it
(a pending extraction, not yet superseded by a review), or (ii) its date
equals the slug's newest capture date (a fresh capture awaiting extraction or
closure review); (c) another dir's ``reviewed.json`` names it in
``carried_from``; (d) its source is a PDF (Rec & Park corpus used by
backtests); or (e) an explicit corpus-retention pin names the dir. A dir
whose source body hash does not match its ``source.sha256`` is deleted unless
(a), (c), (d), or (e) protects it. Everything else is deleted by
``schedules prune``, which ``schedules automate`` runs before every commit.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from collections.abc import Collection
from pathlib import Path

from .paths import all_review_dirs, parse_review_dir_name

# The gemini- and anthropic- prefixes are retired for new extractions and
# kept here because committed PDF capture dirs still hold those artifacts.
PROVIDER_ARTIFACT = re.compile(r"(?:openai|direct|gemini|anthropic)-[a-z0-9.-]+\.json")
RETENTION_FIXTURE = Path("tests/fixtures/corpus-retention.toml")


def plan_prune(data_root: Path, repo_root: Path) -> list[Path]:
    """The snapshot dirs no retention rule still needs."""
    data_root = data_root.resolve()
    repo_root = repo_root.resolve()
    pinned = _explicit_pins(repo_root, data_root)
    if not data_root.is_dir():
        return []
    obsolete: set[Path] = set()
    while True:
        # A deleted review carries nothing forward, so dropping one can leave
        # the capture it was carried from with no reason to stay. Settle on the
        # tree the deletions actually produce.
        carried = _carried_from_dirs(data_root, deleted=obsolete)
        found: set[Path] = set()
        for slug_dir in sorted(data_root.iterdir()):
            if not slug_dir.is_dir():
                continue
            # A symlink is not a capture this tool put there: it is neither
            # removed nor allowed to stand in for the slug's newest review.
            snapshots = [snapshot for snapshot in all_review_dirs(slug_dir.name, root=data_root)
                         if not snapshot.is_symlink()]
            if not snapshots:
                continue
            reviewed = [snapshot for snapshot in snapshots if (snapshot / "reviewed.json").is_file()]
            newest_date = max(parse_review_dir_name(snapshot.name)[0] for snapshot in snapshots)
            found.update(
                snapshot for snapshot in snapshots
                if keep_reason(snapshot, newest_reviewed=reviewed[-1] if reviewed else None,
                               newest_date=newest_date, carried=carried, pinned=pinned) is None
            )
        if found == obsolete:
            return sorted(obsolete)
        obsolete = found


def prune(data_root: Path, repo_root: Path, *, dry_run: bool) -> list[Path]:
    """Delete the obsolete snapshot dirs and return them; list them on a dry run."""
    obsolete = plan_prune(data_root, repo_root)
    if not dry_run:
        for snapshot in obsolete:
            shutil.rmtree(snapshot)
    return obsolete


def keep_reason(
    snapshot: Path, *, newest_reviewed: Path | None, newest_date: str,
    carried: set[Path], pinned: set[Path]
) -> str | None:
    """Why this snapshot stays, or None when nothing needs it any more."""
    if snapshot == newest_reviewed:
        return "newest reviewed capture"
    if snapshot in carried:
        return "a later review was carried from it"
    # A workbook capture stores the sheet's PDF rendering beside it; the
    # backtest corpus is the documents whose source is the PDF itself.
    if (snapshot / "source.pdf").is_file() and not (snapshot / "source.xlsx").is_file():
        return "PDF backtest corpus"
    if snapshot in pinned:
        return "explicit corpus retention pin"
    if not _proves_its_own_identity(snapshot):
        return None
    if (snapshot / "reviewed.json").is_file():
        return None
    captured_on = parse_review_dir_name(snapshot.name)[0]
    extracted = any(PROVIDER_ARTIFACT.fullmatch(path.name) for path in snapshot.iterdir() if path.is_file())
    # An extraction nobody reviewed is still a question the queue owes an
    # answer to; only a review of a later capture answers it. A newer capture
    # on its own extracts nothing and so supersedes nothing.
    if extracted and (newest_reviewed is None
                      or parse_review_dir_name(newest_reviewed.name)[0] <= captured_on):
        return "pending review"
    # Source bytes with no artifact: the newest day's are awaiting extraction
    # or a closure review that reads them back; older ones were left behind.
    if captured_on == newest_date:
        return "capture awaiting extraction"
    return None


def _proves_its_own_identity(snapshot: Path) -> bool:
    """Whether a source body here hashes to what ``source.sha256`` records.

    A capture with no sidecar yet is not in question: the next fetch of those
    bytes backfills it. A capture that contradicts its own sidecar is, and it
    fails every later capture of that slug with a prefix collision.
    """
    bodies = [path for path in snapshot.glob("source.*") if path.name != "source.sha256"]
    recorded = _sidecar_sha256(snapshot)
    if not bodies or recorded is None:
        return True
    return any(hashlib.sha256(body.read_bytes()).hexdigest() == recorded for body in bodies)


def _sidecar_sha256(snapshot: Path) -> str | None:
    sidecar = snapshot / "source.sha256"
    return sidecar.read_text().strip() if sidecar.is_file() else None


def _explicit_pins(repo_root: Path, data_root: Path) -> set[Path]:
    """Load and validate repository-relative capture directories to retain."""
    fixture = repo_root / RETENTION_FIXTURE
    if not fixture.is_file():
        return set()
    try:
        document = tomllib.loads(fixture.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Invalid corpus retention fixture {fixture}: {exc}") from exc
    if set(document) != {"pins"}:
        raise ValueError(f"Invalid corpus retention fixture {fixture}: unsupported fields")
    pins = document.get("pins")
    if not isinstance(pins, list):
        raise ValueError(f"Invalid corpus retention fixture {fixture}: pins must be an array")
    repo_root = repo_root.resolve()
    data_root = data_root.resolve()
    validated: set[Path] = set()
    for index, pin in enumerate(pins):
        if not isinstance(pin, dict) or set(pin) != {"path", "reason"}:
            raise ValueError(f"Invalid corpus retention pin {index} in {fixture}")
        relative = pin["path"]
        reason = pin["reason"]
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError(f"Retention pin {index} has an invalid relative path: {relative!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Retention pin {index} must explain why it is retained")
        candidate = repo_root / relative
        if candidate.is_symlink():
            raise ValueError(f"Retention pin target must not be a symlink: {relative}")
        target = candidate.resolve()
        try:
            target.relative_to(repo_root)
            target.relative_to(data_root)
        except ValueError as exc:
            raise ValueError(f"Retention pin {relative!r} escapes the repository data root") from exc
        if not target.is_dir():
            raise ValueError(f"Retention pin target does not exist as a capture directory: {relative}")
        if parse_review_dir_name(target.name) is None:
            raise ValueError(f"Retention pin target is not a capture directory: {relative}")
        if target in validated:
            raise ValueError(f"Duplicate retention pin: {relative}")
        validated.add(target)
    return validated


def _carried_from_dirs(data_root: Path, *, deleted: Collection[Path] = frozenset()) -> set[Path]:
    """The snapshot dirs a surviving review says it carried a decision from."""
    carried: set[Path] = set()
    for reviewed in sorted(data_root.glob("*/*/reviewed.json")):
        if reviewed.parent in deleted:
            continue
        try:
            envelope = json.loads(reviewed.read_text())
        except (OSError, ValueError):
            continue
        reference = envelope.get("carried_from") if isinstance(envelope, dict) else None
        parts = Path(reference).parts if isinstance(reference, str) else ()
        if len(parts) >= 3:
            carried.add(data_root / parts[-3] / parts[-2])
    return carried
