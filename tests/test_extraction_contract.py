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
import subprocess
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


def test_prompt_separates_session_cancellations_from_facility_closures() -> None:
    prompt = PROMPT_PATH.read_text()
    assert "Never copy facility holiday, maintenance, or training closure dates into session excluded_dates" in prompt
    assert "A date list inside a session cell does not limit a separate facility recurring closure" in prompt


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


@pytest.fixture
def monthly_budget(tmp_path):
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    def git(*args, cwd=tmp_path):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "--bare", "--initial-branch=main", str(remote))
    git("clone", str(remote), str(repo))
    git("config", "user.name", "Budget test", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "baseline.txt").write_text("baseline\n")
    git("add", "baseline.txt", cwd=repo)
    git("commit", "-m", "Baseline", cwd=repo)
    git("push", "origin", "main", cwd=repo)
    budget = openai_provider.MonthlySpendBudget(repo, 1)
    return budget, git, remote


def test_monthly_accounting_requires_explicit_initialization(monthly_budget):
    budget, git, remote = monthly_budget
    with pytest.raises(ValueError, match="initialization"):
        budget.reserve("2026-09", "1-1")
    budget.initialize()
    with pytest.raises(ValueError, match="must not be reset"):
        budget.initialize()
    before = git("rev-parse", "HEAD", cwd=budget.repo_root)
    receipt = budget.reserve("2026-09", "1-1")
    assert receipt["limit_microusd"] == 1_000_000
    assert git("rev-parse", "HEAD", cwd=budget.repo_root) == before
    assert git("status", "--porcelain", cwd=budget.repo_root) == ""
    assert git("rev-parse", "refs/heads/main", cwd=remote) == before


def test_monthly_budget_retains_interrupted_runs_and_survives_new_instances(monthly_budget):
    budget, _, _ = monthly_budget
    budget.initialize()
    receipt = budget.reserve("2026-09", "1-1")
    restarted = openai_provider.MonthlySpendBudget(budget.repo_root, 1)
    with pytest.raises(ValueError, match="exhausted"):
        restarted.reserve("2026-09", "2-1")
    with pytest.raises(ValueError, match="already has"):
        restarted.reserve("2026-09", "1-1")
    restarted.settle(receipt, budget.repo_root / "missing-run-ledger.json")
    assert restarted._load()[1]["months"]["2026-09"]["runs"]["1-1"]["charged_microusd"] == 1_000_000
    assert restarted.reserve("2026-10", "3-1")["limit_microusd"] == 1_000_000
    assert set(restarted._load()[1]["months"]) == {"2026-09", "2026-10"}


def test_monthly_settlement_releases_only_recorded_unspent_allowance(monthly_budget, tmp_path):
    budget, _, _ = monthly_budget
    budget.initialize()
    receipt = budget.reserve("2026-09", "1-1")
    ledger = tmp_path / "run.json"
    ledger.write_text(json.dumps({"limit_microusd": 1_000_000, "requests": [
        {"id": "request", "reserved_microusd": 300_000, "charged_microusd": 250_000, "status": "completed"},
    ]}))
    budget.settle(receipt, ledger)
    with pytest.raises(ValueError, match="already settled"):
        budget.settle(receipt, ledger)
    assert budget.reserve("2026-09", "2-1")["limit_microusd"] == 750_000
    with pytest.raises(ValueError, match="exhausted"):
        budget.reserve("2026-09", "3-1")


@pytest.mark.parametrize("ledger", [
    {"limit_microusd": 1_000_000, "requests": [{"charged_microusd": -1}]},
    {"limit_microusd": 1_000_000, "requests": [{"charged_microusd": 2_000_000}]},
    {"limit_microusd": 1_000_000, "requests": [], "blocked": True},
    {"limit_microusd": 10_000_000, "requests": []},
    {"limit_microusd": 1_000_000, "requests": ["malformed"]},
    {"limit_microusd": 1_000_000, "requests": [{"id": "request", "reserved_microusd": 300_000, "charged_microusd": 0, "status": "reserved"}]},
])
def test_invalid_run_accounting_blocks_later_months(monthly_budget, tmp_path, ledger):
    budget, _, _ = monthly_budget
    budget.initialize()
    receipt = budget.reserve("2026-09", "1-1")
    path = tmp_path / "run.json"
    path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="blocked"):
        budget.settle(receipt, path)
    with pytest.raises(ValueError, match="blocked"):
        budget.reserve("2026-10", "2-1")


