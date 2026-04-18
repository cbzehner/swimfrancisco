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

from schedules.models import PoolResult, PoolResultStatus
from schedules.pipeline import compute_exit_code, should_write


def _pool_result(slug: str, status: PoolResultStatus) -> PoolResult:
    return PoolResult(
        slug=slug,
        status=status,
        official_page_url="",
        pdf_url="",
        source_status="published",
    )


class TestComputeExitCode:
    def test_zero_for_all_success(self) -> None:
        results = [_pool_result("a", "success"), _pool_result("b", "success")]
        assert compute_exit_code(results) == 0

    def test_zero_for_unchanged_and_skipped(self) -> None:
        results = [_pool_result("a", "unchanged"), _pool_result("b", "skipped")]
        assert compute_exit_code(results) == 0

    def test_nonzero_when_any_pool_failed(self) -> None:
        results = [_pool_result("a", "success"), _pool_result("b", "failed")]
        assert compute_exit_code(results) == 1

    def test_nonzero_when_all_failed(self) -> None:
        results = [_pool_result("a", "failed")]
        assert compute_exit_code(results) == 1

    def test_zero_for_empty(self) -> None:
        assert compute_exit_code([]) == 0


class TestShouldWrite:
    def test_writes_when_live_run(self) -> None:
        assert should_write(dry_run=False, compare_with=None, hard_block=False) is True

    def test_dry_run_blocks_writes(self) -> None:
        assert should_write(dry_run=True, compare_with=None, hard_block=False) is False

    def test_hard_block_blocks_writes(self) -> None:
        assert should_write(dry_run=False, compare_with=None, hard_block=True) is False

    def test_compare_mode_blocks_writes(self) -> None:
        # Compare mode is observational by default — operator trust property.
        assert should_write(dry_run=False, compare_with="anthropic", hard_block=False) is False

    def test_compare_mode_blocks_writes_even_with_no_hard_block(self) -> None:
        assert should_write(dry_run=False, compare_with="gemini", hard_block=False) is False
