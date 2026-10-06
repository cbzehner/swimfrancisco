import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import schedules.cli as cli_module
from schedules.eval import EvaluationArtifactError, UnscoredArtifact, collect_pool_evals, render_report


def _write_review(
    data_root: Path,
    slug: str,
    fetch_date: str,
    sha12: str,
    truth_sessions: list[dict],
    provider_sessions: list[dict],
    provider_filename: str = "openai-model.json",
    *,
    attested_by: str | None = None,
    carried_from: str | None = None,
) -> Path:
    review_dir = data_root / slug / f"{fetch_date}-{sha12}"
    review_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "slug": slug,
        "pdf_sha256": sha12 + ("0" * (64 - len(sha12))),
        "reviewed_at": "2026-04-19",
        "source_pdf_url": "https://example.com/x.pdf",
        "payload": {
            "effective_start": "2026-04-21",
            "sessions": truth_sessions,
            "closures": [],
        },
    }
    if attested_by is not None:
        envelope["attested_by"] = attested_by
    if carried_from is not None:
        envelope["carried_from"] = carried_from
    (review_dir / "reviewed.json").write_text(json.dumps(envelope))
    (review_dir / provider_filename).write_text(
        json.dumps({"payload": {"sessions": provider_sessions, "closures": []}})
    )
    return review_dir


def _row(day: str, typ: str, start: str, end: str) -> dict:
    return {"day": day, "type": typ, "start": start, "end": end}


def _dimension(evaluation, name: str):
    return next(item for item in evaluation.fact_comparisons if item.dimension == name)


def _write_fact_review(tmp_path: Path, truth: dict, extracted: dict):
    sessions = truth.get("sessions", [])
    review_dir = _write_review(
        tmp_path, "facts-pool", "2026-04-19", "abcdef123456", sessions, extracted.get("sessions", [])
    )
    reviewed = json.loads((review_dir / "reviewed.json").read_text())
    reviewed["payload"] = truth
    (review_dir / "reviewed.json").write_text(json.dumps(reviewed))
    provider = {"payload": extracted}
    (review_dir / "openai-model.json").write_text(json.dumps(provider))
    return collect_pool_evals(data_root=tmp_path)[0]


