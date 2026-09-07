from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "schedule-tools" / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest


@pytest.fixture
def north_beach_pair():
    """Frozen fall originals and independent visual transcriptions; never production input."""
    from schedules.models import PoolEntry, PoolSource
    from schedules.schema import pool_label_payload
    from schedules.providers import openai_provider
    from schedules.signals import inspect_pdf_source
    from schedules.grounding import source_publication_coverage
    from schedules.paths import PROMPT_PATH
    import hashlib

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
        payload = pool_label_payload(facts)
        source = inspect_pdf_source(document)
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
