from __future__ import annotations

from ..models import ProviderResult
from .anthropic_provider import extract as extract_with_anthropic
from .gemini_provider import extract as extract_with_gemini


def extract(provider: str, pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    normalized = provider.strip().lower()
    if normalized == "anthropic":
        return extract_with_anthropic(pdf_bytes, prompt, schema)
    if normalized == "gemini":
        return extract_with_gemini(pdf_bytes, prompt, schema)
    raise ValueError(f"Unsupported provider {provider!r}.")

