#!/usr/bin/env python3
"""Migrate cached PDFs + reviewed snapshots to per-slug date-prefixed layout.

Usage:
    python scripts/migrate_pdf_layout.py [--data-dir data]

Idempotent. Safe to run on a fresh clone, a partially migrated tree, or
a fully migrated tree. Prints a summary and exits 0 on success.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


TARGET_PDF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{12}\.pdf$")
OLD_FLAT_PDF_RE = re.compile(r"^(?P<slug>[a-z0-9-]+)-(?P<prefix>[0-9a-f]{12})\.pdf$")


def _is_target_layout_complete(data_dir: Path) -> bool:
    """Return True iff every PDF directory contains only new-layout files
    and no old-flat PDFs exist and the index is absent."""
    pdfs_root = data_dir / "pdfs"
    if (data_dir / "pdf-cache-index.json").exists():
        return False
    if not pdfs_root.is_dir():
        # No PDFs at all — technically "complete" (nothing to migrate).
        return True
    for entry in pdfs_root.iterdir():
        if entry.is_file() and OLD_FLAT_PDF_RE.match(entry.name):
            return False
        if entry.is_dir():
            for pdf in entry.glob("*.pdf"):
                if not TARGET_PDF_RE.match(pdf.name):
                    return False
    return True


def _read_snapshot_reviewed_at(snapshot_path: Path) -> str | None:
    try:
        raw = json.loads(snapshot_path.read_text())
    except Exception:
        return None
    value = raw.get("reviewed_at") if isinstance(raw, dict) else None
    return value if isinstance(value, str) else None


def _resolve_pdf_date(slug: str, full_hash: str, data_dir: Path, source_path: Path) -> str:
    """Use reviewed_at from matching snapshot if present, else source mtime."""
    snapshot = data_dir / "reviewed-snapshots" / slug / f"{full_hash}.json"
    if snapshot.exists():
        reviewed_at = _read_snapshot_reviewed_at(snapshot)
        if reviewed_at:
            return reviewed_at
    mtime = dt.datetime.fromtimestamp(source_path.stat().st_mtime)
    return mtime.date().isoformat()


def _parse_old_flat(filename: str) -> tuple[str, str] | None:
    m = OLD_FLAT_PDF_RE.match(filename)
    return (m.group("slug"), m.group("prefix")) if m else None


def _resolve_full_hash_from_index(index: dict, slug: str, prefix: str) -> str | None:
    """Find the full hash from index entries — each value is <slug>-<prefix>.pdf.
    If the snapshot file for this prefix exists under reviewed-snapshots/<slug>/,
    its filename IS the full hash."""
    for _key, filename in index.items():
        parsed = _parse_old_flat(filename)
        if parsed == (slug, prefix):
            return None  # index knows prefix; full hash comes from snapshot dir
    return None


def _find_full_hash_in_snapshots(data_dir: Path, slug: str, prefix: str) -> str | None:
    snap_dir = data_dir / "reviewed-snapshots" / slug
    if not snap_dir.is_dir():
        return None
    candidates: list[str] = []
    for snap in snap_dir.glob(f"{prefix}*.json"):
        stem = snap.stem
        if len(stem) == 64 and all(c in "0123456789abcdef" for c in stem):
            candidates.append(stem)
    if len(candidates) > 1:
        raise SystemExit(
            f"ambiguous prefix {prefix} in {snap_dir}: {candidates}"
        )
    return candidates[0] if candidates else None


def migrate(data_dir: Path) -> tuple[int, int]:
    pdfs_moved = 0
    snapshots_renamed = 0

    pdfs_root = data_dir / "pdfs"
    if pdfs_root.is_dir():
        for entry in list(pdfs_root.iterdir()):
            if not entry.is_file():
                continue
            parsed = _parse_old_flat(entry.name)
            if not parsed:
                continue
            slug, prefix = parsed

            # Resolve full hash: prefer matching snapshot filename.
            full_hash = _find_full_hash_in_snapshots(data_dir, slug, prefix)
            if full_hash is None:
                raise SystemExit(
                    f"could not resolve full hash for {entry} — no matching snapshot at "
                    f"data/reviewed-snapshots/{slug}/{prefix}*.json"
                )
            date_str = _resolve_pdf_date(slug, full_hash, data_dir, entry)
            dest_dir = pdfs_root / slug
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{date_str}-{prefix}.pdf"
            entry.rename(dest)
            pdfs_moved += 1

    snapshots_root = data_dir / "reviewed-snapshots"
    if snapshots_root.is_dir():
        for slug_dir in snapshots_root.iterdir():
            if not slug_dir.is_dir():
                continue
            for snap in list(slug_dir.glob("*.json")):
                stem = snap.stem
                # Only rename files whose stem is a bare 64-char sha256.
                if len(stem) != 64 or not all(c in "0123456789abcdef" for c in stem):
                    continue
                reviewed_at = _read_snapshot_reviewed_at(snap)
                if not reviewed_at:
                    raise SystemExit(f"{snap} has no reviewed_at field")
                new_name = f"{reviewed_at}-{stem[:12]}.json"
                snap.rename(slug_dir / new_name)
                snapshots_renamed += 1

    index_path = data_dir / "pdf-cache-index.json"
    if index_path.exists():
        index_path.unlink()

    return pdfs_moved, snapshots_renamed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", help="Path to data directory (default: data/)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"error: {data_dir} does not exist", file=sys.stderr)
        return 1

    if _is_target_layout_complete(data_dir):
        print("already migrated (or no data to migrate)")
        return 0

    pdfs_moved, snapshots_renamed = migrate(data_dir)
    print(f"migrated: {pdfs_moved} PDFs moved, {snapshots_renamed} snapshots renamed, index deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