def test_monthly_approval_cannot_silently_reset_existing_limit(monthly_budget):
    budget, _, _ = monthly_budget
    budget.initialize()
    budget.reserve("2026-09", "1-1", 0.5)
    changed = openai_provider.MonthlySpendBudget(budget.repo_root, 10)
    with pytest.raises(ValueError, match="differs"):
        changed.reserve("2026-09", "2-1")


def test_concurrent_budget_writers_cannot_both_reserve_the_last_allowance(monthly_budget, monkeypatch):
    budget, _, _ = monthly_budget
    budget.initialize()
    competing = openai_provider.MonthlySpendBudget(budget.repo_root, 1)
    original_save = budget._save

    def race(parent, state, message):
        competing.reserve("2026-09", "2-1")
        original_save(parent, state, message)

    monkeypatch.setattr(budget, "_save", race)
    with pytest.raises(ValueError, match="no paid call is authorized"):
        budget.reserve("2026-09", "1-1")
    assert set(competing._load()[1]["months"]["2026-09"]["runs"]) == {"2-1"}


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
    pdf = REPO_ROOT / "data/balboa-pool/2026-08-20-d6f218710372/source.pdf"
    with pytest.raises(openai_provider.ClosureReviewRequired, match="Unresolved source closures") as held:
        openai_provider.extract(pdf.read_bytes(), PROMPT_PATH.read_text(), EXTRACTION_SCHEMA)
    assert held.value.issues
    assert all({"id", "text", "facility"}.issubset(notice) for notice in held.value.notices)
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
                           "pool_label_raw": "Wrong Pool", "evidence": cell.text, "notes": None, "excluded_dates": None}],
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



def test_north_beach_originals_pass_independent_coverage(north_beach_pair):
    entry, components = north_beach_pair
    for component, count in zip(components, (15, 20), strict=True):
        artifact = component["artifact"]
        assert len(artifact["payload"]["sessions"]) == count
        assert openai_provider.verify_artifact(artifact, component["document"], PROMPT_PATH.read_text())["ok"]


@pytest.mark.parametrize("member", [0, 1])
@pytest.mark.parametrize("damage", ["omission", "duplicate", "exclusion", "window", "closure", "configuration"])
def test_north_beach_each_original_rejects_bad_model_output(north_beach_pair, member, damage):
    import copy
    from schedules.schema import pool_label_payload
    _, components = north_beach_pair
    component = components[member]
    artifact = copy.deepcopy(component["artifact"])
    facts = artifact["details"]["source_facts"]
    if damage == "omission":
        facts["sessions"].pop()
    elif damage == "duplicate":
        facts["sessions"].append(facts["sessions"][0])
    elif damage == "exclusion":
        next(row for row in facts["sessions"] if row.get("excluded_dates"))["excluded_dates"] = []
    elif damage == "window":
        facts["effective_end"] = "2026-12-13"
    elif damage == "closure":
        facts["closures"].pop()
    else:
        artifact["details"]["configuration"]["reasoning"] = "low"
    if damage == "closure":
        with pytest.raises(ValueError, match="omit"):
            openai_provider.source_fact_payload(facts, openai_provider.inspect_pdf_source(component["document"]))
        return
    artifact["payload"] = openai_provider.source_fact_payload(facts, openai_provider.inspect_pdf_source(component["document"]))
    if damage == "configuration":
        with pytest.raises(ValueError, match="stale"):
            openai_provider.verify_artifact(artifact, component["document"], PROMPT_PATH.read_text())
    else:
        assert not openai_provider.verify_artifact(artifact, component["document"], PROMPT_PATH.read_text())["ok"]



def test_paired_pool_closure_never_becomes_facility_wide(north_beach_pair):
    from dataclasses import replace
    from schedules.signals import inspect_pdf_source, SourceNotice
    from schedules.grounding import source_closure_coverage
    _, components = north_beach_pair
    source = inspect_pdf_source(components[1]["document"])
    source = replace(source, notices=(SourceNotice("p1-notice", "Warm Pool will be CLOSED on September 24 from 12pm-2pm", True, physical_pool="warm"),))
    closure = {"start": "2026-09-24", "end": "2026-09-24", "start_time": "12:00", "end_time": "14:00", "reason": "Training"}
    assert not source_closure_coverage(source, {"closures": [closure]})["ok"]
    assert source_closure_coverage(source, {"closures": [closure | {"physical_pool": "warm"}]})["ok"]
    assert not source_closure_coverage(source, {"closures": [closure | {"physical_pool": "cool"}]})["ok"]


