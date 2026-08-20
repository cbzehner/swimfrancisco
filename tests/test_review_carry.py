"""Attestation carry-forward: a new capture whose extracted payload matches
the pool's last human-reviewed payload re-uses that review instead of
queueing the pool again."""

from __future__ import annotations

import json
from pathlib import Path

from schedules.envelope import validate_envelope
from schedules.pr_summary import _has_pending_run, _render_lead
from schedules.review import carry_forward_review

_OLD_SHA = "a" * 64
_NEW_SHA = "b" * 64


def _payload(effective_start: str = "2026-07-06") -> dict:
    return {
        "effective_start": effective_start,
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00", "evidence": "Lap Swim 7-8am"},
        ],
        "closures": [],
    }


def _seed_reviewed(data_root: Path, slug: str, date: str, sha: str, payload: dict) -> Path:
    review_dir = data_root / slug / f"{date}-{sha[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    target = review_dir / "reviewed.json"
    target.write_text(json.dumps({
        "slug": slug,
        "pdf_sha256": sha,
        "reviewed_at": "2026-07-06",
        "source_pdf_url": "https://example.com/x.pdf",
        "payload": payload,
    }, indent=2) + "\n")
    return target


def _new_capture_dir(data_root: Path, slug: str, date: str, sha: str) -> Path:
    review_dir = data_root / slug / f"{date}-{sha[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    return review_dir


def test_carry_writes_reviewed_snapshot_with_provenance(tmp_path):
    _seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, _payload())
    new_dir = _new_capture_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        payload=_payload(effective_start="2026-07-13"),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried == new_dir / "reviewed.json"
    envelope = json.loads(carried.read_text())
    validate_envelope(envelope)
    assert envelope["pdf_sha256"] == _NEW_SHA
    assert envelope["reviewed_at"] == "2026-07-06"
    assert envelope["carried_from"].endswith("reviewed.json")
    # The human-reviewed payload is preserved verbatim, including its
    # original effective_start.
    assert envelope["payload"] == _payload()


def test_carry_treats_absent_and_empty_collections_as_equal(tmp_path):
    """Older reviewed payloads omit collections newer extractors emit as []."""
    _seed_reviewed(tmp_path, "city-sports-20th-ave", "2026-05-17", _OLD_SHA, _payload())
    new_dir = _new_capture_dir(tmp_path, "city-sports-20th-ave", "2026-07-19", _NEW_SHA)

    fresh = _payload(effective_start="2026-07-19")
    fresh["access_exceptions"] = []
    carried = carry_forward_review(
        slug="city-sports-20th-ave",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        payload=fresh,
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is not None


def test_carry_refuses_when_payload_differs(tmp_path):
    _seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, _payload())
    new_dir = _new_capture_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    changed = _payload()
    changed["sessions"][0]["end"] = "09:00"
    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        payload=changed,
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is None
    assert not (new_dir / "reviewed.json").exists()


def test_carry_refuses_without_prior_review(tmp_path):
    new_dir = _new_capture_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        payload=_payload(),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is None


def test_strict_mode_blocks_carry_on_effective_start_change(tmp_path):
    """PDF pools: effective_start comes from the source, so a change there is
    a real schedule change even when the sessions match."""
    _seed_reviewed(tmp_path, "balboa-pool", "2026-07-06", _OLD_SHA, _payload())
    new_dir = _new_capture_dir(tmp_path, "balboa-pool", "2026-07-13", _NEW_SHA)

    carried = carry_forward_review(
        slug="balboa-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        payload=_payload(effective_start="2026-08-12"),
        ignore_effective_start=False,
        data_root=tmp_path,
    )

    assert carried is None


def test_carried_snapshot_can_seed_the_next_carry(tmp_path):
    _seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, _payload())
    first_dir = _new_capture_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)
    carry_forward_review(
        slug="north-beach-pool",
        review_dir=first_dir,
        pdf_sha256=_NEW_SHA,
        payload=_payload(effective_start="2026-07-13"),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    third_sha = "c" * 64
    second_dir = _new_capture_dir(tmp_path, "north-beach-pool", "2026-07-20", third_sha)
    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=second_dir,
        pdf_sha256=third_sha,
        payload=_payload(effective_start="2026-07-20"),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is not None
    envelope = json.loads(carried.read_text())
    validate_envelope(envelope)
    assert envelope["pdf_sha256"] == third_sha
    assert envelope["reviewed_at"] == "2026-07-06"


def test_pending_run_detection_uses_reviewed_presence(tmp_path):
    _seed_reviewed(tmp_path, "carried-pool", "2026-07-13", _NEW_SHA, _payload())
    pending_dir = tmp_path / "pending-pool" / f"2026-07-13-{_OLD_SHA[:12]}"
    pending_dir.mkdir(parents=True)

    carried_run = f"2026-07-13-{_NEW_SHA[:12]}"
    pending_run = f"2026-07-13-{_OLD_SHA[:12]}"
    assert not _has_pending_run("carried-pool", {carried_run: []}, tmp_path)
    assert _has_pending_run("pending-pool", {pending_run: []}, tmp_path)


def test_lead_distinguishes_pending_from_carried():
    changed = {"a-pool": {"2026-07-13-bbbbbbbbbbbb": [("gemini.json", "A")]}}
    all_carried = "\n".join(_render_lead(changed, [], ["a-pool", "b-pool"], 3))
    assert "No human review needed" in all_carried
    assert "auto-merges" in all_carried
    assert "attestation was carried" in all_carried
    assert "unverified projection" not in all_carried

    mixed = "\n".join(_render_lead({}, ["a-pool"], ["b-pool"], 3))
    assert "`a-pool` needs a human review" in mixed
    assert "`b-pool` auto-verified" in mixed
    assert "The live site stays on the last reviewed window until this PR merges." in mixed
    assert "unverified projection" not in mixed
