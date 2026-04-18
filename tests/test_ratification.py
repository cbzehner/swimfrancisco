import json

from schedules.reviewed_snapshots import (
    REVIEWED_SNAPSHOT_VERSION,
    canonicalize_payload,
    find_snapshots_for_slug,
    load_reviewed_snapshot,
    write_ratified_snapshot,
)


def _envelope(slug, pdf_sha256, payload):
    return {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-01-01",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "payload": payload,
    }


def test_find_snapshots_for_slug_returns_empty_when_missing(tmp_path):
    assert find_snapshots_for_slug("hamilton-pool", root=tmp_path / "missing") == []


def test_find_snapshots_for_slug_lists_all(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    payload = {
        "schedule_effective": "2026-01-01",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
        ],
        "closures": [],
    }
    for sha in ("a" * 64, "b" * 64):
        path = root / "hamilton-pool" / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_envelope("hamilton-pool", sha, payload)))
    assert len(find_snapshots_for_slug("hamilton-pool", root=root)) == 2


def test_write_ratified_snapshot_round_trips(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    payload = {
        "schedule_effective": "2026-01-01",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
        ],
        "closures": [],
    }
    new_sha = "c" * 64
    source_sha = "a" * 64
    path = write_ratified_snapshot(
        slug="hamilton-pool",
        pdf_sha256=new_sha,
        source_pdf_url="https://example.com/schedule.pdf",
        payload=payload,
        reviewed_against=[{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        ratified_from_sha256=source_sha,
        root=root,
    )
    loaded, fingerprint, _ = load_reviewed_snapshot("hamilton-pool", new_sha, root=root)
    assert loaded["reviewed_by"] == "ratification"
    assert loaded["ratified_from_sha256"] == source_sha
    assert canonicalize_payload(loaded["payload"]) == canonicalize_payload(payload)
    assert fingerprint and len(fingerprint) == 64
    assert path.exists()
