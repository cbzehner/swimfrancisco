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

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from schedules.paths import PROMPT_PATH
from schedules.providers import openai_provider
from schedules.schema import EXTRACTION_SCHEMA
from schedules.signals import PdfSource, SourceCell


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


def test_prompt_distinguishes_physical_pool_labels_from_program_lane_counts() -> None:
    prompt = PROMPT_PATH.read_text()
    assert "A program name followed by a lane count is not a pool allocation" in prompt
    assert "When shared programs have only numeric lane counts, use null for each program" in prompt


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


def _request() -> dict:
    return openai_provider.api_request("Extract this schedule", EXTRACTION_SCHEMA)


def _usage_result(input_tokens=100, output_tokens=200, **response_fields) -> dict:
    return {"status": "completed", "api_response": {
        "model": openai_provider.API_MODEL, "service_tier": "default",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "input_tokens_details": {"cached_tokens": input_tokens}},
        **response_fields,
    }}


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_api_budget_requires_positive_finite_limit(tmp_path, limit) -> None:
    with pytest.raises(ValueError, match="positive"):
        openai_provider.SpendBudget(tmp_path / "budget.json", limit)


def test_api_budget_stops_before_sending_unaffordable_request(tmp_path, monkeypatch) -> None:
    def unexpected_call(*args):
        pytest.fail("An unaffordable request reached the API")

    monkeypatch.setattr(openai_provider, "call_api", unexpected_call)
    with pytest.raises(ValueError, match="exhausted"):
        openai_provider.budgeted_call(_request(), tmp_path / "call", 1,
                                     openai_provider.SpendBudget(tmp_path / "budget.json", 0.01))


def test_api_budget_reserves_before_call_and_settles_conservatively(tmp_path, monkeypatch) -> None:
    path = tmp_path / "budget.json"
    request = _request()
    maximum = openai_provider.api_reservation_microusd(request)

    def call(*args):
        reservation = json.loads(path.read_text())["requests"][0]
        assert reservation["status"] == "reserved"
        assert reservation["charged_microusd"] == maximum
        return _usage_result()

    monkeypatch.setattr(openai_provider, "call_api", call)
    budget = openai_provider.SpendBudget(path, 1)
    openai_provider.budgeted_call(request, tmp_path / "call", 1, budget)
    item = json.loads(path.read_text())["requests"][0]
    assert item["charged_microusd"] == 6500  # Full input rate, even for cached tokens.
    assert item["status"] == "completed"
    with pytest.raises(ValueError, match="already settled"):
        budget.settle(item["id"], _usage_result())


@pytest.mark.parametrize("result", [
    {"status": "timeout"}, _usage_result(-1, 5), _usage_result(True, 5), _usage_result(None, 5),
])
def test_api_budget_keeps_reservation_without_trustworthy_usage(tmp_path, result) -> None:
    budget = openai_provider.SpendBudget(tmp_path / "budget.json", 1)
    identifier = budget.reserve(_request())
    budget.settle(identifier, result)
    item = json.loads(budget.path.read_text())["requests"][0]
    assert item["charged_microusd"] == item["reserved_microusd"]


def test_api_budget_retains_interrupted_reservation_and_rejects_limit_reset(tmp_path, monkeypatch) -> None:
    path = tmp_path / "budget.json"
    maximum = openai_provider.api_reservation_microusd(_request())
    limit = (maximum + 1) / 1_000_000

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(openai_provider, "call_api", interrupt)
    with pytest.raises(KeyboardInterrupt):
        openai_provider.budgeted_call(_request(), tmp_path / "call", 1,
                                     openai_provider.SpendBudget(path, limit))
    with pytest.raises(ValueError, match="exhausted"):
        openai_provider.SpendBudget(path, limit).reserve(_request())
    with pytest.raises(ValueError, match="differs"):
        openai_provider.SpendBudget(path, 10).reserve(_request())


@pytest.mark.parametrize("result", [
    _usage_result(1_000_000, 10), _usage_result(model="unexpected-model"),
    _usage_result(service_tier="priority"),
])
def test_api_accounting_error_blocks_later_calls(tmp_path, result) -> None:
    budget = openai_provider.SpendBudget(tmp_path / "budget.json", 10)
    identifier = budget.reserve(_request())
    with pytest.raises(ValueError, match="price reservation"):
        budget.settle(identifier, result)
    assert json.loads(budget.path.read_text())["blocked"] is True
    with pytest.raises(ValueError, match="blocked"):
        budget.reserve(_request())


def test_concurrent_api_requests_cannot_overbook_budget(tmp_path) -> None:
    path = tmp_path / "budget.json"
    maximum = openai_provider.api_reservation_microusd(_request())
    limit = (maximum + 1) / 1_000_000

    def reserve(_):
        try:
            return openai_provider.SpendBudget(path, limit).reserve(_request())
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        identifiers = list(workers.map(reserve, range(8)))
    assert sum(identifier is not None for identifier in identifiers) == 1
    assert len(json.loads(path.read_text())["requests"]) == 1


def test_ambiguous_source_requires_original_image_and_reserves_its_cost() -> None:
    cell = SourceCell("p1-c1-b1", 1, "monday", "Family Swim 3:30pm-5:30pm (s (small pool)", (0, 0, 100, 100))
    source = PdfSource("schedule", (cell,), ("p1-c1-b1:unbalanced_text",), 1, ())
    with pytest.raises(ValueError, match="rendered page"):
        openai_provider.source_request(source, "extract", {})
    request = openai_provider.source_request(source, "extract", {1: b"image-bytes"})
    part = request["input"][0]["content"][-1]
    assert part["detail"] == "original"
    assert part["image_url"].startswith("data:image/png;base64,")
    assert openai_provider.api_reservation_microusd(request) > 12_001 * 5 + 8192 * 30
    part["detail"] = "auto"
    with pytest.raises(ValueError, match="explicit original"):
        openai_provider.api_reservation_microusd(request)


