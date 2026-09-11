"""Transport, schema-mapping and budget behaviour of the production provider."""

import copy
import json

import jsonschema
import pytest

from conftest import SOURCE_REFERENCES, load_source_reference
from schedules.paths import REPO_ROOT
from schedules.providers import openai_provider
from schedules.providers.openai_provider import api_payload, api_response_result, api_transport_schema
from schedules.schema import EXTRACTION_SCHEMA, SOURCE_FACTS_SCHEMA, pool_label_payload


CHECK_PAYLOAD = {"check": "schedule-extraction", "sum": 42}
CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"check": {"type": "string"}, "sum": {"type": "integer"}},
    "required": ["check", "sum"],
}


def _reference(reference_id="hamilton-fall"):
    return load_source_reference(SOURCE_REFERENCES, reference_id, repo_root=REPO_ROOT)


def _expected_payload(reference):
    return copy.deepcopy(reference["expected"]) | {"closures": reference["expected"].get("closures", [])}


def _nullable_api_payload(value, schema):
    if isinstance(value, dict):
        return {name: _nullable_api_payload(value[name], child) if name in value else None
                for name, child in schema["properties"].items()}
    if isinstance(value, list):
        return [_nullable_api_payload(child, schema["items"]) for child in value]
    return value


def _api_response(payload):
    return {"model": openai_provider.API_MODEL, "status": "completed", "service_tier": "default",
            "output": [{"type": "message", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(payload)}]}],
            "usage": {"input_tokens": 100, "output_tokens": 50, "input_tokens_details": {"cached_tokens": 20}}}


@pytest.mark.parametrize("label, normalized", [
    (None, None), ("(Main Pool Only)", "main only"),
    ("2 lanes + Small Pool", "2 lanes + small"), ("4 & shallow", "4 & shallow"),
    (" W ", "w"), ("  Therapy   Pool ", "therapy"), ("Whirlpool", "whirlpool"),
    ("Pool", None),
])
def test_pool_label_normalization_preserves_source_facts(label, normalized):
    facts = _expected_payload(_reference())
    facts["sessions"] = [facts["sessions"][0] | {"pool_label_raw": label}]
    facts["sessions"][0].pop("pool", None)
    original = copy.deepcopy(facts)
    jsonschema.validate(facts, SOURCE_FACTS_SCHEMA)
    payload = pool_label_payload(facts)
    jsonschema.validate(payload, EXTRACTION_SCHEMA)
    assert facts == original
    assert "pool_label_raw" not in payload["sessions"][0]
    assert payload["sessions"][0].get("pool") == normalized
    assert "pool_label_raw" in EXTRACTION_SCHEMA["properties"]["sessions"]["items"]["properties"]


def test_source_facts_require_literal_label_and_reject_normalized_field():
    facts = _expected_payload(_reference())
    facts["sessions"] = [facts["sessions"][0] | {"pool_label_raw": None}]
    facts["sessions"][0].pop("pool", None)
    native = _nullable_api_payload(facts, SOURCE_FACTS_SCHEMA)
    result = api_response_result(_api_response(native), SOURCE_FACTS_SCHEMA)
    assert result["transport_valid"] and result["payload"] == facts
    native["sessions"][0]["pool"] = "main"
    assert not api_response_result(_api_response(native), SOURCE_FACTS_SCHEMA)["transport_valid"]
    native["sessions"][0].pop("pool")
    native["sessions"][0].pop("pool_label_raw")
    assert not api_response_result(_api_response(native), SOURCE_FACTS_SCHEMA)["transport_valid"]


