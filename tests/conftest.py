from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "schedule-tools" / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import hashlib
import json
from datetime import date

import jsonschema
import pytest

from schedules.eval import RowKey
from schedules.providers import openai_provider
from schedules.schema import EXTRACTION_SCHEMA


SOURCE_REFERENCES = ROOT / "tests/fixtures/source-references.json"


def pin_publish_clock(monkeypatch, today: date) -> None:
    """Freeze the merge clock: publish prunes windows that expired relative to it,
    so a test with fixed 2026 fixture dates must say which day it is publishing on."""
    monkeypatch.setattr("schedules.merge.pacific_today", lambda: today)


def load_source_reference(path: Path, reference_id: str, *, repo_root: Path) -> dict:
    """Load one checked source reference and re-verify its PDF bytes."""
    references = json.loads(path.read_text())["documents"]
    matches = [item for item in references if item["id"] == reference_id]
    if len(matches) != 1:
        raise ValueError("Source reference must identify exactly one document.")
    reference = matches[0]
    if reference["split"] not in {"development", "finalist", "holdout"} or not reference.get("expected"):
        raise ValueError("This document is reserved or has no checked reference yet.")
    source = (repo_root / reference["source_pdf"]).resolve()
    if not source.is_relative_to(repo_root.resolve()):
        raise ValueError("Source reference must be inside the repository.")
    if hashlib.sha256(source.read_bytes()).hexdigest() != reference["source_sha256"]:
        raise ValueError("Source reference hash does not match the checked document.")
    expected = reference["expected"]
    try:
        jsonschema.validate(
            expected | {"closures": expected.get("closures", [])}, EXTRACTION_SCHEMA,
            format_checker=jsonschema.FormatChecker(),
        )
    except (jsonschema.ValidationError, TypeError, AttributeError) as exc:
        raise ValueError("Source reference contains invalid expected schedule data.") from exc
    rows = [RowKey.from_session(row) for row in expected["sessions"]]
    if len(rows) != len(set(rows)):
        raise ValueError("Source reference contains duplicate sessions.")
    if "as_of" in reference:
        date.fromisoformat(reference["as_of"])
    return reference


def api_usage_result(input_tokens=100, output_tokens=200, **response_fields) -> dict:
    """An OpenAI response envelope carrying trustworthy usage accounting."""
    return {"status": "completed", "api_response": {
        "model": openai_provider.API_MODEL, "service_tier": "default",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "input_tokens_details": {"cached_tokens": input_tokens}},
        **response_fields,
    }}


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


@pytest.fixture
def schedule_payload():
    """Build a minimal valid extraction payload: weekday lap-swim hours."""

    def build(effective_start: str = "2026-03-17", *, days=WEEKDAYS, **overrides) -> dict:
        return {
            "effective_start": effective_start,
            "schedule_basis": "swim_schedule",
            "sessions": [
                {"day": day, "type": "lap_swim", "start": "07:00", "end": "08:00",
                 "evidence": "Lap Swim 7-8am"}
                for day in days
            ],
            "closures": [],
        } | overrides

    return build


@pytest.fixture
def reviewed_envelope(schedule_payload):
    """Build an attested-snapshot envelope around `schedule_payload`."""

    def build(
        slug: str = "hamilton-pool",
        pdf_sha256: str = "a" * 64,
        *,
        reviewed_at: str = "2026-04-19",
        source_pdf_url: str = "https://example.com/schedule.pdf",
        payload: dict | None = None,
        **overrides,
    ) -> dict:
        return {
            "slug": slug,
            "pdf_sha256": pdf_sha256,
            "reviewed_at": reviewed_at,
            "source_pdf_url": source_pdf_url,
            "payload": schedule_payload() if payload is None else payload,
        } | overrides

    return build


