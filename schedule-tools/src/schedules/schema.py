from __future__ import annotations

import copy
import json
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "reviewed-snapshot.json"


def _inline_refs(node, defs):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and len(node) == 1:
            prefix = "#/$defs/"
            if not ref.startswith(prefix):
                raise ValueError(f"unsupported schema $ref: {ref}")
            return _inline_refs(copy.deepcopy(defs[ref[len(prefix):]]), defs)
        return {key: _inline_refs(value, defs) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(value, defs) for value in node]
    return node


def load_extraction_schema() -> dict:
    envelope = json.loads(_SCHEMA_PATH.read_text())
    return _inline_refs(envelope["properties"]["payload"], envelope.get("$defs") or {})


EXTRACTION_SCHEMA = load_extraction_schema()
