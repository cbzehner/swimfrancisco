from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import GroundingResult, PdfSignals
from .paths import ARTIFACTS_DIR, relative_to_repo, slugify


def save_artifact_bundle(
    *,
    slug: str,
    provider: str,
    model: str,
    pdf_url: str,
    pdf_sha256: str,
    pdf_signals: PdfSignals,
    prompt: str,
    schema: dict,
    payload: dict,
    usage: dict,
    cost_estimate: str,
    grounding: GroundingResult | None = None,
    root: Path = ARTIFACTS_DIR,
) -> dict[str, str]:
    artifact_dir = root / slug / pdf_sha256[:12]
    artifact_dir.mkdir(parents=True, exist_ok=True)

    meta_path = artifact_dir / "meta.json"
    provider_path = artifact_dir / f"{provider}-{slugify(model)}.json"

    meta = {
        "slug": slug,
        "pdf_url": pdf_url,
        "pdf_sha256": pdf_sha256,
        "pdf_page_count": pdf_signals.page_count,
        "pdf_text_sha256": pdf_signals.text_sha256,
        "grid_header_pages": pdf_signals.grid_header_pages,
        "timed_lesson_line_count": pdf_signals.timed_lesson_line_count,
        "prompt_hash": _sha256_text(prompt),
        "schema_hash": hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")

    provider_payload = {
        "slug": slug,
        "provider": provider,
        "model": model,
        "pdf_url": pdf_url,
        "pdf_sha256": pdf_sha256,
        "pdf_page_count": pdf_signals.page_count,
        "pdf_text_sha256": pdf_signals.text_sha256,
        "usage": usage,
        "cost_estimate": cost_estimate,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    if grounding is not None:
        provider_payload["grounding"] = {
            "grounded_count": grounding.grounded_count,
            "total": grounding.total,
            "ratio": round(grounding.ratio, 4),
            "sessions": [
                {
                    "index": entry.index,
                    "grounded": entry.grounded,
                    "missing_evidence": entry.missing_evidence,
                    "evidence_in_pdf": entry.evidence_in_pdf,
                    "start_in_evidence": entry.start_in_evidence,
                    "type_in_evidence": entry.type_in_evidence,
                }
                for entry in grounding.sessions
            ],
        }
    provider_path.write_text(json.dumps(provider_payload, indent=2, sort_keys=True) + "\n")

    return {
        "meta": relative_to_repo(meta_path),
        provider: relative_to_repo(provider_path),
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


