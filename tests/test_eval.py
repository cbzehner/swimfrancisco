import json
import copy
import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.eval import collect_pool_evals, load_benchmark_reference, render_report, score_benchmark_run
from schedules.paths import REPO_ROOT


BENCHMARK_ARCHIVE = REPO_ROOT / "benchmarks/pdf/finalists-2026-09-05.zip"


@pytest.fixture
def replay_fixture_archive(tmp_path):
    """Synthetic current-code fixture, not a replacement for historical evidence."""
    from schedules.benchmark import benchmark_implementation

    with zipfile.ZipFile(BENCHMARK_ARCHIVE) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    implementation = benchmark_implementation(REPO_ROOT)
    metadata = json.loads(files["archive.json"])
    run = json.loads(files["run.json"])
    files["reference-manifest.json"] = (REPO_ROOT / "tests/fixtures/schedule-benchmark.json").read_bytes()
    run["reference_manifest_sha256"] = hashlib.sha256(files["reference-manifest.json"]).hexdigest()
    run["implementation_sha256"] = implementation
    files["run.json"] = json.dumps(run).encode()
    metadata["implementation_sha256"] = implementation
    metadata["implementation_capture"] = "Synthetic test fixture for current code; not historical replay."
    metadata["files"]["run.json"] = hashlib.sha256(files["run.json"]).hexdigest()
    metadata["files"]["reference-manifest.json"] = run["reference_manifest_sha256"]
    files["archive.json"] = json.dumps(metadata).encode()
    path = tmp_path / "replay-fixture.zip"
    with zipfile.ZipFile(path, "x") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.mark.parametrize("filename, digest", [
    ("finalists-2026-09-05.zip", "896aaf49a086c755cd86aad29215808563316a97b4071f753f0214ecae84231a"),
    ("api-confirmation-2026-09-05.zip", "67767c80b0afe9908ae527b51ad59889ef2bba0bd4d610b84507f462151c78da"),
    ("literal-pool-labels-2026-09-05.zip", "1358cde019fcfb23cc9b76e70f724c80e82fc2276de8c416e676f6ba842bb07c"),
    ("source-inventory-2026-09-05.zip", "daa9543d0511a940cbb52c7627ba37c9b92567443b950c31a2c8be53d2b3a3e9"),
    ("physical-pool-labels-2026-09-05.zip", "58bb90ccbd6f8f278744f6d6c919f7ceba6e85690a0f97c64a2b4a9b31b0090b"),
    ("mission-holdout-2026-09-05.zip", "8656d13e551772e03ea601a992b427f9ea44f7b2de76e24573f25ffa0e992178"),
])
def test_historical_benchmark_archive_remains_pinned_to_its_source_revision(tmp_path, filename, digest):
    from schedules.benchmark import benchmark_implementation, replay_benchmark

    archive_path = REPO_ROOT / "benchmarks/pdf" / filename
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(archive_path) as archive:
        implementation = json.loads(archive.read("archive.json"))["implementation_sha256"]
    if implementation != benchmark_implementation(REPO_ROOT):
        with pytest.raises(ValueError, match="implementation changed"):
            replay_benchmark(archive_path, tmp_path / "historical", REPO_ROOT)
        assert not (tmp_path / "historical").exists()
    else:
        replay_benchmark(archive_path, tmp_path / "historical", REPO_ROOT)

@pytest.fixture(scope="module")
def api_inputs():
    from schedules.benchmark import prepare_benchmark

    return prepare_benchmark(REPO_ROOT / "tests/fixtures/schedule-benchmark.json",
                             REPO_ROOT, None, "source-inventory")


def _nullable_api_payload(value, schema):
    if isinstance(value, dict):
        return {name: _nullable_api_payload(value[name], child) if name in value else None
                for name, child in schema["properties"].items()}
    if isinstance(value, list):
        return [_nullable_api_payload(child, schema["items"]) for child in value]
    return value


