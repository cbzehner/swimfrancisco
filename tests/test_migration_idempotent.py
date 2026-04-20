from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_pdf_layout.py"


def _setup_old_layout(tmp_data: Path):
    """Simulate pre-migration state: flat data/pdfs/ + index + full-hash snapshots."""
    (tmp_data / "pdfs").mkdir(parents=True)
    (tmp_data / "reviewed-snapshots" / "balboa-pool").mkdir(parents=True)

    # One PDF in flat layout.
    full_sha = "ba9b279ae183" + "a" * 52
    old_pdf = tmp_data / "pdfs" / f"balboa-pool-{full_sha[:12]}.pdf"
    old_pdf.write_bytes(b"fake pdf bytes")

    # Matching snapshot with reviewed_at field.
    snapshot_path = tmp_data / "reviewed-snapshots" / "balboa-pool" / f"{full_sha}.json"
    snapshot_path.write_text(json.dumps({
        "version": 1,
        "slug": "balboa-pool",
        "pdf_sha256": full_sha,
        "reviewed_at": "2026-04-10",
        "source_pdf_url": "https://example.test/balboa.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "flash"}],
        "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
    }))

    index = tmp_data / "pdf-cache-index.json"
    index.write_text(json.dumps({
        f"balboa-pool|https://example.test/balboa.pdf": f"balboa-pool-{full_sha[:12]}.pdf"
    }))


def _run_migration(tmp_data: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(tmp_data)],
        capture_output=True, text=True, check=True,
    )


def test_migration_moves_pdfs_and_renames_snapshots(tmp_path):
    tmp_data = tmp_path / "data"
    _setup_old_layout(tmp_data)

    _run_migration(tmp_data)

    # PDF moved to per-slug dir with date-prefix filename.
    full_sha = "ba9b279ae183" + "a" * 52
    prefix = full_sha[:12]
    new_pdf = tmp_data / "pdfs" / "balboa-pool" / f"2026-04-10-{prefix}.pdf"
    assert new_pdf.exists(), list((tmp_data / "pdfs" / "balboa-pool").iterdir())

    # Snapshot renamed to date-prefix.
    new_snap = tmp_data / "reviewed-snapshots" / "balboa-pool" / f"2026-04-10-{prefix}.json"
    assert new_snap.exists()

    # Index deleted.
    assert not (tmp_data / "pdf-cache-index.json").exists()


def test_migration_is_idempotent(tmp_path):
    tmp_data = tmp_path / "data"
    _setup_old_layout(tmp_data)

    _run_migration(tmp_data)
    result = _run_migration(tmp_data)

    assert "already migrated" in result.stdout


def test_migration_handles_missing_index_post_run(tmp_path):
    """After a first run deletes the index, a second run sees target-layout complete."""
    tmp_data = tmp_path / "data"
    _setup_old_layout(tmp_data)
    _run_migration(tmp_data)
    # Simulate fresh clone with migrated data but no index.
    assert not (tmp_data / "pdf-cache-index.json").exists()

    result = _run_migration(tmp_data)
    assert "already migrated" in result.stdout
