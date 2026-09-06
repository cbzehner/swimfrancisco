from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import time
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import tempfile
import uuid
from importlib.metadata import version

import httpx
import jsonschema
import pdfplumber

from ..grounding import source_closure_coverage, source_coverage, source_publication_coverage, source_slots, source_window_coverage
from ..models import ProviderResult
from ..schema import SOURCE_FACTS_SCHEMA, pool_label_payload
from ..signals import MAX_PAGE_POINTS, MAX_PDF_BYTES, MAX_PDF_PAGES, PdfSource, inspect_pdf_source


API_MODEL = "gpt-5.5-2026-04-23"
API_ENDPOINT = "https://api.openai.com/v1/responses"
API_MAX_OUTPUT_TOKENS = 8192
API_PRICING = {
    "checked_at": "2026-09-05",
    "source": "https://developers.openai.com/api/docs/models/gpt-5.5",
    "input_usd_per_million": 5, "cached_input_usd_per_million": 0.5,
    "output_usd_per_million": 30, "service_tier": "default",
}


def api_transport_schema(schema: dict) -> dict:
    """Require nullable optional fields; enforce dependentRequired after mapping."""
    result = {key: value for key, value in schema.items() if key != "dependentRequired"}
    if "enum" in result and "type" not in result:
        if not all(isinstance(value, str) for value in result["enum"]):
            raise ValueError("API schema only supports string enums without explicit types.")
        result["type"] = "string"
    if "properties" in schema:
        required = schema.get("required", [])
        result["properties"] = {
            name: api_transport_schema(child) if name in required else
            {"anyOf": [api_transport_schema(child), {"type": "null"}]}
            for name, child in schema["properties"].items()
        }
        result["required"] = list(schema["properties"])
        result["additionalProperties"] = False
    if "items" in schema:
        result["items"] = api_transport_schema(schema["items"])
    return result


def api_payload(value, schema: dict):
    """Remove only optional nulls. Never repair content or remove unknown fields."""
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        return {name: api_payload(child, properties.get(name, {})) for name, child in value.items()
                if not (name in properties and name not in schema.get("required", []) and child is None)}
    if isinstance(value, list):
        return [api_payload(child, schema.get("items", {})) for child in value]
    return value


def api_request(prompt: str, schema: dict, *, max_output_tokens: int = API_MAX_OUTPUT_TOKENS) -> dict:
    return {
        "model": API_MODEL, "input": prompt, "reasoning": {"effort": "medium"},
        "text": {"format": {"type": "json_schema", "name": "schedule_extraction",
                            "strict": True, "schema": api_transport_schema(schema)}},
        "max_output_tokens": max_output_tokens, "store": False, "tools": [],
        "service_tier": "default", "truncation": "disabled",
    }


def api_reservation_microusd(request: dict) -> int:
    if request.get("model") != API_MODEL or request.get("service_tier") != "default":
        raise ValueError("Request is outside the pinned model and price contract")
    if type(request.get("max_output_tokens")) is not int or not 1 <= request["max_output_tokens"] <= API_MAX_OUTPUT_TOKENS:
        raise ValueError("Request output limit exceeds the price reservation")
    body = copy.deepcopy(request)
    image_tokens = 0
    if isinstance(body["input"], list):
        for message in body["input"]:
            for part in message["content"]:
                if part["type"] == "input_image":
                    if part.get("detail") != "original":
                        raise ValueError("Image cost reservation requires explicit original detail")
                    part["image_url"] = ""
                    image_tokens += 12_001
    # Reserve the full 10,000-patch image ceiling at 1.2 tokens per patch,
    # plus one rounding token. Text uses UTF-8 bytes plus framing as a bound.
    input_bound = len(json.dumps(body, ensure_ascii=False).encode()) + 4096 + image_tokens
    if input_bound > 200_000:
        raise ValueError("API benchmark input exceeds the short-context price reservation.")
    return input_bound * 5 + request["max_output_tokens"] * 30


def api_response_result(response: dict, schema: dict) -> dict:
    result = {"payload": None, "final_response": None, "response_status": response.get("status"),
              "resolved_model": response.get("model"), "transport_valid": False}
    if response.get("status") != "completed":
        return result | {"status": "provider_error"}
    messages = [item for item in response.get("output", []) if item.get("type") == "message"]
    content = [part for item in messages for part in item.get("content", [])]
    if any(part.get("type") == "refusal" for part in content):
        return result | {"status": "provider_error"}
    texts = [part.get("text") for part in content if part.get("type") == "output_text"]
    if len(messages) != 1 or messages[0].get("status") != "completed" or len(texts) != 1:
        return result | {"status": "provider_error"}
    result["final_response"] = texts[0]
    try:
        value = json.loads(texts[0])
        jsonschema.Draft202012Validator(api_transport_schema(schema), format_checker=jsonschema.FormatChecker()).validate(value)
    except (ValueError, TypeError, jsonschema.ValidationError):
        return result | {"status": "transport_invalid"}
    return result | {"status": "completed", "transport_valid": True, "payload": api_payload(value, schema)}


