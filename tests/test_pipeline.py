"""Tests for pipeline pure helpers.

The pipeline itself has heavy external dependencies (network, provider APIs,
filesystem). These tests cover the pure helpers that gate its two operator-
trust properties:

- honest exit codes (partial failures must not exit 0)
- safe compare mode (`--compare-with` must not write to content or state)

Full-integration tests are out of scope; the invariant lives in the gate
helpers and is exercised here.
"""

from __future__ import annotations

from schedules.models import Aborted, PoolEntry, PoolResult, Proposed, Skipped, Unchanged
from schedules.pipeline import (
    _identity_kwargs,
    compute_exit_code,
    should_write,
)


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
        schedule_effective="2026-01-01",
    )


def _proposed(slug: str, *, written: bool = True) -> Proposed:
    return Proposed(
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
        schedule_effective="2026-01-01",
        cost_estimate="$0.01",
        written=written,
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


class TestShouldWrite:
    def test_writes_when_live_run(self) -> None:
        assert should_write(dry_run=False, compare_with=None, catastrophic=False) is True

    def test_dry_run_blocks_writes(self) -> None:
        assert should_write(dry_run=True, compare_with=None, catastrophic=False) is False

    def test_catastrophic_blocks_writes(self) -> None:
        assert should_write(dry_run=False, compare_with=None, catastrophic=True) is False

    def test_compare_mode_blocks_writes(self) -> None:
        # Compare mode is observational by default — operator trust property.
        assert should_write(dry_run=False, compare_with="anthropic", catastrophic=False) is False

    def test_compare_mode_blocks_writes_even_when_validation_ok(self) -> None:
        assert should_write(dry_run=False, compare_with="gemini", catastrophic=False) is False


class TestIdentityKwargs:
    def test_identity_kwargs_carries_entry_identity(self) -> None:
        entry = PoolEntry(
            slug="rossi-pool",
            pdf_url="https://example.test/rossi.pdf",
            official_page_url="https://example.test/rossi",
            source_status="published",
        )
        assert _identity_kwargs(entry) == {
            "slug": "rossi-pool",
            "pdf_url": "https://example.test/rossi.pdf",
            "official_page_url": "https://example.test/rossi",
            "source_status": "published",
        }

    def test_skipped_variant_carries_entry_notes_and_reason(self) -> None:
        entry = PoolEntry(
            slug="rossi-pool",
            pdf_url="https://example.test/rossi.pdf",
            official_page_url="https://example.test/rossi",
            source_status="missing_current_schedule",
            notes="no PDF published",
        )
        result = Skipped(
            **_identity_kwargs(entry),
            reason="No current schedule PDF is available for this pool.",
            notes=entry.notes,
        )
        assert result.slug == "rossi-pool"
        assert result.source_status == "missing_current_schedule"
        assert result.notes == "no PDF published"
        assert "No current schedule PDF" in result.reason
