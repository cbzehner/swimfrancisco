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


BENCHMARK_ARCHIVE = REPO_ROOT / "benchmarks/pdf/development-2026-09-04.zip"


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


def test_reserved_document_cannot_be_scored():
    with pytest.raises(ValueError, match="reserved"):
        _reference("rossi-spring")


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
    assert len(models) == 24
    extension = tmp_path / "extension.ts"
    extension.touch()
    for model in models:
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
    from schedules.benchmark import benchmark_models, benchmark_jobs
    manifest = REPO_ROOT / "tests/fixtures/schedule-benchmark.json"
    references = [_reference(item["id"]) for item in json.loads(manifest.read_text())["documents"]
                  if item["split"] == "development"]
    jobs = benchmark_jobs(benchmark_models(manifest), references)
    assert len(jobs) == 128
    assert sum(track == "image" for _, _, track in jobs) == 24
    assert sum(model["id"] == "haiku" for model, _, _ in jobs) == 4
    assert sum(model["id"] in {"luna-pi", "grok-cursor"} for model, _, _ in jobs) == 8
    assert len({(model["id"], reference["id"], track) for model, reference, track in jobs}) == 128


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
                                         reference, "text", inputs, tmp_path / "results", tmp_path / "extension.ts", 10)
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
                               "reference": reference["id"], "payload": None,
                               "score": {"status": "schema_invalid"}}
    directory = tmp_path / "test/text" / reference["source_sha256"][:12]
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


def test_benchmark_archive_replays_offline_without_original_paths(tmp_path, monkeypatch):
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
    report = benchmark.replay_benchmark(BENCHMARK_ARCHIVE, output, checkout)
    rows = json.loads((output / "results.json").read_text())
    diagnostics = json.loads((output / "diagnostics.json").read_text())
    assert len(rows) == len(diagnostics) == 128
    assert sum(row["score"]["status"] == "scored" for row in rows) == 58
    assert sum(row["score"]["status"] == "blocked_auth" for row in rows) == 4
    assert sum(row["score"]["status"] == "scored" for row in diagnostics) == 110
    assert "| astra | image | 4/4 | 1.0000 |" in report.read_text()
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
def test_benchmark_replay_rejects_damaged_evidence(tmp_path, damage, message):
    from schedules.benchmark import replay_benchmark
    with zipfile.ZipFile(BENCHMARK_ARCHIVE) as archive:
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


def test_benchmark_archive_excludes_private_cli_metadata(tmp_path):
    from schedules.benchmark import archive_benchmark, extraction_request, replay_benchmark
    raw = tmp_path / "raw"
    replay_benchmark(BENCHMARK_ARCHIVE, raw, REPO_ROOT)
    rows = json.loads((raw / "results.json").read_text())
    for row in rows:
        row["private_account_identifier"] = "DO_NOT_ARCHIVE"
        if row["score"]["status"] == "blocked_auth":
            continue
        directory = raw / row["id"] / row["track"] / row["source_sha256"][:12]
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
