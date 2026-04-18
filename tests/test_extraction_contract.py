"""Contract tests for the extraction prompt and schema.

The closure contract (v1) is: closures are facility-wide, all-day, date-only.
Timed or pool-scoped closures are a future schema migration and are
explicitly out of scope. These tests exist so the prompt and schema cannot
silently drift away from that contract — see docs/plans/review-followup.md
Step 1.
"""

from __future__ import annotations

from schedules.paths import PROMPT_PATH
from schedules.schema import EXTRACTION_SCHEMA


def _closure_properties() -> dict:
    return EXTRACTION_SCHEMA["properties"]["closures"]["items"]["properties"]


def _closure_required() -> list[str]:
    return EXTRACTION_SCHEMA["properties"]["closures"]["items"]["required"]


def test_prompt_forbids_timed_sfusd_rows_in_closures() -> None:
    prompt = PROMPT_PATH.read_text()
    assert (
        "Record these as a closure entry for that day and time" not in prompt
    ), "prompt still instructs providers to encode SFUSD slots as timed closures"
    assert (
        "Do not encode timed school-only bookings in closures[]" in prompt
    ), "prompt is missing the explicit guard against timed school bookings in closures"


def test_closures_are_date_only_and_facility_wide() -> None:
    props = _closure_properties()
    assert "start_time" not in props, "closures gained a start_time field (violates v1 contract)"
    assert "end_time" not in props, "closures gained an end_time field (violates v1 contract)"
    assert "pool" not in props, "closures[].pool still present (pool-scoped closures are out of scope)"


def test_closure_required_fields_are_exactly_start_end_reason() -> None:
    assert set(_closure_required()) == {"start", "end", "reason"}
