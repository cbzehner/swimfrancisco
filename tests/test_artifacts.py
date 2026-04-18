from pathlib import Path

from schedules.artifacts import save_artifact_bundle
from schedules.models import PdfSignals


def test_save_artifact_bundle_writes_meta_and_provider_files(tmp_path):
    paths = save_artifact_bundle(
        slug="hamilton-pool",
        provider="gemini",
        model="gemini-3.1-flash-lite-preview",
        pdf_url="https://example.com/hamilton.pdf",
        pdf_sha256="abc123abc123abc123abc123",
        pdf_signals=PdfSignals(
            page_count=1,
            text_sha256="textsha",
            grid_header_pages=[1],
            timed_lesson_line_count=2,
        ),
        prompt="extract schedule",
        schema={"type": "object"},
        payload={"sessions": [], "closures": [], "schedule_effective": "2026-03-17"},
        usage={"total_token_count": 42},
        cost_estimate="total_tokens=42",
        root=tmp_path,
    )
    assert set(paths) == {"meta", "gemini"}
    assert (tmp_path / "hamilton-pool" / "abc123abc123" / "meta.json").exists()
    assert (tmp_path / "hamilton-pool" / "abc123abc123" / "gemini-gemini-3-1-flash-lite-preview.json").exists()

