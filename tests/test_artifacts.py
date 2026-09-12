import hashlib
import json
import pytest

from schedules.artifacts import find_review_dir_for_sha, save_artifact_bundle, skip_if_fresh
from schedules.paths import artifact_path


def _call_save(tmp_path, **overrides):
    kwargs = dict(
        slug="hamilton-pool",
        date="2026-04-19",
        provider="openai",
        model="gpt-5.5-2026-04-23",
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
        "hamilton-pool", "2026-04-19", "a" * 64, "openai", "gpt-5.5-2026-04-23", root=tmp_path
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
        provider="openai",
        model="gpt-5.5-2026-04-23",
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
        provider="openai",
        model="gpt-5.5-2026-04-23",
        prompt="P-NEW",
        schema={"x": 1},
        root=tmp_path,
    )


def test_skip_if_fresh_false_when_missing(tmp_path):
    assert not skip_if_fresh(
        slug="hamilton-pool",
        date="2026-04-19",
        pdf_sha256="a" * 64,
        provider="openai",
        model="gpt-5.5-2026-04-23",
        prompt="P",
        schema={"x": 1},
        root=tmp_path,
    )


@pytest.mark.parametrize("changed", [None, "model", "prompt", "schema", "parser", "renderer", "reasoning", "max_output_tokens"])
def test_extraction_cache_requires_exact_configuration(tmp_path, changed):
    configuration = {key: "original" for key in ("model", "prompt", "schema", "parser", "renderer", "reasoning", "max_output_tokens")}
    _call_save(tmp_path, prompt="P", schema={"x": 1}, details={"configuration": configuration})
    requested = configuration if changed is None else configuration | {changed: "changed"}
    assert skip_if_fresh(
        slug="hamilton-pool", date="2026-04-19", pdf_sha256="a" * 64,
        provider="openai", model="gpt-5.5-2026-04-23", prompt="P",
        schema={"x": 1}, root=tmp_path, configuration=requested,
    ) is (changed is None)


def test_find_review_dir_sidecar_hit_skips_pdf_hash(tmp_path, monkeypatch):
    sha256 = "a" * 64
    review_dir = tmp_path / "hamilton-pool" / f"2026-04-19-{sha256[:12]}"
    review_dir.mkdir(parents=True)
    (review_dir / "source.sha256").write_text(f"{sha256}\n")
    (review_dir / "source.pdf").write_bytes(b"bytes that would hash differently")

    def boom(_payload: bytes) -> str:
        raise AssertionError("sidecar hit must not hash source.pdf")

    monkeypatch.setattr("schedules.artifacts.hashlib.sha256", boom)
    assert find_review_dir_for_sha("hamilton-pool", sha256, root=tmp_path) == review_dir


def test_find_review_dir_backfills_missing_sidecar(tmp_path):
    pdf_bytes = b"%PDF-fake-source\n"
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    review_dir = tmp_path / "hamilton-pool" / f"2026-04-19-{sha256[:12]}"
    review_dir.mkdir(parents=True)
    (review_dir / "source.pdf").write_bytes(pdf_bytes)

    assert find_review_dir_for_sha("hamilton-pool", sha256, root=tmp_path) == review_dir
    assert (review_dir / "source.sha256").read_text() == f"{sha256}\n"