def test_unresolved_closure_scope_stops_before_spend(tmp_path, monkeypatch):
    from schedules.paths import REPO_ROOT

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "1")

    def unexpected_call(*args, **kwargs):
        pytest.fail("An unresolved source reached the paid API")

    monkeypatch.setattr(openai_provider, "budgeted_call", unexpected_call)
    pdf = REPO_ROOT / "data/mission-community-pool/2026-09-02-67f2a420e8fc/source.pdf"
    with pytest.raises(ValueError, match="Unresolved source closures"):
        openai_provider.extract(pdf.read_bytes(), PROMPT_PATH.read_text(), EXTRACTION_SCHEMA)
    assert not (tmp_path / "budget.json").exists()


@pytest.mark.parametrize("pages,selected", [(0, {1}), (13, {1}), (1, {0}), (1, {2})])
def test_render_rejects_unsupported_page_selection_before_decoding(monkeypatch, pages, selected):
    from contextlib import nullcontext
    from types import SimpleNamespace

    monkeypatch.setattr(openai_provider.pdfplumber, "open", lambda _: nullcontext(SimpleNamespace(pages=[None] * pages)))
    with pytest.raises(ValueError, match="outside the supported source"):
        openai_provider.render_source_pages(b"pdf", frozenset(selected))


@pytest.mark.parametrize("width,height,count", [(2001, 500, 1), (500, 2001, 1), (2000, 2000, 2)])
def test_render_rejects_oversized_evidence_before_decoding(monkeypatch, width, height, count):
    from contextlib import nullcontext
    from types import SimpleNamespace

    document = SimpleNamespace(pages=[SimpleNamespace(width=width, height=height)] * count)
    monkeypatch.setattr(openai_provider.pdfplumber, "open", lambda _: nullcontext(document))
    with pytest.raises(ValueError, match="dimensions|megapixel"):
        openai_provider.render_source_pages(b"pdf", frozenset(range(1, count + 1)))


@pytest.mark.parametrize("http_status,timed_out,expected_calls", [
    (500, False, 2), (503, False, 2), (408, False, 2), (None, True, 2),
    (401, False, 1), (403, False, 1), (429, False, 1), (400, False, 1),
])
def test_production_retry_is_bounded_and_reserves_each_attempt(tmp_path, monkeypatch, http_status, timed_out, expected_calls):
    path = tmp_path / "budget.json"
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(path))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "2")
    source = PdfSource("Schedule August 11-August 29, 2026", (), (), 1, ())
    monkeypatch.setattr(openai_provider, "inspect_pdf_source", lambda _: source)
    monkeypatch.setattr(openai_provider, "time", type("Clock", (), {"sleep": staticmethod(lambda _: None)}))
    calls = []

    def call(*args):
        calls.append(args)
        assert len(json.loads(path.read_text())["requests"]) == len(calls)
        return {"api_response": None, "status": "timeout" if timed_out else "execution_error",
                "timed_out": timed_out, "http_status": http_status}

    monkeypatch.setattr(openai_provider, "call_api", call)
    with pytest.raises(ValueError, match="Extraction failed"):
        openai_provider.extract(b"pdf", "extract", EXTRACTION_SCHEMA)
    assert len(calls) == expected_calls
    requests = json.loads(path.read_text())["requests"]
    assert all(item["charged_microusd"] == item["reserved_microusd"] for item in requests)


def test_production_maps_raw_labels_and_preserves_failed_coverage(tmp_path, monkeypatch):
    from schedules.schema import SOURCE_FACTS_SCHEMA

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "1")
    cell = SourceCell("p1-c1-b1", 1, "monday", "Family Swim 3:30pm-5:30pm (small pool)", (0, 0, 100, 100))
    source = PdfSource("Schedule August 11-August 29, 2026", (cell,), (), 1, ())
    monkeypatch.setattr(openai_provider, "inspect_pdf_source", lambda _: source)
    facts = {"effective_start": "2026-08-11", "effective_end": "2026-08-29", "schedule_basis": "swim_schedule",
             "sessions": [{"day": "monday", "type": "family_swim", "start": "15:30", "end": "17:30",
                           "pool_label_raw": "Wrong Pool", "evidence": cell.text, "notes": None}],
             "closures": [], "access_hours": None, "access_exceptions": None}

    def call(request, *args):
        assert request["model"] == openai_provider.API_MODEL
        assert request["text"]["format"]["schema"] == openai_provider.api_transport_schema(SOURCE_FACTS_SCHEMA)
        return _usage_result(status="completed", output=[{
            "type": "message", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(facts)}],
        }]) | {"http_status": 200, "timed_out": False}

    monkeypatch.setattr(openai_provider, "call_api", call)
    result = openai_provider.extract(b"pdf", "extract", EXTRACTION_SCHEMA)
    assert result.payload["sessions"][0]["pool"] == "wrong"
    assert result.details["source_facts"]["sessions"][0]["pool_label_raw"] == "Wrong Pool"
    assert not result.details["source_coverage"]["ok"]
    assert result.details["source_window"]["ok"]
    assert result.details["final_response"] == json.dumps(facts)
