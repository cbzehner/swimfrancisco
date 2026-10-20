from dataclasses import replace
import hashlib

from schedules.artifacts import save_artifact_bundle
from schedules.detection import changed_sources
from schedules.discover import ClassifiedDocument, DiscoverDecision, DocumentLink
from schedules.providers.openai_provider import API_MODEL, extraction_configuration
from schedules.schema import EXTRACTION_SCHEMA


def decision(digest):
    document = ClassifiedDocument(
        link=DocumentLink(123, "https://sfrecpark.org/DocumentCenter/View/123", "Schedule"),
        kind="session_grid", filename="schedule.pdf", source="table", pdf_sha256=digest,
    )
    return DiscoverDecision("hamilton-pool", "unchanged", document.link.href, None,
                            "session_grid", "same_url", (document,), (), False)


def cached_source(root, prompt="extract"):
    digest = hashlib.sha256(b"schedule").hexdigest()
    capture = root / "hamilton-pool" / f"2026-10-19-{digest[:12]}"
    capture.mkdir(parents=True)
    (capture / "source.sha256").write_text(digest)
    (capture / "source.pdf").write_bytes(b"schedule")
    save_artifact_bundle(
        slug="hamilton-pool", date="2026-10-19", provider="openai", model=API_MODEL,
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/123", pdf_sha256=digest,
        prompt=prompt, schema=EXTRACTION_SCHEMA, payload={}, usage={}, cost_estimate="cached",
        details={"configuration": extraction_configuration(prompt)}, root=root,
    )
    return decision(digest)


def test_unchanged_source_and_configuration_need_no_extraction(tmp_path):
    assert changed_sources([cached_source(tmp_path)], "extract", data_root=tmp_path) == []


def test_changed_bytes_at_same_url_need_extraction(tmp_path):
    cached_source(tmp_path)
    result = changed_sources([decision("b" * 64)], "extract", data_root=tmp_path)
    assert result == [{"slug": "hamilton-pool", "reasons": ["new_source"]}]


def test_prompt_change_invalidates_unchanged_source(tmp_path):
    result = changed_sources([cached_source(tmp_path)], "new prompt", data_root=tmp_path)
    assert result[0]["reasons"] == ["extraction_configuration_changed"]


def test_missing_document_and_discovery_hold_are_not_clean(tmp_path):
    held = replace(decision(None), action="flag", blocking=True, reason="fetch_error")
    assert changed_sources([held], "extract", data_root=tmp_path)[0]["reasons"] == [
        "fetch_error", "unverified_document",
    ]
    empty = replace(held, candidates=())
    assert "no_documents" in changed_sources([empty], "extract", data_root=tmp_path)[0]["reasons"]


def test_changed_second_pool_component_is_detected(tmp_path):
    current = cached_source(tmp_path)
    second = replace(current.candidates[0], kind="split_part", pdf_sha256="b" * 64)
    paired = replace(current, candidates=(*current.candidates, second))
    assert changed_sources([paired], "extract", data_root=tmp_path)[0]["reasons"] == ["new_source"]


def test_new_closure_document_triggers_existing_review_pipeline(tmp_path):
    current = cached_source(tmp_path)
    closure = replace(current.candidates[0], kind="closure_notice", pdf_sha256="c" * 64)
    changed = replace(current, extra_candidates=(closure,))
    assert changed_sources([changed], "extract", data_root=tmp_path)[0]["reasons"] == ["new_source"]


def test_unchanged_pair_adoption_is_not_a_change(tmp_path):
    current = cached_source(tmp_path)
    paired = replace(current, action="adopt", reason="north_beach_pair",
                     candidates=(replace(current.candidates[0], kind="split_part"),))
    assert changed_sources([paired], "extract", data_root=tmp_path) == []


def test_verified_expired_grid_does_not_refresh_old_configuration(tmp_path, monkeypatch):
    current = cached_source(tmp_path)
    monkeypatch.setattr("schedules.detection.verified_expired_grid_ids", lambda *args, **kwargs: {123})
    assert changed_sources([current], "new prompt", data_root=tmp_path) == []