def test_api_schema_mapping_is_explicit_and_does_not_repair_values():
    original = copy.deepcopy(EXTRACTION_SCHEMA)
    source = _expected_payload(_reference())
    native = _nullable_api_payload(source, EXTRACTION_SCHEMA)
    schema = api_transport_schema(EXTRACTION_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(native, schema)
    assert EXTRACTION_SCHEMA == original
    assert api_payload(native, EXTRACTION_SCHEMA) == source
    result = api_response_result(_api_response(native), EXTRACTION_SCHEMA)
    assert result["transport_valid"] and result["payload"] == source
    native["sessions"][0]["pool"] = "wrong literal label"
    assert api_response_result(_api_response(native), EXTRACTION_SCHEMA)["payload"]["sessions"][0]["pool"] == "wrong literal label"
    native["sessions"][0]["start"] = "25:00"
    assert api_response_result(_api_response(native), EXTRACTION_SCHEMA)["status"] == "transport_invalid"


@pytest.mark.parametrize("damage", ["incomplete", "refusal", "two_messages", "framing", "missing_field"])
def test_api_response_never_rescues_failed_or_invalid_output(damage):
    response = _api_response(CHECK_PAYLOAD)
    if damage == "incomplete":
        response["status"] = "incomplete"
    elif damage == "refusal":
        response["output"][0]["content"].append({"type": "refusal", "refusal": "No"})
    elif damage == "two_messages":
        response["output"].append(copy.deepcopy(response["output"][0]))
    elif damage == "framing":
        response["output"][0]["content"][0]["text"] = "```json\n" + json.dumps(CHECK_PAYLOAD) + "\n```"
    else:
        response = _api_response({"check": "schedule-extraction"})
    result = api_response_result(response, CHECK_SCHEMA)
    assert result["payload"] is None and not result["transport_valid"]
    assert result["status"] in {"provider_error", "transport_invalid"}


def test_api_closure_pairs_are_checked_after_null_mapping():
    payload = copy.deepcopy(_reference("garfield-maintenance")["expected"])
    payload["closures"][0]["start_time"] = "12:00"
    result = api_response_result(_api_response(_nullable_api_payload(payload, EXTRACTION_SCHEMA)), EXTRACTION_SCHEMA)
    assert result["transport_valid"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result["payload"], EXTRACTION_SCHEMA,
                            format_checker=jsonschema.FormatChecker())


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_budget_requires_an_explicit_positive_limit(tmp_path, limit):
    with pytest.raises(ValueError, match="positive API budget"):
        openai_provider.SpendBudget(tmp_path / "budget.json", limit)


def test_budgeted_call_reserves_before_paying_and_stops_when_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(openai_provider, "call_api",
                        lambda *args: pytest.fail("Budget guard made a paid call"))
    request = openai_provider.api_request("extract", CHECK_SCHEMA, max_output_tokens=1024)
    budget = openai_provider.SpendBudget(tmp_path / "budget.json", 0.000001)
    with pytest.raises(ValueError, match="budget exhausted"):
        openai_provider.budgeted_call(request, tmp_path / "call", 10, budget)
    assert not (tmp_path / "call").exists()


@pytest.mark.parametrize("failure", [401, 429, "timeout"])
def test_api_failure_stops_without_retry_or_secret_logs(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_PERSIST")
    real_client = openai_provider.httpx.Client
    calls = []

    def respond(request):
        calls.append(request)
        if failure == "timeout":
            raise openai_provider.httpx.ReadTimeout("DO_NOT_PERSIST")
        return openai_provider.httpx.Response(failure, json={"error": {"message": "DO_NOT_PERSIST"}})

    monkeypatch.setattr(openai_provider.httpx, "Client", lambda **kwargs: real_client(
        **kwargs, transport=openai_provider.httpx.MockTransport(respond)))
    directory = tmp_path / "call"
    result = openai_provider.call_api(
        openai_provider.api_request("extract", CHECK_SCHEMA, max_output_tokens=1024), directory, 10)
    assert len(calls) == 1
    assert result["status"] == ("timeout" if failure == "timeout" else "execution_error")
    assert result["api_response"] is None
    assert not (directory / "response.json").exists()
    assert all(b"DO_NOT_PERSIST" not in path.read_bytes() for path in directory.rglob("*") if path.is_file())
