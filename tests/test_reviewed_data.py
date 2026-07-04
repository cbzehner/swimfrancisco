"""Every committed reviewed.json must pass envelope and schema validation.

Reviewed snapshots are the locked source of truth for pool schedules;
this pins them to the same validate() contract the pipeline enforces so
malformed data cannot land silently (see the Coffman 9:00-vs-09:00 fix).
"""

from pathlib import Path

import pytest

from schedules.reviewed_snapshots import load_reviewed_snapshot_from_path
from schedules.validate import validate

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = sorted(ROOT.glob("data/*/*/reviewed.json"))


def _snapshot_id(path: Path) -> str:
    return f"{path.parent.parent.name}/{path.parent.name}"


@pytest.mark.parametrize("path", SNAPSHOTS, ids=_snapshot_id)
def test_reviewed_snapshot_is_valid(path):
    envelope = load_reviewed_snapshot_from_path(path, expected_slug=path.parent.parent.name)
    result = validate(envelope["payload"])
    assert result.ok, [f"{v.code}: {v.message}" for v in result.violations]


def test_reviewed_snapshots_exist():
    assert SNAPSHOTS, "no reviewed.json snapshots found under data/ — glob broken?"
