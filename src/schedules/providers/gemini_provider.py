from __future__ import annotations

import json
import os
from typing import Any

from ..models import ProviderResult

DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"


def extract(pdf_bytes: bytes, prompt: str, schema: dict[str, Any]) -> ProviderResult:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - exercised only in real runs
        raise RuntimeError("google-genai is not installed. Run `uv sync` first.") from exc

    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("GOOGLE_API_KEY is not set.")

    model = os.getenv("SCHEDULES_GEMINI_MODEL", DEFAULT_MODEL)
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(
        model=model,
        contents=[
            prompt,
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )

    payload = getattr(response, "parsed", None)
    if payload is None:
        if not response.text:
            raise RuntimeError("Gemini returned no JSON payload.")
        payload = json.loads(response.text)

    usage_metadata = getattr(response, "usage_metadata", None)
    usage = _usage_dict(usage_metadata)
    return ProviderResult(
        payload=payload,
        model=model,
        usage=usage,
        cost_estimate=_format_usage(usage),
    )


def _usage_dict(usage_metadata: Any) -> dict[str, Any]:
    if usage_metadata is None:
        return {}
    return {
        "prompt_token_count": getattr(usage_metadata, "prompt_token_count", None),
        "candidates_token_count": getattr(usage_metadata, "candidates_token_count", None),
        "total_token_count": getattr(usage_metadata, "total_token_count", None),
    }


def _format_usage(usage: dict[str, Any]) -> str:
    total = usage.get("total_token_count")
    if total is None:
        return "usage unavailable"
    return (
        f"prompt_tokens={usage.get('prompt_token_count') or 0}, "
        f"candidate_tokens={usage.get('candidates_token_count') or 0}, "
        f"total_tokens={total}"
    )
