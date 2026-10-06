from __future__ import annotations

from ..models import ProviderResult
from .openai_provider import extract as extract_with_openai


def extract(provider: str, pdf_bytes: bytes, prompt: str, schema: dict) -> ProviderResult:
    """Dispatch to the only supported extraction provider.

    ``openai_provider.extract`` validates its payload against ``schema``
    before returning, so there is nothing left to check here.
    """
    if provider.strip().lower() != "openai":
        raise ValueError(f"Unsupported provider {provider!r}.")
    return extract_with_openai(pdf_bytes, prompt, schema)
