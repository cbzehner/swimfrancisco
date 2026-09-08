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
    if "direct_source" in envelope:
        source = envelope["direct_source"]
        if not isinstance(source, dict) or source.get("sha256") != envelope.get("pdf_sha256") or source.get("requested_url") != envelope.get("source_pdf_url"):
            raise EnvelopeValidationError("Direct source evidence must match the envelope identity and original URL")
    if "bundle_sha256" in envelope:
        sources = envelope.get("source_bundle", [])
        if not isinstance(sources, list) or len(sources) != 2 or [item.get("pool") for item in sources if isinstance(item, dict)] != ["cool", "warm"]:
            raise EnvelopeValidationError("A bundle requires one Cool and one Warm source")
        for session in envelope.get("payload", {}).get("sessions", []):
            if not isinstance(session, dict):
                raise EnvelopeValidationError("Invalid bundle session")
            member = next((item for item in sources if item["pool"] == session.get("physical_pool")), None)
            if member is None or session.get("source_sha256") != member.get("sha256") or not session.get("source_cell") or "pool_label_raw" not in session:
                raise EnvelopeValidationError("Every bundle session requires its physical pool and original source evidence")
    try:
        jsonschema.validate(
            instance=envelope,
            schema=load_envelope_schema(),
            format_checker=jsonschema.FormatChecker(),
        )
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        message = "; ".join(error.message for error in exc.context if error.validator == "required") or exc.message
        raise EnvelopeValidationError(f"{location}: {message}") from exc
