from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema

from .paths import REVIEWED_SNAPSHOTS_DIR


class EnvelopeValidationError(ValueError):
    """Raised when a reviewed-snapshot envelope fails schema validation."""


_SCHEMA_PATH = REVIEWED_SNAPSHOTS_DIR / "schema.json"


@lru_cache(maxsize=1)
def load_envelope_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def validate_envelope(envelope: dict) -> None:
    """Validate an envelope against the committed schema.

    Raises EnvelopeValidationError with a human-readable message on failure.
    """
    try:
        jsonschema.validate(instance=envelope, schema=load_envelope_schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise EnvelopeValidationError(f"{location}: {exc.message}") from exc
