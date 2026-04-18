from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO

from pypdf import PdfReader

from .models import GroundingResult, SessionGrounding

TYPE_TOKENS: dict[str, tuple[str, ...]] = {
    "lap_swim": ("lap",),
    "family_swim": ("family", "rec", "recreation"),
    "senior_swim": ("senior", "55+", "50+"),
    "lessons": ("lesson", "swim school", "learn to swim", "parent/child", "parent / child", "instruct"),
}

_WS_RE = re.compile(r"\s+")


def compute_grounding(pdf_bytes: bytes, payload: dict) -> GroundingResult:
    reader = PdfReader(BytesIO(pdf_bytes))
    return grounding_from_text(normalize_pdf_text((page.extract_text() or "") for page in reader.pages), payload)


def normalize_pdf_text(page_texts: Iterable[str]) -> str:
    return _normalize("\n".join(page_texts))


def grounding_from_text(pdf_text_normalized: str, payload: dict) -> GroundingResult:
    sessions_out: list[SessionGrounding] = []
    grounded = 0

    for index, session in enumerate(payload.get("sessions") or []):
        evidence_raw = session.get("evidence")
        evidence = _normalize(evidence_raw) if isinstance(evidence_raw, str) else ""
        typ = session.get("type") if isinstance(session.get("type"), str) else ""
        tokens = TYPE_TOKENS.get(typ, ())
        type_in_pdf_text = bool(tokens) and any(token in pdf_text_normalized for token in tokens)

        if not evidence:
            sessions_out.append(
                SessionGrounding(
                    index=index,
                    grounded=False,
                    missing_evidence=True,
                    evidence_in_pdf=False,
                    start_in_evidence=False,
                    type_in_evidence=False,
                    type_in_pdf_text=type_in_pdf_text,
                    session=session,
                )
            )
            continue

        evidence_in_pdf = evidence in pdf_text_normalized

        start = session.get("start") if isinstance(session.get("start"), str) else ""
        start_in_evidence = bool(start) and any(
            variant in evidence for variant in _start_variants(start)
        )

        type_in_evidence = bool(tokens) and any(token in evidence for token in tokens)

        ok = all((evidence_in_pdf, type_in_evidence, start_in_evidence, type_in_pdf_text))
        if ok:
            grounded += 1

        sessions_out.append(
            SessionGrounding(
                index=index,
                grounded=ok,
                missing_evidence=False,
                evidence_in_pdf=evidence_in_pdf,
                start_in_evidence=start_in_evidence,
                type_in_evidence=type_in_evidence,
                type_in_pdf_text=type_in_pdf_text,
                session=session,
            )
        )

    return GroundingResult(sessions=sessions_out, grounded_count=grounded, total=len(sessions_out))


def _normalize(text: str) -> str:
    value = text.lower().replace(".", "")
    value = _WS_RE.sub(" ", value)
    return value.strip()


def _start_variants(start: str) -> list[str]:
    try:
        hour_str, minute_str = start.split(":")
        hour_24 = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        return []

    hour_12 = hour_24 % 12 or 12
    meridiem = "am" if hour_24 < 12 else "pm"
    minute_txt = f"{minute:02d}"
    variants = [
        start,
        f"{hour_12}:{minute_txt}",
        f"{hour_12}:{minute_txt}{meridiem}",
        f"{hour_12}:{minute_txt} {meridiem}",
    ]
    if minute == 0:
        variants.extend([f"{hour_12}{meridiem}", f"{hour_12} {meridiem}"])
    return variants