def _api_response(payload):
    from schedules.benchmark import API_MODEL
    return {"model": API_MODEL, "status": "completed", "service_tier": "default",
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
    import jsonschema
    from schedules.schema import EXTRACTION_SCHEMA, SOURCE_FACTS_SCHEMA, pool_label_payload

    facts = copy.deepcopy(_attempt(_reference())["payload"])
    facts["sessions"] = [facts["sessions"][0] | {"pool_label_raw": label}]
    facts["sessions"][0].pop("pool", None)
    original = copy.deepcopy(facts)
    jsonschema.validate(facts, SOURCE_FACTS_SCHEMA)
    payload = pool_label_payload(facts)
    jsonschema.validate(payload, EXTRACTION_SCHEMA)
    assert facts == original
    assert "pool_label_raw" not in payload["sessions"][0]
    assert payload["sessions"][0].get("pool") == normalized
    assert "pool_label_raw" not in EXTRACTION_SCHEMA["properties"]["sessions"]["items"]["properties"]


def test_source_facts_require_literal_label_and_reject_normalized_field():
    from schedules.benchmark import api_response_result
    from schedules.schema import SOURCE_FACTS_SCHEMA

    facts = copy.deepcopy(_attempt(_reference())["payload"])
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
    import jsonschema
    from schedules.benchmark import api_transport_schema, api_payload, api_response_result
    from schedules.schema import EXTRACTION_SCHEMA

    original = copy.deepcopy(EXTRACTION_SCHEMA)
    source = _attempt(_reference())["payload"]
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
    from schedules.benchmark import api_response_result, CHECK_SCHEMA, CHECK_PAYLOAD

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
        response = _api_response({"check": "schedule-benchmark"})
    result = api_response_result(response, CHECK_SCHEMA)
    assert result["payload"] is None and not result["transport_valid"]
    assert result["status"] in {"provider_error", "transport_invalid"}


def test_api_closure_pairs_are_checked_after_null_mapping():
    from schedules.benchmark import api_response_result
    from schedules.schema import EXTRACTION_SCHEMA

    reference = _reference("garfield-maintenance")
    payload = copy.deepcopy(reference["expected"])
    payload["closures"][0]["start_time"] = "12:00"
    result = api_response_result(_api_response(_nullable_api_payload(payload, EXTRACTION_SCHEMA)), EXTRACTION_SCHEMA)
    assert result["transport_valid"]
    assert score_benchmark_run(reference, _attempt(reference) | {"payload": result["payload"]})["status"] == "schema_invalid"


@pytest.mark.parametrize("budget", [0, -1, 11, float("nan"), float("inf"), 0.01])
def test_api_budget_failure_makes_no_calls(api_inputs, tmp_path, monkeypatch, budget):
    import schedules.benchmark as benchmark
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setattr(benchmark, "budgeted_call", lambda *args: pytest.fail("Budget guard made a paid call"))
    output = tmp_path / "results"
    with pytest.raises(ValueError, match="budget|reservation"):
        benchmark.run_api_benchmark(api_inputs, output, REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT, budget, 10)
    assert not output.exists()


@pytest.mark.parametrize("failure", [401, 429, "timeout"])
def test_api_readiness_failure_stops_without_retry_or_secret_logs(api_inputs, tmp_path, monkeypatch, failure):
    import schedules.benchmark as benchmark

    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_PERSIST")
    real_client = benchmark.httpx.Client
    calls = []

    def respond(request):
        calls.append(request)
        if failure == "timeout":
            raise benchmark.httpx.ReadTimeout("DO_NOT_PERSIST")
        return benchmark.httpx.Response(failure, json={"error": {"message": "DO_NOT_PERSIST"}})

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **kwargs: real_client(
        **kwargs, transport=benchmark.httpx.MockTransport(respond)))
    output = tmp_path / "failed"
    with pytest.raises(ValueError, match="readiness failed"):
        benchmark.run_api_benchmark(api_inputs, output, REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT, 10, 10)
    assert len(calls) == 1
    assert not (output / "results.json").exists()
    assert all(b"DO_NOT_PERSIST" not in path.read_bytes() for path in output.rglob("*") if path.is_file())


def test_api_run_archives_and_replays_requests_responses_and_budget(api_inputs, tmp_path, monkeypatch):
    import schedules.benchmark as benchmark
    from schedules.schema import SOURCE_FACTS_SCHEMA

    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_ARCHIVE")
    manifest = REPO_ROOT / "tests/fixtures/schedule-benchmark.json"
    _, references = benchmark.load_prepared_inputs(api_inputs, manifest, REPO_ROOT)
    payloads = {}
    for reference in references:
        facts = copy.deepcopy(reference["expected"])
        facts.setdefault("closures", [])
        facts["sessions"] = [
            {key: value for key, value in row.items() if key != "pool"} | {"pool_label_raw": row.get("pool")}
            for row in facts["sessions"]
        ]
        request = benchmark.prepared_source_request(api_inputs, reference["source_sha256"])
        payloads[json.dumps(request, sort_keys=True)] = _nullable_api_payload(facts, SOURCE_FACTS_SCHEMA)
    real_client = benchmark.httpx.Client
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url == benchmark.API_ENDPOINT
        assert request.headers["Authorization"] == "Bearer DO_NOT_ARCHIVE"
        assert body["tools"] == [] and body["store"] is False and body["service_tier"] == "default"
        payload = benchmark.CHECK_PAYLOAD if body["input"] == benchmark.CHECK_PROMPT else payloads[json.dumps(body, sort_keys=True)]
        response = _api_response(payload) | {"private_metadata": "DO_NOT_ARCHIVE"}
        response["output"].insert(0, {"type": "reasoning", "encrypted_content": "DO_NOT_ARCHIVE"})
        return benchmark.httpx.Response(200, json=response)

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **kwargs: real_client(
        **kwargs, transport=benchmark.httpx.MockTransport(respond)))
    output = tmp_path / "api-results"
    rows = benchmark.run_api_benchmark(api_inputs, output, manifest, REPO_ROOT, 10, 10, progress=lambda _: None)
    assert len(calls) == 22 and len(rows) == 21
    assert all(row["score"]["checked_fields_match"] for row in rows)
    assert all(row["source_coverage"]["ok"] and row["source_window"]["ok"] for row in rows)
    assert all(row["cost_usd"] == 0.00191 for row in rows)
    exported = tmp_path / "api.zip"
    benchmark.archive_benchmark(api_inputs, output, exported, manifest, REPO_ROOT)
    with zipfile.ZipFile(exported) as archive:
        assert all(b"DO_NOT_ARCHIVE" not in archive.read(name) for name in archive.namelist())
    monkeypatch.setattr(benchmark.httpx, "Client", lambda **kwargs: pytest.fail("Replay made a network call"))
    benchmark.replay_benchmark(exported, tmp_path / "api-replayed", REPO_ROOT)


