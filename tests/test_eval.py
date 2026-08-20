import json
from pathlib import Path

from schedules.eval import collect_pool_evals, render_report


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


def test_carried_ci_stays_quality_same_dir(tmp_path):
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
    assert len(evals) == 1
    assert evals[0].table == "quality"
