from __future__ import annotations

import hashlib
import re
from io import BytesIO

from pypdf import PdfReader

from .models import PdfSignals, ReviewNote

DAY_TOKEN_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)


def extract_page_texts(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


def analyze_pdf(pdf_bytes: bytes) -> PdfSignals:
    return analyze_page_texts(extract_page_texts(pdf_bytes))


def analyze_page_texts(page_texts: list[str]) -> PdfSignals:
    grid_header_pages: list[int] = []

    for page_index, text in enumerate(page_texts, start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if _has_grid_header(lines):
            grid_header_pages.append(page_index)

    return PdfSignals(
        page_count=len(page_texts),
        text_sha256=hashlib.sha256("\n\n".join(page_texts).encode("utf-8")).hexdigest(),
        grid_header_pages=grid_header_pages,
    )


def source_notes_for_payload(signals: PdfSignals, payload: dict) -> list[ReviewNote]:
    del payload  # unused — reserved for future payload-aware signals
    notes: list[ReviewNote] = []

    if len(signals.grid_header_pages) >= 2:
        notes.append(
            ReviewNote(
                kind="multi_grid_suspected",
                message=(
                    f"PDF appears to contain repeated day-grid pages ({len(signals.grid_header_pages)} pages with day headers)"
                ),
                evidence={"grid_header_pages": signals.grid_header_pages},
            )
        )

    return notes


def _has_grid_header(lines: list[str]) -> bool:
    for line in lines:
        day_tokens = {normalize_day_token(match.group(1)) for match in DAY_TOKEN_RE.finditer(line)}
        day_tokens.discard(None)
        if len(day_tokens) >= 3:
            return True
    return False


def normalize_day_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.lower()
    if token.startswith("mon"):
        return "monday"
    if token.startswith("tue"):
        return "tuesday"
    if token.startswith("wed"):
        return "wednesday"
    if token.startswith("thu"):
        return "thursday"
    if token.startswith("fri"):
        return "friday"
    if token.startswith("sat"):
        return "saturday"
    if token.startswith("sun"):
        return "sunday"
    return None
