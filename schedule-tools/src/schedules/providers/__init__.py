from __future__ import annotations

import jsonschema

from ..models import ProviderResult
from .openai_provider import extract as extract_with_openai


def extract(provider: str, pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    if provider.strip().lower() != "openai":
        raise ValueError(f"Unsupported provider {provider!r}.")
    result = extract_with_openai(pdf_bytes, prompt, schema)
    jsonschema.validate(result.payload, schema)
    return result