def call_api(request: dict, directory: Path, timeout: int) -> dict:
    """One paid request, no retries, redirects, proxies, or credential-bearing logs."""
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "request.json").write_text(json.dumps(request, indent=2))
    started = time.monotonic()
    result = {"api_response": None, "http_status": None, "timed_out": False, "exit_code": None,
              "reserved_microusd": api_reservation_microusd(request), "cost_usd": None,
              "runner_retries": 0, "status": "launch_error"}
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.post(API_ENDPOINT, json=request,
                                   headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
        result["http_status"] = response.status_code
        result["exit_code"] = 0 if response.is_success else 1
        result["status"] = "completed" if response.is_success else "execution_error"
        if response.is_success:
            body = response.json()
            (directory / "response.json").write_text(json.dumps(body, indent=2))
            result["api_response"] = {key: body.get(key) for key in
                                      ("status", "model", "output", "usage", "incomplete_details", "service_tier")}
            usage = body.get("usage") or {}
            if type(usage.get("input_tokens")) is int and type(usage.get("output_tokens")) is int:
                cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
                result["cost_usd"] = ((usage["input_tokens"] - cached) * 5 + cached * 0.5 + usage["output_tokens"] * 30) / 1_000_000
    except httpx.TimeoutException:
        result |= {"timed_out": True, "status": "timeout"}
    except (httpx.HTTPError, ValueError, KeyError) as error:
        result |= {"error_type": type(error).__name__, "status": "execution_error", "exit_code": 1}
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


class SpendBudget:
    def __init__(self, path: Path, limit_usd: float):
        if not math.isfinite(limit_usd) or limit_usd <= 0:
            raise ValueError("An explicit positive API budget is required")
        self.path = path
        self.limit = math.floor(limit_usd * 1_000_000)

    def _update(self, update):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.path.read_text()) if self.path.exists() else {"limit_microusd": self.limit, "requests": []}
            if state["limit_microusd"] != self.limit:
                raise ValueError("Budget limit differs from the existing ledger")
            if state.get("blocked"):
                raise ValueError("API budget ledger is blocked after an accounting error")
            if not isinstance(state.get("requests"), list) or any(
                type(item.get("charged_microusd")) is not int or item["charged_microusd"] < 0
                for item in state["requests"]
            ):
                raise ValueError("API budget ledger contains invalid charges")
            result = update(state)
            descriptor, temporary = tempfile.mkstemp(prefix=".budget-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w") as stream:
                    json.dump(state, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return result

    def reserve(self, request: dict) -> str:
        reservation = api_reservation_microusd(request)
        identifier = uuid.uuid4().hex

        def update(state):
            if sum(item["charged_microusd"] for item in state["requests"]) + reservation > self.limit:
                raise ValueError("API budget exhausted; no request sent")
            state["requests"].append({"id": identifier, "reserved_microusd": reservation,
                                      "charged_microusd": reservation, "status": "reserved"})
            return identifier

        return self._update(update)

    def settle(self, identifier: str, result: dict) -> None:
        def update(state):
            item = next(item for item in state["requests"] if item["id"] == identifier)
            if item["status"] != "reserved":
                raise ValueError("Budget reservation was already settled")
            response = result.get("api_response") or {}
            if response and (response.get("model") != API_MODEL or response.get("service_tier") != "default"):
                state["blocked"] = True
            usage = response.get("usage") or {}
            input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
            if all(type(count) is int and count >= 0 for count in (input_tokens, output_tokens)):
                # Do not rely on discounted cache rates when enforcing the cap.
                charged = input_tokens * 5 + output_tokens * 30
                if charged > item["reserved_microusd"]:
                    state["blocked"] = True
                item["charged_microusd"] = charged
            item["status"] = result["status"]
            return state.get("blocked", False)

        if self._update(update):
            raise ValueError("API response violates its price reservation; stop paid calls")


class MonthlySpendBudget:
    branch = "refs/heads/schedule-budget"

    def __init__(self, repo_root: Path, limit_usd: float):
        if not math.isfinite(limit_usd) or limit_usd <= 0:
            raise ValueError("An approved positive monthly API budget is required")
        self.repo_root = repo_root
        self.limit = math.floor(limit_usd * 1_000_000)

    def _git(self, *args: str, input: str | None = None, missing_ok: bool = False) -> str:
        result = subprocess.run(["git", "-c", "user.name=Schedule automation", "-c", "user.email=schedules@users.noreply.github.com", *args],
                                cwd=self.repo_root, input=input, capture_output=True, text=True, timeout=60)
        if missing_ok and result.returncode == 2:
            return ""
        if result.returncode:
            raise ValueError("Durable budget Git operation failed; no paid call is authorized")
        return result.stdout.strip()

    def _load(self) -> tuple[str | None, dict]:
        remote = self._git("ls-remote", "--exit-code", "--heads", "origin", self.branch, missing_ok=True)
        if not remote:
            raise ValueError("Durable budget branch is missing; explicit initialization is required")
        parent = remote.split()[0]
        if not re.fullmatch(r"[a-f0-9]{40}", parent):
            raise ValueError("Invalid durable budget revision")
        self._git("fetch", "--no-tags", "--no-write-fetch-head", "origin", parent)
        state = json.loads(self._git("show", f"{parent}:budget.json"))
        if not isinstance(state, dict) or not isinstance(state.get("months"), dict) or type(state.get("blocked")) is not bool:
            raise ValueError("Invalid durable budget state")
        for month, period in state["months"].items():
            if not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", month) or not isinstance(period, dict):
                raise ValueError("Invalid budget month")
            if type(period.get("limit_microusd")) is not int or period["limit_microusd"] <= 0 or not isinstance(period.get("runs"), dict):
                raise ValueError("Invalid monthly limit or runs")
            for item in period["runs"].values():
                if not isinstance(item, dict) or any(type(item.get(field)) is not int or item[field] < 0
                                                    for field in ("reserved_microusd", "charged_microusd")):
                    raise ValueError("Invalid monthly charges")
                if item.get("status") not in {"reserved", "settled", "blocked"}:
                    raise ValueError("Invalid monthly run status")
                if item["reserved_microusd"] <= 0 or (item["status"] == "reserved" and item["charged_microusd"] != item["reserved_microusd"]):
                    raise ValueError("Invalid unsettled monthly reservation")
                if item["charged_microusd"] > item["reserved_microusd"] and not state["blocked"]:
                    raise ValueError("Run charge exceeds its reservation")
            if sum(item["charged_microusd"] for item in period["runs"].values()) > period["limit_microusd"] and not state["blocked"]:
                raise ValueError("Monthly charges exceed the approved limit")
        return parent, state

    def _save(self, parent: str | None, state: dict, message: str) -> None:
        blob = self._git("hash-object", "-w", "--stdin", input=json.dumps(state, indent=2) + "\n")
        tree = self._git("mktree", input=f"100644 blob {blob}\tbudget.json\n")
        parents = ("-p", parent) if parent else ()
        commit = self._git("commit-tree", tree, *parents, "-m", message)
        self._git("push", "--porcelain", "origin", f"{commit}:{self.branch}")

    def initialize(self) -> None:
        if self._git("ls-remote", "--exit-code", "--heads", "origin", self.branch, missing_ok=True):
            raise ValueError("Durable budget already exists; it must not be reset")
        self._save(None, {"months": {}, "blocked": False}, "Initialize schedule API budget accounting")

    def reserve(self, month: str, run_id: str, run_limit_usd: float = 1.0) -> dict:
        if not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", month) or not re.fullmatch(r"\d+-\d+", run_id):
            raise ValueError("Budget reservation requires a calendar month and Actions run/attempt ID")
        if not math.isfinite(run_limit_usd) or run_limit_usd <= 0:
            raise ValueError("An explicit positive run limit is required")
        parent, state = self._load()
        if state["blocked"]:
            raise ValueError("Durable budget is blocked after an accounting error")
        period = state["months"].setdefault(month, {"limit_microusd": self.limit, "runs": {}})
        if period["limit_microusd"] != self.limit:
            raise ValueError("Monthly approval differs from the recorded limit")
        if run_id in period["runs"]:
            raise ValueError("This run already has a durable reservation; do not reset it")
        remaining = self.limit - sum(item["charged_microusd"] for item in period["runs"].values())
        allowance = min(remaining, math.floor(run_limit_usd * 1_000_000))
        if allowance <= 0:
            raise ValueError("Monthly API budget exhausted")
        period["runs"][run_id] = {"reserved_microusd": allowance, "charged_microusd": allowance, "status": "reserved"}
        self._save(parent, state, f"Reserve schedule API allowance for {month} run {run_id}")
        return {"month": month, "run_id": run_id, "limit_microusd": allowance}

    def settle(self, receipt: dict, local_ledger: Path) -> None:
        parent, state = self._load()
        period = state["months"][receipt["month"]]
        item = period["runs"][receipt["run_id"]]
        if item["status"] != "reserved" or item["reserved_microusd"] != receipt["limit_microusd"]:
            raise ValueError("Run reservation is already settled or differs from the receipt")
        if local_ledger.exists():
            try:
                ledger = json.loads(local_ledger.read_text())
                valid = ledger["limit_microusd"] == item["reserved_microusd"] and isinstance(ledger["requests"], list)
                valid = valid and all(
                    isinstance(request, dict) and isinstance(request.get("id"), str) and request["id"]
                    and type(request.get("reserved_microusd")) is int and request["reserved_microusd"] > 0
                    and type(request.get("charged_microusd")) is int and request["charged_microusd"] >= 0
                    and request.get("status") in {"reserved", "completed", "execution_error", "timeout", "launch_error"}
                    and (request["status"] != "reserved" or request["charged_microusd"] == request["reserved_microusd"])
                    for request in ledger["requests"]
                )
                if not valid:
                    raise ValueError("Invalid run ledger")
                if len({request["id"] for request in ledger["requests"]}) != len(ledger["requests"]):
                    raise ValueError("Duplicate run request IDs")
                charge = sum(request["charged_microusd"] for request in ledger["requests"])
                if ledger.get("blocked") or charge > item["reserved_microusd"] or any(
                    request["charged_microusd"] > request["reserved_microusd"] for request in ledger["requests"]
                ):
                    state["blocked"] = True
                item["charged_microusd"] = charge
            except (KeyError, TypeError, ValueError):
                state["blocked"] = True
        item["status"] = "blocked" if state["blocked"] else "settled"
        self._save(parent, state, f"Settle schedule API allowance for run {receipt['run_id']}")
        if state["blocked"]:
            raise ValueError("Durable budget blocked after invalid run accounting")


def budgeted_call(request: dict, directory: Path, timeout: int, budget: SpendBudget) -> dict:
    identifier = budget.reserve(request)
    result = call_api(request, directory, timeout)
    budget.settle(identifier, result)
    return result | {"reservation_id": identifier}


def extraction_configuration(prompt: str) -> dict:
    package = Path(__file__).resolve().parents[1]
    return {
        "model": API_MODEL, "reasoning": "medium", "max_output_tokens": API_MAX_OUTPUT_TOKENS,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(json.dumps(SOURCE_FACTS_SCHEMA, sort_keys=True).encode()).hexdigest(),
        "implementation_sha256": {name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                                  for name in ("signals.py", "grounding.py", "window_dates.py", "_time.py", "schema.py", "providers/openai_provider.py")},
        "libraries": {name: version(name) for name in ("pdfplumber", "pdfminer-six", "pypdfium2", "pillow")},
        "render_dpi": 150, "image_detail": "original", "pricing": API_PRICING,
    }


def render_source_pages(pdf_bytes: bytes, pages: frozenset[int]) -> dict[int, bytes]:
    if not pages:
        return {}
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 25 MiB source limit")
    images = {}
    with pdfplumber.open(BytesIO(pdf_bytes)) as document:
        if not 1 <= len(document.pages) <= MAX_PDF_PAGES or any(number < 1 or number > len(document.pages) for number in pages):
            raise ValueError("Rendered page is outside the supported source document")
        selected = [document.pages[number - 1] for number in sorted(pages)]
        if any(not (0 < page.width <= MAX_PAGE_POINTS and 0 < page.height <= MAX_PAGE_POINTS) for page in selected):
            raise ValueError("PDF page exceeds the supported dimensions")
        if sum(page.width * page.height * (150 / 72) ** 2 for page in selected) > 20_000_000:
            raise ValueError("Rendered PDF exceeds the 20 megapixel evidence limit")
        for number in sorted(pages):
            image = document.pages[number - 1].to_image(resolution=150).original
            stream = BytesIO()
            image.save(stream, format="PNG")
            images[number] = stream.getvalue()
    return images


def source_request(source: PdfSource, prompt: str, images: dict[int, bytes]) -> dict:
    unsupported = [issue for issue in source.issues if not issue.endswith(":unbalanced_text")]
    if unsupported:
        raise ValueError("Unsupported PDF source: " + ", ".join(unsupported))
    if not visual_page_numbers(source).issubset(images):
        raise ValueError("Ambiguous PDF text requires its rendered page")
    if any(number < 1 or number > source.page_count for number in images):
        raise ValueError("Rendered page is outside the source document")
    source_slots(source)
    body = prompt + "\n\nPDF page text:\n" + source.text
    body += "\n\nCoordinate-based source cells (not model output):\n" + json.dumps([
        {"id": cell.id, "page": cell.page, "day": cell.day, "text": cell.text} for cell in source.cells
    ], ensure_ascii=False)
    content = [{"type": "input_text", "text": body}]
    for number, data in sorted(images.items()):
        content.extend([
            {"type": "input_text", "text": f"Rendered page {number}. Use visible text when extraction contains overlapping characters."},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(data).decode(), "detail": "original"},
        ])
    request = api_request(body, SOURCE_FACTS_SCHEMA)
    if images:
        request["input"] = [{"role": "user", "content": content}]
    return request


