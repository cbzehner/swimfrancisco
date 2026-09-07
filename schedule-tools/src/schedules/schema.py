from __future__ import annotations

import copy
import json
import re
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


def source_facts_schema() -> dict:
    schema = copy.deepcopy(EXTRACTION_SCHEMA)
    session = schema["properties"]["sessions"]["items"]
    for field in ("pool", "physical_pool", "source_sha256", "source_cell"):
        del session["properties"][field]
    session["properties"]["pool_label_raw"] = {
        "type": ["string", "null"], "minLength": 1,
        "description": "Verbatim complete pool allocation printed for this session, including qualifiers and combined lane/section labels. Do not simplify, lowercase, expand codes, or remove words. Null if no label or only a numeric lane count.",
    }
    session["required"].append("pool_label_raw")
    return schema


SOURCE_FACTS_SCHEMA = source_facts_schema()


def pool_label_payload(facts: dict) -> dict:
    def session_payload(session: dict) -> dict:
        row = {key: value for key, value in session.items() if key != "pool_label_raw"}
        label = session["pool_label_raw"]
        if label is None:
            return row
        label = label.strip()
        if label.startswith("(") and label.endswith(")"):
            label = label[1:-1]
        label = " ".join(re.sub(r"\bpool\b", "", label.lower()).split())
        return row | {"pool": label} if label else row

    return facts | {"sessions": [session_payload(session) for session in facts["sessions"]]}
