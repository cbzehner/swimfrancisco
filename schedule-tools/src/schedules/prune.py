"""Retention for captured schedule snapshots.

Per slug, keep a snapshot dir if ANY of: (a) it is the newest dir containing
``reviewed.json``; (b) it contains provider or direct JSON but no
``reviewed.json`` (pending review); (c) another dir's ``reviewed.json`` names
it in ``carried_from``; (d) its source is a PDF (Rec & Park corpus used by
backtests); (e) a file under ``tests/`` or ``docs/`` names the dir. Everything
else is deleted. Deletion never touches dir contents, only whole dirs.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .paths import all_review_dirs

PROVIDER_ARTIFACT = re.compile(r"(?:openai|direct|gemini|anthropic)-[a-z0-9.-]+\.json")
SNAPSHOT_DIR_NAME = re.compile(rb"\d{4}-\d{2}-\d{2}-[0-9a-f]{12}")


def plan_prune(data_root: Path, repo_root: Path) -> list[Path]:
    """The snapshot dirs no review, backtest, test, or document still needs."""
    if not data_root.is_dir():
        return []
    documented = _names_in_tests_and_docs(repo_root)
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
            snapshots = all_review_dirs(slug_dir.name, root=data_root)
            reviewed = [snapshot for snapshot in snapshots if (snapshot / "reviewed.json").is_file()]
            found.update(
                snapshot for snapshot in snapshots
                # A symlink is not a capture this tool put there, so it is
                # never something this tool removes.
                if not snapshot.is_symlink()
                and keep_reason(snapshot, newest_reviewed=reviewed[-1] if reviewed else None,
                                carried=carried, documented=documented) is None
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
    snapshot: Path, *, newest_reviewed: Path | None, carried: set[Path], documented: set[str]
) -> str | None:
    """Why this snapshot stays, or None when nothing needs it any more."""
    if snapshot == newest_reviewed:
        return "newest reviewed capture"
    if not (snapshot / "reviewed.json").is_file() and any(
        PROVIDER_ARTIFACT.fullmatch(path.name) for path in snapshot.iterdir() if path.is_file()
    ):
        return "pending review"
    if snapshot in carried:
        return "a later review was carried from it"
    # A workbook capture stores the sheet's PDF rendering beside it; the
    # backtest corpus is the documents whose source is the PDF itself.
    if (snapshot / "source.pdf").is_file() and not (snapshot / "source.xlsx").is_file():
        return "PDF backtest corpus"
    if snapshot.name in documented:
        return "named by a test or document"
    return None


def _names_in_tests_and_docs(repo_root: Path) -> set[str]:
    """Every snapshot dir name a file under tests/ or docs/ mentions."""
    names: set[str] = set()
    for root in (repo_root / "tests", repo_root / "docs"):
        for path in sorted(root.rglob("*")) if root.is_dir() else []:
            if path.is_symlink() or not path.is_file():
                continue
            names.update(match.group().decode() for match in SNAPSHOT_DIR_NAME.finditer(path.read_bytes()))
    return names


def _carried_from_dirs(data_root: Path, *, deleted: set[Path] = frozenset()) -> set[Path]:
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