def visual_page_numbers(source: PdfSource) -> frozenset[int]:
    return frozenset(cell.page for cell in source.cells if f"{cell.id}:unbalanced_text" in source.issues)


def verify_artifact(artifact: dict, pdf_bytes: bytes, prompt: str) -> dict:
    details = artifact.get("details", {})
    if artifact.get("pdf_sha256") != hashlib.sha256(pdf_bytes).hexdigest():
        raise ValueError("Source PDF does not match the extraction artifact")
    if artifact.get("model") != API_MODEL or details.get("configuration") != extraction_configuration(prompt):
        raise ValueError("Extraction configuration is stale")
    facts = details.get("source_facts")
    jsonschema.validate(facts, SOURCE_FACTS_SCHEMA)
    if pool_label_payload(facts) != artifact.get("payload"):
        raise ValueError("Published payload differs from the extracted source facts")
    source = inspect_pdf_source(pdf_bytes)
    pages = visual_page_numbers(source)
    if details.get("visual_pages") != sorted(pages):
        raise ValueError("Rendered page selection does not match the source")
    images = render_source_pages(pdf_bytes, pages)
    hashes = {str(number): hashlib.sha256(data).hexdigest() for number, data in images.items()}
    if hashes != details.get("image_sha256"):
        raise ValueError("Rendered evidence differs from the extraction input")
    return source_publication_coverage(source, artifact["payload"], visual_pages=pages)


