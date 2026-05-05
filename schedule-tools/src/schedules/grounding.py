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
}

# Substrings that, if present in evidence, mean the row is from an ignore-list
# program — even if the surrounding text shares a token with an allowed type
# (e.g. "SENIOR/SELF GUIDED EXERCISE" contains "senior" but is exercise, not
# senior swim; "MASTER'S SWIM TEAM" might be adjacent to lap-swim cells but
# is a private team booking). Each token is matched against normalized
# (lowercased, period-stripped) evidence.
IGNORE_LIST_TOKENS: tuple[str, ...] = (
    "lessons",
    "learn to swim",
    "tiny tots",
    "aerobics",
    "exercise",
    "master",
    "synchro",
    "hockey",
    "water polo",
    "piranhas",
    "sfusd",
    "self guided",
    "parent/child",
)

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9:/]+")
_EVIDENCE_WINDOW_CHARS = 250


def compute_grounding(pdf_bytes: bytes, payload: dict) -> GroundingResult:
    reader = PdfReader(BytesIO(pdf_bytes))
    return grounding_from_text(normalize_pdf_text((page.extract_text() or "") for page in reader.pages), payload)


def normalize_pdf_text(page_texts: Iterable[str]) -> str:
    return _normalize("\n".join(page_texts))


def _evidence_locally_grounded(evidence: str, pdf_text: str) -> bool:
    """True if evidence is grounded in pdf_text, tolerating cross-line layouts.

    A row in a calendar PDF often serializes through pypdf as program label and
    time range on different lines, with intervening cells from other days.
    The literal substring check fails in those cases. This check accepts an
    extraction iff the evidence's significant tokens appear *in order* within
    a single window of pdf_text. Paraphrased evidence (tokens not present in
    the PDF, or out of order) is still rejected.
    """
    if not evidence or not pdf_text:
        return False
    if evidence in pdf_text:
        return True
    e_tokens = _TOKEN_RE.findall(evidence)
    if not e_tokens:
        return False
    first_token = e_tokens[0]
    for match in re.finditer(re.escape(first_token), pdf_text):
        win_start = match.start()
        win_end = min(len(pdf_text), win_start + _EVIDENCE_WINDOW_CHARS)
        cursor = match.end()
        ok = True
        for tok in e_tokens[1:]:
            i = pdf_text.find(tok, cursor, win_end)
            if i == -1:
                ok = False
                break
            cursor = i + len(tok)
        if ok:
            return True
    return False


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

        evidence_in_pdf = _evidence_locally_grounded(evidence, pdf_text_normalized)

        start = session.get("start") if isinstance(session.get("start"), str) else ""
        start_in_evidence = bool(start) and any(
            variant in evidence for variant in _start_variants(start)
        )

        type_in_evidence = bool(tokens) and any(token in evidence for token in tokens)
        ignore_token_in_evidence = any(token in evidence for token in IGNORE_LIST_TOKENS)

        # Multi-program cells (e.g. "LAP SWIM (4) SELF GUIDED EXERCISE (2)")
        # legitimately contain both a kept-type token and an ignore-list token.
        # Only block when the evidence has an ignore-list token AND no kept-type
        # token, which signals the model classified an ignore-list program as
        # a kept type.
        ignore_only = ignore_token_in_evidence and not type_in_evidence

        ok = all(
            (
                evidence_in_pdf,
                type_in_evidence,
                start_in_evidence,
                type_in_pdf_text,
                not ignore_only,
            )
        )
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
