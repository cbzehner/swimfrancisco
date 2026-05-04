import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schedule-tools"
    / "src"
    / "schedules"
    / "schemas"
    / "reviewed-snapshot.json"
)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _valid_envelope() -> dict:
    return {
        "slug": "hamilton-pool",
        "pdf_sha256": "a" * 64,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_schema_accepts_minimal_envelope():
    schema = _load_schema()
    jsonschema.validate(instance=_valid_envelope(), schema=schema)


@pytest.mark.parametrize(
    "field,value",
    [
        ("$schema", "../schemas/reviewed-snapshot.json"),
        ("version", 1),
        ("reviewed_by", "Chris Zehner <cbzehner@gmail.com>"),
        ("reviewed_against", [{"provider": "gemini", "model": "x"}]),
    ],
)
def test_schema_rejects_removed_fields(field, value):
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=envelope, schema=schema)


def test_schema_rejects_ratified_from_sha256():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["ratified_from_sha256"] = "b" * 64
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=envelope, schema=schema)