def test_collect_perfect_match(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    e = evals[0]
    assert e.true_positives == 1
    assert e.false_positives == 0
    assert e.false_negatives == 0
    assert e.precision == 1.0 and e.recall == 1.0 and e.f1 == 1.0


def test_collect_extra_and_missing(tmp_path):
    truth = [_row("monday", "lap_swim", "07:00", "08:00")]
    extracted = [_row("tuesday", "lap_swim", "09:00", "10:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", truth, extracted)
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    e = evals[0]
    assert e.true_positives == 0
    assert e.false_positives == 1
    assert e.false_negatives == 1
    assert e.f1 == 0.0


def test_collect_treats_pool_field_as_row_identity(tmp_path):
    truth = [_row("monday", "lap_swim", "07:00", "08:00") | {"pool": "warm"}]
    extracted = [_row("monday", "lap_swim", "07:00", "08:00") | {"pool": "cool"}]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", truth, extracted)
    evals = collect_pool_evals(data_root=tmp_path)

    assert len(evals) == 1
    e = evals[0]
    assert e.true_positives == 0
    assert e.false_positives == 1
    assert e.false_negatives == 1


def test_missing_holiday_closure_is_a_semantic_mismatch(tmp_path):
    truth = {
        "effective_start": "2026-09-01", "schedule_basis": "swim_schedule",
        "sessions": [_row("monday", "lap_swim", "07:00", "08:00")],
        "closures": [{"start": "2026-09-14", "end": "2026-09-14", "reason": "holiday"}],
    }
    evaluation = _write_fact_review(tmp_path, truth, {**truth, "closures": []})
    closure = _dimension(evaluation, "closures")
    assert closure.matches is False
    assert closure.missing == (("2026-09-14", "2026-09-14", None, None, None),)
    assert evaluation.f1 == 1.0


def test_wrong_season_is_reported_separately_from_session_f1(tmp_path):
    truth = {
        "effective_start": "2026-09-01", "effective_end": "2026-10-31",
        "schedule_basis": "swim_schedule", "sessions": [], "closures": [],
    }
    extracted = {**truth, "effective_start": "2026-11-01", "effective_end": "2027-02-28"}
    evaluation = _write_fact_review(tmp_path, truth, extracted)
    assert _dimension(evaluation, "effective_window").matches is False
    assert evaluation.f1 == 1.0


def test_physical_pool_and_session_cancellation_are_semantic_facts(tmp_path):
    truth = {
        "effective_start": "2026-09-01", "schedule_basis": "swim_schedule",
        "sessions": [_row("monday", "lap_swim", "07:00", "08:00") | {
            "physical_pool": "cool", "excluded_dates": ["2026-09-14"]
        }],
        "closures": [],
    }
    extracted = {**truth, "sessions": [_row("monday", "lap_swim", "07:00", "08:00") | {
        "physical_pool": "warm", "excluded_dates": []
    }]}
    evaluation = _write_fact_review(tmp_path, truth, extracted)
    assert _dimension(evaluation, "physical_pools").matches is False
    assert _dimension(evaluation, "excluded_dates").matches is False
    assert evaluation.f1 == 0.0


def test_missing_physical_pool_and_exclusion_reference_coverage_is_unknown(tmp_path):
    row = _row("monday", "lap_swim", "07:00", "08:00")
    truth = {
        "effective_start": "2026-09-01", "schedule_basis": "swim_schedule",
        "sessions": [row], "closures": [],
    }
    evaluation = _write_fact_review(tmp_path, truth, {**truth, "sessions": [row | {
        "physical_pool": "cool", "excluded_dates": ["2026-09-14"],
    }]})
    assert _dimension(evaluation, "physical_pools").matches is None
    assert _dimension(evaluation, "excluded_dates").matches is None


def test_access_exception_reason_and_label_are_cosmetic(tmp_path):
    truth = {
        "effective_start": "2026-09-01", "schedule_basis": "facility_hours", "sessions": [],
        "closures": [], "access_exceptions": [{
            "date": "2026-09-14", "start": "08:00", "end": "12:00",
            "label": "holiday", "reason": "staff training",
        }],
    }
    extracted = {**truth, "access_exceptions": [{
        "date": "2026-09-14", "start": "08:00", "end": "12:00",
        "label": "special access", "reason": "revised notice wording",
    }]}
    assert _dimension(_write_fact_review(tmp_path, truth, extracted), "access_exceptions").matches is True


def test_access_hour_label_is_cosmetic(tmp_path):
    truth = {
        "effective_start": "2026-09-01", "schedule_basis": "facility_hours", "sessions": [],
        "closures": [], "access_hours": [{
            "day": "monday", "start": "06:00", "end": "20:00", "label": "facility hours",
        }],
    }
    extracted = {**truth, "access_hours": [{
        "day": "monday", "start": "06:00", "end": "20:00", "label": "opening hours",
    }]}
    assert _dimension(_write_fact_review(tmp_path, truth, extracted), "access_hours").matches is True


@pytest.mark.parametrize(
    "reference_closure, candidate_closure",
    [
        (
            {"start": "2026-09-14", "end": "2026-09-14", "reason": "holiday"},
            {"start": "2026-09-14", "end": "2026-09-14", "start_time": "07:00", "end_time": "08:00", "reason": "holiday"},
        ),
        (
            {"start": "2026-09-14", "end": "2026-09-14", "reason": "holiday"},
            {"start": "2026-09-14", "end": "2026-09-14", "physical_pool": "cool", "reason": "holiday"},
        ),
        (
            {"start": "2026-09-14", "end": "2026-09-14", "physical_pool": "cool", "reason": "holiday"},
            {"start": "2026-09-14", "end": "2026-09-14", "reason": "holiday"},
        ),
    ],
)
def test_closure_time_and_scope_are_semantic_facts(tmp_path, reference_closure, candidate_closure):
    truth = {"effective_start": "2026-09-01", "schedule_basis": "swim_schedule", "sessions": [], "closures": [reference_closure]}
    evaluation = _write_fact_review(tmp_path, truth, {**truth, "closures": [candidate_closure]})
    assert _dimension(evaluation, "closures").matches is False


def test_access_hours_only_source_is_compared_and_missing_reference_coverage_is_unknown(tmp_path):
    truth = {
        "effective_start": "2026-09-01", "schedule_basis": "facility_hours", "sessions": [], "closures": [],
        "access_hours": [{"day": "monday", "start": "06:00", "end": "20:00", "label": "facility"}],
    }
    extracted = {"effective_start": "2026-09-01", "schedule_basis": "facility_hours", "sessions": [], "closures": []}
    evaluation = _write_fact_review(tmp_path, truth, extracted)
    assert _dimension(evaluation, "access_hours").matches is False
    assert _dimension(evaluation, "access_exceptions").matches is None


def test_missing_reference_closure_coverage_is_unknown(tmp_path):
    truth = {"effective_start": "2026-09-01", "schedule_basis": "unknown", "sessions": []}
    evaluation = _write_fact_review(tmp_path, truth, {**truth, "closures": []})
    assert _dimension(evaluation, "closures").matches is None


def test_duplicate_rows_are_reported_without_set_normalization(tmp_path):
    row = _row("monday", "lap_swim", "07:00", "08:00")
    truth = {"effective_start": "2026-09-01", "schedule_basis": "swim_schedule", "sessions": [row], "closures": []}
    evaluation = _write_fact_review(tmp_path, truth, {**truth, "sessions": [row, row]})
    sessions = _dimension(evaluation, "sessions")
    assert sessions.matches is False
    assert sessions.duplicate_extracted == (("monday", "lap_swim", "07:00", "08:00", "", "", ()),)


def test_duplicate_rows_count_as_extra_predictions(tmp_path):
    row = _row("monday", "lap_swim", "07:00", "08:00")
    truth = {"effective_start": "2026-09-01", "schedule_basis": "swim_schedule", "sessions": [row], "closures": []}
    evaluation = _write_fact_review(tmp_path, truth, {**truth, "sessions": [row, row, row, row]})
    assert evaluation.true_positives == 1
    assert evaluation.false_positives == 3
    assert evaluation.false_negatives == 0


def test_default_excludes_older_review_dirs(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-10", "aaaaaaaaaaaa", sessions, sessions)
    _write_review(tmp_path, "x-pool", "2026-04-19", "bbbbbbbbbbbb", sessions, sessions)
    evals = collect_pool_evals(data_root=tmp_path)
    # Only the newer review dir is included
    assert len(evals) == 1
    assert "2026-04-19" in str(evals[0].review_dir)


def test_all_dirs_includes_history(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-10", "aaaaaaaaaaaa", sessions, sessions)
    _write_review(tmp_path, "x-pool", "2026-04-19", "bbbbbbbbbbbb", sessions, sessions)
    evals = collect_pool_evals(data_root=tmp_path, all_dirs=True)
    assert len(evals) == 2


def test_render_report_includes_aggregate_and_pool_rows(tmp_path):
    truth = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", truth, truth)
    evals = collect_pool_evals(data_root=tmp_path)
    report = render_report(evals)
    assert "Aggregate by provider" in report
    assert "Session F1 is session-only" in report
    assert "Per pool / artifact" in report
    assert "x-pool" in report


def test_human_or_omitted_same_dir_stays_quality(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions, attested_by="human"
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    assert evals[0].table == "quality"


def test_latest_ci_looks_back_to_human_for_seasonal_delta_only(tmp_path):
    human = [_row("monday", "lap_swim", "07:00", "08:00")]
    fall = [_row("tuesday", "lap_swim", "09:00", "10:00")]
    _write_review(
        tmp_path, "x-pool", "2026-04-10", "aaaaaaaaaaaa", human, human, attested_by="human"
    )
    _write_review(
        tmp_path, "x-pool", "2026-06-01", "cccccccccccc", fall, fall, attested_by="ci"
    )
    _write_review(
        tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", fall, fall, attested_by="ci"
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert all(item.table != "quality" for item in evals)
    assert all(item.table == "seasonal_delta" for item in evals)
    assert len(evals) == 1
    assert "2026-08-19" in str(evals[0].review_dir)
    report = render_report(evals)
    assert "Seasonal delta (not quality baseline)" in report
    assert "Not in the quality aggregate" in report
    assert "| seasonal_delta |" in report
    assert "| human |" in report
    assert "| ci |" in report


def test_latest_ci_with_no_human_is_omitted(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions, attested_by="ci"
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert evals == []


def test_carried_ci_is_not_independent_quality_truth(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path,
        "x-pool",
        "2026-08-19",
        "bbbbbbbbbbbb",
        sessions,
        sessions,
        attested_by="ci",
        carried_from="data/x-pool/old/reviewed.json",
    )
    evals = collect_pool_evals(data_root=tmp_path)
    assert evals == []


@pytest.mark.parametrize("attested_by", ["human", None])
def test_carried_human_or_legacy_remains_quality(tmp_path, attested_by):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions,
                  attested_by=attested_by, carried_from="data/x-pool/old/reviewed.json")
    assert collect_pool_evals(data_root=tmp_path)[0].table == "quality"


def test_carried_ci_uses_older_human_only_as_seasonal_delta(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "aaaaaaaaaaaa", sessions, sessions,
                  attested_by="human")
    _write_review(tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions,
                  attested_by="ci", carried_from="data/x-pool/ci/reviewed.json")
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    assert evals[0].table == "seasonal_delta"


def test_agent_reference_is_distinct_and_not_a_quality_baseline(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(
        tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions,
        attested_by="agent-reference",
    )
    assert collect_pool_evals(data_root=tmp_path) == []


def test_agent_reference_origin_is_preserved_in_seasonal_report(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "aaaaaaaaaaaa", sessions, sessions, attested_by="human")
    _write_review(tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions, attested_by="agent-reference")
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    assert evals[0].reference_origin == "human"
    assert evals[0].artifact_origin == "agent-reference"
    report = render_report(evals)
    assert "Latest CI or agent-reference provider JSON" in report
    assert "| agent-reference |" in report


@pytest.mark.parametrize("field", ["closures", "access_hours", "access_exceptions"])
def test_malformed_fact_array_fails_with_path(tmp_path, field):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    review_dir = _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    artifact_path = review_dir / "historical.json"
    artifact_path.write_text(json.dumps({
        "status": "completed",
        "payload": {"sessions": sessions, field: [None]},
    }))
    with pytest.raises(EvaluationArtifactError, match=rf"{artifact_path}: payload\.{field}\[0\]"):
        collect_pool_evals(data_root=tmp_path)


@pytest.mark.parametrize(
    ("field", "member"),
    [("closures", "start"), ("access_hours", "day"), ("access_exceptions", "date")],
)
def test_malformed_fact_value_fails_with_path(tmp_path, field, member):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    review_dir = _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    artifact_path = review_dir / "historical.json"
    artifact_path.write_text(json.dumps({
        "status": "completed",
        "payload": {"sessions": sessions, field: [{member: []}]},
    }))
    with pytest.raises(EvaluationArtifactError, match=rf"{artifact_path}: payload\.{field}\[0\]\.{member}"):
        collect_pool_evals(data_root=tmp_path)


def test_auxiliary_source_bundle_array_is_not_a_provider_prediction(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    review_dir = _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    (review_dir / "source-bundle.json").write_text(json.dumps([{"pool": "cool"}]))

    evals = collect_pool_evals(data_root=tmp_path)

    assert len(evals) == 1
    assert not any(item.provider_artifact == "source-bundle.json" for item in evals)


@pytest.mark.parametrize(
    ("artifact", "reason"),
    [
        ({"status": "provider_error"}, "recorded provider failure (provider_error)"),
        ({"status": "unsupported"}, "recorded provider failure (unsupported)"),
        ({"provider": "old-provider"}, "unsupported historical artifact: no payload"),
    ],
)
def test_recorded_failure_or_unsupported_artifact_is_unscored(tmp_path, artifact, reason):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    review_dir = _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    (review_dir / "historical.json").write_text(json.dumps(artifact))

    evals = collect_pool_evals(data_root=tmp_path)

    unscored = [item for item in evals if isinstance(item, UnscoredArtifact)]
    assert len(unscored) == 1
    assert unscored[0].reason == reason
    assert "Unscored artifacts" in render_report(evals)


def test_report_with_only_unscored_artifacts_does_not_hide_the_input(tmp_path):
    review_dir = tmp_path / "x-pool" / "2026-04-19-abcdef123456"
    review_dir.mkdir(parents=True)
    (review_dir / "reviewed.json").write_text(json.dumps({"payload": {"sessions": []}}))
    (review_dir / "failed.json").write_text(json.dumps({"status": "provider_error"}))

    report = render_report(collect_pool_evals(data_root=tmp_path))

    assert "Unscored artifacts" in report
    assert "failed.json" in report


@pytest.mark.parametrize(
    "artifact",
    [
        [],
        {"status": "completed"},
        {"status": "completed", "payload": []},
        {"status": "completed", "payload": {"sessions": None}},
        {"status": "completed", "payload": {"sessions": [42]}},
        {"status": "completed", "payload": {"sessions": [{"evidence": None}]}},
    ],
)
def test_malformed_eligible_artifact_fails_with_path(tmp_path, artifact):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    review_dir = _write_review(tmp_path, "x-pool", "2026-04-19", "abcdef123456", sessions, sessions)
    artifact_path = review_dir / "historical.json"
    artifact_path.write_text(json.dumps(artifact))

    with pytest.raises(EvaluationArtifactError, match=str(artifact_path)):
        collect_pool_evals(data_root=tmp_path)


def test_cli_reports_malformed_artifact_as_nonzero(monkeypatch, tmp_path):
    review_dir = tmp_path / "x-pool" / "2026-04-19-abcdef123456"
    review_dir.mkdir(parents=True)
    (review_dir / "reviewed.json").write_text(json.dumps({"payload": {"sessions": []}}))
    artifact_path = review_dir / "historical.json"
    artifact_path.write_text(
        json.dumps({"status": "completed", "payload": {"sessions": [{"evidence": None}]}})
    )

    def collect_from_fixture(**kwargs):
        from schedules.eval import collect_pool_evals

        return collect_pool_evals(data_root=tmp_path, all_dirs=kwargs["all_dirs"])

    monkeypatch.setattr(cli_module, "collect_pool_evals", collect_from_fixture)
    result = CliRunner().invoke(cli_module.cli, ["eval", "--stdout"])

    assert result.exit_code != 0
    assert str(artifact_path) in result.output
    assert "evidence must be a string" in result.output


def test_real_tracked_corpus_includes_north_beach_bundle_without_writing():
    repo_root = Path(__file__).resolve().parents[1]
    before = {
        path: path.read_bytes()
        for path in (repo_root / "data").rglob("*.json")
    }

    evals = collect_pool_evals(data_root=repo_root / "data")
    all_evals = collect_pool_evals(data_root=repo_root / "data", all_dirs=True)

    assert any(item.pool == "north-beach-pool" for item in evals)
    assert any(item.pool == "north-beach-pool" for item in all_evals)
    assert not any(item.provider_artifact == "source-bundle.json" for item in [*evals, *all_evals])
    assert all(path.read_bytes() == contents for path, contents in before.items())
