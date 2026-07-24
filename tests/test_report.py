"""Tests for the operator-facing markdown report.

The report is what a human reads after a pipeline run. It drives the decision
to approve or reject `git diff content/spots/`. A silent formatting regression
(wrong delta sign, missing note severity, stale header) leads operators to
approve bad data or reject good data.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from schedules.models import Aborted, Extracted, PoolResult, ReviewNote, Skipped, Unchanged, Violation
from schedules.pr_summary import render_pr_body, staged_data_has_meaningful_changes
from schedules.report import write_report


def _proposed(**overrides: object) -> Extracted:
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
        "effective_start": "2026-04-01",
        "cost_estimate": "$0.01",
    }
    defaults.update(overrides)
    return Extracted(**defaults)  # type: ignore[arg-type]


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
        "effective_start": "2026-04-01",
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


def _aborted(**overrides: object) -> Aborted:
    defaults: dict[str, object] = {
        "slug": "rossi-pool",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "published",
        "error": "boom",
        "prior_sessions_count": 0,
        "prior_closures_count": 0,
        "prior_schedule_effective": None,
    }
    defaults.update(overrides)
    return Aborted(**defaults)  # type: ignore[arg-type]


def _rejected(**overrides: object) -> Extracted:
    defaults: dict[str, object] = {
        "slug": "rossi-pool",
        "official_page_url": "https://example.test/rossi",
        "pdf_url": "https://example.test/rossi.pdf",
        "source_status": "published",
        "provider": "anthropic",
        "model": "claude",
        "pdf_sha256": "a" * 64,
        "page_count": 1,
        "sessions_count": 0,
        "prior_sessions_count": 8,
        "closures_count": 0,
        "effective_start": None,
        "cost_estimate": "$0.01",
        "catastrophic": True,
        "violations": [],
    }
    defaults.update(overrides)
    return Extracted(**defaults)  # type: ignore[arg-type]


def _render(results: list[PoolResult], tmp_path: Path) -> str:
    path = write_report(results, tmp_path / "report.md")
    return path.read_text()


class TestSummaryHeader:
    def test_counts_each_status_bucket(self, tmp_path: Path) -> None:
        results: list[PoolResult] = [
            _proposed(slug="a"),
            _unchanged(slug="b"),
            _skipped(slug="c"),
            _aborted(slug="d"),
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
        ok_text = _render([_proposed(slug="ok")], tmp_path)
        bad_text = _render(
            [
                _rejected(
                    slug="bad",
                    violations=[
                        Violation(code="invalid_session_time_range", message="session_ends_before_start"),
                        Violation(code="invalid_closure_date_range", message="duplicate_closure"),
                    ],
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
                            severity="warning",
                        ),
                    ],
                )
            ],
            tmp_path,
        )
        assert "- review_note[warning::grounding_coverage_low]: 70% grounded" in text
        assert "- review_note[warning::compare_provider_failed]: gemini failed" in text

    def test_no_notes_renders_none_marker(self, tmp_path: Path) -> None:
        text = _render([_proposed()], tmp_path)
        assert "- review_notes: none" in text

    def test_pdf_sha256_truncated_to_12(self, tmp_path: Path) -> None:
        sha = "a" * 64
        text = _render([_proposed(pdf_sha256=sha)], tmp_path)
        assert "- pdf_sha256: " + "a" * 12 + "\n" in text

    def test_failed_error_renders(self, tmp_path: Path) -> None:
        text = _render(
            [
                _aborted(
                    slug="broke",
                    error="Semantic delta validation blocked merge.",
                ),
            ],
            tmp_path,
        )
        assert "- error: Semantic delta validation blocked merge." in text

    def test_artifact_paths_sorted(self, tmp_path: Path) -> None:
        text = _render(
            [
                _proposed(
                    artifact_paths={
                        "payload": "data/hamilton-pool/2026-04-19-aaaaaaaaaaaa/gemini-model.json",
                        "reviewed-snapshot": "data/hamilton-pool/2026-04-19-aaaaaaaaaaaa/reviewed.json",
                        "pdf": "data/hamilton-pool/2026-04-19-aaaaaaaaaaaa/source.pdf",
                    }
                )
            ],
            tmp_path,
        )
        lines = [line for line in text.splitlines() if line.startswith("- artifact[")]
        assert lines == [
            "- artifact[reviewed-snapshot]: data/hamilton-pool/2026-04-19-aaaaaaaaaaaa/reviewed.json",
            "- artifact[payload]: data/hamilton-pool/2026-04-19-aaaaaaaaaaaa/gemini-model.json",
            "- artifact[pdf]: data/hamilton-pool/2026-04-19-aaaaaaaaaaaa/source.pdf",
        ]


class TestFooter:
    def test_next_steps_always_rendered(self, tmp_path: Path) -> None:
        text = _render([], tmp_path)
        assert "## Next Steps" in text
        assert "git diff content/spots/" in text
        assert "data/<slug>/<fetch-date>-<sha12>/" in text
        assert "git add content/spots data/" in text


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _write_provider_json(path: Path, *, extracted_at: str, effective_start: str, sessions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "provider": "direct",
        "model": "direct-test-v1",
        "extracted_at": extracted_at,
        "prompt_sha256": "prompt",
        "schema_sha256": "schema",
        "source_pdf_url": "https://example.test/source",
        "pdf_sha256": "a" * 64,
        "usage": {},
        "cost_estimate": "deterministic",
        "payload": {
            "effective_start": effective_start,
            "schedule_basis": "pool_hours",
            "sessions": sessions,
            "closures": [],
            "access_hours": [],
            "access_exceptions": [],
        },
    }, indent=2, sort_keys=True) + "\n")


def _write_reviewed_json(path: Path, *, sessions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "slug": "koret-center",
        "pdf_sha256": "a" * 64,
        "reviewed_at": "2026-07-01",
        "source_pdf_url": "https://example.test/source.pdf",
        "payload": {"sessions": sessions},
    }, indent=2, sort_keys=True) + "\n")


class TestMeaningfulStagedDataChanges:
    def test_metadata_only_provider_json_change_is_not_meaningful(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        artifact = repo / "data" / "koret-center" / "2026-06-16-aaaaaaaaaaaa" / "direct-test-v1.json"
        sessions = [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "19:00"}]
        _write_provider_json(artifact, extracted_at="2026-06-16T00:00:00+00:00", effective_start="2026-06-16", sessions=sessions)
        _git(repo, "add", "data")
        _git(repo, "commit", "-m", "seed")

        _write_provider_json(artifact, extracted_at="2026-06-23T00:00:00+00:00", effective_start="2026-06-23", sessions=sessions)
        _git(repo, "add", "data")

        assert staged_data_has_meaningful_changes(repo) is False

    def test_payload_change_is_meaningful(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        artifact = repo / "data" / "koret-center" / "2026-06-16-aaaaaaaaaaaa" / "direct-test-v1.json"
        _write_provider_json(
            artifact,
            extracted_at="2026-06-16T00:00:00+00:00",
            effective_start="2026-06-16",
            sessions=[{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "19:00"}],
        )
        _git(repo, "add", "data")
        _git(repo, "commit", "-m", "seed")

        _write_provider_json(
            artifact,
            extracted_at="2026-06-23T00:00:00+00:00",
            effective_start="2026-06-23",
            sessions=[{"day": "monday", "type": "lap_swim", "start": "08:00", "end": "19:00"}],
        )
        _git(repo, "add", "data")

        assert staged_data_has_meaningful_changes(repo) is True


class TestArtifactAwarePrSummary:
    def test_changed_rows_precede_disagreement_details(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")

        run = repo / "data" / "koret-center" / "2026-07-23-cccccccccccc"
        truth_sessions = [{"day": "saturday", "type": "lap_swim", "start": "08:00", "end": "16:00"}]
        _write_reviewed_json(run / "reviewed.json", sessions=truth_sessions)
        _git(repo, "add", "data")
        _git(repo, "commit", "-m", "reviewed run")

        _write_provider_json(
            run / "direct-koret-google-alpha-v1.json",
            extracted_at="2026-07-23T00:00:00+00:00",
            effective_start="2026-07-23",
            sessions=truth_sessions + [
                {"day": "sunday", "type": "lap_swim", "start": "08:00", "end": "16:00"},
            ],
        )
        _write_provider_json(
            run / "direct-koret-google-beta-v1.json",
            extracted_at="2026-07-23T00:00:00+00:00",
            effective_start="2026-07-23",
            sessions=truth_sessions,
        )
        _git(repo, "add", "data")

        text = render_pr_body(repo_root=repo, data_root=repo / "data")
        table = text.split("## Changed artifacts", 1)[1].split("## ", 1)[0]
        alpha_row = "| `data/koret-center/2026-07-23-cccccccccccc/direct-koret-google-alpha-v1.json` | scored |"
        beta_row = "| `data/koret-center/2026-07-23-cccccccccccc/direct-koret-google-beta-v1.json` | scored |"

        assert table.index(alpha_row) < table.index(beta_row)
        assert table.index(beta_row) < table.index("_data/koret-center/2026-07-23-cccccccccccc/direct-koret-google-alpha-v1.json:_")

    def test_unreviewed_workbook_does_not_borrow_reviewed_sheet_score(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")

        old_run = repo / "data" / "koret-center" / "2026-07-01-aaaaaaaaaaaa"
        sessions = [{"day": "saturday", "type": "lap_swim", "start": "08:00", "end": "16:00"}]
        _write_reviewed_json(old_run / "reviewed.json", sessions=sessions)
        _write_provider_json(
            old_run / "direct-koret-google-sheet-v1.json",
            extracted_at="2026-07-01T00:00:00+00:00",
            effective_start="2026-07-01",
            sessions=sessions,
        )
        _git(repo, "add", "data")
        _git(repo, "commit", "-m", "old reviewed run")

        new_run = repo / "data" / "koret-center" / "2026-07-23-f8fe9dc76a47"
        _write_provider_json(
            new_run / "direct-koret-google-workbook-v1.json",
            extracted_at="2026-07-23T00:00:00+00:00",
            effective_start="2026-07-23",
            sessions=[{"day": "saturday", "type": "lap_swim", "start": "08:00", "end": "15:00"}],
        )
        _git(repo, "add", "data")

        text = render_pr_body(repo_root=repo, data_root=repo / "data")

        assert "`data/koret-center/2026-07-23-f8fe9dc76a47/direct-koret-google-workbook-v1.json`" in text
        assert "unscored — human review required" in text
        assert "| `data/koret-center/2026-07-23-f8fe9dc76a47/direct-koret-google-workbook-v1.json` | unscored" in text
        assert "| `data/koret-center/2026-07-23-f8fe9dc76a47/direct-koret-google-workbook-v1.json` | scored" not in text
        assert "| `data/koret-center/2026-07-01-aaaaaaaaaaaa/direct-koret-google-sheet-v1.json` |" not in text
        assert "Historical reviewed baseline" in text
        assert "not a score for unreviewed changed artifacts" in text

    def test_same_directory_reviewed_artifact_is_scored(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")

        run = repo / "data" / "koret-center" / "2026-07-23-bbbbbbbbbbbb"
        sessions = [{"day": "saturday", "type": "lap_swim", "start": "08:00", "end": "16:00"}]
        _write_reviewed_json(run / "reviewed.json", sessions=sessions)
        _git(repo, "add", "data")
        _git(repo, "commit", "-m", "reviewed run")
        _write_provider_json(
            run / "direct-koret-google-workbook-v1.json",
            extracted_at="2026-07-23T00:00:00+00:00",
            effective_start="2026-07-23",
            sessions=sessions,
        )
        _git(repo, "add", "data")

        text = render_pr_body(repo_root=repo, data_root=repo / "data")

        assert "| `data/koret-center/2026-07-23-bbbbbbbbbbbb/direct-koret-google-workbook-v1.json` | scored | 1 | 1 | 1.00 |" in text

    def test_added_source_file_is_meaningful(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("seed\n")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "seed")

        source = repo / "data" / "koret-center" / "2026-06-16-aaaaaaaaaaaa" / "source.csv"
        source.parent.mkdir(parents=True)
        source.write_text("Monday Hours: 7am-7pm\n")
        _git(repo, "add", "data")

        assert staged_data_has_meaningful_changes(repo) is True
