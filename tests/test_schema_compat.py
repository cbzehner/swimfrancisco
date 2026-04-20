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
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_schema_accepts_human_reviewer_envelope():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["reviewed_by"] = "Chris Zehner <cbzehner@gmail.com>"
    jsonschema.validate(instance=envelope, schema=schema)


def test_schema_accepts_envelope_without_reviewed_by():
    # Legacy / LLM-generated snapshots omit reviewed_by entirely.
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope.pop("reviewed_by", None)
    jsonschema.validate(instance=envelope, schema=schema)


def test_schema_rejects_ratified_from_sha256():
    # The ratification field was removed; additionalProperties:false blocks it.
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["ratified_from_sha256"] = "b" * 64
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=envelope, schema=schema)
