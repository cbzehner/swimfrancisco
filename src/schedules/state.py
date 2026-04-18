from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ReviewFlag
from .paths import STATE_PATH
from .review import deserialize_flags, serialize_flag


def load_state(path: Path = STATE_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return raw


def save_state(state: dict[str, dict], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def entry_for(slug: str, *, path: Path = STATE_PATH) -> dict | None:
    return load_state(path).get(slug)


def build_state_entry(
    *,
    pdf_url: str,
    pdf_sha256: str,
    sessions_count: int,
    session_types: list[str],
    schedule_effective: str,
    provider: str,
    model: str,
    invariants_passed: bool,
    flags: list[ReviewFlag],
    artifact_paths: dict[str, str],
    pdf_page_count: int,
    pdf_text_sha256: str,
    adjudication_sha256: str | None = None,
) -> dict:
    return {
        "pdf_url": pdf_url,
        "pdf_sha256": pdf_sha256,
        "sessions_count": sessions_count,
        "session_types": sorted(set(session_types)),
        "schedule_effective": schedule_effective,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "invariants_passed": invariants_passed,
        "flags": [flag.message for flag in flags],
        "flag_details": [serialize_flag(flag) for flag in flags],
        "artifact_paths": artifact_paths,
        "pdf_page_count": pdf_page_count,
        "pdf_text_sha256": pdf_text_sha256,
        "adjudication_sha256": adjudication_sha256,
    }


def flags_for_entry(entry: dict | None) -> list[ReviewFlag]:
    if not entry:
        return []
    return deserialize_flags(entry.get("flag_details"), entry.get("flags"))
