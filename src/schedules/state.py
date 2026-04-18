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
    pdf_sha256: str,
    provider: str,
    model: str,
    notes: list[ReviewNote],
    artifact_paths: dict[str, str],
    pdf_page_count: int,
    pdf_text_sha256: str,
    reviewed_snapshot_sha256: str | None = None,
) -> dict:
    """Build a state entry carrying *provenance only*.

    Anything derivable from ``content/spots/<slug>.md`` (sessions, closures,
    schedule_effective, invariants_passed) lives there — duplicating it here
    invites drift. State retains only data that cannot be reconstructed from
    content: the fast-path pdf/reviewed snapshot hashes, the provider/model that
    produced the extraction, and operator-facing notes/artifacts.
    """
    return {
        "pdf_sha256": pdf_sha256,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "notes": [note.message for note in notes],
        "note_details": [serialize_note(note) for note in notes],
        "artifact_paths": artifact_paths,
        "pdf_page_count": pdf_page_count,
        "pdf_text_sha256": pdf_text_sha256,
        "reviewed_snapshot_sha256": reviewed_snapshot_sha256,
    }


def notes_for_entry(entry: dict | None) -> list[ReviewNote]:
    if not entry:
        return []
    return deserialize_notes(entry.get("note_details"), entry.get("notes"))
