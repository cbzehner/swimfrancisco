import json

import pytest

from schedules.reviewed_snapshots import REVIEWED_SNAPSHOT_VERSION, load_reviewed_snapshot


def test_load_reviewed_snapshot(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    file_path = root / "hamilton-pool" / f"{pdf_sha256}.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        json.dumps(
            {
                "version": REVIEWED_SNAPSHOT_VERSION,
                "slug": "hamilton-pool",
                "pdf_sha256": pdf_sha256,
                "reviewed_at": "2026-04-18",
                "summary": "manual review",
                "source_pdf_url": "https://example.com/schedule.pdf",
                "reviewed_against": [
                    {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}
                ],
                "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
            }
        )
    )

    snapshot, fingerprint, relative_path = load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)

    assert snapshot["summary"] == "manual review"
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert relative_path == str(file_path)


def _write_snapshot(root, slug, pdf_sha256, envelope):
    file_path = root / slug / f"{pdf_sha256}.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(envelope))
    return file_path


def _valid_envelope(slug, pdf_sha256):
    return {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [
            {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}
        ],
        "summary": "manual review",
        "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
    }


def test_load_reviewed_snapshot_accepts_valid_envelope(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    _write_snapshot(root, "hamilton-pool", pdf_sha256, _valid_envelope("hamilton-pool", pdf_sha256))
    snapshot, fingerprint, _ = load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)
    assert snapshot["version"] == REVIEWED_SNAPSHOT_VERSION
    assert len(fingerprint) == 64


def test_load_reviewed_snapshot_rejects_missing_version(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    del envelope["version"]
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="version"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


def test_load_reviewed_snapshot_rejects_wrong_version(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    envelope["version"] = 999
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="version"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


def test_load_reviewed_snapshot_rejects_missing_required_field(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    del envelope["source_pdf_url"]
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="source_pdf_url"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


def test_load_reviewed_snapshot_rejects_mismatched_slug(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    envelope["slug"] = "rossi-pool"
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="slug"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


from schedules.reviewed_snapshots import canonicalize_payload


def test_canonicalize_payload_sorts_sessions():
    payload = {
        "schedule_effective": "2026-03-17",
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
        "schedule_effective": "2026-03-17",
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
        "schedule_effective": "2026-03-17",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "deep"}
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert canonical["sessions"][0]["pool"] == "deep"


def test_canonicalize_payload_identical_on_equivalent_inputs():
    a = {
        "schedule_effective": "2026-03-17",
        "schedule_effective_end": None,
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
        "schedule_effective": "2026-03-17",
    }
    assert canonicalize_payload(a) == canonicalize_payload(b)