@pytest.fixture
def north_beach_pair():
    """Frozen fall originals and independent visual transcriptions; never production input."""
    from schedules.models import PoolEntry, PoolSource
    from schedules.providers import openai_provider
    from schedules.signals import inspect_pdf_source
    from schedules.grounding import source_publication_coverage
    from schedules.paths import PROMPT_PATH

    rows = {
        "cool": {
            "tuesday": [("lap_swim", "07:30", "10:15"), ("lap_swim", "12:30", "15:00"), ("lap_swim", "15:30", "18:30")],
            "wednesday": [("lap_swim", "09:00", "10:15"), ("lap_swim", "11:45", "15:15"), ("lap_swim", "17:30", "18:30")],
            "thursday": [("lap_swim", "07:30", "11:00"), ("lap_swim", "11:00", "14:00"), ("lap_swim", "14:15", "15:15"), ("lap_swim", "16:00", "18:30")],
            "friday": [("lap_swim", "09:00", "10:15"), ("lap_swim", "11:45", "15:15"), ("lap_swim", "17:30", "19:30")],
            "saturday": [("lap_swim", "12:00", "13:30"), ("lap_swim", "13:45", "16:30")],
        },
        "warm": {
            "tuesday": [("lap_swim", "07:30", "09:00", "Lap/ Therapy"), ("senior_swim", "09:00", "10:15", "Lap/Therapy"), ("lap_swim", "12:00", "15:00", "Lap/Therapy"), ("family_swim", "15:30", "17:30"), ("lap_swim", "17:30", "18:30")],
            "wednesday": [("senior_swim", "09:00", "10:15", "Lap/Therapy"), ("lap_swim", "12:50", "15:15", "Lap/Therapy"), ("family_swim", "17:30", "18:30")],
            "thursday": [("lap_swim", "07:30", "09:00", "Lap/ Therapy"), ("senior_swim", "09:00", "11:00", "Lap/Therapy"), ("lap_swim", "11:15", "14:00", "Lap/Therapy"), ("lap_swim", "14:15", "15:15"), ("family_swim", "16:00", "17:30")],
            "friday": [("family_swim", "09:00", "10:15"), ("senior_swim", "09:00", "10:15"), ("lap_swim", "12:50", "15:15", "Lap/Therapy"), ("family_swim", "17:30", "19:00")],
            "saturday": [("family_swim", "12:00", "13:15"), ("lap_swim", "13:45", "15:00", "Lap/Therapy"), ("family_swim", "15:30", "17:00")],
        },
    }
    closures = [
        {"start": "2026-10-13", "end": "2026-10-31", "reason": "Annual maintenance"},
        *[{"start": day, "end": day, "start_time": "12:00", "end_time": "14:00", "reason": "Aquatics Division Training"} for day in ("2026-09-24", "2026-10-22", "2026-11-26")],
        {"start": "2026-11-11", "end": "2026-11-11", "reason": "Veteran's Day"},
        {"start": "2026-11-26", "end": "2026-11-27", "reason": "Thanksgiving"},
        {"start": "2026-12-12", "end": "2026-12-12", "start_time": "09:00", "end_time": "12:00", "reason": "Aquatics In-service Training"},
    ]
    components = []
    for pool, prefix, view in (("cool", "6c2b2e77fb23", 29953), ("warm", "ac196df42a14", 29954)):
        source_path = ROOT / "data/north-beach-pool" / ("2026-09-06-" + prefix) / "source.pdf"
        document = source_path.read_bytes()
        digest = hashlib.sha256(document).hexdigest()
        assert (source_path.parent / "source.sha256").read_text().strip() == digest
        sessions = []
        for day, values in rows[pool].items():
            for kind, start, end, *label in values:
                row = {"day": day, "type": kind, "start": start, "end": end, "pool_label_raw": label[0] if label else None}
                if day == "thursday" and start in {"11:00", "11:15"}:
                    row["excluded_dates"] = ["2026-09-24", "2026-10-22"]
                sessions.append(row)
        facts = {"effective_start": "2026-09-01", "effective_end": "2026-12-12", "schedule_basis": "swim_schedule", "sessions": sessions, "closures": closures}
        source = inspect_pdf_source(document)
        payload = openai_provider.source_fact_payload(facts, source)
        details = {"configuration": openai_provider.extraction_configuration(PROMPT_PATH.read_text().strip()),
                   "source_facts": facts, "visual_pages": [], "image_sha256": {},
                   "source_coverage": source_publication_coverage(source, payload)}
        url = f"https://sfrecpark.org/DocumentCenter/View/{view}"
        artifact = {"provider": "openai", "model": openai_provider.API_MODEL, "pdf_sha256": digest,
                    "source_pdf_url": url, "extracted_at": "2026-09-06T12:00:00Z", "payload": payload, "details": details}
        components.append({"pool": pool, "document": document, "artifact": artifact, "path": source_path})
    entry = PoolEntry("north-beach-pool", "", "https://sfrecpark.org/facilities/facility/details/North-Beach-Pool-218",
                      pool_sources=tuple(PoolSource(item["pool"], item["artifact"]["source_pdf_url"]) for item in components))
    return entry, components


@pytest.fixture
def mission_autumn_original():
    """Immutable original and visual transcription; never input or approval for production."""
    from schedules.signals import inspect_pdf_source

    path = ROOT / 'data/mission-community-pool/2026-10-18-43fd76a64a6f/source.pdf'
    document = path.read_bytes()
    digest = '43fd76a64a6fada732f0e6e26d50ef66fc39d2b6244350c03705477797362915'
    assert hashlib.sha256(document).hexdigest() == path.with_suffix('.sha256').read_text().strip() == digest
    rows = {
        'tuesday': [('lap_swim', '08:00', '09:00'), ('senior_swim', '09:15', '10:15'), ('lap_swim', '10:30', '12:00')],
        'wednesday': [('lap_swim', '08:00', '09:00'), ('senior_swim', '09:15', '10:15'), ('lap_swim', '10:30', '12:00')],
        'thursday': [('lap_swim', '08:00', '09:30'), ('senior_swim', '09:45', '11:45')],
        'friday': [('lap_swim', '08:00', '09:00'), ('senior_swim', '09:15', '10:15'), ('lap_swim', '10:30', '12:00')],
        'saturday': [('lap_swim', '10:00', '11:15'), ('family_swim', '11:30', '14:00')],
    }
    sessions = []
    for day, values in rows.items():
        for kind, start, end in values:
            row = {'day': day, 'type': kind, 'start': start, 'end': end, 'pool_label_raw': None}
            if day == 'tuesday' and start in {'09:15', '10:30'}:
                row['excluded_dates'] = ['2026-10-20']
            sessions.append(row)
    facts = {'effective_start': '2026-10-20', 'effective_end': '2026-11-21', 'schedule_basis': 'swim_schedule',
             'sessions': sessions, 'closures': [
                 {'start': '2026-10-20', 'end': '2026-10-20', 'start_time': '09:00', 'end_time': '12:30', 'reason': 'All-staff meeting'},
                 {'start': '2026-11-11', 'end': '2026-11-11', 'reason': 'Veterans Day'},
             ]}
    return {'document': document, 'sha256': digest, 'source': inspect_pdf_source(document), 'facts': facts}
