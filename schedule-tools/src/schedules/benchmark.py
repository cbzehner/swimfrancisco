"""Local CLI readiness checks and label-free inputs; never publishes schedules."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .eval import load_benchmark_reference, prf1, score_benchmark_run
from .schema import EXTRACTION_SCHEMA


CHECK_PAYLOAD = {"check": "schedule-benchmark", "sum": 42}
CHECK_PROMPT = (
    'Do not use tools. Return only JSON with check="schedule-benchmark" '
    'and sum equal to 19 + 23. No markdown.'
)
CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"check": {"type": "string"}, "sum": {"type": "integer"}},
    "required": ["check", "sum"],
}


def benchmark_models(manifest: Path) -> list[dict]:
    models = json.loads(manifest.read_text())["models"]
    identifiers = [model["id"] for model in models]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Benchmark model IDs must be unique.")
    for model in models:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model["id"]):
            raise ValueError("Benchmark model IDs must be safe directory names.")
        if model["harness"] not in {"codex", "pi-cursor", "pi-anthropic", "pi-codex", "claude", "gemini", "grok"}:
            raise ValueError("Unknown benchmark harness.")
        if not isinstance(model["model"], str) or not model["model"].strip():
            raise ValueError("Benchmark requires an explicit model.")
    return models


def prepare_benchmark(manifest: Path, repo_root: Path, poppler: Path) -> Path:
    """Render development inputs outside the repository, with no expected answers."""
    data = json.loads(manifest.read_text())
    models = benchmark_models(manifest)
    references = [load_benchmark_reference(manifest, item["id"], repo_root=repo_root)
                  for item in data["documents"] if item["split"] == "development"]
    for name in ("pdftotext", "pdftoppm"):
        if not (poppler / name).is_file():
            raise ValueError(f"Poppler directory is missing {name}.")
    root = Path(tempfile.mkdtemp(prefix="swimfrancisco-benchmark-"))
    prompt = (repo_root / "schedule-tools/src/schedules/prompts/extract.txt").read_text()
    prompt += (
        f"\nBenchmark reference date: {data['as_of']}. Extract the printed schedule even "
        "if it has expired. Never extend its dates or discard its historical sessions. "
        "An expired schedule does not prove that the facility is closed. "
        "Preserve printed pool-section codes in lowercase without expanding the legend "
        "or splitting a shared-pool slot. Numeric lane counts are not pool sections.\n"
    )
    (root / "prompt.txt").write_text(prompt)
    (root / "schema.json").write_text(json.dumps(EXTRACTION_SCHEMA, indent=2))
    inputs = []
    for reference in references:
        # Use only the content hash in model-visible paths, not descriptive case labels.
        directory = root / reference["source_sha256"][:12]
        directory.mkdir()
        shutil.copyfile(repo_root / reference["source_pdf"], directory / "source.pdf")
        subprocess.run([str(poppler / "pdftotext"), "-layout", "source.pdf", "source.txt"],
                       cwd=directory, check=True, capture_output=True, timeout=60)
        subprocess.run([str(poppler / "pdftoppm"), "-r", "150", "-png", "source.pdf", "page"],
                       cwd=directory, check=True, capture_output=True, timeout=60)
        inputs.append({
            "source_sha256": reference["source_sha256"],
            "files": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in sorted(directory.iterdir())},
        })
    renderer = subprocess.run([str(poppler / "pdftoppm"), "-v"], capture_output=True,
                              text=True, check=True, timeout=10)
    (root / "inputs.json").write_text(json.dumps({
        "as_of": data["as_of"], "models": models, "inputs": inputs,
        "renderer": renderer.stderr.strip(), "dpi": 150,
        "prompt_sha256": hashlib.sha256((root / "prompt.txt").read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256((root / "schema.json").read_bytes()).hexdigest(),
    }, indent=2))
    return root


def harness_command(model: dict, directory: Path, pi_extension: Path | None,
                    prompt: str, schema: dict | None, images: tuple[Path, ...] = ()) -> list[str]:
    """Build argv without shell interpolation or implicit model fallback."""
    identity = ["--model", model["model"]]
    effort = model.get("effort")
    if images and (model["harness"] != "codex" or model["model"] == "gpt-5.3-codex-spark"):
        raise ValueError("Direct image checks are only configured for image-capable Codex models.")
    match model["harness"]:
        case "codex":
            return [
                "codex", "exec", *identity, "--ignore-user-config", "--ignore-rules",
                "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                "--disable", "shell_tool", "--disable", "multi_agent", "--disable", "memories",
                "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
                "-c", f'model_reasoning_effort="{effort}"', "--json",
                *(["--output-schema", str(directory / "schema.json")] if schema else []),
                "--output-last-message", str(directory / "answer.json"),
                *(["--image", *map(str, images)] if images else []), "--", "-",
            ]
        case "pi-cursor" | "pi-anthropic" | "pi-codex":
            if pi_extension is None or not pi_extension.is_file():
                raise ValueError("Pi checks require the installed multi-account extension path.")
            return [
                "pi", "--provider", {"pi-cursor": "cursor", "pi-anthropic": "anthropic",
                                      "pi-codex": "openai-codex"}[model["harness"]],
                *identity, "--no-extensions", "-e", str(pi_extension),
                "--no-tools", "--no-session", "--no-skills", "--no-context-files",
                "--no-prompt-templates", "--no-themes", "--no-approve",
                "--system-prompt", "Return the requested JSON. Do not use tools.",
                "--thinking", (effort or "off") if model["harness"] == "pi-codex" else "off",
                "--mode", "json", "-p", "--", prompt,
            ]
        case "claude":
            return [
                "claude", "-p", *identity, "--output-format", "json", "--tools", "",
                "--safe-mode", "--no-session-persistence", "--disable-slash-commands",
                "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--system-prompt", "Return the requested JSON. Do not use tools.",
                *(["--json-schema", json.dumps(schema)] if schema else []), prompt,
            ]
        case "gemini":
            return [
                "gemini", *identity, "--skip-trust", "--approval-mode", "plan",
                "--extensions", "none", "--admin-policy", str(directory / "deny-tools.toml"),
                "--output-format", "json", "-p", prompt,
            ]
        case "grok":
            return [
                "grok", *identity, "--tools", "", "--no-subagents", "--disable-web-search",
                "--permission-mode", "plan", "--max-turns", "1",
                "--reasoning-effort", effort, "--output-format", "json",
                "--system-prompt-override", "Return the requested JSON. Do not use tools.",
                *(["--json-schema", json.dumps(schema)] if schema else []), "-p", prompt,
            ]
    raise ValueError("Unknown benchmark harness.")


def response_events(stdout: str) -> list[dict]:
    events = []
    try:
        events = [json.loads(stdout)]
    except ValueError:
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return [event for event in events if isinstance(event, dict)]


def final_usage_reports(events: list[dict], harness: str) -> list[dict]:
    reports = []
    for event in events:
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        if harness.startswith("pi-"):
            if event.get("type") != "message_end" or message.get("role") != "assistant":
                continue
            usage = message.get("usage")
        else:
            usage = event.get("usage") or event.get("stats")
        if usage:
            reports.append({"source": "adapter_estimate" if harness.startswith("pi-") else "harness_report",
                            "usage": usage, "reported_cost_usd": event.get("total_cost_usd")})
    return reports


def check_response(stdout: str, answer: Path) -> tuple[object, list[str], bool]:
    """Read final response fields only; reasoning and tool output are not answers."""
    payload = None
    reported_models = set()
    provider_error = False
    for event in response_events(stdout):
        reported_models.update((event.get("modelUsage") or {}).keys())
        candidate = event.get("structured_output", event.get("structuredOutput",
                    event.get("result", event.get("response", event.get("text")))))
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        provider_error |= (event.get("is_error") is True or event.get("type") in {"error", "turn.failed"}
                           or message.get("stopReason") in {"error", "aborted"})
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            candidate = "".join(part.get("text", "") for part in message.get("content", [])
                                if part.get("type") == "text")
            if message.get("model"):
                reported_models.add(message["model"])
        if isinstance(candidate, dict):
            payload = candidate
        elif isinstance(candidate, str):
            try:
                payload = json.loads(candidate)
            except ValueError:
                pass
    if answer.is_file():
        try:
            payload = json.loads(answer.read_text())
        except ValueError:
            pass
    return payload, sorted(reported_models), provider_error


def check_model(model: dict, root: Path, pi_extension: Path | None, timeout: int = 60) -> dict:
    """One tiny inference check. Logs stay local; no extraction quality is scored."""
    directory = root / model["id"]
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "schema.json").write_text(json.dumps(CHECK_SCHEMA))
    (directory / "deny-tools.toml").write_text(
        '[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n'
    )
    command = harness_command(model, directory, pi_extension, CHECK_PROMPT, CHECK_SCHEMA)
    environment = os.environ | {"PI_SUBAGENT_CHILD": "1", "PI_CURSOR_PROVIDER_DEBUG": "0"}
    started = time.monotonic()
    result = model | {"status": "launch_error", "exit_code": None, "timed_out": False,
                      "cost_usd": None, "resolved_model": None}
    try:
        with (directory / "stdout.log").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
            process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.PIPE,
                                       stdout=stdout, stderr=stderr, text=True, start_new_session=True)
            try:
                process.communicate(CHECK_PROMPT if model["harness"] == "codex" else "", timeout=timeout)
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            result["exit_code"] = process.returncode
        payload, reported, provider_error = check_response((directory / "stdout.log").read_text(), directory / "answer.json")
        result |= {"payload": payload, "reported_models": reported}
        result["status"] = ("timeout" if result["timed_out"] else
                            "execution_error" if result["exit_code"] != 0 else
                            "provider_error" if provider_error else
                            "text_ready" if payload == CHECK_PAYLOAD else "response_invalid")
    except OSError as error:
        result["error_type"] = type(error).__name__
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (directory / "check.json").write_text(json.dumps(result, indent=2))
    return result


def load_prepared_inputs(root: Path, manifest: Path, repo_root: Path) -> tuple[dict, list[dict]]:
    frozen = json.loads((root / "inputs.json").read_text())
    if frozen["models"] != benchmark_models(manifest):
        raise ValueError("Prepared model matrix differs from the current manifest.")
    for name, suffix in (("prompt", "txt"), ("schema", "json")):
        if hashlib.sha256((root / f"{name}.{suffix}").read_bytes()).hexdigest() != frozen[f"{name}_sha256"]:
            raise ValueError(f"Prepared {name} hash changed.")
    if json.loads((root / "schema.json").read_text()) != EXTRACTION_SCHEMA:
        raise ValueError("Prepared extraction schema differs from the scorer schema.")
    references = [load_benchmark_reference(manifest, item["id"], repo_root=repo_root)
                  for item in json.loads(manifest.read_text())["documents"] if item["split"] == "development"]
    if sorted(item["source_sha256"] for item in frozen["inputs"]) != sorted(item["source_sha256"] for item in references):
        raise ValueError("Prepared inputs must contain exactly the development documents.")
    for item in frozen["inputs"]:
        prefix = item["source_sha256"][:12]
        if {str(path.relative_to(root)) for path in (root / prefix).iterdir()} != set(item["files"]):
            raise ValueError("Prepared source directory contains untracked inputs.")
        for name, digest in item["files"].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Prepared input path or hash changed.")
        if any(f"{prefix}/{name}" not in item["files"] for name in ("source.pdf", "source.txt")):
            raise ValueError("Prepared input is missing its PDF or text.")
        if not any(name.startswith(f"{prefix}/page-") and name.endswith(".png") for name in item["files"]):
            raise ValueError("Prepared input is missing page images.")
    return frozen, references


def benchmark_jobs(models: list[dict], references: list[dict]) -> list[tuple[dict, dict, str]]:
    jobs = [(model, reference, "text") for model in models for reference in references]
    jobs += [(model, reference, "image") for model in models for reference in references
             if model["harness"] == "codex" and model["model"] != "gpt-5.3-codex-spark"]
    comparisons = [
        {"id": "luna-pi", "harness": "pi-codex", "model": "gpt-5.6-luna", "effort": "medium"},
        {"id": "grok-cursor", "harness": "pi-cursor", "model": "cursor-grok-4.6-medium", "effort": "medium"},
    ]
    return jobs + [(model, reference, "text") for model in comparisons for reference in references]


def extraction_request(inputs: Path, source_sha256: str, track: str) -> tuple[str, tuple[Path, ...]]:
    source = inputs / source_sha256[:12]
    images = tuple(sorted(source.glob("page-*.png"))) if track == "image" else ()
    prompt = (inputs / "prompt.txt").read_text() + "\nJSON schema:\n" + (inputs / "schema.json").read_text()
    prompt += ("\nRead all attached page images.\n" if images else
               "\nPDF text extracted with pdftotext -layout:\n" + (source / "source.txt").read_text())
    return prompt, images


def extraction_attempt(model: dict, reference: dict, track: str, inputs: Path,
                       output: Path, pi_extension: Path, timeout: int) -> dict:
    directory = output / model["id"] / track / reference["source_sha256"][:12]
    directory.mkdir(parents=True, exist_ok=False)
    prompt, images = extraction_request(inputs, reference["source_sha256"], track)
    (directory / "request.txt").write_text(prompt)
    (directory / "deny-tools.toml").write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n')
    command = harness_command(model, directory, pi_extension, prompt, None, images)
    (directory / "command.json").write_text(json.dumps(command, indent=2))
    environment = os.environ | {"PI_SUBAGENT_CHILD": "1", "PI_CURSOR_PROVIDER_DEBUG": "0"}
    started = time.monotonic()
    attempt = model | {
        "transport": model["harness"], "reference": reference["id"], "track": track,
        "source_sha256": reference["source_sha256"], "timed_out": False, "exit_code": None,
        "payload": None, "cost_usd": None, "resolved_model": None, "runner_retries": 0,
        "request_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "image_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in images],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    status = "launch_error"
    try:
        with (directory / "stdout.log").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
            process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.PIPE,
                                       stdout=stdout, stderr=stderr, text=True, start_new_session=True)
            try:
                process.communicate(prompt if model["harness"] == "codex" else "", timeout=timeout)
            except subprocess.TimeoutExpired:
                attempt["timed_out"] = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
            attempt["exit_code"] = process.returncode
        stdout = (directory / "stdout.log").read_text()
        payload, reported_models, provider_error = check_response(stdout, directory / "answer.json")
        attempt |= {"payload": payload, "reported_models": reported_models, "provider_error": provider_error}
        attempt["usage_reports"] = final_usage_reports(response_events(stdout), model["harness"])
        status = ("timeout" if attempt["timed_out"] else "execution_error" if process.returncode != 0 else
                  "provider_error" if provider_error else "completed")
    except OSError as error:
        attempt["error_type"] = type(error).__name__
    attempt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    attempt["score"] = score_benchmark_run(reference, attempt) if status == "completed" else {"status": status}
    (directory / "attempt.json").write_text(json.dumps(attempt, indent=2))
    return attempt


def benchmark_report(results: list[dict]) -> str:
    groups = {}
    for result in results:
        groups.setdefault((result["id"], result["track"]), []).append(result)
    lines = ["# Development PDF benchmark", "",
             "One run per cell. Agent-checked references; human review pending. "
             "Closure accuracy is scored only for North Beach. Costs are not verified billing data.", "",
             "F1 includes day, type, time and literal pool label. No aggregate F1 is shown for incomplete groups.", "",
             "| Candidate | Track | Scored | Session F1 | Exact session grids | Exact date windows | Checked fields match | Mean seconds |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for (candidate, track), cells in sorted(groups.items()):
        scored = [cell for cell in cells if cell["score"]["status"] == "scored"]
        total = len(cells)
        f1 = "—"
        if len(scored) == total:
            rows = [cell["score"]["scores"]["sessions"] for cell in scored]
            matches = sum(row["expected_count"] - len(row["missing"]) for row in rows)
            f1 = f"{prf1(matches, sum(len(row['extra']) for row in rows), sum(len(row['missing']) for row in rows))[2]:.4f}"
        grids = sum(cell["score"]["scores"]["sessions"]["f1"] == 1 for cell in scored)
        dates = sum(all(cell["score"]["scores"][field]["match"] for field in ("effective_start", "effective_end")) for cell in scored)
        checked = sum(cell["score"]["checked_fields_match"] for cell in scored)
        elapsed = [cell["elapsed_seconds"] for cell in cells if "elapsed_seconds" in cell]
        mean = f"{sum(elapsed) / len(elapsed):.1f}" if elapsed else "—"
        lines.append(f"| {candidate} | {track} | {len(scored)}/{total} | {f1} | {grids}/{total} | {dates}/{total} | {checked}/{total} | {mean} |")
    failures = [cell for cell in results if cell["score"]["status"] != "scored"]
    if failures:
        lines += ["", "## Unscored cells", ""]
        lines += [f"- {cell['id']} / {cell['track']} / {cell['reference']}: {cell['score']['status']}" for cell in failures]
    return "\n".join(lines) + "\n"


def embedded_extraction(text: str) -> dict | None:
    """Diagnostic only: decode one extraction object without repairing its values."""
    decoder = json.JSONDecoder()
    candidates = []
    required = set(EXTRACTION_SCHEMA["required"])
    offset = 0
    while offset < len(text):
        start = text.find("{", offset)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(text[start:])
        except ValueError:
            offset = start + 1
            continue
        if isinstance(value, dict) and required <= value.keys():
            candidates.append(value)
        offset = start + consumed
    return candidates[0] if len(candidates) == 1 else None


def final_response_text(stdout: str, answer: Path) -> str | None:
    """Preserve the final answer, including framing, without private CLI event metadata."""
    if answer.is_file():
        return answer.read_text()
    final = None
    for event in response_events(stdout):
        candidate = event.get("structured_output", event.get("structuredOutput",
                    event.get("result", event.get("response", event.get("text")))))
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            candidate = "".join(part.get("text", "") for part in message.get("content", []) if part.get("type") == "text")
        if isinstance(candidate, str):
            final = candidate
        elif isinstance(candidate, dict):
            final = json.dumps(candidate)
    return final


def diagnostic_response(stdout: str, answer: Path) -> dict | None:
    final = final_response_text(stdout, answer)
    return embedded_extraction(final) if final is not None else None


def pool_label_difference_count(session_score: dict) -> int:
    fields = ("day", "type", "start", "end")
    missing = Counter(tuple(row[field] for field in fields) for row in session_score["missing"])
    extra = Counter(tuple(row[field] for field in fields) for row in session_score["extra"])
    return (missing & extra).total()


def write_benchmark_diagnostics(output: Path, manifest: Path, repo_root: Path) -> Path:
    """Write a separate framing diagnostic. Never modify strict attempts or scores."""
    run = json.loads((output / "run.json").read_text())
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != run["reference_manifest_sha256"]:
        raise ValueError("Reference manifest changed since this run.")
    results = json.loads((output / "results.json").read_text())
    diagnostics = []
    groups = {}
    for result in results:
        row = {key: result[key] for key in ("id", "model", "harness", "track", "reference")}
        row["strict_status"] = result["score"]["status"]
        row["score"] = result["score"]
        if row["strict_status"] == "schema_invalid":
            directory = output / result["id"] / result["track"] / result["source_sha256"][:12]
            payload = diagnostic_response((directory / "stdout.log").read_text(), directory / "answer.json")
            reference = load_benchmark_reference(manifest, result["reference"], repo_root=repo_root)
            row["score"] = score_benchmark_run(reference, result | {"payload": payload})
            row["decoded_payload"] = payload
        if row["score"]["status"] == "scored":
            sessions = row["score"]["scores"]["sessions"]
            row["pool_label_only_pairs"] = pool_label_difference_count(sessions)
            row["other_missing_rows"] = len(sessions["missing"]) - row["pool_label_only_pairs"]
            row["other_extra_rows"] = len(sessions["extra"]) - row["pool_label_only_pairs"]
        diagnostics.append(row)
        groups.setdefault((row["id"], row["track"]), []).append(row)
    lines = ["# Extraction diagnostic", "",
             "Separate from strict output-contract results. Decode only one complete extraction JSON object; "
             "do not repair values. Ambiguous or schema-invalid objects stay unscored. "
             "Execution failures and timeouts are never rescued.", "",
             "Literal F1 retains pool identity. Pool-label pairs categorize differences; they do not change the score. "
             "Other missing/extra rows may represent wrong days, times, types, omissions, or duplicates.", "",
             "| Candidate | Track | Strict passes | Valid objects | Literal session F1 | Pool-label pairs | Other missing / extra | Date windows | Checked fields |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for (candidate, track), cells in sorted(groups.items()):
        scored = [cell for cell in cells if cell["score"]["status"] == "scored"]
        total = len(cells)
        strict = sum(cell["strict_status"] == "scored" for cell in cells)
        f1 = "—"
        if len(scored) == total:
            rows = [cell["score"]["scores"]["sessions"] for cell in scored]
            f1 = f"{prf1(sum(row['expected_count'] - len(row['missing']) for row in rows), sum(len(row['extra']) for row in rows), sum(len(row['missing']) for row in rows))[2]:.4f}"
        pairs = sum(cell["pool_label_only_pairs"] for cell in scored)
        missing = sum(cell["other_missing_rows"] for cell in scored)
        extra = sum(cell["other_extra_rows"] for cell in scored)
        dates = sum(all(cell["score"]["scores"][field]["match"] for field in ("effective_start", "effective_end")) for cell in scored)
        checked = sum(cell["score"]["checked_fields_match"] for cell in scored)
        lines.append(f"| {candidate} | {track} | {strict}/{total} | {len(scored)}/{total} | {f1} | {pairs} | {missing} / {extra} | {dates}/{total} | {checked}/{total} |")
    (output / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
    report = output / "diagnostics.md"
    report.write_text("\n".join(lines) + "\n")
    return report


def run_benchmark(inputs: Path, output: Path, manifest: Path, repo_root: Path,
                  pi_extension: Path, blocked: tuple[str, ...], timeout: int, progress=print) -> list[dict]:
    frozen, references = load_prepared_inputs(inputs, manifest, repo_root)
    if not pi_extension.is_file():
        raise ValueError("Missing Pi multi-account extension.")
    if set(blocked) - {model["id"] for model in frozen["models"]}:
        raise ValueError("Unknown blocked candidate.")
    jobs = benchmark_jobs(frozen["models"], references)
    output.mkdir(parents=True, exist_ok=False)
    (output / "run.json").write_text(json.dumps({
        "inputs": str(inputs), "frozen": frozen, "blocked_candidates": blocked,
        "reference_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "timeout_seconds": timeout, "output_control": "prompt_schema", "planned_cells": len(jobs),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "environment": benchmark_environment(jobs, pi_extension),
        "implementation_sha256": benchmark_implementation(repo_root),
    }, indent=2))
    results = []
    pending = []
    for model, reference, track in jobs:
        if model["id"] in blocked:
            results.append(model | {"reference": reference["id"], "track": track,
                                    "score": {"status": "blocked_auth"}})
        else:
            pending.append((model, reference, track))
    codex = [job for job in pending if job[0]["harness"] == "codex"]
    lanes = [codex[::2], codex[1::2],
             [job for job in pending if job[0]["harness"].startswith("pi-")],
             [job for job in pending if job[0]["harness"] in {"gemini", "grok", "claude"}]]

    def run_lane(lane):
        completed = []
        for model, reference, track in lane:
            result = extraction_attempt(model, reference, track, inputs, output, pi_extension, timeout)
            completed.append(result)
            progress(f"{model['id']} / {track} / {reference['id']}: {result['score']['status']} ({result['elapsed_seconds']}s)")
        return completed

    with ThreadPoolExecutor(max_workers=4) as executor:
        for future in as_completed([executor.submit(run_lane, lane) for lane in lanes]):
            results.extend(future.result())
    (output / "results.json").write_text(json.dumps(results, indent=2))
    (output / "report.md").write_text(benchmark_report(results))
    write_benchmark_diagnostics(output, manifest, repo_root)
    return results


def benchmark_environment(jobs: list[tuple], pi_extension: Path) -> dict:
    """Record tool versions, never auth, environment variables, or account configuration."""
    executables = {model["harness"].split("-")[0] for model, _, _ in jobs}
    versions = {}
    for executable in sorted(executables):
        try:
            result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10)
            match = re.search(r"\b\d+\.\d+\.\d+\b", result.stdout) if result.returncode == 0 else None
            versions[executable] = match.group() if match else None
        except (OSError, subprocess.TimeoutExpired):
            versions[executable] = None
    return {"python": platform.python_version(), "system": platform.system(),
            "machine": platform.machine(), "cli_versions": versions,
            "pi_extension_sha256": hashlib.sha256(pi_extension.read_bytes()).hexdigest()}


def benchmark_implementation(repo_root: Path) -> dict[str, str]:
    paths = [repo_root / "schedule-tools" / name for name in ("pyproject.toml", "uv.lock")]
    source = repo_root / "schedule-tools/src/schedules"
    paths += sorted(source.rglob("*.py")) + sorted((source / "schemas").glob("*.json"))
    return {str(path.relative_to(repo_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def validate_benchmark_cases(results: list[dict], run: dict, references: list[dict]) -> None:
    planned = {(model["id"], reference["id"], track): model
               for model, reference, track in benchmark_jobs(run["frozen"]["models"], references)}
    actual = [(row["id"], row["reference"], row["track"]) for row in results]
    if set(run["blocked_candidates"]) - {key[0] for key in planned}:
        raise ValueError("Unknown blocked candidate in archived run.")
    if len(actual) != len(set(actual)) or set(actual) != set(planned) or len(actual) != run["planned_cells"]:
        raise ValueError("Benchmark has missing, duplicate, or unexpected cells.")
    for row, key in zip(results, actual):
        if any(row.get(field) != value for field, value in planned[key].items()):
            raise ValueError("Recorded model identity or effort differs from the planned cell.")
        if (row["score"]["status"] == "blocked_auth") != (row["id"] in run["blocked_candidates"]):
            raise ValueError("Blocked candidate status differs from the run specification.")


def replay_attempt(reference: dict, row: dict) -> dict:
    if row["score"]["status"] == "blocked_auth":
        return {"status": "blocked_auth"}
    if row["timed_out"]:
        return {"status": "timeout"}
    if row["exit_code"] is None:
        return {"status": "launch_error"}
    if row["exit_code"] != 0:
        return {"status": "execution_error"}
    if row.get("provider_error"):
        return {"status": "provider_error"}
    try:
        payload = json.loads(row["final_response"])
    except (ValueError, TypeError):
        payload = None
    if payload != row["payload"]:
        raise ValueError("Final response does not reproduce the recorded strict payload.")
    return score_benchmark_run(reference, row | {"payload": payload})


def archive_benchmark(inputs: Path, results_dir: Path, output: Path, manifest: Path, repo_root: Path) -> Path:
    """Export portable evidence. Raw CLI logs, account IDs, and local paths stay local."""
    frozen, references = load_prepared_inputs(inputs, manifest, repo_root)
    run = json.loads((results_dir / "run.json").read_text())
    if run["frozen"] != frozen or run["reference_manifest_sha256"] != hashlib.sha256(manifest.read_bytes()).hexdigest():
        raise ValueError("Run inputs or references differ from the archive sources.")
    results = json.loads((results_dir / "results.json").read_text())
    validate_benchmark_cases(results, run, references)
    attempts = {results_dir / row["id"] / row["track"] / row["source_sha256"][:12] / "attempt.json"
                for row in results if row["score"]["status"] != "blocked_auth"}
    if set(results_dir.rglob("attempt.json")) != attempts:
        raise ValueError("Raw attempt files differ from the recorded case list.")
    fields = ("id", "model", "harness", "effort", "transport", "reference", "track", "source_sha256",
              "timed_out", "exit_code", "payload", "cost_usd", "resolved_model", "runner_retries",
              "request_sha256", "image_sha256", "started_at", "elapsed_seconds", "reported_models",
              "provider_error", "error_type", "score")
    portable = []
    for result in results:
        row = {key: result[key] for key in fields if key in result}
        if row["score"]["status"] != "blocked_auth":
            directory = results_dir / row["id"] / row["track"] / row["source_sha256"][:12]
            if json.loads((directory / "attempt.json").read_text()) != result:
                raise ValueError("Attempt file differs from aggregate results.")
            request = (directory / "request.txt").read_bytes()
            if hashlib.sha256(request).hexdigest() != row["request_sha256"]:
                raise ValueError("Recorded request hash changed.")
            stdout = (directory / "stdout.log").read_text()
            row["final_response"] = final_response_text(stdout, directory / "answer.json")
            row["usage_reports"] = final_usage_reports(response_events(stdout), row["harness"])
        portable.append(row)
    run_fields = ("frozen", "blocked_candidates", "reference_manifest_sha256", "timeout_seconds",
                  "output_control", "planned_cells", "started_at", "implementation_sha256")
    files = {"reference-manifest.json": manifest.read_bytes(),
             "run.json": json.dumps({key: run[key] for key in run_fields if key in run}
                                    | {"environment": run.get("environment")}, indent=2).encode(),
             "results.json": json.dumps(portable, indent=2).encode(),
             "report.md": (results_dir / "report.md").read_bytes()}
    names = ["inputs.json", "prompt.txt", "schema.json"]
    names += [name for source in frozen["inputs"] for name in source["files"]]
    files.update({f"inputs/{name}": (inputs / name).read_bytes() for name in names})
    for name in ("diagnostics.json", "diagnostics.md"):
        files[name] = (results_dir / name).read_bytes()
    metadata = {"format": "swimfrancisco-pdf-benchmark", "archived_at": datetime.now(timezone.utc).isoformat(),
                "implementation_sha256": benchmark_implementation(repo_root),
                "implementation_capture": "Archive-time source and dependency hashes, not a claim of run-time capture.",
                "excluded": ["raw CLI events", "stderr", "account configuration", "local absolute paths"],
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    files["archive.json"] = json.dumps(metadata, indent=2).encode()
    with tempfile.TemporaryDirectory(prefix="swimfrancisco-archive-check-") as temporary:
        root = Path(temporary)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        verify_benchmark_replay(root, repo_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return output


def verify_benchmark_replay(root: Path, repo_root: Path) -> None:
    metadata = json.loads((root / "archive.json").read_text())
    if metadata["format"] != "swimfrancisco-pdf-benchmark":
        raise ValueError("Unknown benchmark archive format.")
    if metadata["implementation_sha256"] != benchmark_implementation(repo_root):
        raise ValueError("Benchmark implementation changed. Check out the archive's Git revision for exact replay.")
    manifest = root / "reference-manifest.json"
    run = json.loads((root / "run.json").read_text())
    if run["reference_manifest_sha256"] != hashlib.sha256(manifest.read_bytes()).hexdigest():
        raise ValueError("Archived reference manifest hash changed.")
    for item in json.loads(manifest.read_text())["documents"]:
        if item["split"] != "development":
            continue
        if not re.fullmatch(r"[a-f0-9]{64}", item["source_sha256"]):
            raise ValueError("Invalid archived source hash.")
        path = (root / item["source_pdf"]).resolve()
        if not path.is_relative_to(root.resolve()) or not item["source_pdf"].startswith("data/"):
            raise ValueError("Unsafe archived source path.")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "inputs" / item["source_sha256"][:12] / "source.pdf", path)
    frozen, references = load_prepared_inputs(root / "inputs", manifest, root)
    if run["frozen"] != frozen:
        raise ValueError("Archived input specification differs from the run.")
    results = json.loads((root / "results.json").read_text())
    validate_benchmark_cases(results, run, references)
    by_id = {reference["id"]: reference for reference in references}
    for row in results:
        if row["score"]["status"] != "blocked_auth":
            reference = by_id[row["reference"]]
            if row["source_sha256"] != reference["source_sha256"]:
                raise ValueError("Archived cell source differs from its reference.")
            prompt, images = extraction_request(root / "inputs", reference["source_sha256"], row["track"])
            if (hashlib.sha256(prompt.encode()).hexdigest() != row["request_sha256"] or
                    [hashlib.sha256(path.read_bytes()).hexdigest() for path in images] != row["image_sha256"]):
                raise ValueError("Archived cell request differs from the frozen inputs.")
        if replay_attempt(by_id[row["reference"]], row) != row["score"]:
            raise ValueError(f"Replayed score differs: {row['id']} / {row['track']} / {row['reference']}.")
        if row["score"]["status"] == "schema_invalid":
            directory = root / row["id"] / row["track"] / row["source_sha256"][:12]
            directory.mkdir(parents=True)
            (directory / "stdout.log").write_text(json.dumps({"response": row["final_response"]}))
    if benchmark_report(results) != (root / "report.md").read_text():
        raise ValueError("Replayed strict report differs from the archived report.")
    expected = {name: (root / name).read_bytes() for name in ("diagnostics.json", "diagnostics.md")}
    write_benchmark_diagnostics(root, manifest, root)
    if any((root / name).read_bytes() != content for name, content in expected.items()):
        raise ValueError("Replayed diagnostic differs from the archived diagnostic.")


def replay_benchmark(archive_path: Path, output: Path, repo_root: Path) -> Path:
    """Verify every archived score offline before writing to a new output directory."""
    if output.exists():
        raise ValueError("Replay output must be a new directory.")
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(prefix="swimfrancisco-replay-") as temporary:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(item.file_size for item in archive.infolist()) > 100_000_000:
            raise ValueError("Duplicate or oversized archive members.")
        metadata = json.loads(archive.read("archive.json"))
        if set(names) != set(metadata["files"]) | {"archive.json"}:
            raise ValueError("Archive member list differs from its checksums.")
        root = Path(temporary)
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name:
                raise ValueError("Unsafe archive member path.")
            content = archive.read(name)
            if name != "archive.json" and hashlib.sha256(content).hexdigest() != metadata["files"][name]:
                raise ValueError(f"Archive checksum mismatch: {name}.")
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        verify_benchmark_replay(root, repo_root)
        # Keep derived source copies and diagnostic scratch logs out of the restored bundle.
        output.mkdir(parents=True)
        for name in names:
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, destination)
    return output / "report.md"
