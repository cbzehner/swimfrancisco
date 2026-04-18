from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ReviewNote
from .paths import STATE_PATH
from .review import deserialize_notes, serialize_note


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
    notes: list[ReviewNote],
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
        "notes": [note.message for note in notes],
        "note_details": [serialize_note(note) for note in notes],
        "artifact_paths": artifact_paths,
        "pdf_page_count": pdf_page_count,
        "pdf_text_sha256": pdf_text_sha256,
        "adjudication_sha256": adjudication_sha256,
    }


def notes_for_entry(entry: dict | None) -> list[ReviewNote]:
    if not entry:
        return []
    # Read both key schemes during the rename transition. Older state files
    # used ``flags``/``flag_details``; once Step 5 lands the old keys disappear.
    details = entry.get("note_details") or entry.get("flag_details")
    messages = entry.get("notes") or entry.get("flags")
    return deserialize_notes(details, messages)
