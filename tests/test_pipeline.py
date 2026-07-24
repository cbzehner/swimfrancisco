"""Tests for pipeline pure helpers.

The pipeline itself has heavy external dependencies (network, provider APIs,
filesystem). These tests cover the pure helper that gates its operator-trust
property: honest exit codes — partial failures must not exit 0.

Full-integration tests are out of scope; the invariant lives in the helper
and is exercised here.
"""

from __future__ import annotations

from schedules.models import Aborted, Extracted, PoolResult, Skipped, Unchanged
from schedules.models import PoolEntry
from schedules.paths import REPORT_PATHS
from schedules.pipeline import compute_exit_code, run_pipeline, select_registry_entries


def _skipped(slug: str) -> Skipped:
    return Skipped(slug=slug, official_page_url="", pdf_url="", source_status="published")


def _unchanged(slug: str) -> Unchanged:
    return Unchanged(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        provider="anthropic",
        model="claude",
        pdf_sha256="x",
        page_count=1,
        sessions_count=0,
        closures_count=0,
        effective_start="2026-01-01",
    )


def _proposed(slug: str) -> Extracted:
    return Extracted(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        provider="anthropic",
        model="claude",
        pdf_sha256="x",
        page_count=1,
        sessions_count=5,
        prior_sessions_count=5,
        closures_count=0,
        effective_start="2026-01-01",
        cost_estimate="$0.01",
    )


def _failed(slug: str) -> Aborted:
    return Aborted(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        error="boom",
        prior_sessions_count=0,
        prior_closures_count=0,
        prior_schedule_effective=None,
    )


class TestComputeExitCode:
    def test_zero_for_all_success(self) -> None:
        results: list[PoolResult] = [_proposed("a"), _proposed("b")]
        assert compute_exit_code(results) == 0

    def test_zero_for_unchanged_and_skipped(self) -> None:
        results: list[PoolResult] = [_unchanged("a"), _skipped("b")]
        assert compute_exit_code(results) == 0

    def test_nonzero_when_any_pool_failed(self) -> None:
        results: list[PoolResult] = [_proposed("a"), _failed("b")]
        assert compute_exit_code(results) == 1

    def test_nonzero_when_all_failed(self) -> None:
        results: list[PoolResult] = [_failed("a")]
        assert compute_exit_code(results) == 1

    def test_zero_for_empty(self) -> None:
        assert compute_exit_code([]) == 0


def _entry(slug: str, source_kind: str) -> PoolEntry:
    return PoolEntry(
        slug=slug,
        pdf_url="https://example.test/source",
        official_page_url="https://example.test/pool",
        source_kind=source_kind,  # type: ignore[arg-type]
    )


def test_source_modes_partition_registry_without_overlap() -> None:
    registry = [
        _entry("direct-one", "jccsf_html"),
        _entry("pdf-one", "sfrecpark_pdf"),
        _entry("direct-two", "koret_google_sheet"),
        _entry("pdf-two", "sfrecpark_pdf"),
    ]

    assert [entry.slug for entry in select_registry_entries(registry, source_mode="direct", slugs=None)] == [
        "direct-one",
        "direct-two",
    ]
    assert [entry.slug for entry in select_registry_entries(registry, source_mode="gemini", slugs=None)] == [
        "pdf-one",
        "pdf-two",
    ]


def test_source_mode_rejects_slug_from_other_partition() -> None:
    registry = [_entry("direct-one", "jccsf_html"), _entry("pdf-one", "sfrecpark_pdf")]

    try:
        select_registry_entries(registry, source_mode="anthropic", slugs=["direct-one"])
    except ValueError as exc:
        assert "mismatched" in str(exc)
    else:
        raise AssertionError("expected a mismatched source slug to fail")


def test_each_source_mode_processes_its_partition_exactly_once(monkeypatch, tmp_path) -> None:
    registry = [
        _entry("direct-one", "jccsf_html"),
        _entry("pdf-one", "sfrecpark_pdf"),
        _entry("direct-two", "koret_google_sheet"),
        _entry("pdf-two", "sfrecpark_pdf"),
    ]
    calls: list[tuple[str, str]] = []
    reports: dict[str, list[str]] = {}

    monkeypatch.setattr("schedules.pipeline.load_registry", lambda: registry)
    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("prompt")

    def process(entry, *, provider, compare_with, force, prompt):
        calls.append((provider, entry.slug))
        return _skipped(entry.slug)

    def report(results, *, path):
        reports[path.name] = [result.slug for result in results]
        return path

    monkeypatch.setattr("schedules.pipeline._process_entry", process)
    monkeypatch.setattr("schedules.pipeline.write_report", report)

    for mode in ("direct", "gemini", "anthropic"):
        run_pipeline(slugs=None, source_mode=mode, compare_with=None, force=False)

    assert calls == [
        ("direct", "direct-one"),
        ("direct", "direct-two"),
        ("gemini", "pdf-one"),
        ("gemini", "pdf-two"),
        ("anthropic", "pdf-one"),
        ("anthropic", "pdf-two"),
    ]
    assert reports == {
        "extraction-report-direct.md": ["direct-one", "direct-two"],
        "extraction-report-gemini.md": ["pdf-one", "pdf-two"],
        "extraction-report-anthropic.md": ["pdf-one", "pdf-two"],
    }


def test_source_modes_have_distinct_report_paths() -> None:
    assert len(set(REPORT_PATHS.values())) == 3
    assert REPORT_PATHS["direct"].name == "extraction-report-direct.md"
    assert REPORT_PATHS["gemini"].name == "extraction-report-gemini.md"
    assert REPORT_PATHS["anthropic"].name == "extraction-report-anthropic.md"
