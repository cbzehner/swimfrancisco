"""Tests for the operator-facing markdown report.

The report is what a human reads after a pipeline run. It drives the decision
to approve or reject `git diff content/spots/`. A silent formatting regression
(wrong delta sign, missing note severity, stale header) leads operators to
approve bad data or reject good data.
"""

from __future__ import annotations

from pathlib import Path

from schedules.models import Failed, PoolResult, Proposed, ReviewNote, Skipped, Unchanged
from schedules.report import write_report


def _proposed(**overrides: object) -> Proposed:
    defaults: dict[str, object] = {
        "slug": "rossi-pool",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "published",
        "provider": "anthropic",
        "model": "claude",
        "pdf_sha256": "a" * 64,
        "page_count": 1,
        "sessions_count": 5,
        "prior_sessions_count": 5,
        "closures_count": 0,
        "schedule_effective": "2026-04-01",
        "invariants_passed": True,
        "cost_estimate": "$0.01",
        "pdf_text_sha256": "b" * 64,
    }
    defaults.update(overrides)
    return Proposed(**defaults)  # type: ignore[arg-type]


def _unchanged(**overrides: object) -> Unchanged:
    defaults: dict[str, object] = {
        "slug": "rossi-pool",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "published",
        "provider": "anthropic",
        "model": "claude",
        "pdf_sha256": "a" * 64,
        "page_count": 1,
        "sessions_count": 5,
        "closures_count": 0,
        "schedule_effective": "2026-04-01",
        "invariants_passed": True,
    }
    defaults.update(overrides)
    return Unchanged(**defaults)  # type: ignore[arg-type]


def _skipped(**overrides: object) -> Skipped:
    defaults: dict[str, object] = {
        "slug": "rossi-pool",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "missing_current_schedule",
        "reason": "No current schedule PDF is available for this pool.",
    }
    defaults.update(overrides)
    return Skipped(**defaults)  # type: ignore[arg-type]


def _failed(**overrides: object) -> Failed:
    defaults: dict[str, object] = {
        "slug": "rossi-pool",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "published",
        "error": "boom",
    }
    defaults.update(overrides)
    return Failed(**defaults)  # type: ignore[arg-type]


def _render(results: list[PoolResult], tmp_path: Path) -> str:
    path = write_report(results, tmp_path / "report.md")
    return path.read_text()


class TestSummaryHeader:
    def test_counts_each_status_bucket(self, tmp_path: Path) -> None:
        results: list[PoolResult] = [
            _proposed(slug="a"),
            _unchanged(slug="b"),
            _skipped(slug="c"),
            _failed(slug="d"),
        ]
        text = _render(results, tmp_path)
        assert "4 pools processed, 1 succeeded, 1 unchanged, 1 skipped, 1 failed" in text

    def test_flagged_count_reflects_needs_review(self, tmp_path: Path) -> None:
        results: list[PoolResult] = [
            _proposed(slug="clean"),
            _proposed(
                slug="flagged",
                review_notes=[ReviewNote(kind="k", message="m")],
            ),
            _skipped(slug="skipped-counts-too"),
        ]
        text = _render(results, tmp_path)
        # `needs_review` is true for the flagged row AND for any non-published
        # source_status row (skipped rows are non-published).
        assert "2 flagged for manual review" in text


class TestPoolBlock:
    def test_sessions_delta_renders_with_sign(self, tmp_path: Path) -> None:
        text = _render(
            [_proposed(sessions_count=12, prior_sessions_count=9)],
            tmp_path,
        )
        assert "- sessions: 12 (+3 vs last run)" in text

    def test_unchanged_row_has_zero_delta(self, tmp_path: Path) -> None:
        text = _render(
            [_unchanged(sessions_count=7)],
            tmp_path,
        )
        # Unchanged uses sessions_count as prior — delta is always 0.
        assert "- sessions: 7 (+0 vs last run)" in text

    def test_invariants_ok_vs_violations(self, tmp_path: Path) -> None:
        ok_text = _render([_proposed(slug="ok", invariants_passed=True)], tmp_path)
        bad_text = _render(
            [
                _failed(
                    slug="bad",
                    error="Validation refused the extracted payload.",
                    provider="anthropic",
                    model="claude",
                    pdf_sha256="a" * 64,
                    page_count=1,
                    sessions_count=0,
                    prior_sessions_count=8,
                    closures_count=0,
                    schedule_effective=None,
                    violations=["session_ends_before_start", "duplicate_closure"],
                )
            ],
            tmp_path,
        )
        assert "- invariants: ok" in ok_text
        assert "- invariants: session_ends_before_start, duplicate_closure" in bad_text

    def test_review_note_includes_severity_and_kind(self, tmp_path: Path) -> None:
        text = _render(
            [
                _proposed(
                    review_notes=[
                        ReviewNote(kind="grounding_coverage_low", message="70% grounded"),
                        ReviewNote(
                            kind="compare_provider_failed",
                            message="gemini failed",
                            severity="error",
                        ),
                    ],
                )
            ],
            tmp_path,
        )
        assert "- review_note[warning::grounding_coverage_low]: 70% grounded" in text
        assert "- review_note[error::compare_provider_failed]: gemini failed" in text

    def test_no_notes_renders_none_marker(self, tmp_path: Path) -> None:
        text = _render([_proposed()], tmp_path)
        assert "- review_notes: none" in text

    def test_pdf_sha256_truncated_to_12(self, tmp_path: Path) -> None:
        sha = "a" * 64
        text = _render([_proposed(pdf_sha256=sha)], tmp_path)
        assert "- pdf_sha256: " + "a" * 12 + "\n" in text

    def test_adjudicated_notes_and_error_render(self, tmp_path: Path) -> None:
        text = _render(
            [
                _proposed(
                    adjudication_notes="manual override: pinned to hash deadbeef",
                ),
                _failed(
                    slug="broke",
                    error="Semantic delta validation blocked merge.",
                ),
            ],
            tmp_path,
        )
        assert "- notes: manual override: pinned to hash deadbeef" in text
        assert "- error: Semantic delta validation blocked merge." in text

    def test_artifact_paths_sorted(self, tmp_path: Path) -> None:
        text = _render(
            [
                _proposed(
                    artifact_paths={
                        "payload": "data/artifacts/x/payload.json",
                        "adjudicated": "data/adjudications/x.json",
                        "pdf": "data/pdf/x.pdf",
                    }
                )
            ],
            tmp_path,
        )
        lines = [line for line in text.splitlines() if line.startswith("- artifact[")]
        assert lines == [
            "- artifact[adjudicated]: data/adjudications/x.json",
            "- artifact[payload]: data/artifacts/x/payload.json",
            "- artifact[pdf]: data/pdf/x.pdf",
        ]


class TestFooter:
    def test_next_steps_always_rendered(self, tmp_path: Path) -> None:
        text = _render([], tmp_path)
        assert "## Next Steps" in text
        assert "git diff content/spots/" in text
        assert "data/adjudications" in text
