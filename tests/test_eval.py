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
) -> Path:
    review_dir = data_root / slug / f"{fetch_date}-{sha12}"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "reviewed.json").write_text(
        json.dumps(
            {
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
        )
    )
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
