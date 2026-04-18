from __future__ import annotations

import base64
import os
from typing import Any

from ..models import ProviderResult

DEFAULT_MODEL = "claude-sonnet-4-6"


def extract(pdf_bytes: bytes, prompt: str, schema: dict[str, Any]) -> ProviderResult:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only in real runs
        raise RuntimeError("anthropic is not installed. Run `uv sync` first.") from exc

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    model = os.getenv("SCHEDULES_ANTHROPIC_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        tools=[
            {
                "name": "submit_pool_schedule",
                "description": "Submit the extracted pool schedule as structured JSON.",
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": "submit_pool_schedule"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(pdf_bytes).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    payload = _extract_tool_input(response.content)
    usage = _usage_dict(getattr(response, "usage", None))
    return ProviderResult(
        payload=payload,
        model=model,
        usage=usage,
        cost_estimate=_format_usage(usage),
    )


def _extract_tool_input(blocks: list[Any]) -> dict[str, Any]:
    for block in blocks:
        block_type = getattr(block, "type", None) or block.get("type")
        if block_type == "tool_use":
            payload = getattr(block, "input", None) or block.get("input")
            if isinstance(payload, dict):
                return payload
    raise RuntimeError("Anthropic response did not contain the expected tool_use payload.")


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }


def _format_usage(usage: dict[str, Any]) -> str:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return "usage unavailable"
    return f"input_tokens={input_tokens or 0}, output_tokens={output_tokens or 0}"

