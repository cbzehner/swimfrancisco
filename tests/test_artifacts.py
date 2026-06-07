import json

from schedules.artifacts import save_artifact_bundle, skip_if_fresh
from schedules.paths import artifact_path


def _call_save(tmp_path, **overrides):
    kwargs = dict(
        slug="hamilton-pool",
        date="2026-04-19",
        provider="gemini",
        model="gemini-3.1-flash-lite-preview",
        source_pdf_url="https://example.com/hamilton.pdf",
        pdf_sha256="a" * 64,
        prompt="extract schedule",
        schema={"type": "object"},
        payload={"sessions": [], "closures": [], "effective_start": "2026-03-17"},
        usage={"total_token_count": 42},
        cost_estimate="total_tokens=42",
        root=tmp_path,
    )
    kwargs.update(overrides)
    return save_artifact_bundle(**kwargs)


def test_artifact_bundle_writes_self_describing_provider_json(tmp_path):
    _call_save(tmp_path)
    target = artifact_path(
        "hamilton-pool", "2026-04-19", "a" * 64, "gemini", "gemini-3.1-flash-lite-preview", root=tmp_path
    )
    assert target.exists()
    data = json.loads(target.read_text())
    assert set(data) >= {
        "provider", "model", "extracted_at",
        "prompt_sha256", "schema_sha256",
        "source_pdf_url", "pdf_sha256",
        "usage", "cost_estimate", "payload",
    }
    assert not {"slug", "pdf_page_count", "pdf_text_sha256"} & set(data)


def test_artifact_bundle_writes_no_meta_json(tmp_path):
    _call_save(tmp_path)
    review_dir = tmp_path / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa"
    assert not (review_dir / "meta.json").exists()


def test_skip_if_fresh_returns_true_when_hashes_match(tmp_path):
    _call_save(tmp_path, prompt="P", schema={"x": 1})
    assert skip_if_fresh(
        slug="hamilton-pool",
        date="2026-04-19",
        pdf_sha256="a" * 64,
        provider="gemini",
        model="gemini-3.1-flash-lite-preview",
        prompt="P",
        schema={"x": 1},
        root=tmp_path,
    )


def test_skip_if_fresh_false_on_prompt_change(tmp_path):
    _call_save(tmp_path, prompt="P", schema={"x": 1})
    assert not skip_if_fresh(
        slug="hamilton-pool",
        date="2026-04-19",
        pdf_sha256="a" * 64,
        provider="gemini",
        model="gemini-3.1-flash-lite-preview",
        prompt="P-NEW",
        schema={"x": 1},
        root=tmp_path,
    )


def test_skip_if_fresh_false_when_missing(tmp_path):
    assert not skip_if_fresh(
        slug="hamilton-pool",
        date="2026-04-19",
        pdf_sha256="a" * 64,
        provider="gemini",
        model="gemini-3.1-flash-lite-preview",
        prompt="P",
        schema={"x": 1},
        root=tmp_path,
    )
