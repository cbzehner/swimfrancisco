import json
from pathlib import Path

import pytest

from schedules.envelope import (
    EnvelopeValidationError,
    load_envelope_schema,
    validate_envelope,
)


def _valid_envelope() -> dict:
    return {
        "version": 1,
        "slug": "hamilton-pool",
        "pdf_sha256": "a" * 64,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_load_envelope_schema_returns_dict():
    schema = load_envelope_schema()
    assert isinstance(schema, dict)
    assert schema["title"].startswith("Reviewed Snapshot")


def test_validate_envelope_accepts_valid():
    validate_envelope(_valid_envelope())


def test_validate_envelope_rejects_missing_required():
    envelope = _valid_envelope()
    del envelope["source_pdf_url"]
    with pytest.raises(EnvelopeValidationError) as exc:
        validate_envelope(envelope)
    assert "source_pdf_url" in str(exc.value)


def test_validate_envelope_rejects_bad_time_format():
    envelope = _valid_envelope()
    envelope["payload"]["sessions"][0]["start"] = "7:00"  # schema requires HH:MM zero-padded
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)


def test_validate_envelope_rejects_extra_top_level():
    envelope = _valid_envelope()
    envelope["bogus_field"] = True
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)
