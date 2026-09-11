"""The attested-snapshot envelope: its schema file and its validator.

`validate_envelope` is what every writer of a reviewed.json goes through;
the tests at the bottom read the schema document directly, because the
same file is the published contract and must stay in step with
EXTRACTION_SCHEMA and keep rejecting the fields earlier versions carried.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from schedules.envelope import (
    AttestationCarried,
    AttestationCi,
    AttestationHuman,
    AttestationLegacy,
    EnvelopeValidationError,
    load_envelope_schema,
    parse_attestation,
    validate_envelope,
)


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
            "effective_start": "2026-03-17",
            "schedule_basis": "swim_schedule",
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
    assert schema["title"] == "Attested snapshot"


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reviewed_at", "2026-99-99"),
        ("effective_start", "2026-02-30"),
        ("effective_end", "2026-99-99"),
    ],
)
def test_validate_envelope_rejects_impossible_dates(field, value):
    envelope = _valid_envelope()
    if field == "reviewed_at":
        envelope[field] = value
    else:
        envelope["payload"][field] = value

    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)


def test_validate_envelope_rejects_extra_top_level():
    envelope = _valid_envelope()
    envelope["bogus_field"] = True
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)


def test_validate_envelope_accepts_attested_by_ci():
    envelope = _valid_envelope()
    envelope["attested_by"] = "ci"
    validate_envelope(envelope)


def test_validate_envelope_accepts_omitted_attested_by():
    validate_envelope(_valid_envelope())
    assert "attested_by" not in _valid_envelope()


def test_validate_envelope_rejects_attested_by_robot():
    envelope = _valid_envelope()
    envelope["attested_by"] = "robot"
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)


def test_parse_attestation_four_states():
    assert isinstance(parse_attestation(_valid_envelope()), AttestationLegacy)
    human = {**_valid_envelope(), "attested_by": "human"}
    assert isinstance(parse_attestation(human), AttestationHuman)
    ci = {**_valid_envelope(), "attested_by": "ci"}
    assert isinstance(parse_attestation(ci), AttestationCi)
    carried = {**_valid_envelope(), "attested_by": "ci", "carried_from": "data/hamilton-pool/reviewed.json"}
    parsed = parse_attestation(carried)
    assert isinstance(parsed, AttestationCarried)
    assert isinstance(parsed.origin, AttestationCi)


# ---- the schema document itself ---------------------------------------------


def test_extraction_schema_is_the_envelope_payload():
    from schedules.schema import EXTRACTION_SCHEMA

    schema = _load_schema()
    assert EXTRACTION_SCHEMA["required"] == schema["properties"]["payload"]["required"]
    assert "schedule_basis" in EXTRACTION_SCHEMA["required"]
    closure = EXTRACTION_SCHEMA["properties"]["closures"]["items"]
    assert closure["dependentRequired"] == schema["$defs"]["closure"]["dependentRequired"]
    # Closures stay facility-wide and all-day by default: required is exactly
    # the date range plus a reason, and the optional v2 partial-day times are
    # the only extra fields either side knows about.
    assert closure["required"] == schema["$defs"]["closure"]["required"] == ["start", "end", "reason"]
    assert set(closure["properties"]) == set(schema["$defs"]["closure"]["properties"])
    assert {"start_time", "end_time"} <= set(closure["properties"])
    assert "pool" not in closure["properties"]


def test_schema_accepts_minimal_envelope():
    jsonschema.validate(instance=_valid_envelope(), schema=_load_schema())


def test_schema_accepts_access_hours_without_sessions():
    envelope = _valid_envelope()
    envelope["payload"]["sessions"] = []
    envelope["payload"]["access_hours"] = [
        {"day": "monday", "start": "05:30", "end": "20:30", "label": "Facility hours"}
    ]
    jsonschema.validate(instance=envelope, schema=_load_schema())


@pytest.mark.parametrize(
    "field,value",
    [
        ("$schema", "../schemas/reviewed-snapshot.json"),
        ("version", 1),
        ("reviewed_by", "reviewer@example.com"),
        ("reviewed_against", [{"provider": "gemini", "model": "x"}]),
        ("ratified_from_sha256", "b" * 64),
    ],
)
def test_schema_rejects_removed_fields(field, value):
    envelope = _valid_envelope()
    envelope[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=envelope, schema=_load_schema())
