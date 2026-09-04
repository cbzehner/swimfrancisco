from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jsonschema

class EnvelopeValidationError(ValueError):
    """Raised when a reviewed-snapshot envelope fails schema validation."""


_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reviewed-snapshot.json"


@lru_cache(maxsize=1)
def load_envelope_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


@dataclass(frozen=True)
class AttestationLegacy:
    pass


@dataclass(frozen=True)
class AttestationHuman:
    pass


@dataclass(frozen=True)
class AttestationCi:
    pass


@dataclass(frozen=True)
class AttestationCarried:
    from_path: str
    origin: AttestationLegacy | AttestationHuman | AttestationCi


def _origin(attested_by: object) -> AttestationLegacy | AttestationHuman | AttestationCi:
    if attested_by == "ci":
        return AttestationCi()
    if attested_by == "human":
        return AttestationHuman()
    return AttestationLegacy()


def parse_attestation(envelope: dict) -> AttestationLegacy | AttestationHuman | AttestationCi | AttestationCarried:
    carried = envelope.get("carried_from")
    origin = _origin(envelope.get("attested_by"))
    if isinstance(carried, str) and carried:
        return AttestationCarried(carried, origin)
    return origin


def validate_envelope(envelope: dict) -> None:
    """Validate an envelope against the committed schema.

    Raises EnvelopeValidationError with a human-readable message on failure.
    """
    try:
        jsonschema.validate(
            instance=envelope,
            schema=load_envelope_schema(),
            format_checker=jsonschema.FormatChecker(),
        )
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise EnvelopeValidationError(f"{location}: {exc.message}") from exc
