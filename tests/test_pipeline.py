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

from schedules.models import PoolEntry, PoolResult, PoolResultStatus
from schedules.pipeline import (
    _identity_kwargs,
    _snapshot_kwargs,
    compute_exit_code,
    should_write,
)


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


class TestResultBuilders:
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

    def test_snapshot_kwargs_derives_counts_from_prior(self) -> None:
        snapshot = {
            "sessions": [{"type": "lap_swim"}, {"type": "family_swim"}],
            "closures": [{"reason": "maintenance"}],
            "schedule_effective": "2026-04-01",
        }
        assert _snapshot_kwargs(snapshot) == {
            "prior_sessions_count": 2,
            "sessions_count": 2,
            "closures_count": 1,
            "schedule_effective": "2026-04-01",
        }

    def test_builders_compose_into_a_valid_PoolResult(self) -> None:
        entry = PoolEntry(
            slug="rossi-pool",
            pdf_url="https://example.test/rossi.pdf",
            official_page_url="https://example.test/rossi",
            source_status="missing_current_schedule",
            notes="no PDF published",
        )
        snapshot = {"sessions": [], "closures": [], "schedule_effective": None}
        result = PoolResult(
            **_identity_kwargs(entry),
            **_snapshot_kwargs(snapshot),
            status="skipped",
            notes=entry.notes,
        )
        assert result.slug == "rossi-pool"
        assert result.status == "skipped"
        assert result.sessions_count == 0
        assert result.source_status == "missing_current_schedule"
        assert result.notes == "no PDF published"