def _write_review(
    data_root: Path,
    slug: str,
    fetch_date: str,
    sha12: str,
    truth_sessions: list[dict],
    provider_sessions: list[dict],
    provider_filename: str = "gemini-gemini-3-1-flash-lite-preview.json",
    *,
    attested_by: str | None = None,
    carried_from: str | None = None,
) -> Path:
    review_dir = data_root / slug / f"{fetch_date}-{sha12}"
    review_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "slug": slug,
        "pdf_sha256": sha12 + ("0" * (64 - len(sha12))),
        "reviewed_at": "2026-04-19",
        "source_pdf_url": "https://example.com/x.pdf",
        "payload": {
            "effective_start": "2026-04-21",
            "sessions": truth_sessions,
            "closures": [],
        },
    }
    if attested_by is not None:
        envelope["attested_by"] = attested_by
    if carried_from is not None:
        envelope["carried_from"] = carried_from
    (review_dir / "reviewed.json").write_text(json.dumps(envelope))
    (review_dir / provider_filename).write_text(
        json.dumps({"payload": {"sessions": provider_sessions, "closures": []}})
    )
    return review_dir


def _row(day: str, typ: str, start: str, end: str) -> dict:
    return {"day": day, "type": typ, "start": start, "end": end}


def test_collect_perfect_match(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    e = evals[0]
    assert e.true_positives == 1
    assert e.false_positives == 0
    assert e.false_negatives == 0
    assert e.precision == 1.0 and e.recall == 1.0 and e.f1 == 1.0


def test_collect_extra_and_missing(tmp_path):
    truth = [_row("monday", "lap_swim", "07:00", "08:00")]
    extracted = [_row("tuesday", "lap_swim", "09:00", "10:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", truth, extracted)
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    e = evals[0]
    assert e.true_positives == 0
    assert e.false_positives == 1
    assert e.false_negatives == 1
    assert e.f1 == 0.0


def test_collect_treats_pool_field_as_row_identity(tmp_path):
    truth = [_row("monday", "lap_swim", "07:00", "08:00") | {"pool": "warm"}]
    extracted = [_row("monday", "lap_swim", "07:00", "08:00") | {"pool": "cool"}]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", truth, extracted)
    evals = collect_pool_evals(data_root=tmp_path)

    assert len(evals) == 1
    e = evals[0]
    assert e.true_positives == 0
    assert e.false_positives == 1
    assert e.false_negatives == 1


def test_default_excludes_older_review_dirs(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-10", "aaaaaaaaaaaa", sessions, sessions)
    _write_review(tmp_path, "x-pool", "2026-04-19", "bbbbbbbbbbbb", sessions, sessions)
    evals = collect_pool_evals(data_root=tmp_path)
    # Only the newer review dir is included
    assert len(evals) == 1
    assert "2026-04-19" in str(evals[0].review_dir)


def test_all_dirs_includes_history(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-10", "aaaaaaaaaaaa", sessions, sessions)
    _write_review(tmp_path, "x-pool", "2026-04-19", "bbbbbbbbbbbb", sessions, sessions)
    evals = collect_pool_evals(data_root=tmp_path, all_dirs=True)
    assert len(evals) == 2


def test_render_report_includes_aggregate_and_pool_rows(tmp_path):
    truth = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", truth, truth)
    evals = collect_pool_evals(data_root=tmp_path)
    report = render_report(evals)
    assert "Aggregate by provider" in report
    assert "Row identity is `(day, type, start, end, pool)`." in report
    assert "Per pool / artifact" in report
    assert "x-pool" in report


def test_human_or_omitted_same_dir_stays_quality(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions, attested_by="human"
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    assert evals[0].table == "quality"


def test_latest_ci_looks_back_to_human_for_seasonal_delta_only(tmp_path):
    human = [_row("monday", "lap_swim", "07:00", "08:00")]
    fall = [_row("tuesday", "lap_swim", "09:00", "10:00")]
    _write_review(
        tmp_path, "x-pool", "2026-04-10", "aaaaaaaaaaaa", human, human, attested_by="human"
    )
    _write_review(
        tmp_path, "x-pool", "2026-06-01", "cccccccccccc", fall, fall, attested_by="ci"
    )
    _write_review(
        tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", fall, fall, attested_by="ci"
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert all(item.table != "quality" for item in evals)
    assert all(item.table == "seasonal_delta" for item in evals)
    assert len(evals) == 1
    assert "2026-08-19" in str(evals[0].review_dir)
    report = render_report(evals)
    assert "Seasonal delta (not quality baseline)" in report
    assert "Not in the quality aggregate" in report


def test_latest_ci_with_no_human_is_omitted(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions, attested_by="ci"
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert evals == []


def test_carried_ci_is_not_independent_quality_truth(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path,
        "x-pool",
        "2026-08-19",
        "bbbbbbbbbbbb",
        sessions,
        sessions,
        attested_by="ci",
        carried_from="data/x-pool/old/reviewed.json",
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert evals == []


@pytest.mark.parametrize("attested_by", ["human", None])
def test_carried_human_or_legacy_remains_quality(tmp_path, attested_by):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions,
                  attested_by=attested_by, carried_from="data/x-pool/old/reviewed.json")
    assert collect_pool_evals(data_root=tmp_path)[0].table == "quality"


def _reference(reference_id="hamilton-fall"):
    return load_benchmark_reference(
        REPO_ROOT / "tests/fixtures/schedule-benchmark.json", reference_id, repo_root=REPO_ROOT,
    )


def _attempt(reference):
    return {
        "model": "test-model", "transport": "test-fixture", "exit_code": 0,
        "timed_out": False, "source_sha256": reference["source_sha256"],
        "payload": copy.deepcopy(reference["expected"]) | {"closures": []},
    }


def test_checked_source_hashes_and_split_are_disjoint():
    documents = json.loads((REPO_ROOT / "tests/fixtures/schedule-benchmark.json").read_text())["documents"]
    assert len({item["id"] for item in documents}) == len(documents)
    assert len({item["source_sha256"] for item in documents}) == len(documents)
    for item in documents:
        assert hashlib.sha256((REPO_ROOT / item["source_pdf"]).read_bytes()).hexdigest() == item["source_sha256"]
        if item["split"] == "reserved":
            assert "expected" not in item


def test_benchmark_reference_rejects_changed_pdf(tmp_path):
    reference = copy.deepcopy(_reference())
    reference["source_pdf"] = "source.pdf"
    (tmp_path / "source.pdf").write_bytes(b"changed")
    manifest = tmp_path / "references.json"
    manifest.write_text(json.dumps({"documents": [reference]}))
    with pytest.raises(ValueError, match="hash"):
        load_benchmark_reference(manifest, reference["id"], repo_root=tmp_path)


def test_reserved_document_cannot_be_scored(tmp_path):
    manifest = tmp_path / "reserved.json"
    manifest.write_text(json.dumps({"documents": [{"id": "unreviewed", "split": "reserved"}]}))
    with pytest.raises(ValueError, match="reserved"):
        load_benchmark_reference(manifest, "unreviewed", repo_root=tmp_path)


def test_benchmark_marks_unresolved_closures_unscored():
    reference = _reference()
    result = score_benchmark_run(reference, _attempt(reference))
    assert result["checked_fields_match"] is True
    assert result["scores"]["sessions"]["f1"] == 1
    assert result["unscored_fields"] == ["closures"]
    assert result["unresolved"]
    assert "human sign-off pending" in result["reference_review"]


def test_north_beach_preserves_expired_sessions_and_holiday_closures():
    reference = _reference("north-beach-expired")
    attempt = _attempt(reference) | {"payload": copy.deepcopy(reference["expected"])}
    result = score_benchmark_run(reference, attempt)
    assert result["checked_fields_match"]
    assert result["scores"]["sessions"]["expected_count"] == 30
    assert result["scores"]["closures"]["expected_count"] == 2
    assert result["scores"]["window_status"]["actual"] == "expired"
    attempt["payload"]["effective_end"] = None
    result = score_benchmark_run(reference, attempt)
    assert not result["checked_fields_match"]
    assert result["scores"]["window_status"]["actual"] == "unknown_end"


@pytest.mark.parametrize("as_of, status", [
    ("2026-06-08", "future"), ("2026-06-09", "within_window"),
    ("2026-08-15", "within_window"), ("2026-08-16", "expired"),
])
def test_benchmark_expiry_uses_inclusive_dates(as_of, status):
    from schedules.eval import benchmark_window_status
    assert benchmark_window_status(_reference("north-beach-expired")["expected"], as_of) == status


def test_benchmark_model_matrix_and_no_tool_commands(tmp_path):
    from schedules.benchmark import benchmark_models, harness_command, CHECK_PROMPT, CHECK_SCHEMA
    models = benchmark_models(REPO_ROOT / "tests/fixtures/schedule-benchmark.json")
    assert len(models) == 27
    extension = tmp_path / "extension.ts"
    extension.touch()
    for model in models:
        if model["harness"] == "openai-api":
            continue
        command = harness_command(model, tmp_path, extension, CHECK_PROMPT, CHECK_SCHEMA)
        assert command[command.index("--model") + 1] == model["model"]
        assert "--fallback-model" not in command
        if model["harness"] == "codex":
            assert command[-2:] == ["--", "-"]
            assert "--ignore-user-config" in command
        elif model["harness"].startswith("pi-"):
            assert "--no-tools" in command
            assert "--no-context-files" in command
        elif model["harness"] == "gemini":
            assert "--sandbox" not in command
            assert "--skip-trust" in command
            assert command[command.index("--approval-mode") + 1] == "plan"
        else:
            assert command[command.index("--tools") + 1] == ""


def test_benchmark_check_parser_ignores_reasoning_and_tools(tmp_path):
    from schedules.benchmark import CHECK_PAYLOAD, check_response
    tool = {"type": "message_end", "message": {"role": "toolResult", "content": [
        {"type": "text", "text": json.dumps(CHECK_PAYLOAD)},
    ]}}
    assert check_response(json.dumps(tool), tmp_path / "absent")[0] is None
    assistant = {"type": "message_end", "message": {"role": "assistant", "model": "kimi-k3", "content": [
        {"type": "thinking", "thinking": "not the final answer"},
        {"type": "text", "text": json.dumps(CHECK_PAYLOAD)},
    ]}}
    assert check_response(json.dumps(assistant), tmp_path / "absent") == (CHECK_PAYLOAD, ["kimi-k3"], False)
    assistant["message"]["stopReason"] = "error"
    assert check_response(json.dumps(assistant), tmp_path / "absent")[2] is True


def test_benchmark_grok_final_output_is_not_thought(tmp_path):
    from schedules.benchmark import CHECK_PAYLOAD, check_response
    response = {"structuredOutput": CHECK_PAYLOAD, "thought": "not the answer",
                "modelUsage": {"grok-4.6-build": {"modelCalls": 1}}}
    assert check_response(json.dumps(response), tmp_path / "absent") == (CHECK_PAYLOAD, ["grok-4.6-build"], False)


def test_codex_image_arguments_cannot_consume_stdin_prompt(tmp_path):
    from schedules.benchmark import harness_command, CHECK_PROMPT, CHECK_SCHEMA
    model = {"harness": "codex", "model": "gpt-5.6-luna", "effort": "medium"}
    images = (tmp_path / "page-1.png", tmp_path / "page-2.png")
    command = harness_command(model, tmp_path, None, CHECK_PROMPT, CHECK_SCHEMA, images)
    assert command[command.index("--image"):] == ["--image", *map(str, images), "--", "-"]
    with pytest.raises(ValueError, match="image-capable"):
        harness_command(model | {"model": "gpt-5.3-codex-spark"}, tmp_path, None, CHECK_PROMPT, CHECK_SCHEMA, images)


def test_benchmark_check_failure_is_not_text_ready(tmp_path, monkeypatch):
    from schedules.benchmark import check_model
    import schedules.benchmark as benchmark
    monkeypatch.setattr(benchmark.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    result = check_model({"id": "absent", "model": "gpt-5.5", "harness": "codex", "effort": "medium"}, tmp_path, None)
    assert result["status"] == "launch_error"
    assert result["cost_usd"] is None
    assert result["resolved_model"] is None


def test_benchmark_preparation_has_no_reference_answers_or_reserved_sources(tmp_path, monkeypatch):
    import schedules.benchmark as benchmark
    from subprocess import CompletedProcess
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    poppler = tmp_path / "poppler"
    poppler.mkdir()
    for name in ("pdftotext", "pdftoppm"):
        (poppler / name).touch()
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        if "-v" not in command:
            destination = "source.txt" if "-layout" in command else "page-1.png"
            (kwargs["cwd"] / destination).write_text("rendered input")
        return CompletedProcess(command, 0, stdout="", stderr="test renderer")

    monkeypatch.setattr(benchmark.tempfile, "mkdtemp", lambda **kwargs: str(bundle))
    monkeypatch.setattr(benchmark.subprocess, "run", render)
    root = benchmark.prepare_benchmark(REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT, poppler)
    manifest = json.loads((root / "inputs.json").read_text())
    assert len(manifest["inputs"]) == 4
    assert len(list(root.rglob("source.pdf"))) == 4
    assert "expected" not in (root / "inputs.json").read_text()
    assert "reserved" not in (root / "inputs.json").read_text()
    assert not list(root.rglob("reviewed.json"))
    assert "Extract the printed schedule even if it has expired" in (root / "prompt.txt").read_text()
    assert len([command for command in calls if "150" in command]) == 4
    for source in manifest["inputs"]:
        for name, expected_hash in source["files"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected_hash
    frozen, references = benchmark.load_prepared_inputs(root, REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT)
    assert len(references) == 4
    assert frozen == manifest
    (root / "prompt.txt").write_text("changed")
    with pytest.raises(ValueError, match="prompt hash"):
        benchmark.load_prepared_inputs(root, REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT)


def test_benchmark_jobs_include_every_document_and_comparison():
    from schedules.benchmark import benchmark_comparison, benchmark_jobs
    manifest = REPO_ROOT / "tests/fixtures/schedule-benchmark.json"
    plan, models, references = benchmark_comparison(manifest, "development", REPO_ROOT)
    jobs = benchmark_jobs(models, references, plan)
    assert len(jobs) == 128
    assert sum(track == "image" for _, _, track, _ in jobs) == 24
    assert sum(model["id"] == "haiku" for model, _, _, _ in jobs) == 4
    assert sum(model["id"] in {"luna-pi", "grok-cursor"} for model, _, _, _ in jobs) == 8
    assert len({(model["id"], reference["id"], track, repetition) for model, reference, track, repetition in jobs}) == 128


def test_finalist_comparison_has_exact_tracks_and_three_repetitions():
    from schedules.benchmark import benchmark_comparison, benchmark_jobs
    plan, models, references = benchmark_comparison(REPO_ROOT / "tests/fixtures/schedule-benchmark.json", "finalists", REPO_ROOT)
    jobs = benchmark_jobs(models, references, plan)
    assert len(jobs) == 36
    assert {reference["id"] for reference in references} == {"rossi-spring", "mlk-fall", "garfield-maintenance"}
    assert sum(track == "image" for _, _, track, _ in jobs) == 9
    assert {model["id"] for model, _, track, _ in jobs if track == "image"} == {"astra"}
    assert {repetition for _, _, _, repetition in jobs} == {1, 2, 3}
    assert len({(model["id"], reference["id"], track, repetition) for model, reference, track, repetition in jobs}) == 36


@pytest.mark.parametrize("change", ["repetitions", "duplicate", "image_transport"])
def test_finalist_comparison_rejects_invalid_plan(tmp_path, change):
    from schedules.benchmark import benchmark_comparison
    data = json.loads((REPO_ROOT / "tests/fixtures/schedule-benchmark.json").read_text())
    plan = data["comparisons"]["finalists"]
    if change == "repetitions":
        plan["repetitions"] = 0
    elif change == "duplicate":
        plan["candidates"].append(plan["candidates"][0])
    else:
        plan["candidates"][1]["tracks"] = ["image"]
    manifest = tmp_path / "invalid.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        benchmark_comparison(manifest, "finalists", REPO_ROOT)


def test_historical_archive_is_immutable_and_requires_its_original_revision(tmp_path):
    from schedules.benchmark import replay_benchmark
    archive = REPO_ROOT / "benchmarks/pdf/development-2026-09-04.zip"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == "b0e6ad57bbd0d8a2c8802f1ae71719d189e41670967f1604ec9531fabed9ac50"
    with pytest.raises(ValueError, match="implementation changed"):
        replay_benchmark(archive, tmp_path / "historical", REPO_ROOT)
    assert not (tmp_path / "historical").exists()


@pytest.mark.parametrize("reference_id, count", [("rossi-spring", 21), ("mlk-fall", 27), ("garfield-maintenance", 0)])
def test_finalist_references_match_checked_counts_and_closure_policy(reference_id, count):
    reference = _reference(reference_id)
    attempt = _attempt(reference) | {"payload": reference["expected"] | {"closures": reference["expected"].get("closures", [])}}
    score = score_benchmark_run(reference, attempt)
    assert score["checked_fields_match"]
    assert score["scores"]["sessions"]["expected_count"] == count
    assert ("closures" in score["unscored_fields"]) == (reference_id != "garfield-maintenance")
    if reference_id == "garfield-maintenance":
        assert attempt["payload"]["schedule_basis"] == "temporarily_closed"
        assert score["scores"]["closures"]["expected_count"] == 1


@pytest.mark.parametrize("provider_error", [False, True])
def test_extraction_scores_only_completed_payload_and_never_sends_labels(tmp_path, monkeypatch, provider_error):
    import schedules.benchmark as benchmark
    reference = _reference()
    inputs = tmp_path / "inputs"
    source = inputs / reference["source_sha256"][:12]
    source.mkdir(parents=True)
    (inputs / "prompt.txt").write_text("Extract the source. No tools.")
    (inputs / "schema.json").write_text(json.dumps(benchmark.EXTRACTION_SCHEMA))
    (source / "source.txt").write_text("SOURCE TEXT ONLY")

    def process(command, **kwargs):
        assert "--output-schema" not in command
        assert "--json-schema" not in command
        event = {"result": _attempt(reference)["payload"], "is_error": provider_error}
        kwargs["stdout"].write(json.dumps(event))

        class Process:
            returncode = 0

            def communicate(self, prompt, timeout):
                assert "SOURCE TEXT ONLY" in prompt
                assert json.dumps(reference["expected"]) not in prompt

        return Process()

    monkeypatch.setattr(benchmark.subprocess, "Popen", process)
    result = benchmark.extraction_attempt({"id": "luna", "model": "gpt-5.6-luna", "harness": "codex", "effort": "medium"},
                                         reference, "text", 1, inputs, tmp_path / "results", tmp_path / "extension.ts", 10)
    assert result["score"]["status"] == ("provider_error" if provider_error else "scored")
    assert result["exit_code"] == 0
    assert result["runner_retries"] == 0
    assert result["cost_usd"] is None
    assert list((tmp_path / "results").rglob("attempt.json"))


def test_benchmark_report_does_not_hide_failed_cells():
    from schedules.benchmark import benchmark_report
    reference = _reference()
    row = {"id": "candidate", "track": "text", "reference": reference["id"], "elapsed_seconds": 1,
           "score": score_benchmark_run(reference, _attempt(reference))}
    report = benchmark_report([row, row | {"reference": "failed", "score": {"status": "timeout"}}])
    assert "| candidate | text | 1/2 | — |" in report
    assert "candidate / text / failed: timeout" in report


def test_benchmark_parser_handles_codex_error_string(tmp_path):
    from schedules.benchmark import check_response
    assert check_response('{"type":"error","message":"Unavailable"}', tmp_path / "answer") == (None, [], True)


def test_format_diagnostic_requires_one_complete_object_and_does_not_repair_values():
    from schedules.benchmark import embedded_extraction
    payload = _attempt(_reference())["payload"]
    text = json.dumps(payload)
    assert embedded_extraction(f"Here is the extraction:\n```json\n{text}\n```\nDone.") == payload
    assert embedded_extraction(text + text) is None
    assert embedded_extraction(text[:-1]) is None
    payload["sessions"][0]["start"] = "invalid time"
    assert embedded_extraction(json.dumps(payload)) == payload


def test_usage_reports_do_not_sum_streaming_snapshots():
    from schedules.benchmark import final_usage_reports
    message = {"role": "assistant", "usage": {"totalTokens": 10}}
    events = [{"type": "message_update", "message": message}] * 100
    events += [{"type": "message_end", "message": message}]
    reports = final_usage_reports(events, "pi-cursor")
    assert len(reports) == 1
    assert reports[0]["source"] == "adapter_estimate"


def test_diagnostics_preserve_strict_failures_and_original_files(tmp_path):
    from schedules.benchmark import write_benchmark_diagnostics
    manifest = REPO_ROOT / "tests/fixtures/schedule-benchmark.json"
    reference = _reference()
    payload = _attempt(reference)["payload"]
    row = _attempt(reference) | {"id": "test", "harness": "gemini", "track": "text",
                               "reference": reference["id"], "payload": None, "repetition": 1,
                               "score": {"status": "schema_invalid"}}
    directory = tmp_path / "test/text" / reference["source_sha256"][:12] / "repeat-1"
    directory.mkdir(parents=True)
    (directory / "stdout.log").write_text(json.dumps({"response": f"```json\n{json.dumps(payload)}\n```"}))
    (tmp_path / "results.json").write_text(json.dumps([row]))
    original = (tmp_path / "results.json").read_bytes()
    (tmp_path / "run.json").write_text(json.dumps({"reference_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    report = write_benchmark_diagnostics(tmp_path, manifest, REPO_ROOT)
    diagnostics = json.loads((tmp_path / "diagnostics.json").read_text())
    assert diagnostics[0]["strict_status"] == "schema_invalid"
    assert diagnostics[0]["score"]["checked_fields_match"]
    assert (tmp_path / "results.json").read_bytes() == original
    assert "| test | text | 0/1 | 1/1 |" in report.read_text()


def test_benchmark_archive_replays_offline_without_original_paths(tmp_path, monkeypatch, replay_fixture_archive):
    import schedules.benchmark as benchmark

    def forbidden(*args, **kwargs):
        pytest.fail("Offline replay attempted to execute a process")

    monkeypatch.setattr(benchmark.subprocess, "Popen", forbidden)
    monkeypatch.setattr(benchmark.subprocess, "run", forbidden)
    checkout = tmp_path / "checkout"
    for name in benchmark.benchmark_implementation(REPO_ROOT):
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, path)
    assert not (checkout / "data").exists()
    output = tmp_path / "replayed"
    report = benchmark.replay_benchmark(replay_fixture_archive, output, checkout)
    rows = json.loads((output / "results.json").read_text())
    diagnostics = json.loads((output / "diagnostics.json").read_text())
    assert len(rows) == len(diagnostics) == 36
    assert not any(row["score"]["status"] == "blocked_auth" for row in rows)
    assert {row["repetition"] for row in rows} == {1, 2, 3}
    assert "| astra | image |" in report.read_text()
    assert not list(output.rglob("stdout.log"))
    assert not (output / "data").exists()
    with zipfile.ZipFile(BENCHMARK_ARCHIVE) as archive:
        assert (output / "results.json").read_bytes() == archive.read("results.json")
        assert (output / "diagnostics.md").read_bytes() == archive.read("diagnostics.md")


@pytest.mark.parametrize("damage, message", [
    ("checksum", "checksum"), ("missing_cell", "missing, duplicate"),
    ("duplicate_cell", "missing, duplicate"), ("model", "identity or effort"),
    ("score", "Replayed score differs"), ("request", "request differs"),
    ("traversal", "Unsafe archive"), ("implementation", "implementation changed"),
])
def test_benchmark_replay_rejects_damaged_evidence(tmp_path, damage, message, replay_fixture_archive):
    from schedules.benchmark import replay_benchmark
    with zipfile.ZipFile(replay_fixture_archive) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(files["archive.json"])
    rows = json.loads(files["results.json"])
    scored = next(row for row in rows if row["score"]["status"] == "scored")
    if damage == "checksum":
        files["report.md"] += b"changed"
    elif damage == "missing_cell":
        rows.pop()
    elif damage == "duplicate_cell":
        rows.append(rows[0])
    elif damage == "model":
        scored["model"] = "different-model"
    elif damage == "score":
        scored["score"]["checked_fields_match"] = not scored["score"]["checked_fields_match"]
    elif damage == "request":
        scored["request_sha256"] = "0" * 64
    elif damage == "traversal":
        files["../outside.txt"] = b"must not write"
    else:
        metadata["implementation_sha256"] = {}
    files["results.json"] = json.dumps(rows, indent=2).encode()
    if damage != "checksum":
        metadata["files"] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()
                             if name != "archive.json"}
    files["archive.json"] = json.dumps(metadata).encode()
    altered = tmp_path / "altered.zip"
    with zipfile.ZipFile(altered, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    output = tmp_path / "replayed"
    with pytest.raises(ValueError, match=message):
        replay_benchmark(altered, output, REPO_ROOT)
    assert not output.exists()
    assert not (tmp_path / "outside.txt").exists()


def test_benchmark_replay_cli_refuses_overwrite(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("user data")
    result = CliRunner().invoke(cli, ["benchmark-replay", str(BENCHMARK_ARCHIVE), "--output", str(tmp_path)])
    assert result.exit_code == 1
    assert "new directory" in result.output
    assert marker.read_text() == "user data"


def test_benchmark_archive_excludes_private_cli_metadata(tmp_path, replay_fixture_archive):
    from schedules.benchmark import archive_benchmark, attempt_directory, extraction_request, replay_benchmark
    raw = tmp_path / "raw"
    replay_benchmark(replay_fixture_archive, raw, REPO_ROOT)
    rows = json.loads((raw / "results.json").read_text())
    for row in rows:
        row["private_account_identifier"] = "DO_NOT_ARCHIVE"
        if row["score"]["status"] == "blocked_auth":
            continue
        directory = attempt_directory(raw, row)
        directory.mkdir(parents=True)
        prompt, _ = extraction_request(raw / "inputs", row["source_sha256"], row["track"])
        (directory / "request.txt").write_text(prompt)
        (directory / "attempt.json").write_text(json.dumps(row))
        (directory / "stdout.log").write_text(json.dumps({"response": row["final_response"], "account": "DO_NOT_ARCHIVE"}))
        (directory / "stderr.log").write_text("DO_NOT_ARCHIVE")
    (raw / "results.json").write_text(json.dumps(rows))
    exported = tmp_path / "exported.zip"
    archive_benchmark(raw / "inputs", raw, exported, REPO_ROOT / "tests/fixtures/schedule-benchmark.json", REPO_ROOT)
    with zipfile.ZipFile(exported) as archive:
        assert not any(b"DO_NOT_ARCHIVE" in archive.read(name) for name in archive.namelist())
    replay_benchmark(exported, tmp_path / "exported-replay", REPO_ROOT)


def test_benchmark_timeout_terminates_child_process_group(tmp_path, monkeypatch):
    import schedules.benchmark as benchmark
    killed = []

    class TimedOutProcess:
        pid = 12345
        returncode = -9

        def communicate(self, *args, **kwargs):
            if "timeout" in kwargs:
                raise benchmark.subprocess.TimeoutExpired("test", kwargs["timeout"])

    monkeypatch.setattr(benchmark.subprocess, "Popen", lambda *args, **kwargs: TimedOutProcess())
    monkeypatch.setattr(benchmark.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    result = benchmark.check_model({"id": "timeout", "model": "gpt-5.5", "harness": "codex", "effort": "medium"}, tmp_path, None)
    assert result["timed_out"]
    assert result["status"] == "timeout"
    assert killed == [(12345, benchmark.signal.SIGKILL)]


@pytest.mark.parametrize("reference_id, count", [
    ("hamilton-fall", 23), ("balboa-fall", 22), ("balboa-interim", 22),
])
def test_checked_references_have_valid_unique_sessions(reference_id, count):
    reference = _reference(reference_id)
    result = score_benchmark_run(reference, _attempt(reference))
    assert result["checked_fields_match"] is True
    assert result["scores"]["sessions"]["expected_count"] == count


def test_carried_ci_uses_older_human_only_as_seasonal_delta(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "aaaaaaaaaaaa", sessions, sessions,
                  attested_by="human")
    _write_review(tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions,
                  attested_by="ci", carried_from="data/x-pool/ci/reviewed.json")
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    assert evals[0].table == "seasonal_delta"


def test_benchmark_catches_hamilton_wrong_day_and_numeric_pool():
    reference = _reference()
    attempt = _attempt(reference)
    early = next(row for row in attempt["payload"]["sessions"]
                 if row["day"] == "wednesday" and row["start"] == "06:30")
    early["day"] = "tuesday"
    early["pool"] = "6"
    result = score_benchmark_run(reference, attempt)
    assert not result["checked_fields_match"]
    assert result["scores"]["sessions"]["missing"][0]["day"] == "wednesday"
    assert result["scores"]["sessions"]["extra"][0]["pool"] == "6"


def test_benchmark_counts_duplicates_as_extra_rows():
    reference = _reference()
    attempt = _attempt(reference)
    attempt["payload"]["sessions"].append(attempt["payload"]["sessions"][0].copy())
    result = score_benchmark_run(reference, attempt)
    assert len(result["scores"]["sessions"]["extra"]) == 1
    assert not result["checked_fields_match"]


def test_benchmark_checks_dates_separately_from_rows():
    reference = _reference()
    attempt = _attempt(reference)
    attempt["payload"]["effective_start"] = "2026-08-19"
    result = score_benchmark_run(reference, attempt)
    assert result["scores"]["sessions"]["f1"] == 1
    assert not result["scores"]["effective_start"]["match"]
    assert not result["checked_fields_match"]


def test_benchmark_scores_partial_closure_times_not_reason_wording():
    reference = copy.deepcopy(_reference())
    reference["expected"]["closures"] = [
        {"start": "2026-08-22", "end": "2026-08-22", "start_time": "08:30", "end_time": "12:30"},
    ]
    attempt = _attempt(reference)
    attempt["payload"]["closures"] = [reference["expected"]["closures"][0] | {"reason": "Training"}]
    assert score_benchmark_run(reference, attempt)["scores"]["closures"]["f1"] == 1
    del attempt["payload"]["closures"][0]["start_time"]
    del attempt["payload"]["closures"][0]["end_time"]
    result = score_benchmark_run(reference, attempt)
    assert result["scores"]["closures"]["f1"] == 0
    assert not result["checked_fields_match"]


@pytest.mark.parametrize("updates, status", [
    ({"exit_code": 1, "payload": None}, "execution_error"),
    ({"exit_code": None, "timed_out": True}, "timeout"),
    ({"payload": None}, "schema_invalid"),
    ({"payload": {}}, "schema_invalid"),
])
def test_benchmark_does_not_score_failed_attempts(updates, status):
    reference = _reference()
    result = score_benchmark_run(reference, _attempt(reference) | updates)
    assert result["status"] == status
    assert "scores" not in result


def test_benchmark_rejects_wrong_source_and_missing_transport():
    reference = _reference()
    for updates in ({"source_sha256": "0" * 64}, {"transport": ""}, {"exit_code": True}):
        with pytest.raises(ValueError):
            score_benchmark_run(reference, _attempt(reference) | updates)


def test_benchmark_cli_is_offline_and_read_only(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network call"))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(_attempt(_reference())))
    before = attempt.read_bytes()
    result = CliRunner().invoke(cli, ["benchmark", str(attempt), "--reference", "hamilton-fall"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["checked_fields_match"] is True
    assert attempt.read_bytes() == before
    assert list(tmp_path.iterdir()) == [attempt]
