from __future__ import annotations

import hashlib
import re
from io import BytesIO

from pypdf import PdfReader

from .models import PdfSignals, ReviewFlag

DAY_TOKEN_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[-–—‒‑‐−]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    re.IGNORECASE,
)


def extract_page_texts(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


def analyze_pdf(pdf_bytes: bytes) -> PdfSignals:
    return analyze_page_texts(extract_page_texts(pdf_bytes))


def analyze_page_texts(page_texts: list[str]) -> PdfSignals:
    grid_header_pages: list[int] = []
    timed_lesson_line_count = 0

    for page_index, text in enumerate(page_texts, start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if _has_grid_header(lines):
            grid_header_pages.append(page_index)
        timed_lesson_line_count += _count_timed_lesson_blocks(lines)

    return PdfSignals(
        page_count=len(page_texts),
        text_sha256=hashlib.sha256("\n\n".join(page_texts).encode("utf-8")).hexdigest(),
        grid_header_pages=grid_header_pages,
        timed_lesson_line_count=timed_lesson_line_count,
    )


def source_flags_for_payload(signals: PdfSignals, payload: dict) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []

    if len(signals.grid_header_pages) >= 2:
        flags.append(
            ReviewFlag(
                kind="multi_grid_suspected",
                message=(
                    f"PDF appears to contain repeated day-grid pages ({len(signals.grid_header_pages)} pages with day headers)"
                ),
                evidence={"grid_header_pages": signals.grid_header_pages},
            )
        )

    extracted_lessons = sum(
        1
        for session in payload.get("sessions") or []
        if str(session.get("type")) == "lessons"
    )
    if signals.timed_lesson_line_count > extracted_lessons:
        flags.append(
            ReviewFlag(
                kind="timed_lessons_under_extracted",
                message=(
                    f"source PDF contains {signals.timed_lesson_line_count} timed lesson-like lines but extraction produced {extracted_lessons} lesson sessions"
                ),
                evidence={
                    "timed_lesson_line_count": signals.timed_lesson_line_count,
                    "extracted_lessons": extracted_lessons,
                },
            )
        )

    return flags


def _has_grid_header(lines: list[str]) -> bool:
    for line in lines:
        day_tokens = {normalize_day_token(match.group(1)) for match in DAY_TOKEN_RE.finditer(line)}
        day_tokens.discard(None)
        if len(day_tokens) >= 3:
            return True
    return False


def _count_timed_lesson_blocks(lines: list[str]) -> int:
    count = 0
    pending_lesson = False

    for line in lines:
        low = line.lower()
        has_lesson = "lesson" in low
        has_time = bool(TIME_RANGE_RE.search(line))

        if has_lesson and has_time:
            count += 1
            pending_lesson = False
            continue
        if has_lesson:
            pending_lesson = True
            continue
        if pending_lesson and has_time:
            count += 1
            pending_lesson = False
            continue
        if has_time:
            pending_lesson = False

    return count


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
