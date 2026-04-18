"""Tests for the operator-facing markdown report.

The report is what a human reads after a pipeline run. It drives the decision
to approve or reject `git diff content/spots/`. A silent formatting regression
(wrong delta sign, missing flag severity, stale header) leads operators to
approve bad data or reject good data.
"""

from __future__ import annotations

from pathlib import Path

from schedules.models import PoolResult, ReviewFlag
from schedules.report import write_report


def _base_result(**overrides: object) -> PoolResult:
    fields: dict[str, object] = {
        "slug": "rossi-pool",
        "status": "success",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "published",
    }
    fields.update(overrides)
    return PoolResult(**fields)  # type: ignore[arg-type]


def _render(results: list[PoolResult], tmp_path: Path) -> str:
    path = write_report(results, tmp_path / "report.md")
    return path.read_text()


class TestSummaryHeader:
    def test_counts_each_status_bucket(self, tmp_path: Path) -> None:
        results = [
            _base_result(slug="a", status="success"),
            _base_result(slug="b", status="unchanged"),
            _base_result(slug="c", status="skipped", source_status="missing_current_schedule"),
            _base_result(slug="d", status="failed", error="boom"),
        ]
        text = _render(results, tmp_path)
        assert "4 pools processed, 1 succeeded, 1 unchanged, 1 skipped, 1 failed" in text

    def test_flagged_count_reflects_needs_review(self, tmp_path: Path) -> None:
        results = [
            _base_result(slug="clean", status="success"),
            _base_result(
                slug="flagged",
                status="success",
                review_flags=[ReviewFlag(kind="k", message="m")],
            ),
            _base_result(
                slug="skipped-counts-too",
                status="skipped",
                source_status="missing_current_schedule",
            ),
        ]
        text = _render(results, tmp_path)
        # `needs_review` is true for the flagged row AND for any non-published
        # source_status row.
        assert "2 flagged for manual review" in text


class TestPoolBlock:
    def test_sessions_delta_renders_with_sign(self, tmp_path: Path) -> None:
        text = _render(
            [_base_result(sessions_count=12, prior_sessions_count=9)],
            tmp_path,
        )
        assert "- sessions: 12 (+3 vs last run)" in text

    def test_sessions_delta_omitted_without_prior(self, tmp_path: Path) -> None:
        text = _render(
            [_base_result(sessions_count=12, prior_sessions_count=None)],
            tmp_path,
        )
        assert "- sessions: 12\n" in text
        assert "vs last run" not in text

    def test_invariants_ok_vs_violations(self, tmp_path: Path) -> None:
        ok_text = _render([_base_result(slug="ok", invariants_passed=True)], tmp_path)
        bad_text = _render(
            [
                _base_result(
                    slug="bad",
                    invariants_passed=False,
                    violations=["session_ends_before_start", "duplicate_closure"],
                )
            ],
            tmp_path,
        )
        assert "- invariants: ok" in ok_text
        assert "- invariants: session_ends_before_start, duplicate_closure" in bad_text

    def test_review_flag_includes_severity_and_kind(self, tmp_path: Path) -> None:
        text = _render(
            [
                _base_result(
                    review_flags=[
                        ReviewFlag(kind="grounding_coverage_low", message="70% grounded"),
                        ReviewFlag(
                            kind="compare_provider_failed",
                            message="gemini failed",
                            severity="error",
                        ),
                    ],
                )
            ],
            tmp_path,
        )
        assert "- review_flag[warning::grounding_coverage_low]: 70% grounded" in text
        assert "- review_flag[error::compare_provider_failed]: gemini failed" in text

    def test_no_flags_renders_none_marker(self, tmp_path: Path) -> None:
        text = _render([_base_result()], tmp_path)
        assert "- review_flags: none" in text

    def test_pdf_sha256_truncated_to_12(self, tmp_path: Path) -> None:
        sha = "a" * 64
        text = _render([_base_result(pdf_sha256=sha)], tmp_path)
        assert "- pdf_sha256: " + "a" * 12 + "\n" in text

    def test_adjudicated_notes_and_error_render(self, tmp_path: Path) -> None:
        text = _render(
            [
                _base_result(
                    status="success",
                    notes="manual override: pinned to hash deadbeef",
                    error=None,
                ),
                _base_result(
                    slug="broke",
                    status="failed",
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
                _base_result(
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
