"""Pipeline fast-path tests: reviewed.json existence and provider-cache freshness."""
from __future__ import annotations

import json
from pathlib import Path

from schedules import artifacts as artifacts_mod
from schedules import paths as paths_mod
from schedules import registry as registry_mod
from schedules.models import FetchResult, Proposed, Unchanged
from schedules.pipeline import run_pipeline
from schedules.report import write_report
from schedules.schema import EXTRACTION_SCHEMA as _EXTRACTION_SCHEMA


SLUG = "hamilton-pool"
PDF_SHA = "a" * 64
SHA12 = PDF_SHA[:12]
DATE = "2026-04-19"
PDF_URL = "https://example.com/x.pdf"


def _payload() -> dict:
    return {
        "schedule_effective": "2026-03-17",
        "sessions": [
            {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
        ],
        "closures": [],
    }


def _setup_world(tmp_path: Path, monkeypatch, *, with_reviewed: bool, with_cached_provider: bool, prompt_text: str) -> Path:
    data_root = tmp_path / "data"
    review_dir = data_root / SLUG / f"{DATE}-{SHA12}"
    review_dir.mkdir(parents=True)
    (review_dir / "source.pdf").write_bytes(b"%PDF-fake")

    if with_reviewed:
        (review_dir / "reviewed.json").write_text(json.dumps({
            "slug": SLUG,
            "pdf_sha256": PDF_SHA,
            "reviewed_at": DATE,
            "source_pdf_url": PDF_URL,
            "payload": _payload(),
        }) + "\n")

    if with_cached_provider:
        artifacts_mod.save_artifact_bundle(
            slug=SLUG,
            date=DATE,
            provider="gemini",
            model="gemini-3.1-flash-lite-preview",
            source_pdf_url=PDF_URL,
            pdf_sha256=PDF_SHA,
            prompt=prompt_text,
            schema=_EXTRACTION_SCHEMA,
            payload=_payload(),
            usage={},
            cost_estimate="cached",
            root=data_root,
        )

    content_dir = tmp_path / "content" / "spots"
    content_dir.mkdir(parents=True)
    (content_dir / f"{SLUG}.md").write_text("+++\ntitle = \"Hamilton\"\n\n[extra]\n+++\n")

    registry_path = tmp_path / "registry.toml"
    registry_path.write_text(
        f'[[pool]]\nslug = "{SLUG}"\npdf_url = "{PDF_URL}"\n'
        f'official_page_url = "https://example.com/"\n'
    )

    prompt_path = tmp_path / "extract.txt"
    prompt_path.write_text(prompt_text)

    report_path = tmp_path / "report.md"

    orig_reviewed_path = paths_mod.reviewed_path
    orig_artifact_path = paths_mod.artifact_path
    orig_skip_if_fresh = artifacts_mod.skip_if_fresh
    orig_save = artifacts_mod.save_artifact_bundle
    orig_load_registry = registry_mod.load_registry

    monkeypatch.setattr("schedules.registry.CONTENT_SPOTS_DIR", content_dir)
    monkeypatch.setattr("schedules.pipeline.CONTENT_SPOTS_DIR", content_dir)
    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", prompt_path)
    monkeypatch.setattr(
        "schedules.pipeline.load_registry",
        lambda: orig_load_registry(path=registry_path),
    )
    monkeypatch.setattr(
        "schedules.pipeline.reviewed_path",
        lambda slug, date, sha: orig_reviewed_path(slug, date, sha, root=data_root),
    )
    monkeypatch.setattr(
        "schedules.pipeline.artifact_path",
        lambda slug, date, sha, provider, model: orig_artifact_path(
            slug, date, sha, provider, model, root=data_root
        ),
    )
    monkeypatch.setattr(
        "schedules.pipeline.skip_if_fresh",
        lambda **kw: orig_skip_if_fresh(root=data_root, **kw),
    )
    monkeypatch.setattr(
        "schedules.pipeline.save_artifact_bundle",
        lambda **kw: orig_save(root=data_root, **kw),
    )
    monkeypatch.setattr(
        "schedules.pipeline.write_report",
        lambda results: write_report(results, path=report_path),
    )

    # PDF inspection is out of scope for these pipeline-flow tests.
    from schedules.models import GroundingResult, PdfSignals
    monkeypatch.setattr("schedules.pipeline.extract_page_texts", lambda _bytes: [""])
    monkeypatch.setattr(
        "schedules.pipeline.analyze_page_texts",
        lambda _pages: PdfSignals(page_count=1, text_sha256="x", grid_header_pages=[], timed_lesson_line_count=0),
    )
    monkeypatch.setattr("schedules.pipeline.normalize_pdf_text", lambda _pages: "")
    monkeypatch.setattr(
        "schedules.pipeline.grounding_from_text",
        lambda _text, _payload: GroundingResult(sessions=[], grounded_count=0, total=0),
    )
    monkeypatch.setattr("schedules.pipeline.source_notes_for_payload", lambda _sig, _payload: [])
    monkeypatch.setattr("schedules.pipeline.check_delta", lambda _payload, _prior: [])

    source_pdf = review_dir / "source.pdf"

    def fake_fetch(slug_, url_, *, force=False):
        return FetchResult(
            path=source_pdf,
            sha256=PDF_SHA,
            bytes=source_pdf.read_bytes(),
            from_cache=True,
            page_count=1,
            response_url=url_,
        )

    monkeypatch.setattr("schedules.pipeline.fetch_pdf", fake_fetch)

    return data_root


def _raise_if_called(*_args, **_kwargs):
    raise AssertionError("extract_with_provider must not be called on the fast path")


def test_extract_skips_llm_when_reviewed_exists(tmp_path, monkeypatch):
    _setup_world(tmp_path, monkeypatch, with_reviewed=True, with_cached_provider=False, prompt_text="P")
    monkeypatch.setattr("schedules.pipeline.extract_with_provider", _raise_if_called)

    exit_code, _, results = run_pipeline(
        slugs=[SLUG], provider="gemini", compare_with=None, force=False, dry_run=True,
    )

    assert exit_code == 0
    assert len(results) == 1
    assert isinstance(results[0], Unchanged)
    assert results[0].sessions_count == 5


def test_extract_uses_cached_provider_when_prompt_hashes_match(tmp_path, monkeypatch):
    _setup_world(tmp_path, monkeypatch, with_reviewed=False, with_cached_provider=True, prompt_text="P")
    monkeypatch.setattr("schedules.pipeline.extract_with_provider", _raise_if_called)

    exit_code, _, results = run_pipeline(
        slugs=[SLUG], provider="gemini", compare_with=None, force=False, dry_run=True,
    )

    from schedules.models import Failed as _Failed
    if isinstance(results[0], _Failed):
        raise AssertionError(f"pipeline Failed: {results[0].error!r}")
    assert isinstance(results[0], Proposed), results[0]
    assert exit_code == 0
    assert results[0].sessions_count == 5


def test_extract_reruns_after_prompt_change(tmp_path, monkeypatch):
    # Cache was written with prompt "OLD"; current prompt is "NEW" ⇒ skip_if_fresh False ⇒ LLM called.
    _setup_world(tmp_path, monkeypatch, with_reviewed=False, with_cached_provider=True, prompt_text="NEW")
    # Overwrite cached provider JSON so it carries the OLD prompt hash.
    from schedules.artifacts import save_artifact_bundle
    data_root = tmp_path / "data"
    save_artifact_bundle(
        slug=SLUG, date=DATE, provider="gemini", model="gemini-3.1-flash-lite-preview",
        source_pdf_url=PDF_URL, pdf_sha256=PDF_SHA,
        prompt="OLD", schema={"type": "object"},
        payload=_payload(), usage={}, cost_estimate="cached",
        root=data_root,
    )

    call_count = {"n": 0}

    def fake_extract(provider, pdf_bytes, prompt, schema):
        call_count["n"] += 1
        from schedules.models import ProviderResult
        return ProviderResult(
            payload=_payload(),
            model="gemini-3.1-flash-lite-preview",
            usage={},
            cost_estimate="fresh",
        )

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", fake_extract)

    exit_code, _, results = run_pipeline(
        slugs=[SLUG], provider="gemini", compare_with=None, force=False, dry_run=True,
    )

    assert exit_code == 0
    assert call_count["n"] == 1
    assert isinstance(results[0], Proposed)
