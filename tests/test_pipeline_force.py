"""--force and --compare-with must bypass the reviewed.json fast-path."""
from __future__ import annotations

import json
from pathlib import Path

from schedules import artifacts as artifacts_mod
from schedules import paths as paths_mod
from schedules import registry as registry_mod
from schedules.models import FetchResult, ProviderResult
from schedules.pipeline import BakeoffRun, PdfRun, ExpandFromDecisions, run_pipeline
from schedules.report import write_report


SLUG = "hamilton-pool"
PDF_SHA = "a" * 64
SHA12 = PDF_SHA[:12]
DATE = "2026-04-19"
PDF_URL = "https://example.com/x.pdf"


def _payload() -> dict:
    return {
        "effective_start": "2026-03-17",
        "sessions": [
            {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
        ],
        "closures": [],
    }


def _setup(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    review_dir = data_root / SLUG / f"{DATE}-{SHA12}"
    review_dir.mkdir(parents=True)
    (review_dir / "source.pdf").write_bytes(b"%PDF-fake")
    (review_dir / "reviewed.json").write_text(json.dumps({
        "slug": SLUG,
        "pdf_sha256": PDF_SHA,
        "reviewed_at": DATE,
        "source_pdf_url": PDF_URL,
        "payload": _payload(),
    }) + "\n")

    content_dir = tmp_path / "content" / "spots"
    content_dir.mkdir(parents=True)
    (content_dir / f"{SLUG}.md").write_text("+++\ntitle = \"Hamilton\"\n\n[extra]\n+++\n")

    registry_path = tmp_path / "registry.toml"
    registry_path.write_text(
        f'[[pool]]\nslug = "{SLUG}"\npdf_url = "{PDF_URL}"\n'
        f'official_page_url = "https://example.com/"\n'
    )

    prompt_path = tmp_path / "extract.txt"
    prompt_path.write_text("P")
    report_path = tmp_path / "report.md"

    orig_reviewed_path = paths_mod.reviewed_path
    orig_artifact_path = paths_mod.artifact_path
    orig_skip = artifacts_mod.skip_if_fresh
    orig_save = artifacts_mod.save_artifact_bundle
    orig_load = registry_mod.load_registry

    monkeypatch.setattr("schedules.registry.CONTENT_SPOTS_DIR", content_dir)
    monkeypatch.setattr("schedules.pipeline.CONTENT_SPOTS_DIR", content_dir)
    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", prompt_path)
    monkeypatch.setattr(
        "schedules.pipeline.load_registry",
        lambda: orig_load(path=registry_path),
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
    monkeypatch.setattr("schedules.pipeline.skip_if_fresh", lambda **kw: orig_skip(root=data_root, **kw))
    monkeypatch.setattr("schedules.pipeline.save_artifact_bundle", lambda **kw: orig_save(root=data_root, **kw))
    monkeypatch.setattr(
        "schedules.pipeline.write_report",
        lambda results, path=None: write_report(results, path=report_path),
    )

    from schedules.models import GroundingResult
    monkeypatch.setattr("schedules.pipeline.extract_page_texts", lambda _bytes: [""])
    monkeypatch.setattr(
        "schedules.pipeline.analyze_page_texts",
        lambda _pages: [],
    )
    monkeypatch.setattr("schedules.pipeline.normalize_pdf_text", lambda _pages: "")
    monkeypatch.setattr(
        "schedules.pipeline.grounding_from_text",
        lambda _text, _payload: GroundingResult(sessions=[]),
    )
    monkeypatch.setattr("schedules.pipeline.source_notes_for_signals", lambda _sig: [])
    monkeypatch.setattr("schedules.pipeline.check_delta", lambda _payload, _prior: [])

    source_pdf = review_dir / "source.pdf"

    def fake_fetch(slug_, url_, *, force=False):
        return FetchResult(
            path=source_pdf,
            sha256=PDF_SHA,
            bytes=source_pdf.read_bytes(),
            from_cache=True,
            page_count=1,
        )

    monkeypatch.setattr("schedules.pipeline.fetch_pdf", fake_fetch)


def _provider_result() -> ProviderResult:
    return ProviderResult(
        payload=_payload(),
        model="gemini-3.1-flash-lite-preview",
        usage={},
    )


def test_force_bypasses_reviewed_fast_path(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_extract(provider, pdf_bytes, prompt, schema):
        calls["n"] += 1
        return _provider_result()

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", fake_extract)

    exit_code, _, results = run_pipeline(
        PdfRun(provider="gemini", slugs=(SLUG,), force=True, urls=ExpandFromDecisions()),
    )

    assert exit_code == 0
    assert calls["n"] == 1, "--force must invoke the provider even when reviewed.json exists"
    assert results[0].provider == "gemini"


def test_compare_with_bypasses_reviewed_fast_path(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_extract(provider, pdf_bytes, prompt, schema):
        calls["n"] += 1
        return _provider_result()

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", fake_extract)

    exit_code, _, results = run_pipeline(
        BakeoffRun(provider="gemini", compare_with="anthropic", slugs=(SLUG,), force=False),
    )

    assert exit_code == 0
    # Primary + compare = two invocations.
    assert calls["n"] == 2, "--compare-with must invoke both providers"
