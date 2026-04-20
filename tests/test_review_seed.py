import json
from datetime import date
from pathlib import Path

import pytest

from schedules.review import ReviewCandidate, seed_draft


def _write_provider(artifact_dir: Path, provider: str, model: str, pdf_sha256: str, sessions_count: int = 5) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    from schedules.artifacts import slugify
    path = artifact_dir / f"{provider}-{slugify(model)}.json"
    path.write_text(json.dumps({
        "slug": "hamilton-pool",
        "provider": provider,
        "model": model,
        "pdf_url": "https://example.com/hamilton.pdf",
        "pdf_sha256": pdf_sha256,
        "extracted_at": "2026-04-10T12:00:00+00:00",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")[:sessions_count]
            ],
            "closures": [],
        },
    }))
    return path


def _make_candidate(artifact_dir: Path, pdf_sha256: str, slug: str = "hamilton-pool") -> ReviewCandidate:
    return ReviewCandidate(
        slug=slug,
        pdf_sha256=pdf_sha256,
        artifact_dir=artifact_dir,
        pdf_path=None,
        pdf_date="2026-04-01",
    )


def test_seed_draft_prefers_gemini(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)
    _write_provider(artifact_dir, "anthropic", "claude-sonnet-4-6", "a" * 64)
    drafts_root = tmp_path / "drafts"

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        drafts_root=drafts_root,
        today=date(2026, 4, 19),
    )

    envelope = json.loads(path.read_text())
    providers = [r["provider"] for r in envelope["reviewed_against"]]
    assert providers[0] == "gemini"
    assert set(providers) == {"gemini", "anthropic"}
    assert envelope["slug"] == "hamilton-pool"
    assert envelope["pdf_sha256"] == "a" * 64
    assert envelope["reviewed_at"] == "2026-04-19"
    assert envelope["summary"] == "(draft)"
    assert envelope["payload"]["schedule_effective"] == "2026-03-17"


def test_seed_draft_falls_back_to_anthropic_when_no_gemini(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "anthropic", "claude-sonnet-4-6", "a" * 64)
    drafts_root = tmp_path / "drafts"

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        drafts_root=drafts_root,
        today=date(2026, 4, 19),
    )
    envelope = json.loads(path.read_text())
    assert envelope["reviewed_against"][0]["provider"] == "anthropic"


def test_seed_draft_falls_back_to_latest_mtime_for_unknown_provider(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    older = _write_provider(artifact_dir, "future", "model-v1", "a" * 64)
    newer = _write_provider(artifact_dir, "other", "model-v2", "a" * 64)
    import os, time
    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        drafts_root=tmp_path / "drafts",
        today=date(2026, 4, 19),
    )
    envelope = json.loads(path.read_text())
    assert envelope["reviewed_against"][0]["provider"] == "other"


def test_seed_draft_is_idempotent(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)
    drafts_root = tmp_path / "drafts"
    candidate = _make_candidate(artifact_dir, "a" * 64)

    first = seed_draft(candidate=candidate, drafts_root=drafts_root, today=date(2026, 4, 19))
    first.write_text(first.read_text().replace('"(draft)"', '"reviewer edits"'))
    second = seed_draft(candidate=candidate, drafts_root=drafts_root, today=date(2026, 4, 20))

    assert first == second
    assert '"reviewer edits"' in second.read_text()


def test_seed_draft_raises_when_no_provider_artifact(tmp_path):
    empty_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    empty_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        seed_draft(
            candidate=_make_candidate(empty_dir, "a" * 64),
            drafts_root=tmp_path / "drafts",
            today=date(2026, 4, 19),
        )
