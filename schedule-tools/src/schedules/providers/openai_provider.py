from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import date
from io import BytesIO
from pathlib import Path
import uuid
from importlib.metadata import version

import httpx
import jsonschema
import pdfplumber

from ..grounding import source_excluded_dates, source_closure_inventory, source_closure_coverage, source_coverage, source_publication_coverage, source_slots, source_window_coverage
from ..models import ProviderResult
from ..paths import TMP_DIR
from ..schema import SOURCE_FACTS_SCHEMA, pool_label_payload
from ..signals import MAX_PAGE_POINTS, MAX_PDF_BYTES, MAX_PDF_PAGES, PdfSource, inspect_pdf_source


API_MODEL = "gpt-5.5-2026-04-23"
API_ENDPOINT = "https://api.openai.com/v1/responses"
API_MAX_OUTPUT_TOKENS = 8192
def api_transport_schema(schema: dict) -> dict:
    """Require nullable optional fields; enforce dependentRequired after mapping."""
    result = {key: value for key, value in schema.items() if key not in {"dependentRequired", "uniqueItems"}}
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
    except httpx.TimeoutException:
        result |= {"timed_out": True, "status": "timeout"}
    except (httpx.HTTPError, ValueError, KeyError) as error:
        result |= {"error_type": type(error).__name__, "status": "execution_error", "exit_code": 1}
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def extraction_configuration(prompt: str) -> dict:
    package = Path(__file__).resolve().parents[1]
    return {
        "model": API_MODEL, "reasoning": "medium", "max_output_tokens": API_MAX_OUTPUT_TOKENS,
        "prompt_sha256": hashlib.sha256(prompt.strip().encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(json.dumps(SOURCE_FACTS_SCHEMA, sort_keys=True).encode()).hexdigest(),
        "implementation_sha256": {name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                                  for name in ("artifacts.py", "signals.py", "grounding.py", "window_dates.py", "_time.py", "schema.py", "providers/openai_provider.py")},
        "libraries": {name: version(name) for name in ("pdfplumber", "pdfminer-six", "pypdfium2", "pillow")},
        "render_dpi": 150, "image_detail": "original",
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
    source_excluded_dates(source)
    body = prompt + "\n\nPDF page text:\n" + source.text
    if any(notice.session_cell for notice in source.notices):
        body += "\nFor a session cell marked CLOSED on specific dates, retain its weekly hours and return excluded_dates. These are session exclusions, not facility closures."
    from ..signals import north_beach_pool_identity
    if north_beach_pool_identity(source.text):
        body += ("\nThis is one physical pool document in a North Beach pair. "
                 "The document title is the physical pool identity; do not insert it into pool_label_raw. "
                 "Lap/Therapy in parentheses is an allocation, not a second lap_swim program beside Senior Swim. "
                 "For a cell marked (CLOSED dates), preserve the weekly session and put those ISO dates in its excluded_dates. "
                 "Do not replace these whole-session cancellations with the general training closure. "
                 "Facility-wide notices still belong in closures, including the notice inside Saturday's column. "
                 "An explicitly named Cool or Warm pool closure uses physical_pool; omit physical_pool for facility-wide notices. "
                 "Retain each printed recurring and holiday closure even when their dates overlap.")
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


def matched_source_closures(closure: dict, inventory: list[dict]) -> list[dict]:
    fields = ("start", "end", "start_time", "end_time", "physical_pool")
    exact = [item for item in inventory if all(item.get(field) == closure.get(field) for field in fields)]
    if len(exact) == 1:
        return exact
    if exact or closure.get("start_time") or closure.get("end_time"):
        raise ValueError("Closure does not match one independently verified source notice")
    matches = sorted([
        item for item in inventory
        if closure["start"] <= item["start"] <= closure["end"]
        and item.get("physical_pool") == closure.get("physical_pool")
    ], key=lambda item: item["start"])
    day_count = (date.fromisoformat(closure["end"]) - date.fromisoformat(closure["start"])).days + 1
    if (
        len(matches) < 2 or len(matches) != day_count
        or len({item["start"] for item in matches}) != day_count
        or any(
            item["start"] != item["end"] or item.get("start_time") or item.get("end_time")
            or item["reason_code"] != matches[0]["reason_code"]
            or item["source_notices"] != matches[0]["source_notices"]
            for item in matches
        )
    ):
        raise ValueError("Closure does not match one independently verified source notice")
    return matches


def source_fact_payload(facts: dict, source: PdfSource) -> dict:
    payload = pool_label_payload(facts)
    remaining = list(source_closure_inventory(source))
    closures = []
    identities = set()
    for closure in payload.get("closures", []):
        identity = tuple(closure.get(field) for field in ("start", "end", "start_time", "end_time", "physical_pool"))
        if identity in identities:
            raise ValueError("Duplicate closure cannot consume independently verified source notices")
        identities.add(identity)
        for item in matched_source_closures(closure, remaining):
            remaining.remove(item)
            closures.append(closure | {
                "start": item["start"], "end": item["end"],
                "reason_code": item["reason_code"], "source_notices": item["source_notices"],
            })
    if remaining:
        raise ValueError("Extracted closures omit independently verified source notices")
    return payload | {"closures": closures}


def verify_artifact(artifact: dict, pdf_bytes: bytes, prompt: str) -> dict:
    details = artifact.get("details", {})
    if artifact.get("pdf_sha256") != hashlib.sha256(pdf_bytes).hexdigest():
        raise ValueError("Source PDF does not match the extraction artifact")
    if artifact.get("model") != API_MODEL or details.get("configuration") != extraction_configuration(prompt):
        raise ValueError("Extraction configuration is stale")
    facts = details.get("source_facts")
    jsonschema.validate(facts, SOURCE_FACTS_SCHEMA)
    source = inspect_pdf_source(pdf_bytes)
    if source_fact_payload(facts, source) != artifact.get("payload"):
        raise ValueError("Published payload differs from the extracted source facts")
    pages = visual_page_numbers(source)
    if details.get("visual_pages") != sorted(pages):
        raise ValueError("Rendered page selection does not match the source")
    images = render_source_pages(pdf_bytes, pages)
    hashes = {str(number): hashlib.sha256(data).hexdigest() for number, data in images.items()}
    if hashes != details.get("image_sha256"):
        raise ValueError("Rendered evidence differs from the extraction input")
    return source_publication_coverage(source, artifact["payload"], visual_pages=pages)


class ClosureReviewRequired(ValueError):
    def __init__(self, source: PdfSource, issues: list[str]):
        self.issues = issues
        self.notices = [asdict(notice) for notice in source.notices]
        super().__init__("Unresolved source closures: " + ", ".join(issues))


def extract(pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    source = inspect_pdf_source(pdf_bytes)
    closure_issues = [issue for issue in source_closure_coverage(source, {})["issues"]
                      if issue != "source_closure_mismatch"]
    if closure_issues:
        if any(":" in issue for issue in closure_issues):
            raise ClosureReviewRequired(source, closure_issues)
        raise ValueError("Unresolved source closures: " + ", ".join(closure_issues))
    try:
        source_closure_inventory(source)
    except ValueError as error:
        raise ClosureReviewRequired(source, [str(error)]) from error
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is not configured")
    visual_pages = visual_page_numbers(source)
    images = render_source_pages(pdf_bytes, visual_pages)
    request = source_request(source, prompt, images)
    attempts = []
    for attempt in range(2):
        result = call_api(request, TMP_DIR / "api-attempts" / uuid.uuid4().hex, 240)
        attempts.append({key: result.get(key) for key in ("status", "http_status", "elapsed_seconds")})
        if not (result["timed_out"] or result["http_status"] in {408, 500, 502, 503, 504}) or attempt == 1:
            break
        time.sleep(1)
    parsed = api_response_result(result["api_response"], SOURCE_FACTS_SCHEMA) if result["api_response"] else {}
    if parsed.get("status") != "completed" or parsed.get("resolved_model") != API_MODEL:
        raise ValueError(f"Extraction failed: {parsed.get('status', result['status'])}; HTTP {result['http_status']}")
    facts = parsed["payload"]
    payload = source_fact_payload(facts, source)
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
