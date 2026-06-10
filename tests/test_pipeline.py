"""Tests for pipeline pure helpers.

The pipeline itself has heavy external dependencies (network, provider APIs,
filesystem). These tests cover the pure helper that gates its operator-trust
property: honest exit codes — partial failures must not exit 0.

Full-integration tests are out of scope; the invariant lives in the helper
and is exercised here.
"""

from __future__ import annotations

from schedules.models import Aborted, Extracted, PoolResult, Skipped, Unchanged
from schedules.pipeline import compute_exit_code


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