def test_session_exclusions_resolve_year_rollover_without_guessing(monkeypatch):
    from datetime import date
    from schedules import grounding
    from schedules.signals import SourceNotice
    cell = SourceCell("p1-c1-b1", 1, "thursday", "Lap Swim 11am-2pm (CLOSED 12/31 & 1/7)", (0, 0, 100, 100))
    source = PdfSource("North Beach Pool", (cell,), (), 1, (SourceNotice("p1-exclusion", cell.text, False, session_cell=cell.id),))
    monkeypatch.setattr(grounding, "source_window", lambda _: (date(2026, 12, 1), date(2027, 1, 31)))
    assert grounding.source_excluded_dates(source) == {cell.id: ["2026-12-31", "2027-01-07"]}
    monkeypatch.setattr(grounding, "source_window", lambda _: (date(2026, 12, 1), date(2028, 1, 31)))
    with pytest.raises(ValueError, match="ambiguous_exclusion_date"):
        grounding.source_excluded_dates(source)



@pytest.mark.parametrize("member", [0, 1])
def test_paired_original_uses_production_request_with_mocked_model_response(tmp_path, north_beach_pair, monkeypatch, member):
    from schedules.schema import SOURCE_FACTS_SCHEMA
    _, components = north_beach_pair
    component = components[member]
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "1")
    def transport(value, schema):
        if isinstance(value, dict):
            return {key: transport(value.get(key), child) for key, child in schema["properties"].items()}
        if isinstance(value, list):
            return [transport(item, schema["items"]) for item in value]
        return value
    response = transport(component["artifact"]["details"]["source_facts"], SOURCE_FACTS_SCHEMA)
    def call(request, *args):
        assert request["model"] == "gpt-5.5-2026-04-23"
        assert request["reasoning"] == {"effort": "medium"}
        assert "uniqueItems" not in json.dumps(request["text"]["format"]["schema"])
        assert "whole-session cancellations" in request["input"]
        return _usage_result(status="completed", output=[{"type": "message", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(response)}]}]) | {"http_status": 200, "timed_out": False}
    monkeypatch.setattr(openai_provider, "call_api", call)
    result = openai_provider.extract(component["document"], PROMPT_PATH.read_text().strip(), EXTRACTION_SCHEMA)
    assert result.payload == component["artifact"]["payload"]
    assert result.details["source_coverage"]["ok"] and result.details["source_closures"]["ok"]


def test_closure_display_code_comes_from_original_notice(north_beach_pair):
    import copy
    _, components = north_beach_pair
    component = components[0]
    artifact = copy.deepcopy(component['artifact'])
    facts = artifact['details']['source_facts']
    source = openai_provider.inspect_pdf_source(component['document'])
    expected = artifact['payload']['closures'][0]
    facts['closures'][0]['reason'] = 'A different model summary of the same closure'
    payload = openai_provider.source_fact_payload(facts, source)
    assert payload['closures'][0]['reason'] == facts['closures'][0]['reason']
    assert payload['closures'][0]['reason_code'] == expected['reason_code']
    assert payload['closures'][0]['source_notices'] == expected['source_notices']
    artifact['payload'] = payload
    assert openai_provider.verify_artifact(artifact, component['document'], PROMPT_PATH.read_text())['ok']
    artifact['payload']['closures'][0]['reason_code'] = 'holiday'
    with pytest.raises(ValueError, match='differs'):
        openai_provider.verify_artifact(artifact, component['document'], PROMPT_PATH.read_text())


def test_mlk_named_registered_lessons_are_not_public_sessions():
    from schedules.paths import REPO_ROOT
    from schedules.signals import inspect_pdf_source, program_types
    from schedules.grounding import source_slots

    source = inspect_pdf_source((REPO_ROOT / 'data/martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a/source.pdf').read_bytes())
    lessons = [cell for cell in source.cells if 'Bayview Safety Swim' in cell.text]
    assert len(lessons) == 4
    assert {cell.day for cell in lessons} == {'tuesday', 'wednesday', 'thursday', 'friday'}
    assert not source.issues
    assert all(program_types(cell.text) == () for cell in lessons)
    slots = source_slots(source)
    assert len(slots) == 23
    assert not {slot.cell.id for slot in slots} & {cell.id for cell in lessons}


def test_garfield_school_group_booking_is_not_public_family_swim():
    from schedules.paths import REPO_ROOT
    from schedules.signals import inspect_pdf_source, program_types

    source = inspect_pdf_source((REPO_ROOT / 'data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf').read_bytes())
    bookings = [cell for cell in source.cells if 'School Groups' in cell.text]
    assert len(bookings) == 1
    assert bookings[0].day == 'wednesday'
    assert program_types(bookings[0].text) == ()
    assert not any(issue.startswith(bookings[0].id + ':') for issue in source.issues)
    assert program_types('Rec/Family Swim (Small Pool) 2:00pm-3:45pm') == ('family_swim',)
    assert program_types('Senior/SFUSD 9am-11am') == ('senior_swim',)


