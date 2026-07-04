import json

import pytest

from schedules.reviewed_snapshots import load_reviewed_snapshot_from_path
from schedules.validate import validate


def _write_snapshot(root, slug, pdf_sha256, envelope):
    file_path = root / slug / f"2026-04-18-{pdf_sha256[:12]}.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(envelope))
    return file_path


def _valid_envelope(slug, pdf_sha256):
    return {
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "payload": {
            "effective_start": "2026-03-17",
            "sessions": [
                {"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}
            ],
            "closures": [],
        },
    }


def test_load_reviewed_snapshot_from_path_checks_envelope_sha(tmp_path):
    # Filename stem is <reviewed_at>-<prefix>, not a sha; loader must read
    # the real pdf_sha256 from the envelope contents, not the filename.
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    path = _write_snapshot(root, "hamilton-pool", pdf_sha256, _valid_envelope("hamilton-pool", pdf_sha256))
    env = load_reviewed_snapshot_from_path(path, expected_slug="hamilton-pool", expected_sha=pdf_sha256)
    assert env["pdf_sha256"] == pdf_sha256
    with pytest.raises(ValueError):
        load_reviewed_snapshot_from_path(path, expected_slug="hamilton-pool", expected_sha="b" * 64)


def test_load_reviewed_snapshot_from_path_rejects_invalid_envelope(tmp_path):
    slug_dir = tmp_path / "reviewed-snapshots" / "hamilton-pool"
    slug_dir.mkdir(parents=True)
    path = slug_dir / "2026-04-18-abcabcabcabc.json"
    path.write_text("{}")
    with pytest.raises(ValueError):
        load_reviewed_snapshot_from_path(path, expected_slug="hamilton-pool")


from schedules.reviewed_snapshots import canonicalize_payload


def test_canonicalize_payload_sorts_sessions():
    payload = {
        "effective_start": "2026-03-17",
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "12:30", "end": "15:00"},
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert [s["day"] for s in canonical["sessions"]] == ["monday", "tuesday"]


def test_canonicalize_payload_strips_session_evidence_and_notes():
    payload = {
        "effective_start": "2026-03-17",
        "sessions": [
            {
                "day": "monday",
                "type": "lap_swim",
                "start": "07:30",
                "end": "08:30",
                "evidence": "LAP SWIM 7:30-8:30 AM",
                "notes": "closed 3rd thursday",
            }
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert "evidence" not in canonical["sessions"][0]
    assert "notes" not in canonical["sessions"][0]


def test_canonicalize_payload_preserves_pool_field():
    payload = {
        "effective_start": "2026-03-17",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "deep"}
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert canonical["sessions"][0]["pool"] == "deep"


def test_canonicalize_payload_preserves_timed_closure_fields():
    payload = {
        "effective_start": "2026-03-17",
        "sessions": [],
        "closures": [
            {
                "start": "2026-05-21",
                "end": "2026-05-21",
                "reason": "Staff training",
                "start_time": "11:00",
                "end_time": "15:00",
            }
        ],
    }
    canonical = canonicalize_payload(payload)
    assert canonical["closures"][0] == {
        "start": "2026-05-21",
        "end": "2026-05-21",
        "reason": "Staff training",
        "start_time": "11:00",
        "end_time": "15:00",
    }


def test_canonicalize_payload_identical_on_equivalent_inputs():
    a = {
        "effective_start": "2026-03-17",
        "effective_end": None,
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30",
             "evidence": "LAP 7:30-8:30"},
            {"day": "tuesday", "type": "family_swim", "start": "15:30", "end": "17:00",
             "evidence": "REC 3:30-5"},
        ],
        "closures": [
            {"start": "2026-05-25", "end": "2026-05-25", "reason": "Holiday Closure"},
        ],
    }
    b = {
        "sessions": [
            {"day": "tuesday", "type": "family_swim", "start": "15:30", "end": "17:00"},
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        ],
        "closures": [
            {"start": "2026-05-25", "end": "2026-05-25", "reason": "Holiday Closure"},
        ],
        "effective_start": "2026-03-17",
    }
    assert canonicalize_payload(a) == canonicalize_payload(b)


def test_reviewed_snapshot_payload_passes_validate():
    payload = {
        "effective_start": "2026-03-17",
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30", "evidence": "Lap Swim 7:30-8:30"},
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30", "evidence": "Lap Swim 7:30-8:30"},
            {"day": "wednesday", "type": "lap_swim", "start": "07:30", "end": "08:30", "evidence": "Lap Swim 7:30-8:30"},
            {"day": "thursday", "type": "lap_swim", "start": "07:30", "end": "08:30", "evidence": "Lap Swim 7:30-8:30"},
            {"day": "friday", "type": "lap_swim", "start": "07:30", "end": "08:30", "evidence": "Lap Swim 7:30-8:30"},
        ],
        "closures": [],
    }
    result = validate(payload, prior_sessions_count=5)
    assert result.ok
