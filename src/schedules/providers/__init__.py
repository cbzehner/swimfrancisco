from __future__ import annotations

from .anthropic_provider import extract as extract_with_anthropic
from .gemini_provider import extract as extract_with_gemini


def extract(provider: str, pdf_bytes: bytes, prompt: str, schema: dict) -> tuple[dict, str, dict, str]:
    normalized = provider.strip().lower()
    if normalized == "anthropic":
        result = extract_with_anthropic(pdf_bytes, prompt, schema)
    elif normalized == "gemini":
        result = extract_with_gemini(pdf_bytes, prompt, schema)
    else:
        raise ValueError(f"Unsupported provider {provider!r}.")

    return result.payload, result.model, result.usage, result.cost_estimate

