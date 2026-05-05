"""Contract tests for the extraction prompt and schema.

The closure contract (v2) is: closures are facility-wide. By default they
are all-day (start..end inclusive, no time fields). Single-day closures MAY
carry optional `start_time` / `end_time` (24-hour HH:MM) to mark a
partial-day window — both must appear together, and they're not allowed on
multi-day ranges. Pool-scoped closures remain out of scope.

The original v1 contract (no times at all) was lifted in 2026-05 to model
SF Rec & Park's recurring partial-day "Aquatics Division Training"
windows, which were previously rounded to all-day and over-reported pool
unavailability. These tests guard the v2 boundaries.
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


def test_closures_have_optional_partial_day_time_fields() -> None:
    props = _closure_properties()
    assert "start_time" in props, "closures lost the v2 partial-day start_time field"
    assert "end_time" in props, "closures lost the v2 partial-day end_time field"
    assert "pool" not in props, "closures[].pool reintroduced (pool-scoped closures are still out of scope)"
    # start_time/end_time stay optional — required is still just date+reason.
    assert "start_time" not in _closure_required()
    assert "end_time" not in _closure_required()


def test_closure_required_fields_are_exactly_start_end_reason() -> None:
    assert set(_closure_required()) == {"start", "end", "reason"}
