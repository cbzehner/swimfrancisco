"""The review lane: scan for candidates, carry an attestation forward, finalize.

`find_review_candidates` decides what a reviewer is shown,
`carry_forward_review` decides when a pool can skip the queue entirely
because the extraction still matches the last human-reviewed payload, and
`finalize_draft` is the gate a reviewed envelope passes through on its way
into content. Envelopes and payloads come from the shared
`reviewed_envelope` / `schedule_payload` builders in conftest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schedules.envelope import validate_envelope
from schedules.review import (
    FinalizeError,
    carry_forward_review,
    finalize_draft,
    find_review_candidates,
)

_OLD_SHA = "a" * 64
_NEW_SHA = "b" * 64


def _review_dir(data_root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    review_dir = data_root / slug / f"{date}-{pdf_sha256[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    return review_dir


def _write_reviewed(review_dir: Path, envelope: dict) -> Path:
    path = review_dir / "reviewed.json"
    path.write_text(json.dumps(envelope, indent=2) + "\n")
    return path


# ---- find_review_candidates -------------------------------------------------


def _write_provider_json(review_dir: Path, pdf_sha256: str, provider: str = "openai") -> Path:
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"{provider}-model.json"
    path.write_text(json.dumps({
        "provider": provider,
        "model": "model",
        "source_pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "effective_start": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))
    return path


def test_find_review_candidates_empty(tmp_path):
    assert find_review_candidates(data_root=tmp_path / "data") == []


def test_find_review_candidates_returns_unreviewed(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_provider_json(review_dir, "a" * 64)

    candidates = find_review_candidates(data_root=data_root)
    assert len(candidates) == 1
    assert candidates[0].slug == "hamilton-pool"
    assert candidates[0].pdf_sha256 == "a" * 64
    assert candidates[0].fetch_date == "2026-04-01"
    assert candidates[0].review_dir == review_dir
    assert candidates[0].source_path == review_dir / "source.pdf"
    assert candidates[0].source_url == "https://example.com/x.pdf"
    assert candidates[0].payload["effective_start"] == "2026-03-17"
    assert candidates[0].view_id is None


def test_find_review_candidates_uses_csv_source_when_pdf_missing(tmp_path):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "koret-center", "2026-04-01", "a" * 64)
    _write_provider_json(review_dir, "a" * 64, provider="direct")
    (review_dir / "source.csv").write_text("Monday Hours: 7am-7pm\n")

    candidates = find_review_candidates(data_root=data_root)
    assert len(candidates) == 1
    assert candidates[0].source_path == review_dir / "source.csv"


def test_find_review_candidates_skips_already_reviewed(tmp_path, reviewed_envelope):
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_provider_json(review_dir, "a" * 64)
    _write_reviewed(review_dir, reviewed_envelope(
        "hamilton-pool", "a" * 64, reviewed_at="2026-04-10",
        source_pdf_url="https://example.com/x.pdf", payload={},
    ))

    assert find_review_candidates(data_root=data_root) == []


def test_find_review_candidates_orders_by_date_then_slug(tmp_path):
    data_root = tmp_path / "data"
    _write_provider_json(_review_dir(data_root, "zulu-pool", "2026-01-01", "a" * 64), "a" * 64)
    _write_provider_json(_review_dir(data_root, "alpha-pool", "2026-03-01", "b" * 64), "b" * 64)
    _write_provider_json(_review_dir(data_root, "bravo-pool", "2026-03-01", "c" * 64), "c" * 64)

    candidates = find_review_candidates(data_root=data_root)
    assert [c.slug for c in candidates] == ["zulu-pool", "alpha-pool", "bravo-pool"]


def test_find_review_candidates_filters_by_slug(tmp_path):
    data_root = tmp_path / "data"
    _write_provider_json(_review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64), "a" * 64)
    _write_provider_json(_review_dir(data_root, "balboa-pool", "2026-04-01", "b" * 64), "b" * 64)

    candidates = find_review_candidates(data_root=data_root, only_slug="balboa-pool")
    assert [c.slug for c in candidates] == ["balboa-pool"]


def test_find_review_candidates_skips_review_dir_without_provider_json(tmp_path):
    # A review dir that only has source.pdf (no provider JSON, no reviewed.json)
    # is mid-state and should not surface in the queue.
    data_root = tmp_path / "data"
    review_dir = _review_dir(data_root, "hamilton-pool", "2026-04-01", "a" * 64)
    (review_dir / "source.pdf").write_bytes(b"%PDF-fake")

    assert find_review_candidates(data_root=data_root) == []


def test_changed_current_city_extraction_requeues_only_ci_review(tmp_path, reviewed_envelope):
    from schedules.paths import PROMPT_PATH
    from schedules.providers.openai_provider import API_MODEL, extraction_configuration

    root = tmp_path / "data"
    directory = _review_dir(root, "hamilton-pool", "2026-08-20", "a" * 64)
    artifact_path = _write_provider_json(directory, "a" * 64, provider="openai")
    artifact = json.loads(artifact_path.read_text())
    artifact.update(model=API_MODEL, details={"configuration": extraction_configuration(PROMPT_PATH.read_text())})
    artifact["payload"]["sessions"][3]["excluded_dates"] = ["2026-09-24"]
    artifact_path.write_text(json.dumps(artifact))
    envelope = reviewed_envelope(
        "hamilton-pool", "a" * 64, reviewed_at="2026-04-10",
        source_pdf_url="https://example.com/x.pdf", payload={},
    )
    reviewed_path = _write_reviewed(directory, envelope | {"attested_by": "ci"})
    reviewed = json.loads(reviewed_path.read_text())
    original = reviewed_path.read_bytes()
    candidates = find_review_candidates(data_root=root)
    assert len(candidates) == 1
    assert candidates[0].payload["sessions"][3]["excluded_dates"] == ["2026-09-24"]
    assert reviewed_path.read_bytes() == original

    for attestor in ("human", None):
        reviewed["attested_by"] = attestor
        reviewed_path.write_text(json.dumps(reviewed))
        original = reviewed_path.read_bytes()
        assert find_review_candidates(data_root=root) == []
        assert reviewed_path.read_bytes() == original

    reviewed["attested_by"] = "ci"
    reviewed_path.write_text(json.dumps(reviewed))
    artifact["details"]["configuration"]["reasoning"] = "low"
    artifact_path.write_text(json.dumps(artifact))
    assert find_review_candidates(data_root=root) == []
    artifact["details"]["configuration"] = extraction_configuration(PROMPT_PATH.read_text())
    artifact_path.write_text(json.dumps(artifact))
    reviewed["payload"] = artifact["payload"]
    reviewed_path.write_text(json.dumps(reviewed))
    assert find_review_candidates(data_root=root) == []


# ---- carry_forward_review ---------------------------------------------------
#
# A new capture whose extracted payload matches the pool's last
# human-reviewed payload re-uses that review instead of queueing the pool
# again.


@pytest.fixture
def carry_payload(schedule_payload):
    """One monday lap-swim hour — the shape the carry tests compare."""

    def build(effective_start: str = "2026-07-06") -> dict:
        return schedule_payload(effective_start, days=("monday",))

    return build


@pytest.fixture
def seed_reviewed(reviewed_envelope):
    """Write a prior human-reviewed snapshot for a pool."""

    def seed(data_root: Path, slug: str, date: str, sha: str, payload: dict) -> Path:
        return _write_reviewed(
            _review_dir(data_root, slug, date, sha),
            reviewed_envelope(slug, sha, reviewed_at="2026-07-06",
                              source_pdf_url="https://example.com/x.pdf", payload=payload),
        )

    return seed


def test_carry_writes_reviewed_snapshot_with_provenance(tmp_path, seed_reviewed, carry_payload):
    seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, carry_payload())
    new_dir = _review_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=carry_payload("2026-07-13"),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried == new_dir / "reviewed.json"
    envelope = json.loads(carried.read_text())
    validate_envelope(envelope)
    assert envelope["pdf_sha256"] == _NEW_SHA
    assert envelope["source_pdf_url"] == "https://example.com/y.pdf"
    assert envelope["reviewed_at"] == "2026-07-06"
    assert envelope["carried_from"].endswith("reviewed.json")
    # The human-reviewed payload is preserved verbatim, including its
    # original effective_start.
    assert envelope["payload"] == carry_payload()


def test_carry_treats_absent_and_empty_collections_as_equal(tmp_path, seed_reviewed, carry_payload):
    """Older reviewed payloads omit collections newer extractors emit as []."""
    seed_reviewed(tmp_path, "city-sports-20th-ave", "2026-05-17", _OLD_SHA, carry_payload())
    new_dir = _review_dir(tmp_path, "city-sports-20th-ave", "2026-07-19", _NEW_SHA)

    fresh = carry_payload("2026-07-19")
    fresh["access_exceptions"] = []
    carried = carry_forward_review(
        slug="city-sports-20th-ave",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=fresh,
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is not None


def test_carry_ignores_evidence_and_session_order(tmp_path, seed_reviewed, carry_payload):
    seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, carry_payload())
    new_dir = _review_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    reordered = carry_payload()
    reordered["sessions"][0]["evidence"] = "different quote"
    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=reordered,
        ignore_effective_start=False,
        data_root=tmp_path,
    )

    assert carried is not None


def test_carry_refuses_when_payload_differs(tmp_path, seed_reviewed, carry_payload):
    seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, carry_payload())
    new_dir = _review_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    changed = carry_payload()
    changed["sessions"][0]["end"] = "09:00"
    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=changed,
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is None
    assert not (new_dir / "reviewed.json").exists()


def test_carry_refuses_without_prior_review(tmp_path, carry_payload):
    new_dir = _review_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)

    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=carry_payload(),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is None


def test_strict_mode_blocks_carry_on_effective_start_change(tmp_path, seed_reviewed, carry_payload):
    """PDF pools: effective_start comes from the source, so a change there is
    a real schedule change even when the sessions match."""
    seed_reviewed(tmp_path, "balboa-pool", "2026-07-06", _OLD_SHA, carry_payload())
    new_dir = _review_dir(tmp_path, "balboa-pool", "2026-07-13", _NEW_SHA)

    carried = carry_forward_review(
        slug="balboa-pool",
        review_dir=new_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=carry_payload("2026-08-12"),
        ignore_effective_start=False,
        data_root=tmp_path,
    )

    assert carried is None


def test_carried_snapshot_can_seed_the_next_carry(tmp_path, seed_reviewed, carry_payload):
    seed_reviewed(tmp_path, "north-beach-pool", "2026-07-06", _OLD_SHA, carry_payload())
    first_dir = _review_dir(tmp_path, "north-beach-pool", "2026-07-13", _NEW_SHA)
    carry_forward_review(
        slug="north-beach-pool",
        review_dir=first_dir,
        pdf_sha256=_NEW_SHA,
        source_pdf_url="https://example.com/y.pdf",
        payload=carry_payload("2026-07-13"),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    third_sha = "c" * 64
    second_dir = _review_dir(tmp_path, "north-beach-pool", "2026-07-20", third_sha)
    carried = carry_forward_review(
        slug="north-beach-pool",
        review_dir=second_dir,
        pdf_sha256=third_sha,
        source_pdf_url="https://example.com/z.pdf",
        payload=carry_payload("2026-07-20"),
        ignore_effective_start=True,
        data_root=tmp_path,
    )

    assert carried is not None
    envelope = json.loads(carried.read_text())
    validate_envelope(envelope)
    assert envelope["pdf_sha256"] == third_sha
    assert envelope["source_pdf_url"] == "https://example.com/z.pdf"
    assert envelope["reviewed_at"] == "2026-07-06"


def test_carry_never_overwrites_existing_review_with_older_attestation(
    tmp_path, seed_reviewed, carry_payload
):
    data_root = tmp_path / "data"
    seed_reviewed(data_root, "hamilton-pool", "2026-07-06", _OLD_SHA, carry_payload())
    target = seed_reviewed(data_root, "hamilton-pool", "2026-08-20", _NEW_SHA, carry_payload("2026-08-18"))
    reviewed = json.loads(target.read_text()) | {"attested_by": "human"}
    target.write_text(json.dumps(reviewed))
    original = target.read_bytes()
    assert carry_forward_review(slug="hamilton-pool", review_dir=target.parent,
                                pdf_sha256=_NEW_SHA, source_pdf_url="https://example.com/x.pdf",
                                payload=carry_payload(), ignore_effective_start=False,
                                data_root=data_root) is None
    assert target.read_bytes() == original


# ---- finalize_draft ---------------------------------------------------------


def _write_draft(data_root: Path, envelope: dict) -> Path:
    review_dir = _review_dir(data_root, envelope["slug"], "2026-04-19", envelope["pdf_sha256"])
    path = review_dir / "reviewed.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")
    return path


def _write_provider_artifact(review_dir: Path, payload: dict) -> Path:
    path = review_dir / "openai-model.json"
    path.write_text(json.dumps({"payload": payload}))
    return path


def test_finalize_happy_path(tmp_path, reviewed_envelope):
    content = tmp_path / "content" / "spots"
    reviewed = _write_draft(tmp_path / "data", reviewed_envelope())
    _seed_content_md(content, "hamilton-pool")

    result = finalize_draft(reviewed_json_path=reviewed, content_spots_dir=content)

    assert result == reviewed
    assert reviewed.exists()
    rendered = (content / "hamilton-pool.md").read_text()
    assert "[[extra.schedules.sessions]]" in rendered
    assert "last_verified_at = \"2026-04-19\"" in rendered


def test_finalize_rejects_malformed_json(tmp_path):
    review_dir = _review_dir(tmp_path / "data", "hamilton-pool", "2026-04-19", "a" * 64)
    reviewed = review_dir / "reviewed.json"
    reviewed.write_text("{ bogus")

    with pytest.raises(FinalizeError, match="invalid JSON"):
        finalize_draft(
            reviewed_json_path=reviewed,
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert reviewed.exists()


def test_finalize_rejects_validate_failure(tmp_path, reviewed_envelope, schedule_payload):
    envelope = reviewed_envelope(payload=schedule_payload(days=("monday", "tuesday")))
    reviewed = _write_draft(tmp_path / "data", envelope)

    with pytest.raises(FinalizeError, match="fewer than 5"):
        finalize_draft(
            reviewed_json_path=reviewed,
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert reviewed.exists()


def test_finalize_rejects_envelope_missing_required_field(tmp_path, reviewed_envelope):
    envelope = reviewed_envelope()
    del envelope["source_pdf_url"]
    reviewed = _write_draft(tmp_path / "data", envelope)

    with pytest.raises(FinalizeError, match="source_pdf_url"):
        finalize_draft(
            reviewed_json_path=reviewed,
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert reviewed.exists()


def test_finalize_accepts_byte_identical_provider_payload(tmp_path, reviewed_envelope):
    envelope = reviewed_envelope()
    reviewed = _write_draft(tmp_path / "data", envelope)
    _write_provider_artifact(reviewed.parent, envelope["payload"])
    _seed_content_md(tmp_path / "content" / "spots", "hamilton-pool")

    result = finalize_draft(
        reviewed_json_path=reviewed,
        content_spots_dir=tmp_path / "content" / "spots",
    )
    assert result == reviewed


def test_finalize_allows_byte_identical_direct_payload(tmp_path, reviewed_envelope):
    envelope = reviewed_envelope("pomeroy-pool")
    reviewed = _write_draft(tmp_path / "data", envelope)
    path = reviewed.parent / "direct-pomeroy-html-v1.json"
    path.write_text(json.dumps({"provider": "direct", "payload": envelope["payload"]}))
    _seed_content_md(tmp_path / "content" / "spots", "pomeroy-pool")

    result = finalize_draft(
        reviewed_json_path=reviewed,
        content_spots_dir=tmp_path / "content" / "spots",
    )

    assert result == reviewed


def test_finalize_accepts_payload_with_any_diff_from_provider(tmp_path, reviewed_envelope):
    envelope = reviewed_envelope()
    reviewed = _write_draft(tmp_path / "data", envelope)
    # Provider seed had one extra session the reviewer dropped — meaningful edit.
    provider_payload = {
        **envelope["payload"],
        "sessions": envelope["payload"]["sessions"] + [
            {"day": "saturday", "type": "lap_swim", "start": "08:00", "end": "09:00"}
        ],
    }
    _write_provider_artifact(reviewed.parent, provider_payload)
    _seed_content_md(tmp_path / "content" / "spots", "hamilton-pool")

    result = finalize_draft(
        reviewed_json_path=reviewed,
        content_spots_dir=tmp_path / "content" / "spots",
    )
    assert result == reviewed
