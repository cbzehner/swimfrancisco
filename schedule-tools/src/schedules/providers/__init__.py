from __future__ import annotations

import jsonschema

from ..models import ProviderResult
from .anthropic_provider import extract as extract_with_anthropic
from .gemini_provider import extract as extract_with_gemini


def extract(provider: str, pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    normalized = provider.strip().lower()
    if normalized == "anthropic":
        result = extract_with_anthropic(pdf_bytes, prompt, schema)
    elif normalized == "gemini":
        result = extract_with_gemini(pdf_bytes, prompt, schema)
    else:
        raise ValueError(f"Unsupported provider {provider!r}.")
    # Provider structured-output modes are not guaranteed schema-valid
    # (Anthropic tool_use input in particular); fail here rather than at
    # review finalize.
    jsonschema.validate(result.payload, schema)
    return result

