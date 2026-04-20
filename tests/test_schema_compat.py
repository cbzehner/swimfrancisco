import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "reviewed-snapshots" / "schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _valid_envelope() -> dict:
    return {
        "version": 1,
        "slug": "hamilton-pool",
        "pdf_sha256": "a" * 64,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "manual review",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_schema_accepts_ratification_envelope():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["reviewed_by"] = "ratification"
    envelope["ratified_from_sha256"] = "b" * 64
    jsonschema.validate(instance=envelope, schema=schema)


def test_schema_accepts_reviewed_by_without_ratification():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["reviewed_by"] = "manual"
    jsonschema.validate(instance=envelope, schema=schema)


def test_schema_rejects_bad_ratified_from_sha256():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["ratified_from_sha256"] = "not-a-hash"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=envelope, schema=schema)
