from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .paths import ADJUDICATIONS_DIR, relative_to_repo


def adjudication_path(slug: str, pdf_sha256: str, root: Path = ADJUDICATIONS_DIR) -> Path:
    return root / slug / f"{pdf_sha256}.json"


def load_adjudication(
    slug: str,
    pdf_sha256: str,
    *,
    root: Path = ADJUDICATIONS_DIR,
) -> tuple[dict | None, str | None, str | None]:
    path = adjudication_path(slug, pdf_sha256, root)
    if not path.exists():
        return None, None, None

    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is missing a payload object.")

    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    return raw, fingerprint, relative_to_repo(path)
