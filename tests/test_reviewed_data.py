"""Every committed reviewed.json must pass envelope and schema validation.

Reviewed snapshots are the locked source of truth for pool schedules;
this pins them to the same validate() contract the pipeline enforces so
malformed data cannot land silently (see the Coffman 9:00-vs-09:00 fix).
"""

import hashlib
import json
from pathlib import Path

import pytest

from schedules.reviewed_snapshots import load_reviewed_snapshot_from_path
from schedules.validate import validate

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = sorted(ROOT.glob("data/*/*/reviewed.json"))
SOURCE_BODIES = ("source.pdf", "source.html", "source.xlsx", "source.csv")
CAPTURE_DIRS = sorted(
    path
    for path in ROOT.glob("data/*/*")
    if path.is_dir() and path.parent.name != "i18n"
)


def _snapshot_id(path: Path) -> str:
    return f"{path.parent.parent.name}/{path.parent.name}"


def _capture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.mark.parametrize("path", SNAPSHOTS, ids=_snapshot_id)
def test_reviewed_snapshot_is_valid(path):
    envelope = load_reviewed_snapshot_from_path(path, expected_slug=path.parent.parent.name)
    result = validate(envelope["payload"])
    assert result.ok, [f"{v.code}: {v.message}" for v in result.violations]


def test_reviewed_snapshots_exist():
    assert SNAPSHOTS, "no reviewed.json snapshots found under data/ — glob broken?"


@pytest.mark.parametrize("path", CAPTURE_DIRS, ids=_capture_id)
def test_capture_dir_keeps_source_bytes(path):
    bodies = [path / name for name in SOURCE_BODIES if (path / name).exists()]
    assert bodies, f"{path} has no source.pdf/html/xlsx/csv — cannot backtest"
    sha_path = path / "source.sha256"
    assert sha_path.exists(), f"{path} is missing source.sha256"
    recorded = sha_path.read_text().strip()
    assert recorded, f"{path}/source.sha256 is empty"
    assert path.name.endswith(f"-{recorded[:12]}"), (
        f"{path.name} prefix does not match source.sha256 {recorded[:12]}"
    )
    if (path / "source.pdf").exists() and not (path / "source.xlsx").exists():
        actual = hashlib.sha256((path / "source.pdf").read_bytes()).hexdigest()
        assert actual == recorded, f"{path}/source.pdf bytes do not match source.sha256"
    for json_path in sorted(path.glob("*.json")):
        data = json.loads(json_path.read_text())
        pdf_sha256 = data.get("pdf_sha256")
        if pdf_sha256:
            assert pdf_sha256 == recorded, (
                f"{json_path.name} pdf_sha256 does not match source.sha256"
            )