def extract(pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is not configured")
    budget_path = os.environ.get("SCHEDULES_API_BUDGET_FILE")
    if not budget_path:
        raise ValueError("SCHEDULES_API_BUDGET_FILE is required")
    budget = SpendBudget(Path(budget_path), float(os.environ.get("SCHEDULES_API_BUDGET_USD", "0")))
    source = inspect_pdf_source(pdf_bytes)
    closure_issues = [issue for issue in source_closure_coverage(source, {})["issues"]
                      if issue != "source_closure_mismatch"]
    if closure_issues:
        raise ValueError("Unresolved source closures: " + ", ".join(closure_issues))
    visual_pages = visual_page_numbers(source)
    images = render_source_pages(pdf_bytes, visual_pages)
    request = source_request(source, prompt, images)
    attempts = []
    for attempt in range(2):
        directory = Path(budget_path).parent / "api-attempts" / uuid.uuid4().hex
        result = budgeted_call(request, directory, 240, budget)
        attempts.append({key: result.get(key) for key in ("status", "http_status", "elapsed_seconds", "cost_usd", "reserved_microusd")})
        if not (result["timed_out"] or result["http_status"] in {408, 500, 502, 503, 504}) or attempt == 1:
            break
        time.sleep(1)
    parsed = api_response_result(result["api_response"], SOURCE_FACTS_SCHEMA) if result["api_response"] else {}
    if parsed.get("status") != "completed" or parsed.get("resolved_model") != API_MODEL:
        raise ValueError(f"Extraction failed: {parsed.get('status', result['status'])}; HTTP {result['http_status']}")
    facts = parsed["payload"]
    payload = pool_label_payload(facts)
    jsonschema.validate(payload, schema)
    coverage = source_coverage(source, payload, visual_pages=visual_pages)
    return ProviderResult(payload=payload, model=API_MODEL, usage=result["api_response"].get("usage") or {}, details={
        "source_facts": facts, "source_inventory": asdict(source), "source_coverage": coverage,
        "source_window": source_window_coverage(source, payload),
        "source_closures": source_closure_coverage(source, payload),
        "visual_pages": sorted(visual_pages),
        "image_sha256": {str(number): hashlib.sha256(data).hexdigest() for number, data in images.items()},
        "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
        "response_status": parsed["response_status"], "final_response": parsed["final_response"],
        "configuration": extraction_configuration(prompt), "attempts": attempts,
    })