@pytest.mark.parametrize('capture,heading,replacement', [
    ('martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a', 'Bayview Safety Swim\n& Splash', 'Bayview Safety Swim'),
    ('martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a', 'Bayview Safety Swim\n& Splash', 'Bayview Safety Swim & Splash Special'),
    ('garfield-pool/2026-08-20-7f5c0074e8dd', 'Rec/Family Swim\nSchool Groups', 'Rec/Family Swim School Group'),
    ('garfield-pool/2026-08-20-7f5c0074e8dd', 'Rec/Family Swim\nSchool Groups', 'Rec/Family Swim School Groups and Guests'),
    ('garfield-pool/2026-08-20-7f5c0074e8dd', 'Rec/Family Swim\nSchool Groups', 'Rec/Family Swim School Groups / Lap Swim / Water Exercise'),
    ('martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a', 'Bayview Safety Swim\n& Splash', 'Bayview Safety Swim & Splash / Senior Swim / Lessons'),
])
def test_changed_registered_program_names_remain_unknown(monkeypatch, capture, heading, replacement):
    from dataclasses import replace
    from schedules.paths import REPO_ROOT
    from schedules import signals

    original = signals._column_cells
    changed = []
    def changed_cells(page, header):
        cells = original(page, header)
        for cell in cells:
            if heading in cell.text:
                changed.append(cell.id)
        return [replace(cell, text=cell.text.replace(heading, replacement)) for cell in cells]
    monkeypatch.setattr(signals, '_column_cells', changed_cells)
    source = signals.inspect_pdf_source((REPO_ROOT / 'data' / capture / 'source.pdf').read_bytes())
    assert changed
    assert all(cell_id + ':unknown_program' in source.issues for cell_id in changed)


def test_column_boundary_characters_belong_to_exactly_one_weekday():
    from schedules.signals import _column_cells

    class Page:
        width, height, page_number = 200, 100, 1
        def __init__(self, objects):
            self.objects = objects
        def filter(self, predicate):
            return Page([item for item in self.objects if predicate(item)])
        def crop(self, bounds):
            return Page([item for item in self.objects if item['x1'] > bounds[0] and item['x0'] < bounds[2]])
        def extract_text_lines(self, **kwargs):
            return [{'text': ' '.join(item['text'] for item in self.objects if item['object_type'] == 'char'),
                     'top': 20, 'bottom': 30}]

    page = Page([
        {'object_type': 'char', 'text': 'Lap Swim 9am-10am', 'x0': 20, 'x1': 80},
        {'object_type': 'char', 'text': 'Lap Swim 9am-10am', 'x0': 120, 'x1': 180},
        {'object_type': 'char', 'text': 'A', 'x0': 94, 'x1': 104},
        {'object_type': 'char', 'text': 'W', 'x0': 95, 'x1': 107},
        {'object_type': 'char', 'text': 'B', 'x0': 99, 'x1': 101},
        {'object_type': 'rect', 'x0': 0, 'x1': 200},
    ])
    header = [{'text': 'SUNDAY', 'x0': 40, 'x1': 60, 'bottom': 10},
              {'text': 'MONDAY', 'x0': 140, 'x1': 160, 'bottom': 10}]
    cells = _column_cells(page, header)
    assert [(cell.day, cell.text) for cell in cells] == [
        ('sunday', 'Lap Swim 9am-10am A'), ('monday', 'Lap Swim 9am-10am W B'),
    ]


def test_garfield_boundary_keeps_monday_water_exercise_out_of_sunday_cell():
    from collections import Counter
    from schedules.paths import REPO_ROOT
    from schedules.signals import inspect_pdf_source
    from schedules.grounding import source_slots

    source = inspect_pdf_source((REPO_ROOT / 'data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf').read_bytes())
    shared = next(cell for cell in source.cells if cell.id == 'p1-c1-b3')
    assert shared.text == 'Lap Swim (Main Pool)\nRec/Family Swim\n(Small Pool)\n12:30 pm-2:00 pm'
    assert any(cell.day == 'monday' and 'Water Exercise-Instructor Led' in cell.text for cell in source.cells)
    slots = source_slots(source)
    assert Counter(slot.type for slot in slots) == {'lap_swim': 15, 'family_swim': 14, 'senior_swim': 4}
    assert [(slot.type, slot.pool) for slot in slots if slot.cell.id == shared.id] == [
        ('family_swim', 'small'), ('lap_swim', 'main'),
    ]
