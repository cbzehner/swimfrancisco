"""Cheap city-pool preflight; publication still belongs to ``automate``."""
from __future__ import annotations

from pathlib import Path
from datetime import date

from ._time import pacific_today
from .artifacts import find_review_dir_for_sha, skip_if_fresh
from .discover import DiscoverDecision, _decision_to_json, collapse_grid_candidates
from .paths import DATA_DIR
from .providers.openai_provider import API_MODEL, extraction_configuration
from .schema import EXTRACTION_SCHEMA
from .window_dates import verified_expired_grid_ids


def changed_sources(decisions: list[DiscoverDecision], prompt: str, *, data_root: Path = DATA_DIR,
                    today: date | None = None) -> list[dict]:
    """Return reasons to run extraction, never permission to publish.

    Missing or ambiguous evidence deliberately runs the normal pipeline, whose
    reports and publication gates handle those cases. An unchanged PDF still
    needs extraction when its model, prompt, schema, or configuration changes.
    """
    changes = []
    configuration = extraction_configuration(prompt)
    for decision in decisions:
        reasons = set()
        # Complete paired discovery deliberately returns adopt on every pass.
        # Its component hashes/configuration below establish actual changes.
        if decision.blocking or (decision.action != "unchanged" and decision.reason != "north_beach_pair"):
            reasons.add(decision.reason)
        documents = (*decision.candidates, *decision.extra_candidates)
        serialized = _decision_to_json(decision)
        expired = verified_expired_grid_ids(decision.slug, serialized, today or pacific_today(), data_root=data_root)
        selected_grids = {item["view_id"] for item in collapse_grid_candidates(
            serialized["candidates"] + serialized["extra_candidates"])}
        if not documents:
            reasons.add("no_documents")
        for document in documents:
            if document.kind == "session_grid" and (
                document.link.view_id in expired or document.link.view_id not in selected_grids
            ):
                continue
            digest = document.pdf_sha256
            if not digest:
                reasons.add("unverified_document")
                continue
            capture = find_review_dir_for_sha(decision.slug, digest, root=data_root)
            if capture is None:
                reasons.add("new_source")
            elif document.kind in {"session_grid", "split_part"} and not skip_if_fresh(
                slug=decision.slug, date=capture.name[:10], pdf_sha256=digest,
                provider="openai", model=API_MODEL, prompt=prompt,
                schema=EXTRACTION_SCHEMA, configuration=configuration, root=data_root,
            ):
                reasons.add("extraction_configuration_changed")
        if reasons:
            changes.append({"slug": decision.slug, "reasons": sorted(reasons)})
    return changes
