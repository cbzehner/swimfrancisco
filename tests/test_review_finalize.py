import json
from pathlib import Path

import pytest

from schedules.review import FinalizeError, finalize_draft


def _valid_draft_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-19",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "payload": {
            "effective_start": "2026-03-17",
            "schedule_basis": "swim_schedule",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00", "evidence": "Lap Swim 7-8am"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _write_reviewed(data_root: Path, slug: str, pdf_sha256: str, envelope: dict) -> Path:
    review_dir = data_root / slug / f"2026-04-19-{pdf_sha256[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / "reviewed.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")
    return path


def test_finalize_happy_path(tmp_path):
    data_root = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    reviewed = _write_reviewed(data_root, "hamilton-pool", "a" * 64, _valid_draft_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    result = finalize_draft(
        reviewed_json_path=reviewed,
        content_spots_dir=content,
    )

    assert result == reviewed
    assert reviewed.exists()
    rendered = (content / "hamilton-pool.md").read_text()
    assert "[[extra.schedules.sessions]]" in rendered
    assert "last_verified_at = \"2026-04-19\"" in rendered


def test_finalize_rejects_malformed_json(tmp_path):
    data_root = tmp_path / "data"
    review_dir = data_root / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa"
    review_dir.mkdir(parents=True)
    reviewed = review_dir / "reviewed.json"
    reviewed.write_text("{ bogus")

    with pytest.raises(FinalizeError, match="invalid JSON"):
        finalize_draft(
            reviewed_json_path=reviewed,
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert reviewed.exists()


def test_finalize_rejects_schema_invalid(tmp_path):
    data_root = tmp_path / "data"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    del envelope["source_pdf_url"]  # violates required
    reviewed = _write_reviewed(data_root, "hamilton-pool", "a" * 64, envelope)

    with pytest.raises(FinalizeError, match="source_pdf_url"):
        finalize_draft(
            reviewed_json_path=reviewed,
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert reviewed.exists()


def test_finalize_rejects_validate_failure(tmp_path):
    data_root = tmp_path / "data"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = envelope["payload"]["sessions"][:2]
    reviewed = _write_reviewed(data_root, "hamilton-pool", "a" * 64, envelope)

    with pytest.raises(FinalizeError, match="fewer than 5"):
        finalize_draft(
            reviewed_json_path=reviewed,
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert reviewed.exists()


def _write_provider_artifact(review_dir: Path, payload: dict) -> Path:
    path = review_dir / "gemini-gemini-3-1-flash-lite-preview.json"
    path.write_text(json.dumps({"payload": payload}))
    return path


def test_finalize_accepts_byte_identical_provider_payload(tmp_path):
    data_root = tmp_path / "data"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    reviewed = _write_reviewed(data_root, "hamilton-pool", "a" * 64, envelope)
    _write_provider_artifact(reviewed.parent, envelope["payload"])
    _seed_content_md(tmp_path / "content" / "spots", "hamilton-pool")

    result = finalize_draft(
        reviewed_json_path=reviewed,
        content_spots_dir=tmp_path / "content" / "spots",
    )
    assert result == reviewed


def test_finalize_allows_byte_identical_direct_payload(tmp_path):
    data_root = tmp_path / "data"
    envelope = _valid_draft_envelope("pomeroy-pool", "a" * 64)
    reviewed = _write_reviewed(data_root, "pomeroy-pool", "a" * 64, envelope)
    path = reviewed.parent / "direct-pomeroy-html-v1.json"
    path.write_text(json.dumps({"provider": "direct", "payload": envelope["payload"]}))
    _seed_content_md(tmp_path / "content" / "spots", "pomeroy-pool")

    result = finalize_draft(
        reviewed_json_path=reviewed,
        content_spots_dir=tmp_path / "content" / "spots",
    )

    assert result == reviewed


def _seed_content_with_sessions(content_dir: Path, slug: str, n: int = 5) -> Path:
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    sessions = "\n".join(
        (
            "[[extra.schedules.sessions]]\n"
            f'day = "{days[i]}"\n'
            'type = "lap_swim"\n'
            'start = "07:00"\n'
            'end = "08:00"\n'
        )
        for i in range(n)
    )
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        'title = "X"\n\n'
        "[extra]\n\n"
        "[[extra.schedules]]\n"
        'effective_start = "2026-03-17"\n'
        'schedule_basis = "swim_schedule"\n'
        'effective_end = "2026-06-06"\n'
        'last_verified_at = "2026-04-19"\n\n'
        f"{sessions}"
        "+++\n"
    )
    return path


def test_finalize_drop_to_zero_fails_unless_temporarily_closed(tmp_path):
    data_root = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = []
    envelope["payload"]["schedule_basis"] = "swim_schedule"
    reviewed = _write_reviewed(data_root, "hamilton-pool", "a" * 64, envelope)
    _seed_content_with_sessions(content, "hamilton-pool")

    with pytest.raises(FinalizeError, match="dropped to 0"):
        finalize_draft(reviewed_json_path=reviewed, content_spots_dir=content)
    assert reviewed.exists()

    envelope["payload"]["schedule_basis"] = "temporarily_closed"
    reviewed.write_text(json.dumps(envelope))
    result = finalize_draft(reviewed_json_path=reviewed, content_spots_dir=content)
    assert result == reviewed


def test_finalize_accepts_payload_with_any_diff_from_provider(tmp_path):
    data_root = tmp_path / "data"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    reviewed = _write_reviewed(data_root, "hamilton-pool", "a" * 64, envelope)
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
