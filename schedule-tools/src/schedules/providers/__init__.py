from __future__ import annotations

import jsonschema
from dataclasses import replace

from ..models import ProviderResult
from ..schema import SOURCE_FACTS_SCHEMA, pool_label_payload
from .anthropic_provider import extract as extract_with_anthropic
from .gemini_provider import extract as extract_with_gemini
from .openai_provider import extract as extract_with_openai


def extract(provider: str, pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    normalized = provider.strip().lower()
    if normalized == "openai":
        result = extract_with_openai(pdf_bytes, prompt, schema)
    elif normalized == "anthropic":
        result = extract_with_anthropic(pdf_bytes, prompt, SOURCE_FACTS_SCHEMA)
    elif normalized == "gemini":
        result = extract_with_gemini(pdf_bytes, prompt, SOURCE_FACTS_SCHEMA)
    else:
        raise ValueError(f"Unsupported provider {provider!r}.")
    if normalized != "openai":
        jsonschema.validate(result.payload, SOURCE_FACTS_SCHEMA)
        result = replace(result, payload=pool_label_payload(result.payload), details={"source_facts": result.payload})
    # Provider structured-output modes are not guaranteed schema-valid
    # (Anthropic tool_use input in particular); fail here rather than at
    # review finalize.
    jsonschema.validate(result.payload, schema)
    return result
