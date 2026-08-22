from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import GroundingResult
from .paths import DATA_DIR, all_review_dirs, artifact_path, parse_review_dir_name, relative_to_repo


class PrefixCollisionError(RuntimeError):
    """Two review dirs share a sha12 prefix but differ in full hash."""


def _sidecar_sha256(review_dir: Path) -> str | None:
    sidecar = review_dir / "source.sha256"
    if not sidecar.is_file():
        return None
    try:
        text = sidecar.read_text().strip()
    except OSError:
        return None
    if len(text) == 64 and all(char in "0123456789abcdef" for char in text):
        return text
    return None


def _hash_and_backfill_source_pdf(review_dir: Path) -> str | None:
    pdf = review_dir / "source.pdf"
    if not pdf.is_file():
        return None
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    (review_dir / "source.sha256").write_text(f"{digest}\n")
    return digest


def find_review_dir_for_sha(slug: str, sha256: str, *, root: Path = DATA_DIR) -> Path | None:
    """Return the review dir whose full source hash is ``sha256``.

    Only parsed ``<date>-<sha12>`` dirs whose sha12 matches ``sha256[:12]``
    are considered. A present ``source.sha256`` sidecar wins; otherwise the
    helper hashes ``source.pdf`` and backfills the sidecar. Any prefix match
    with a different full hash is a collision.
    """
    prefix = sha256[:12]
    hits: list[Path] = []
    collision: PrefixCollisionError | None = None
    for review_dir in all_review_dirs(slug, root=root):
        parsed = parse_review_dir_name(review_dir.name)
        if parsed is None or parsed[1] != prefix:
            continue
        full = _sidecar_sha256(review_dir)
        if full is None:
            full = _hash_and_backfill_source_pdf(review_dir)
        if full is None:
            continue
        if full != sha256:
            collision = PrefixCollisionError(
                f"prefix collision in {slug}: existing={full} new={sha256}"
            )
            continue
        hits.append(review_dir)
    if collision is not None:
        raise collision
    return hits[0] if hits else None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def save_artifact_bundle(
    *,
    slug: str,
    date: str,
    provider: str,
    model: str,
    source_pdf_url: str,
    pdf_sha256: str,
    prompt: str,
    schema: dict,
    payload: dict,
    usage: dict,
    cost_estimate: str,
    grounding: GroundingResult | None = None,
    root: Path = DATA_DIR,
) -> dict[str, str]:
    target = artifact_path(slug, date, pdf_sha256, provider, model, root=root)
    target.parent.mkdir(parents=True, exist_ok=True)

    provider_payload: dict = {
        "provider": provider,
        "model": model,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "prompt_sha256": _sha256_text(prompt),
        "schema_sha256": _sha256_json(schema),
        "source_pdf_url": source_pdf_url,
        "pdf_sha256": pdf_sha256,
        "usage": usage,
        "cost_estimate": cost_estimate,
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
    target.write_text(json.dumps(provider_payload, indent=2, sort_keys=True) + "\n")

    return {provider: relative_to_repo(target)}


def skip_if_fresh(
    *,
    slug: str,
    date: str,
    pdf_sha256: str,
    provider: str,
    model: str,
    prompt: str,
    schema: dict,
    root: Path = DATA_DIR,
) -> bool:
    """Return True iff a cached provider JSON exists and its hashes match."""
    provider_file = artifact_path(slug, date, pdf_sha256, provider, model, root=root)
    if not provider_file.exists():
        return False
    try:
        data = json.loads(provider_file.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (
        data.get("prompt_sha256") == _sha256_text(prompt)
        and data.get("schema_sha256") == _sha256_json(schema)
    )
