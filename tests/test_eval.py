import json
import copy
import hashlib
from pathlib import Path

import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.eval import collect_pool_evals, load_benchmark_reference, render_report, score_benchmark_run
from schedules.paths import REPO_ROOT


def _write_review(
    data_root: Path,
    slug: str,
    fetch_date: str,
    sha12: str,
    truth_sessions: list[dict],
    provider_sessions: list[dict],
    provider_filename: str = "gemini-gemini-3-1-flash-lite-preview.json",
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
    assert "Row identity is `(day, type, start, end, pool)`." in report
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


def _reference(reference_id="hamilton-fall"):
    return load_benchmark_reference(
        REPO_ROOT / "tests/fixtures/schedule-benchmark.json", reference_id, repo_root=REPO_ROOT,
    )


def _attempt(reference):
    return {
        "model": "test-model", "transport": "test-fixture", "exit_code": 0,
        "timed_out": False, "source_sha256": reference["source_sha256"],
        "payload": copy.deepcopy(reference["expected"]) | {"closures": []},
    }


def test_checked_source_hashes_and_split_are_disjoint():
    documents = json.loads((REPO_ROOT / "tests/fixtures/schedule-benchmark.json").read_text())["documents"]
    assert len({item["id"] for item in documents}) == len(documents)
    assert len({item["source_sha256"] for item in documents}) == len(documents)
    for item in documents:
        assert hashlib.sha256((REPO_ROOT / item["source_pdf"]).read_bytes()).hexdigest() == item["source_sha256"]
        if item["split"] == "reserved":
            assert "expected" not in item


def test_benchmark_reference_rejects_changed_pdf(tmp_path):
    reference = copy.deepcopy(_reference())
    reference["source_pdf"] = "source.pdf"
    (tmp_path / "source.pdf").write_bytes(b"changed")
    manifest = tmp_path / "references.json"
    manifest.write_text(json.dumps({"documents": [reference]}))
    with pytest.raises(ValueError, match="hash"):
        load_benchmark_reference(manifest, reference["id"], repo_root=tmp_path)


def test_reserved_document_cannot_be_scored():
    with pytest.raises(ValueError, match="reserved"):
        _reference("rossi-spring")


def test_benchmark_marks_unresolved_closures_unscored():
    reference = _reference()
    result = score_benchmark_run(reference, _attempt(reference))
    assert result["checked_fields_match"] is True
    assert result["scores"]["sessions"]["f1"] == 1
    assert result["unscored_fields"] == ["closures"]
    assert result["unresolved"]
    assert "human sign-off pending" in result["reference_review"]


@pytest.mark.parametrize("reference_id, count", [
    ("hamilton-fall", 23), ("balboa-fall", 22), ("balboa-interim", 22),
])
def test_checked_references_have_valid_unique_sessions(reference_id, count):
    reference = _reference(reference_id)
    result = score_benchmark_run(reference, _attempt(reference))
    assert result["checked_fields_match"] is True
    assert result["scores"]["sessions"]["expected_count"] == count


def test_carried_ci_uses_older_human_only_as_seasonal_delta(tmp_path):
    sessions = [_row("monday", "lap_swim", "07:00", "08:00")]
    _write_review(tmp_path, "x-pool", "2026-04-19", "aaaaaaaaaaaa", sessions, sessions,
                  attested_by="human")
    _write_review(tmp_path, "x-pool", "2026-08-19", "bbbbbbbbbbbb", sessions, sessions,
                  attested_by="ci", carried_from="data/x-pool/ci/reviewed.json")
    evals = collect_pool_evals(data_root=tmp_path)
    assert len(evals) == 1
    assert evals[0].table == "seasonal_delta"


def test_benchmark_catches_hamilton_wrong_day_and_numeric_pool():
    reference = _reference()
    attempt = _attempt(reference)
    early = next(row for row in attempt["payload"]["sessions"]
                 if row["day"] == "wednesday" and row["start"] == "06:30")
    early["day"] = "tuesday"
    early["pool"] = "6"
    result = score_benchmark_run(reference, attempt)
    assert not result["checked_fields_match"]
    assert result["scores"]["sessions"]["missing"][0]["day"] == "wednesday"
    assert result["scores"]["sessions"]["extra"][0]["pool"] == "6"


def test_benchmark_counts_duplicates_as_extra_rows():
    reference = _reference()
    attempt = _attempt(reference)
    attempt["payload"]["sessions"].append(attempt["payload"]["sessions"][0].copy())
    result = score_benchmark_run(reference, attempt)
    assert len(result["scores"]["sessions"]["extra"]) == 1
    assert not result["checked_fields_match"]


def test_benchmark_checks_dates_separately_from_rows():
    reference = _reference()
    attempt = _attempt(reference)
    attempt["payload"]["effective_start"] = "2026-08-19"
    result = score_benchmark_run(reference, attempt)
    assert result["scores"]["sessions"]["f1"] == 1
    assert not result["scores"]["effective_start"]["match"]
    assert not result["checked_fields_match"]


def test_benchmark_scores_partial_closure_times_not_reason_wording():
    reference = copy.deepcopy(_reference())
    reference["expected"]["closures"] = [
        {"start": "2026-08-22", "end": "2026-08-22", "start_time": "08:30", "end_time": "12:30"},
    ]
    attempt = _attempt(reference)
    attempt["payload"]["closures"] = [reference["expected"]["closures"][0] | {"reason": "Training"}]
    assert score_benchmark_run(reference, attempt)["scores"]["closures"]["f1"] == 1
    del attempt["payload"]["closures"][0]["start_time"]
    del attempt["payload"]["closures"][0]["end_time"]
    result = score_benchmark_run(reference, attempt)
    assert result["scores"]["closures"]["f1"] == 0
    assert not result["checked_fields_match"]


@pytest.mark.parametrize("updates, status", [
    ({"exit_code": 1, "payload": None}, "execution_error"),
    ({"exit_code": None, "timed_out": True}, "timeout"),
    ({"payload": None}, "schema_invalid"),
    ({"payload": {}}, "schema_invalid"),
])
def test_benchmark_does_not_score_failed_attempts(updates, status):
    reference = _reference()
    result = score_benchmark_run(reference, _attempt(reference) | updates)
    assert result["status"] == status
    assert "scores" not in result


def test_benchmark_rejects_wrong_source_and_missing_transport():
    reference = _reference()
    for updates in ({"source_sha256": "0" * 64}, {"transport": ""}, {"exit_code": True}):
        with pytest.raises(ValueError):
            score_benchmark_run(reference, _attempt(reference) | updates)


def test_benchmark_cli_is_offline_and_read_only(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network call"))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(_attempt(_reference())))
    before = attempt.read_bytes()
    result = CliRunner().invoke(cli, ["benchmark", str(attempt), "--reference", "hamilton-fall"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["checked_fields_match"] is True
    assert attempt.read_bytes() == before
    assert list(tmp_path.iterdir()) == [attempt]
