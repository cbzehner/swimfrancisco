import json
from datetime import date
from pathlib import Path

import pytest

from schedules.paths import slugify
from schedules.review import ReviewCandidate, seed_draft


def _write_provider(artifact_dir: Path, provider: str, model: str, pdf_sha256: str, sessions_count: int = 5) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{provider}-{slugify(model)}.json"
    path.write_text(json.dumps({
        "slug": "hamilton-pool",
        "provider": provider,
        "model": model,
        "pdf_url": "https://example.com/hamilton.pdf",
        "source_pdf_url": "https://example.com/hamilton.pdf",
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
        fetch_date="2026-04-01",
    )


def test_seed_draft_envelope_fields(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)
    _write_provider(artifact_dir, "anthropic", "claude-sonnet-4-6", "a" * 64)
    data_root = tmp_path / "data"

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        data_root=data_root,
        today=date(2026, 4, 19),
    )

    assert path == data_root / "hamilton-pool" / "2026-04-01-aaaaaaaaaaaa" / "reviewed.json"
    envelope = json.loads(path.read_text())
    assert envelope["slug"] == "hamilton-pool"
    assert envelope["pdf_sha256"] == "a" * 64
    assert envelope["reviewed_at"] == "2026-04-19"
    assert envelope["source_pdf_url"] == "https://example.com/hamilton.pdf"
    assert envelope["payload"]["schedule_effective"] == "2026-03-17"


def test_seed_draft_is_idempotent(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)
    data_root = tmp_path / "data"
    candidate = _make_candidate(artifact_dir, "a" * 64)

    first = seed_draft(candidate=candidate, data_root=data_root, today=date(2026, 4, 19))
    envelope = json.loads(first.read_text())
    envelope["reviewed_by"] = "Chris Zehner <cbzehner@gmail.com>"
    first.write_text(json.dumps(envelope, indent=2) + "\n")
    second = seed_draft(candidate=candidate, data_root=data_root, today=date(2026, 4, 20))

    assert first == second
    assert '"reviewed_by": "Chris Zehner <cbzehner@gmail.com>"' in second.read_text()


def test_seed_draft_uses_pacific_time_for_today(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)

    # 2026-04-20 00:30 UTC is 2026-04-19 17:30 PT — PT date must win.
    fixed_utc = datetime(2026, 4, 20, 0, 30, tzinfo=ZoneInfo("UTC"))

    class _FixedDatetime:
        @classmethod
        def now(cls, tz=None):
            return fixed_utc.astimezone(tz) if tz else fixed_utc.replace(tzinfo=None)

    monkeypatch.setattr("schedules.review._datetime", _FixedDatetime)

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        data_root=tmp_path / "data",
    )
    envelope = json.loads(path.read_text())
    assert envelope["reviewed_at"] == "2026-04-19"


def test_seed_draft_raises_when_no_provider_artifact(tmp_path):
    empty_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    empty_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        seed_draft(
            candidate=_make_candidate(empty_dir, "a" * 64),
            data_root=tmp_path / "data",
            today=date(2026, 4, 19),
        )
