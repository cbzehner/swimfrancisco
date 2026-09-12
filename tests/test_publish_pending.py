from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.fetch import FetchResult
from schedules.models import PoolEntry
from schedules.publish import (
    Eligibility,
    latest_effective_start,
    pager_flagged_set,
    parse_closure_dates,
    publish_candidate,
    publish_eligible,
    publish_pending_all,
)
from schedules.review import (
    FinalizeError,
    ReviewCandidate,
    finalize_draft,
    find_review_candidates,
)
from schedules.validate import validate
from conftest import pin_publish_clock


SHA = "a" * 64
SHA2 = "b" * 64
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _pomeroy_candidate(tmp_path: Path, monkeypatch):
    from schedules.direct_sources import direct_configuration, observation_window
    from schedules.direct_sources.providers.pomeroy import _extract_pomeroy
    source = Path(__file__).parents[1] / "data/pomeroy-pool/2026-08-12-5348b4b7f7e3/source.html"
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    review_dir = tmp_path / "data/pomeroy-pool" / f"2026-09-07-{digest[:12]}"
    review_dir.mkdir(parents=True)
    (review_dir / "source.html").write_bytes(content)
    (review_dir / "source.sha256").write_text(digest + "\n")
    url = "https://www.prrcsf.org/therapeutic-swim"
    payload = observation_window(_extract_pomeroy(content.decode(), observed_on=date(2026, 9, 7)), "2026-09-07")
    artifact = {"provider": "direct", "model": "pomeroy-html-v1", "pdf_sha256": digest,
                "source_pdf_url": url, "payload": payload, "details": {"direct_source": {
                    "sha256": digest, "url": url, "requested_url": url, "observed_on": "2026-09-07",
                    "freshness_days": 14, "configuration": direct_configuration()}}}
    path = review_dir / "direct-pomeroy-html-v1.json"
    path.write_text(json.dumps(artifact))
    candidate = find_review_candidates(data_root=tmp_path / "data")[0]
    return candidate, artifact, path


def _pomeroy_eligible(candidate, artifact, **kwargs):
    return publish_eligible(candidate=candidate, payload=artifact["payload"], prior_sessions_count=16,
                            latest_effective_start="2026-05-17", source_kind="pomeroy_html",
                            source_status="published", blocking_slugs=frozenset(), quarantined_shas=frozenset(),
                            has_prior_schedule_window=True, source_pdf_path=candidate.source_path,
                            pin_url="https://www.prrcsf.org/therapeutic-swim", **kwargs)


def test_pomeroy_requires_opt_in_and_expires_at_pacific_observation_boundary(tmp_path, monkeypatch):
    candidate, artifact, _ = _pomeroy_candidate(tmp_path, monkeypatch)
    assert not _pomeroy_eligible(candidate, artifact, today=date(2026, 9, 7)).ok
    assert _pomeroy_eligible(candidate, artifact, direct_opt_in=True, today=date(2026, 9, 20)).ok
    assert not _pomeroy_eligible(candidate, artifact, direct_opt_in=True, today=date(2026, 9, 21)).ok
    assert not _pomeroy_eligible(candidate, artifact, direct_opt_in=True, today=date(2026, 9, 6)).ok


@pytest.mark.parametrize("mutation", ["configuration", "source_bytes", "original_url", "final_url", "freshness", "omission", "closure_start", "access_exception"])
def test_pomeroy_acceptance_rejects_changed_evidence(tmp_path, monkeypatch, mutation):
    candidate, artifact, path = _pomeroy_candidate(tmp_path, monkeypatch)
    if mutation == "configuration":
        artifact["details"]["direct_source"]["configuration"]["parser_sha256"] = "0" * 64
    elif mutation == "source_bytes":
        candidate.source_path.write_bytes(candidate.source_path.read_bytes() + b" ")
    elif mutation == "original_url":
        artifact["source_pdf_url"] = "https://example.org/"
    elif mutation == "final_url":
        artifact["details"]["direct_source"]["url"] = "https://example.org/"
    elif mutation == "freshness":
        artifact["payload"]["effective_end"] = "2026-09-21"
    elif mutation == "omission":
        artifact["payload"]["sessions"].pop()
    elif mutation == "closure_start":
        artifact["payload"]["closures"][0]["start"] = "2026-09-08"
    else:
        artifact["payload"]["access_exceptions"] = [{"date": "2026-09-08", "start": "01:00", "end": "23:00", "label": "Pool hours", "reason": "Extra", "evidence": "Extra"}]
    path.write_text(json.dumps(artifact))
    assert not _pomeroy_eligible(candidate, artifact, direct_opt_in=True, today=date(2026, 9, 7)).ok


def test_pomeroy_failed_current_extraction_cannot_publish_prior_candidate(tmp_path, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 9, 7))
    import schedules.publish as module
    candidate, artifact, path = _pomeroy_candidate(tmp_path, monkeypatch)
    content = tmp_path / "content"
    content.mkdir()
    _seed_content(content, "pomeroy-pool")
    reports = tmp_path / "tmp"
    reports.mkdir()
    monkeypatch.setattr(module, "TMP_DIR", reports)
    monkeypatch.setattr(module, "auto_project_enabled", lambda: True)
    monkeypatch.setattr(module, "load_quarantine", lambda: frozenset())
    entry = PoolEntry("pomeroy-pool", "https://www.prrcsf.org/therapeutic-swim", "https://www.prrcsf.org/pool", source_kind="pomeroy_html", auto_publish=True)
    monkeypatch.setattr(module, "load_registry", lambda: [entry])
    assert publish_pending_all(data_root=tmp_path / "data", content_spots_dir=content, today=date(2026, 9, 7))[0] == 0
    assert not (candidate.review_dir / "reviewed.json").exists()
    (reports / "extraction-report-direct.json").write_text(json.dumps({"ready_direct": {"pomeroy-pool": f"data/pomeroy-pool/{candidate.review_dir.name}/{path.name}"}}))
    assert publish_pending_all(data_root=tmp_path / "data", content_spots_dir=content, today=date(2026, 9, 7))[0] == 1
    reviewed = json.loads((candidate.review_dir / "reviewed.json").read_text())
    assert reviewed["direct_source"] == artifact["details"]["direct_source"]
    assert reviewed["payload"]["effective_end"] == "2026-09-20"



@pytest.mark.parametrize("current_ready", [False, True])
def test_pomeroy_superseded_candidate_is_skipped_only_with_current_ready_artifact(tmp_path, monkeypatch, current_ready):
    pin_publish_clock(monkeypatch, date(2026, 9, 7))
    import shutil
    import schedules.publish as module

    candidate, artifact, path = _pomeroy_candidate(tmp_path, monkeypatch)
    older_dir = candidate.review_dir.with_name("2026-09-06-" + candidate.pdf_sha256[:12])
    shutil.copytree(candidate.review_dir, older_dir)
    older_artifact = older_dir / path.name
    stale = json.loads(older_artifact.read_text())
    stale["details"]["direct_source"]["configuration"]["parser_sha256"] = "0" * 64
    older_artifact.write_text(json.dumps(stale))
    original = older_artifact.read_bytes()
    content = tmp_path / "content"
    content.mkdir()
    _seed_content(content, "pomeroy-pool")
    reports = tmp_path / "tmp"
    reports.mkdir()
    monkeypatch.setattr(module, "TMP_DIR", reports)
    monkeypatch.setattr(module, "auto_project_enabled", lambda: True)
    monkeypatch.setattr(module, "load_quarantine", lambda: frozenset())
    entry = PoolEntry("pomeroy-pool", "https://www.prrcsf.org/therapeutic-swim", "https://www.prrcsf.org/pool", source_kind="pomeroy_html", auto_publish=True)
    monkeypatch.setattr(module, "load_registry", lambda: [entry])
    if current_ready:
        (reports / "extraction-report-direct.json").write_text(json.dumps({"ready_direct": {
            "pomeroy-pool": f"data/pomeroy-pool/{candidate.review_dir.name}/{path.name}"
        }}))
    count, _ = publish_pending_all(data_root=tmp_path / "data", content_spots_dir=content, today=date(2026, 9, 7))
    report = json.loads((reports / "publish-pending.json").read_text())
    assert count == int(current_ready)
    assert (candidate.review_dir / "reviewed.json").exists() is current_ready
    assert not (older_dir / "reviewed.json").exists()
    assert older_artifact.read_bytes() == original
    if current_ready:
        assert report["refused"] == []
    else:
        assert report["refused"]
        assert {row["code"] for row in report["refused"]} == {"direct_extraction_incomplete"}

def test_direct_configuration_change_requeues_review_without_destroying_it(tmp_path, monkeypatch):
    candidate, artifact, path = _pomeroy_candidate(tmp_path, monkeypatch)
    from schedules.review import draft_envelope
    reviewed = draft_envelope(candidate=candidate, today=date(2026, 9, 7), attested_by="ci")
    target = candidate.review_dir / "reviewed.json"
    target.write_text(json.dumps(reviewed))
    assert find_review_candidates(data_root=tmp_path / "data") == []
    artifact["details"]["direct_source"]["configuration"]["parser_sha256"] = "0" * 64
    path.write_text(json.dumps(artifact))
    assert len(find_review_candidates(data_root=tmp_path / "data")) == 1
    assert json.loads(target.read_text()) == reviewed
SAVA_FALL1 = "https://sfrecpark.org/DocumentCenter/View/29815"
SAVA_FALL2 = "https://sfrecpark.org/DocumentCenter/View/29805"


def _sessions(n: int = 5) -> list[dict]:
    return [
        {"day": DAYS[i], "type": "lap_swim", "start": "07:00", "end": "08:00"}
        for i in range(n)
    ]


def _payload(
    *,
    n: int = 5,
    start: str = "2026-08-18",
    end: str = "2026-12-12",
    basis: str = "swim_schedule",
) -> dict:
    return {
        "effective_start": start,
        "effective_end": end,
        "schedule_basis": basis,
        "sessions": _sessions(n),
        "closures": [],
    }


def _entry(slug: str = "hamilton-pool", *, kind: str = "sfrecpark_pdf", status: str = "published") -> PoolEntry:
    return PoolEntry(
        slug=slug,
        pdf_url="https://sfrecpark.org/DocumentCenter/View/29800",
        official_page_url="https://sfrecpark.org/facilities/facility/details/Hamilton-Pool-215",
        source_kind=kind,  # type: ignore[arg-type]
        source_status=status,  # type: ignore[arg-type]
    )


def _write_candidate(
    data: Path,
    slug: str = "hamilton-pool",
    sha: str = SHA,
    *,
    payload: dict | None = None,
    source_verified: bool = True,
    source_pdf: bool = True,
    fetch_date: str = "2026-08-19",
    source_pdf_url: str = "https://sfrecpark.org/DocumentCenter/View/29800",
) -> ReviewCandidate:
    payload = payload if payload is not None else _payload()
    review_dir = data / slug / f"{fetch_date}-{sha[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    artifact: dict = {
        "provider": "openai",
        "test_source_verified": source_verified,
        "pdf_sha256": sha,
        "source_pdf_url": source_pdf_url,
        "payload": payload,
    }
    (review_dir / "openai-fixture.json").write_text(json.dumps(artifact))
    source_path = review_dir / "source.pdf"
    if source_pdf:
        source_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return ReviewCandidate(
        slug=slug,
        pdf_sha256=sha,
        review_dir=review_dir,
        source_path=source_path,
        fetch_date=fetch_date,
    )


def _seed_content(
    content_dir: Path,
    slug: str,
    *,
    windows: list[tuple[str, str]] | None = None,
    sessions: int = 5,
) -> Path:
    windows = windows or [("2026-03-17", "2026-06-06")]
    blocks = []
    for start, end in windows:
        session_rows = "\n".join(
            (
                "[[extra.schedules.sessions]]\n"
                f'day = "{DAYS[i % 7]}"\n'
                'type = "lap_swim"\n'
                'start = "07:00"\n'
                'end = "08:00"\n'
            )
            for i in range(sessions)
        )
        blocks.append(
            "[[extra.schedules]]\n"
            f'effective_start = "{start}"\n'
            'schedule_basis = "swim_schedule"\n'
            f'effective_end = "{end}"\n'
            'last_verified_at = "2026-04-19"\n\n'
            f"{session_rows}"
        )
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'title = "{slug}"\n'
        f'slug = "{slug}"\n\n'
        "[extra]\n\n"
        + "\n".join(blocks)
        + "+++\n"
    )
    return path


def _kwargs(candidate: ReviewCandidate, **overrides) -> dict:
    payload = json.loads((candidate.review_dir / "openai-fixture.json").read_text())["payload"]
    defaults = {
        "candidate": candidate,
        "payload": payload,
        "prior_sessions_count": 5,
        "latest_effective_start": "2026-03-17",
        "source_kind": "sfrecpark_pdf",
        "source_status": "published",
        "blocking_slugs": frozenset(),
        "quarantined_shas": frozenset(),
        "has_prior_schedule_window": True,
        "source_pdf_path": candidate.source_path if candidate.source_path.exists() else None,
        "kill_switch": False,
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def iso(tmp_path, monkeypatch) -> SimpleNamespace:
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    tmp = tmp_path / "tmp"
    data.mkdir()
    content.mkdir(parents=True)
    tmp.mkdir()
    monkeypatch.setattr("schedules.publish.DATA_DIR", data)
    monkeypatch.setattr("schedules.publish.CONTENT_SPOTS_DIR", content)
    monkeypatch.setattr("schedules.publish.TMP_DIR", tmp)
    monkeypatch.setattr("schedules.publish.pacific_today", lambda: date(2026, 8, 20))
    monkeypatch.setattr("schedules.publish.extract_page_texts", lambda _bytes: ["Monday"])
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_entry()])
    monkeypatch.setattr("schedules.publish.load_quarantine", lambda: frozenset())
    monkeypatch.setattr("schedules.publish.verify_artifact", lambda artifact, *_: {"ok": artifact.get("test_source_verified", False)})
    return SimpleNamespace(data=data, content=content, tmp=tmp)


def test_unique_grid_eligible(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate))
    assert result.ok is True
    assert result.code is None


def test_incomplete_source_refuses(iso):
    candidate = _write_candidate(iso.data, source_verified=False)
    result = publish_eligible(**_kwargs(candidate))
    assert result.ok is False
    assert result.code == "source_coverage_failed"


def test_legacy_provider_refuses_even_with_matching_coverage(iso):
    candidate = _write_candidate(iso.data)
    path = candidate.review_dir / "openai-fixture.json"
    artifact = json.loads(path.read_text())
    artifact.update(provider="gemini")
    path.write_text(json.dumps(artifact))
    assert publish_eligible(**_kwargs(candidate)).code == "unsupported_provider"


def test_verified_closure_without_sessions_eligible(iso):
    payload = _payload(n=0, basis="temporarily_closed") | {
        "closures": [{"start": "2026-08-18", "end": "2026-12-12", "reason": "Maintenance"}],
    }
    candidate = _write_candidate(iso.data, payload=payload)
    result = publish_eligible(
        **_kwargs(
            candidate,
            payload=payload,
        )
    )
    assert result.ok is True


def test_missing_source_evidence_refuses(iso, monkeypatch):
    candidate = _write_candidate(iso.data)
    def missing(*args, **kwargs):
        raise ValueError("Missing evidence")
    monkeypatch.setattr("schedules.publish.verify_artifact", missing)
    result = publish_eligible(**_kwargs(candidate))
    assert result.code == "source_coverage_failed"


def test_drop_to_zero_catastrophic_unless_temporarily_closed(iso):
    candidate = _write_candidate(iso.data)
    empty = {**_payload(n=0), "schedule_basis": "swim_schedule"}
    closed = {**_payload(n=0), "schedule_basis": "temporarily_closed",
              "closures": [{"start": "2026-08-18", "end": "2026-12-12", "reason": "Maintenance"}]}
    dropped = publish_eligible(**_kwargs(candidate, payload=empty, prior_sessions_count=8))
    assert dropped.code == "sessions_dropped_to_zero"
    assert validate(empty, prior_sessions_count=8).catastrophic is True
    candidate = _write_candidate(iso.data, payload=closed)
    allowed = publish_eligible(**_kwargs(candidate, prior_sessions_count=8))
    assert allowed.ok is True


def test_closure_without_dates_refuses_even_with_matching_coverage(iso):
    candidate = _write_candidate(iso.data, payload=_payload(n=0, basis="temporarily_closed"))
    result = publish_eligible(**_kwargs(candidate))
    assert result.code == "closure_notice_missing_dates"


def test_closure_with_invented_sessions_refuses(iso):
    payload = _payload(basis="temporarily_closed") | {
        "closures": [{"start": "2026-08-18", "end": "2026-12-12", "reason": "Maintenance"}],
    }
    candidate = _write_candidate(iso.data, payload=payload)
    assert publish_eligible(**_kwargs(candidate)).code == "closure_notice_has_open_hours"


def test_duplicate_sessions_refuse_even_with_matching_coverage(iso):
    payload = _payload()
    payload["sessions"].append(payload["sessions"][0].copy())
    candidate = _write_candidate(iso.data, payload=payload)
    assert publish_eligible(**_kwargs(candidate)).code == "duplicate_session"


def test_too_few_refuses(iso):
    candidate = _write_candidate(iso.data)
    payload = _payload(n=2)
    result = publish_eligible(**_kwargs(candidate, payload=payload))
    assert result.ok is False
    assert result.code == "too_few_weekly_sessions"


def test_not_rec_park_refuses(iso):
    candidate = _write_candidate(iso.data, slug="koret-center")
    result = publish_eligible(**_kwargs(candidate, source_kind="koret_google_sheet"))
    assert result.code == "not_rec_park"


def test_discovery_flagged_refuses(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(
        **_kwargs(candidate, blocking_slugs=frozenset({"hamilton-pool"}))
    )
    assert result.code == "discovery_flagged"


def test_missing_current_schedule_refuses(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate, source_status="missing_current_schedule"))
    assert result.code == "split_pdf"


def test_quarantine_refuses(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate, quarantined_shas=frozenset({SHA})))
    assert result.code == "quarantined"


def test_human_finalize_allows_quarantined_sha(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    from schedules.review import finalize_draft

    envelope = {
        "slug": "hamilton-pool",
        "pdf_sha256": SHA,
        "reviewed_at": "2026-08-20",
        "attested_by": "human",
        "source_pdf_url": "https://example.com/x.pdf",
        "payload": _payload(),
    }
    candidate = _write_candidate(iso.data)
    reviewed = candidate.review_dir / "reviewed.json"
    reviewed.write_text(json.dumps(envelope))
    _seed_content(iso.content, "hamilton-pool")
    result = finalize_draft(reviewed_json_path=reviewed, content_spots_dir=iso.content)
    assert result == reviewed


def test_no_merge_baseline_refuses(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate, has_prior_schedule_window=False))
    assert result.code == "no_merge_baseline"


def test_effective_start_regressed_uses_max_window_not_active(iso):
    payload = _payload(start="2026-04-01")
    candidate = _write_candidate(iso.data, payload=payload)
    result = publish_eligible(
        **_kwargs(candidate, payload=payload, latest_effective_start="2026-08-18")
    )
    assert result.code == "effective_start_regressed"


def test_verified_existing_window_can_refresh_beside_a_future_window(iso):
    payload = _payload(start="2026-08-18", end="2026-09-26")
    candidate = _write_candidate(iso.data, payload=payload)
    reviewed = {"attested_by": "ci", "pdf_sha256": candidate.pdf_sha256, "payload": payload}
    target = candidate.review_dir / "reviewed.json"
    target.write_text(json.dumps(reviewed))
    assert publish_eligible(**_kwargs(candidate, latest_effective_start="2026-09-29")).ok
    reviewed["payload"] = dict(payload, effective_end="2026-09-25")
    target.write_text(json.dumps(reviewed))
    assert publish_eligible(**_kwargs(candidate, latest_effective_start="2026-09-29")).code == "effective_start_regressed"


def test_session_count_shift_is_eligible(iso):
    payload = _payload(n=7)
    candidate = _write_candidate(iso.data, payload=payload)
    result = publish_eligible(
        **_kwargs(candidate, payload=payload, prior_sessions_count=5)
    )
    assert result.ok is True


def test_payload_cannot_differ_from_verified_artifact(iso):
    candidate = _write_candidate(iso.data)
    assert publish_eligible(**_kwargs(candidate, payload=_payload(n=6))).code == "source_coverage_failed"


def test_identity_mismatch_provider_sha(iso):
    candidate = _write_candidate(iso.data)
    other = ReviewCandidate(
        slug=candidate.slug,
        pdf_sha256="b" * 64,
        review_dir=candidate.review_dir,
        source_path=candidate.source_path,
        fetch_date=candidate.fetch_date,
    )
    result = publish_eligible(**_kwargs(other))
    assert result.code == "identity_mismatch"


def test_source_pdf_missing_refuses(iso):
    candidate = _write_candidate(iso.data, source_pdf=False)
    result = publish_eligible(**_kwargs(candidate, source_pdf_path=None))
    assert result.code == "source_pdf_missing"


def test_multi_grid_source_pdf_refuses(iso, monkeypatch):
    candidate = _write_candidate(iso.data)
    monkeypatch.setattr(
        "schedules.publish.extract_page_texts",
        lambda _bytes: [
            "Monday Tuesday Wednesday Thursday Friday",
            "Monday Tuesday Wednesday Thursday Friday",
        ],
    )
    result = publish_eligible(**_kwargs(candidate))
    assert result.code == "multi_grid_suspected"


def test_publish_candidate_writes_ci_attestation(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    candidate = _write_candidate(iso.data)
    _seed_content(iso.content, "hamilton-pool")
    path = publish_candidate(
        candidate=candidate,
        content_spots_dir=iso.content,
        attested_at=date(2026, 8, 20),
        eligibility=Eligibility(ok=True, code=None),
    )
    envelope = json.loads(path.read_text())
    assert envelope["attested_by"] == "ci"
    assert envelope["reviewed_at"] == "2026-08-20"
    assert "carried_from" not in envelope
    rendered = (iso.content / "hamilton-pool.md").read_text()
    assert "[[extra.schedules.sessions]]" in rendered
    assert 'last_verified_at = "2026-08-20"' in rendered
    assert 'effective_start = "2026-08-18"' in rendered


def test_finalize_failure_unlinks_reviewed_json(iso, monkeypatch):
    candidate = _write_candidate(iso.data)
    _seed_content(iso.content, "hamilton-pool")

    def boom(**_kwargs):
        raise FinalizeError("projection exploded")

    monkeypatch.setattr("schedules.publish.finalize_draft", boom)
    with pytest.raises(FinalizeError, match="projection exploded"):
        publish_candidate(
            candidate=candidate,
            content_spots_dir=iso.content,
            attested_at=date(2026, 8, 20),
            eligibility=Eligibility(ok=True, code=None),
        )
    assert not (candidate.review_dir / "reviewed.json").exists()


def test_reviewed_pdf_refresh_requires_current_success(iso, monkeypatch):
    candidate = _write_candidate(iso.data)
    _seed_content(iso.content, "hamilton-pool")
    reviewed = candidate.review_dir / "reviewed.json"
    original = b'{"attested_by":"ci","payload":{"sessions":[]}}\n'
    reviewed.write_bytes(original)
    monkeypatch.setattr("schedules.publish.find_review_candidates", lambda **kwargs: [candidate])
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_entry()])
    count, report = publish_pending_all(data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20))
    assert count == 0
    assert reviewed.read_bytes() == original
    assert json.loads(report.with_name("publish-pending.json").read_text())["refused"][0]["code"] == "current_extraction_incomplete"


def test_second_run_has_no_candidate(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    candidate = _write_candidate(iso.data)
    _seed_content(iso.content, "hamilton-pool")
    publish_candidate(
        candidate=candidate,
        content_spots_dir=iso.content,
        attested_at=date(2026, 8, 20),
        eligibility=Eligibility(ok=True, code=None),
    )
    assert find_review_candidates(data_root=iso.data) == []
    count, _ = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0


def test_parse_closure_dates_from_anchor_text(monkeypatch):
    monkeypatch.setattr("schedules.publish.pacific_today", lambda: date(2026, 8, 20))
    parsed = parse_closure_dates("", "Garfield Pool Maintenance Closure 8-14_9-7 2026")
    assert parsed == (date(2026, 8, 14), date(2026, 9, 7))


def test_parse_closure_dates_from_filename(monkeypatch):
    monkeypatch.setattr("schedules.publish.pacific_today", lambda: date(2026, 8, 20))
    parsed = parse_closure_dates("Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf", "")
    assert parsed == (date(2026, 8, 14), date(2026, 9, 7))


def test_parse_closure_dates_unparseable():
    assert parse_closure_dates("notes.pdf", "See website") is None


def test_parse_closure_dates_accepts_month_alias(monkeypatch):
    monkeypatch.setattr("schedules.publish.pacific_today", lambda: date(2026, 8, 20))
    parsed = parse_closure_dates("", "Sept 8 to Dec 10")
    assert parsed == (date(2026, 9, 8), date(2026, 12, 10))


def _garfield_decision(*, notices: list[dict], band: dict | None = None) -> dict:
    candidates = list(notices)
    if band is not None:
        candidates.append(band)
    return {
        "slug": "garfield-pool",
        "action": "flag",
        "blocking": True,
        "kind": "session_grid",
        "reason": "band_session_grid",
        "candidates": candidates,
    }


def _flyer(*, view_id: int = 29808, source: str = "table", text: str | None = None) -> dict:
    title = text if text is not None else "Garfield Pool Maintenance Closure 8-14_9-7 2026"
    return {
        "view_id": view_id,
        "href": f"https://sfrecpark.org/DocumentCenter/View/{view_id}",
        "anchor_text": title,
        "filename": f"{title}.pdf" if title else "",
        "kind": "closure_notice",
        "source": source,
    }


def test_closure_window_from_anchor_text_matches_source_pdf(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    source_bytes = (Path(__file__).parents[1] / "data/garfield-pool/2026-08-20-241f3a02fd75/source.pdf").read_bytes()
    flyer_sha = hashlib.sha256(source_bytes).hexdigest()
    flyer_dir = iso.data / "garfield-pool" / f"2026-08-20-{flyer_sha[:12]}"
    flyer_dir.mkdir(parents=True)
    source = flyer_dir / "source.pdf"
    source.write_bytes(source_bytes)
    fetched_urls: list[str] = []

    def fake_fetch(slug, url, **_kwargs):
        fetched_urls.append(url)
        return FetchResult(
            path=source, sha256=flyer_sha, bytes=source_bytes, from_cache=False, page_count=1
        )

    monkeypatch.setattr("schedules.publish.fetch_pdf", fake_fetch)
    monkeypatch.setattr(
        "schedules.publish.load_registry",
        lambda: [_entry("garfield-pool")],
    )
    _seed_content(iso.content, "garfield-pool")
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps(
            [
                _garfield_decision(
                    notices=[_flyer(text="Garfield Pool Maintenance Closure 8-14_9-7 2026")],
                    band={
                        "view_id": 29799,
                        "href": "https://sfrecpark.org/DocumentCenter/View/29799",
                        "anchor_text": "Garfield Weekdays Fall 2026",
                        "filename": "Garfield Weekdays Fall 2026.pdf",
                        "kind": "session_grid",
                        "source": "band",
                    },
                )
            ]
        )
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 1
    assert fetched_urls == ["https://sfrecpark.org/DocumentCenter/View/29808"]
    envelope = json.loads((flyer_dir / "reviewed.json").read_text())
    assert envelope["attested_by"] == "ci"
    assert envelope["payload"]["effective_start"] == "2026-08-14"
    assert envelope["payload"]["effective_end"] == "2026-09-07"
    assert envelope["payload"]["schedule_basis"] == "temporarily_closed"
    rendered = (iso.content / "garfield-pool.md").read_text()
    assert 'effective_start = "2026-08-14"' in rendered
    payload = json.loads(report.with_name("publish-pending.json").read_text())
    assert payload["closure"] == ["garfield-pool"]


def test_closure_zero_table_flyers_does_not_fetch(iso, monkeypatch):
    monkeypatch.setattr(
        "schedules.publish.fetch_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_entry("garfield-pool")])
    _seed_content(iso.content, "garfield-pool")
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps(
            [
                {
                    "slug": "garfield-pool",
                    "action": "flag",
                    "blocking": True,
                    "kind": "closure_notice",
                    "reason": "closure_notice",
                    "candidates": [],
                }
            ]
        )
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused == [{"slug": "garfield-pool", "code": "closure_notice_missing"}]


@pytest.mark.parametrize("source_bytes", [None, b"not a PDF"])
def test_closure_flyer_cannot_publish_from_title_alone(iso, monkeypatch, source_bytes):
    from schedules.publish import PublishRefuse, publish_closure_notice

    if source_bytes is None:
        source_bytes = (Path(__file__).parents[1] / "data/garfield-pool/2026-08-20-241f3a02fd75/source.pdf").read_bytes()
    source = iso.data / "source.pdf"
    source.write_bytes(source_bytes)
    monkeypatch.setattr("schedules.publish.fetch_pdf", lambda *args, **kwargs: FetchResult(
        path=source, sha256=hashlib.sha256(source_bytes).hexdigest(), bytes=source_bytes, from_cache=False, page_count=1,
    ))
    _seed_content(iso.content, "garfield-pool")
    before = (iso.content / "garfield-pool.md").read_bytes()
    with pytest.raises(PublishRefuse, match="printed PDF|pdf|PDF") as error:
        publish_closure_notice(slug="garfield-pool", flyer=_flyer(text="Maintenance Closure 8-14_9-8 2026"),
                               content_spots_dir=iso.content, attested_at=date(2026, 8, 20),
                               quarantined_shas=frozenset(), data_root=iso.data)
    assert error.value.code == "source_coverage_failed"
    assert (iso.content / "garfield-pool.md").read_bytes() == before
    assert not list(iso.data.glob("**/reviewed.json"))


def test_closure_two_table_flyers_does_not_fetch(iso, monkeypatch):
    monkeypatch.setattr(
        "schedules.publish.fetch_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_entry("garfield-pool")])
    _seed_content(iso.content, "garfield-pool")
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps(
            [
                _garfield_decision(
                    notices=[_flyer(view_id=29808), _flyer(view_id=29809, text="Other Closure")]
                )
            ]
        )
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "closure_notice_not_unique"


def test_closure_unparseable_title_retains_evidence_for_a_review_pr(iso, monkeypatch):
    source_bytes = (Path(__file__).parents[1] / "data/garfield-pool/2026-08-20-241f3a02fd75/source.pdf").read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    source = iso.data / "garfield-pool" / f"2026-08-20-{digest[:12]}" / "source.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)
    monkeypatch.setattr(
        "schedules.publish.fetch_pdf",
        lambda *_args, **_kwargs: FetchResult(path=source, bytes=source_bytes, sha256=digest, from_cache=False, page_count=1),
    )
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_entry("garfield-pool")])
    _seed_content(iso.content, "garfield-pool")
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_garfield_decision(notices=[_flyer(text="Closed for a while")])])
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "closure_dates_unparsed"
    assert refused[0]["closure_review"]["source_sha256"] == digest
    assert refused[0]["closure_review"]["notices"]
    assert not (iso.content / "garfield-pool.md").read_text().count("temporarily_closed")


def test_carry_hides_candidate_from_publish_pending(iso):
    prior = iso.data / "hamilton-pool" / f"2026-07-02-{('b' * 64)[:12]}"
    prior.mkdir(parents=True)
    (prior / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": "b" * 64,
                "reviewed_at": "2026-07-02",
                "attested_by": "human",
                "carried_from": "data/hamilton-pool/old/reviewed.json",
                "source_pdf_url": "https://example.com/x.pdf",
                "payload": _payload(start="2026-07-02"),
            }
        )
    )
    carried = iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}"
    carried.mkdir(parents=True)
    (carried / "gemini-model.json").write_text(
        json.dumps({"pdf_sha256": SHA, "payload": _payload()})
    )
    (carried / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": SHA,
                "reviewed_at": "2026-07-02",
                "attested_by": "human",
                "carried_from": "data/hamilton-pool/2026-07-02-bbbbbbbbbbbb/reviewed.json",
                "source_pdf_url": "https://example.com/x.pdf",
                "payload": _payload(start="2026-07-02"),
            }
        )
    )
    _seed_content(iso.content, "hamilton-pool")
    before = (iso.content / "hamilton-pool.md").read_bytes()
    assert find_review_candidates(data_root=iso.data) == []
    count, _ = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    assert (iso.content / "hamilton-pool.md").read_bytes() == before


def test_publish_pending_all_eligible_unique_grid(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(iso.data)
    _seed_content(iso.content, "hamilton-pool")
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 1
    envelope = json.loads(
        (iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json").read_text()
    )
    assert envelope["attested_by"] == "ci"
    assert "1 published; pools with refusals: 0; candidate refusals: 0" in report.read_text()


def test_unique_grid_refuses_sibling_session_grids(iso, monkeypatch):
    _write_candidate(
        iso.data,
        slug="sava-pool",
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29815",
    )
    _seed_content(iso.content, "sava-pool")
    monkeypatch.setattr(
        "schedules.publish.load_registry",
        lambda: [
            PoolEntry(
                slug="sava-pool",
                pdf_url="https://sfrecpark.org/DocumentCenter/View/29815",
                official_page_url="https://sfrecpark.org/facilities/facility/details/Sava-Pool-220",
                source_kind="sfrecpark_pdf",
                source_status="published",
            )
        ],
    )
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps(
            [
                {
                    "slug": "sava-pool",
                    "action": "adopt",
                    "blocking": False,
                    "kind": "session_grid",
                    "reason": "operator_adopt",
                    "candidates": [
                        {
                            "view_id": 29815,
                            "kind": "session_grid",
                            "source": "table",
                        },
                        {
                            "view_id": 29805,
                            "kind": "session_grid",
                            "source": "band",
                        },
                    ],
                }
            ]
        )
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "sequential_incomplete"
    assert not (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()


def test_unique_grid_refuses_not_current_pin(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(
        iso.data,
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29799",
    )
    _seed_content(iso.content, "hamilton-pool")
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "not_current_pin"
    assert not (
        iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()


def test_incomplete_source_does_not_write(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(
        iso.data,
        source_verified=False,
    )
    _seed_content(iso.content, "hamilton-pool")
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "source_coverage_failed"
    assert not (iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json").exists()


def test_kill_switch_noops(iso, monkeypatch):
    _write_candidate(iso.data)
    _seed_content(iso.content, "hamilton-pool")
    monkeypatch.setenv("SCHEDULES_AUTO_PROJECT", "false")
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    assert "skipped: kill_switch" in report.read_text()
    assert not (iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json").exists()


def test_cli_mixed_published_and_refused(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(iso.data, slug="hamilton-pool")
    _seed_content(iso.content, "hamilton-pool")
    _write_candidate(iso.data, slug="koret-center")
    _seed_content(iso.content, "koret-center")
    monkeypatch.setattr(
        "schedules.publish.load_registry",
        lambda: [_entry("hamilton-pool"), _entry("koret-center", kind="koret_google_sheet")],
    )
    result = CliRunner().invoke(cli, ["publish-pending"])
    assert result.exit_code == 0, result.output
    assert "1 published; pools with refusals: 1; candidate refusals: 1" in result.output
    payload = json.loads((iso.tmp / "publish-pending.json").read_text())
    assert "hamilton-pool" in payload["published"]
    assert {"slug": "koret-center", "code": "not_rec_park"} in payload["refused"]
    flagged = pager_flagged_set(refused=payload["refused"])
    assert flagged == []


def test_report_distinguishes_pools_from_retained_candidate_refusals(tmp_path):
    from schedules.publish import _write_reports
    report = tmp_path / 'report.md'
    evidence = tmp_path / 'report.json'
    refusals = [{'slug': 'sava-pool', 'code': 'source_coverage_failed', 'message': 'Review source'}] * 3
    _write_reports(report, evidence, published=[], refused=refusals, closure=[], windows=[], skipped=None)
    assert 'pools with refusals: 1; candidate refusals: 3' in report.read_text()
    assert report.read_text().count('- sava-pool:') == 1
    assert len(json.loads(evidence.read_text())['refused']) == 3


def test_pager_flagged_set_omits_not_rec_park():
    flagged = pager_flagged_set(
        refused=[
            {"slug": "koret-center", "code": "not_rec_park"},
            {"slug": "rossi-pool", "code": "closure_dates_unparsed"},
            {"slug": "balboa-pool", "code": "sequential_partial"},
        ],
        blocking=[{"slug": "sava-pool", "reason": "windows_unparsed"}],
    )
    assert flagged == [
        ("balboa-pool", "sequential_partial"),
        ("rossi-pool", "closure_dates_unparsed"),
        ("sava-pool", "windows_unparsed"),
    ]


def test_latest_effective_start_reads_every_window(iso):
    path = _seed_content(
        iso.content,
        "hamilton-pool",
        windows=[("2026-03-17", "2026-06-06"), ("2026-08-18", "2026-12-12")],
    )
    assert latest_effective_start(path) == "2026-08-18"


def _sava_entry() -> PoolEntry:
    return PoolEntry(
        slug="sava-pool",
        pdf_url=SAVA_FALL1,
        official_page_url="https://sfrecpark.org/facilities/facility/details/Sava-Pool-220",
        source_kind="sfrecpark_pdf",
        source_status="published",
    )


def _sava_sequential_decision() -> dict:
    return {
        "slug": "sava-pool",
        "action": "unchanged",
        "blocking": False,
        "kind": "session_grid",
        "reason": "sequential_windows",
        "candidates": [
            {
                "view_id": 29815,
                "href": SAVA_FALL1,
                "kind": "session_grid",
                "source": "table",
                "window_start": "2026-08-18",
                "window_end": "2026-08-28",
            },
            {
                "view_id": 29805,
                "href": SAVA_FALL2,
                "kind": "session_grid",
                "source": "band",
                "window_start": "2026-08-29",
                "window_end": "2026-12-12",
            },
        ],
    }


def test_sequential_sitting_does_not_refuse_not_current_pin(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA,
        payload=_payload(start="2026-08-18", end="2026-08-28"),
        source_pdf_url=SAVA_FALL1,
    )
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=_payload(n=5, start="2026-08-29", end="2026-12-12"),
        source_pdf_url=SAVA_FALL2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "sava-pool")
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_sava_sequential_decision()])
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 1
    payload = json.loads(report.with_name("publish-pending.json").read_text())
    assert payload["published"] == ["sava-pool"]
    assert payload["refused"] == []
    assert {row["view_id"] for row in payload["windows"]} == {29815, 29805}
    assert (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert (
        iso.data / "sava-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    rendered = (iso.content / "sava-pool.md").read_text()
    assert 'effective_start = "2026-08-18"' in rendered
    assert 'effective_start = "2026-08-29"' in rendered


def test_sequential_incomplete_source_writes_nothing(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA,
        payload=_payload(start="2026-08-18", end="2026-08-28"),
        source_pdf_url=SAVA_FALL1,
    )
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=_payload(n=5, start="2026-08-29", end="2026-12-12"),
        source_verified=False,
        source_pdf_url=SAVA_FALL2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "sava-pool")
    before = (iso.content / "sava-pool.md").read_bytes()
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_sava_sequential_decision()])
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "sequential_partial"
    assert "source_coverage_failed" in (refused[0].get("code", "") + report.read_text())
    assert not (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert not (
        iso.data / "sava-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    assert (iso.content / "sava-pool.md").read_bytes() == before


def test_sequential_incomplete_single_extracted(iso, monkeypatch):
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA,
        payload=_payload(start="2026-08-18", end="2026-08-28"),
        source_pdf_url=SAVA_FALL1,
    )
    _seed_content(iso.content, "sava-pool")
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_sava_sequential_decision()])
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "sequential_incomplete"
    assert not (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()


def test_sequential_recovery_publishes_remaining_window(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    attested = iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}"
    attested.mkdir(parents=True)
    (attested / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "sava-pool",
                "pdf_sha256": SHA,
                "reviewed_at": "2026-08-19",
                "attested_by": "ci",
                "source_pdf_url": SAVA_FALL1,
                "payload": _payload(start="2026-08-18", end="2026-08-28"),
            }
        )
    )
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=_payload(n=5, start="2026-08-29", end="2026-12-12"),
        source_pdf_url=SAVA_FALL2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "sava-pool")
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_sava_sequential_decision()])
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 1
    payload = json.loads(report.with_name("publish-pending.json").read_text())
    assert payload["published"] == ["sava-pool"]
    assert payload["windows"][0]["view_id"] == 29805
    assert (
        iso.data / "sava-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()


def test_sequential_overlapping_payload_writes_nothing(iso, monkeypatch):
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA,
        payload=_payload(start="2026-08-18", end="2026-12-12"),
        source_pdf_url=SAVA_FALL1,
    )
    overlap = _payload(n=5, start="2026-08-20", end="2026-12-12")
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=overlap,
        source_pdf_url=SAVA_FALL2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "sava-pool")
    before = (iso.content / "sava-pool.md").read_bytes()
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_sava_sequential_decision()])
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "overlapping_windows"
    assert (iso.content / "sava-pool.md").read_bytes() == before


def test_band_session_grid_flag_does_not_sequential_publish(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    band1 = "https://sfrecpark.org/DocumentCenter/View/29799"
    band2 = "https://sfrecpark.org/DocumentCenter/View/29796"
    _write_candidate(
        iso.data,
        slug="garfield-pool",
        sha=SHA,
        payload=_payload(start="2026-09-08", end="2026-12-12"),
        source_pdf_url=band1,
    )
    _write_candidate(
        iso.data,
        slug="garfield-pool",
        sha=SHA2,
        payload=_payload(n=5, start="2026-08-11", end="2026-08-29"),
        source_pdf_url=band2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "garfield-pool")
    before = (iso.content / "garfield-pool.md").read_bytes()
    monkeypatch.setattr(
        "schedules.publish.load_registry",
        lambda: [
            PoolEntry(
                slug="garfield-pool",
                pdf_url="https://sfrecpark.org/DocumentCenter/View/29564",
                official_page_url="https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214",
                source_kind="sfrecpark_pdf",
                source_status="published",
            )
        ],
    )
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps(
            [
                {
                    "slug": "garfield-pool",
                    "action": "flag",
                    "blocking": True,
                    "kind": "session_grid",
                    "reason": "band_session_grid",
                    "candidates": [
                        {
                            "view_id": 29799,
                            "href": band1,
                            "kind": "session_grid",
                            "source": "band",
                            "window_start": "2026-09-08",
                            "window_end": "2026-12-12",
                        },
                        {
                            "view_id": 29796,
                            "href": band2,
                            "kind": "session_grid",
                            "source": "band",
                            "window_start": "2026-08-11",
                            "window_end": "2026-08-29",
                        },
                    ],
                }
            ]
        )
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert {item["code"] for item in refused} <= {
        "discovery_flagged",
        "sibling_session_grids",
        "sequential_partial",
    }
    assert refused
    assert not (
        iso.data / "garfield-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert not (
        iso.data / "garfield-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    assert (iso.content / "garfield-pool.md").read_bytes() == before


def test_dated_sibling_grids_publish_as_sequential(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA,
        payload=_payload(start="2026-08-18", end="2026-08-28"),
        source_pdf_url=SAVA_FALL1,
    )
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=_payload(n=5, start="2026-08-29", end="2026-12-12"),
        source_pdf_url=SAVA_FALL2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "sava-pool")
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps(
            [
                {
                    "slug": "sava-pool",
                    "action": "adopt",
                    "blocking": False,
                    "kind": "session_grid",
                    "reason": "session_grid",
                    "candidates": [
                        {
                            "view_id": 29815,
                            "href": SAVA_FALL1,
                            "kind": "session_grid",
                            "source": "table",
                            "window_start": "2026-08-18",
                            "window_end": "2026-08-28",
                        },
                        {
                            "view_id": 29805,
                            "href": SAVA_FALL2,
                            "kind": "session_grid",
                            "source": "band",
                            "window_start": "2026-08-29",
                            "window_end": "2026-12-12",
                        },
                    ],
                }
            ]
        )
    )
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 1
    payload = json.loads(report.with_name("publish-pending.json").read_text())
    assert payload["published"] == ["sava-pool"]
    assert payload["refused"] == []
    assert (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert (
        iso.data / "sava-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    rendered = (iso.content / "sava-pool.md").read_text()
    assert 'effective_start = "2026-08-18"' in rendered
    assert 'effective_start = "2026-08-29"' in rendered


@pytest.mark.parametrize("existing_reviews", [False, True])
def test_sequential_second_finalize_rolls_back_window_1(iso, monkeypatch, existing_reviews):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA,
        payload=_payload(start="2026-08-18", end="2026-08-28"),
        source_pdf_url=SAVA_FALL1,
    )
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=_payload(n=5, start="2026-08-29", end="2026-12-12"),
        source_pdf_url=SAVA_FALL2,
        fetch_date="2026-08-20",
    )
    _seed_content(iso.content, "sava-pool")
    candidates = find_review_candidates(data_root=iso.data)
    prior_reviews = {}
    if existing_reviews:
        from schedules.review import draft_envelope
        for candidate in candidates:
            target = candidate.review_dir / "reviewed.json"
            target.write_text(json.dumps(draft_envelope(candidate=candidate, attested_by="ci")))
            prior_reviews[target] = target.read_bytes()
        monkeypatch.setattr("schedules.publish.find_review_candidates", lambda **kwargs: candidates)
        iso.tmp.joinpath("extraction-report-openai.json").write_text(json.dumps({"ready_openai": [
            f"data/{candidate.slug}/{candidate.review_dir.name}/openai-fixture.json" for candidate in candidates]}))
    before = (iso.content / "sava-pool.md").read_bytes()
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    iso.tmp.joinpath("discovery-decisions.json").write_text(
        json.dumps([_sava_sequential_decision()])
    )
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("second window exploded")
        return finalize_draft(**kwargs)

    monkeypatch.setattr("schedules.publish.finalize_draft", flaky)
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "sequential_partial"
    for candidate in candidates:
        target = candidate.review_dir / "reviewed.json"
        if existing_reviews:
            assert target.read_bytes() == prior_reviews[target]
        else:
            assert not target.exists()
    assert (iso.content / "sava-pool.md").read_bytes() == before


def test_drop_to_zero_does_not_write(iso, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 8, 20))
    _write_candidate(iso.data, payload=_payload(n=0, basis="swim_schedule"))
    _seed_content(iso.content, "hamilton-pool", sessions=8)
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "sessions_dropped_to_zero"
    assert not (iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json").exists()


def test_sequential_expired_reexport_is_covered_not_refused(iso, monkeypatch):
    """Sava Fall 1 re-exported at a second View ID after it ended: no refuse,
    no write, sitting stays quiet."""
    attested_dir = iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}"
    attested_dir.mkdir(parents=True)
    (attested_dir / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "sava-pool",
                "pdf_sha256": SHA,
                "reviewed_at": "2026-08-19",
                "attested_by": "ci",
                "source_pdf_url": SAVA_FALL2,
                "payload": _payload(start="2026-08-29", end="2026-12-12"),
            }
        )
    )
    _write_candidate(
        iso.data,
        slug="sava-pool",
        sha=SHA2,
        payload=_payload(n=4, start="2026-08-18", end="2026-08-28"),
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29806",
        fetch_date="2026-09-01",
    )
    _seed_content(
        iso.content,
        "sava-pool",
        windows=[("2026-08-18", "2026-08-28"), ("2026-08-29", "2026-12-12")],
    )
    monkeypatch.setattr("schedules.publish.load_registry", lambda: [_sava_entry()])
    decision = _sava_sequential_decision()
    decision["candidates"][0]["view_id"] = 29806
    decision["candidates"][0]["href"] = "https://sfrecpark.org/DocumentCenter/View/29806"
    decision["candidates"][0]["source"] = "persisted"
    iso.tmp.joinpath("discovery-decisions.json").write_text(json.dumps([decision]))
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 9, 4)
    )
    assert count == 0
    payload = json.loads(report.with_name("publish-pending.json").read_text())
    assert payload["refused"] == []
    assert not (
        iso.data / "sava-pool" / f"2026-09-01-{SHA2[:12]}" / "reviewed.json"
    ).exists()



def _frozen_pool_bundle(tmp_path, north_beach_pair):
    from schedules.artifacts import save_pool_bundle
    from schedules.paths import PROMPT_PATH, slugify
    entry, components = north_beach_pair
    paths = []
    for component in components:
        artifact = component["artifact"]
        directory = tmp_path / "data" / entry.slug / ("2026-09-06-" + artifact["pdf_sha256"][:12])
        directory.mkdir(parents=True)
        (directory / "source.pdf").write_bytes(component["document"])
        path = directory / ("openai-" + slugify(artifact["model"]) + ".json")
        path.write_text(json.dumps(artifact))
        paths.append(path)
    bundle = save_pool_bundle(entry.slug, paths, PROMPT_PATH.read_text().strip())
    candidate = next(item for item in find_review_candidates(data_root=tmp_path / "data") if item.bundle_sha256)
    return entry, components, paths, bundle, candidate


def test_pair_bundle_preserves_identity_and_simultaneous_sessions(tmp_path, north_beach_pair):
    from schedules.artifacts import verify_pool_bundle, pool_bundle_identity
    from schedules.paths import PROMPT_PATH
    from schedules.review import draft_envelope
    from schedules.envelope import validate_envelope
    entry, components, paths, bundle, candidate = _frozen_pool_bundle(tmp_path, north_beach_pair)
    artifact = json.loads(bundle.read_text())
    assert verify_pool_bundle(artifact, bundle.parent, PROMPT_PATH.read_text())["ok"]
    envelope = draft_envelope(candidate=candidate)
    validate_envelope(envelope)
    assert "pdf_sha256" not in envelope and "source_pdf_url" not in envelope
    assert len(envelope["payload"]["sessions"]) == 35
    for closure in envelope["payload"]["closures"]:
        assert closure["reason_code"]
        assert {notice["source_sha256"] for notice in closure["source_notices"]} == {member["artifact"]["pdf_sha256"] for member in components}
    simultaneous = [row for row in envelope["payload"]["sessions"] if row["day"] == "thursday" and row["start"] == "14:15"]
    assert {row["physical_pool"] for row in simultaneous} == {"cool", "warm"}
    assert len({row["source_sha256"] for row in simultaneous}) == 2
    assert all(row["source_cell"].startswith("p1-") for row in simultaneous)
    assert not validate(envelope["payload"] | {"sessions": envelope["payload"]["sessions"] + simultaneous[:1]}).ok
    modified = [dict(item) for item in artifact["source_bundle"]]
    modified[1]["sha256"] = "0" * 64
    assert pool_bundle_identity(modified) != candidate.bundle_sha256


@pytest.mark.parametrize("member", [0, 1])
def test_pair_bundle_reverifies_every_original(tmp_path, north_beach_pair, member):
    from schedules.artifacts import verify_pool_bundle
    from schedules.paths import PROMPT_PATH
    _, _, paths, bundle, _ = _frozen_pool_bundle(tmp_path, north_beach_pair)
    (paths[member].parent / "source.pdf").write_bytes(b"broken")
    with pytest.raises(Exception):
        verify_pool_bundle(json.loads(bundle.read_text()), bundle.parent, PROMPT_PATH.read_text())


def test_pair_publish_is_atomic_and_requires_current_discovery(tmp_path, north_beach_pair, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 9, 6))
    from schedules import publish, discover
    from schedules.review import DecisionSet
    entry, components, paths, bundle, candidate = _frozen_pool_bundle(tmp_path, north_beach_pair)
    content = tmp_path / "content"
    content.mkdir()
    original = Path("content/spots/north-beach-pool.md").read_bytes()
    md = content / (entry.slug + ".md")
    md.write_bytes(original)
    monkeypatch.setattr(discover, "pacific_today", lambda: date(2026, 9, 6))
    documents = [discover.classify_pdf(discover.DocumentLink(29953 + index, part["artifact"]["source_pdf_url"], "Fall"), pool_slug=entry.slug, pdf_bytes=part["document"], filename=None) for index, part in enumerate(components)]
    decision = discover._decision_to_json(discover.choose_roll(entry, documents))
    arguments = dict(candidate=candidate, entries={entry.slug: entry}, blocking_slugs=frozenset(), quarantined_shas=frozenset(), content_spots_dir=content, attested_at=date(2026, 9, 6), decisions=DecisionSet.from_items([decision]))
    finalize = publish.finalize_draft
    def fail(**kwargs):
        md.write_text("partial")
        raise FinalizeError("injected failure")
    monkeypatch.setattr(publish, "finalize_draft", fail)
    with pytest.raises(FinalizeError):
        publish._publish_unique_grid(**arguments)
    assert md.read_bytes() == original and not (bundle.parent / "reviewed.json").exists()
    monkeypatch.setattr(publish, "finalize_draft", finalize)
    with pytest.raises(publish.PublishRefuse):
        publish._publish_unique_grid(**(arguments | {"decisions": DecisionSet.from_items([])}))
    with pytest.raises(publish.PublishRefuse, match="expired"):
        publish._publish_unique_grid(**(arguments | {"attested_at": date(2026, 12, 13)}))
    publish._publish_unique_grid(**arguments)
    assert (bundle.parent / "reviewed.json").exists()
    assert 'physical_pool = "cool"' in md.read_text() and 'physical_pool = "warm"' in md.read_text()
    assert '2026-12-12' in md.read_text()



@pytest.mark.parametrize("damage", ["missing_sources", "invalid_json", "wrong_identity"])
def test_malformed_pair_refuses_before_content_write(tmp_path, north_beach_pair, damage):
    from schedules import publish
    from schedules.review import DecisionSet
    entry, _, _, bundle, candidate = _frozen_pool_bundle(tmp_path, north_beach_pair)
    artifact = json.loads(bundle.read_text())
    if damage == "missing_sources":
        del artifact["source_bundle"]
    elif damage == "wrong_identity":
        artifact["bundle_sha256"] = "0" * 64
    bundle.write_text("{" if damage == "invalid_json" else json.dumps(artifact))
    content = tmp_path / "content"
    content.mkdir()
    md = content / (entry.slug + ".md")
    original = Path("content/spots/north-beach-pool.md").read_bytes()
    md.write_bytes(original)
    with pytest.raises(publish.PublishRefuse):
        publish._publish_unique_grid(
            candidate=candidate, entries={entry.slug: entry}, blocking_slugs=frozenset(),
            quarantined_shas=frozenset(), content_spots_dir=content,
            attested_at=date(2026, 9, 6), decisions=DecisionSet.from_items([]),
        )
    assert md.read_bytes() == original
    assert not (bundle.parent / "reviewed.json").exists()


def test_pair_review_opens_both_originals_and_saves_one_bundle(tmp_path, north_beach_pair, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 9, 6))
    from schedules import review_server
    from schedules.review_server import ReviewApp
    from schedules.review import draft_envelope
    entry, _, _, bundle, candidate = _frozen_pool_bundle(tmp_path, north_beach_pair)
    content = tmp_path / "content"
    content.mkdir()
    (content / (entry.slug + ".md")).write_bytes(Path("content/spots/north-beach-pool.md").read_bytes())
    monkeypatch.setattr(review_server, "load_registry", lambda: [entry])
    app = ReviewApp(data_root=tmp_path / "data", content_spots_dir=content, tmp_dir=tmp_path / "tmp")
    assert [item.source_identity for item in app.candidates()] == [candidate.bundle_sha256]
    monkeypatch.setattr(review_server, "current_source_identity", lambda *args, **kwargs: candidate.bundle_sha256)
    assert app.check_source(entry.slug)["status"] == "current"
    envelope = draft_envelope(candidate=candidate)
    assert len(app.review(entry.slug)["envelope"]["source_bundle"]) == 2
    app.save(entry.slug, envelope, candidate.bundle_sha256)
    assert json.loads((bundle.parent / "reviewed.json").read_text())["attested_by"] == "human"
    assert not app.candidates()


def test_failed_pair_sitting_cannot_publish_an_older_pending_bundle(tmp_path, north_beach_pair, monkeypatch):
    from schedules import publish
    entry, _, _, bundle, _ = _frozen_pool_bundle(tmp_path, north_beach_pair)
    content = tmp_path / "content"
    content.mkdir()
    md = content / (entry.slug + ".md")
    original = Path("content/spots/north-beach-pool.md").read_bytes()
    md.write_bytes(original)
    report = tmp_path / "tmp"
    report.mkdir()
    (report / "extraction-report-openai.json").write_text('{"pool_bundles": {}}')
    monkeypatch.setattr(publish, "load_registry", lambda: [entry])
    monkeypatch.setattr(publish, "TMP_DIR", report)
    monkeypatch.setattr(publish, "auto_project_enabled", lambda: True)
    count, _ = publish.publish_pending_all(data_root=tmp_path / "data", content_spots_dir=content, today=date(2026, 9, 6))
    assert count == 0 and md.read_bytes() == original and not (bundle.parent / "reviewed.json").exists()
    assert json.loads((report / "publish-pending.json").read_text())["refused"][0]["code"] == "paired_extraction_incomplete"


def test_pair_review_refresh_reuses_valid_components(tmp_path, north_beach_pair, monkeypatch):
    from schedules import review_server
    entry, _, _, _, candidate = _frozen_pool_bundle(tmp_path, north_beach_pair)
    monkeypatch.setattr(review_server, "load_registry", lambda: [entry])
    monkeypatch.setattr(review_server, "current_source_identity", lambda *args, **kwargs: "0" * 64)
    commands = []
    def run(command):
        commands.append(command)
        return 1, None, ["stopped before model call"]
    monkeypatch.setattr(review_server, "run_pipeline", run)
    app = review_server.ReviewApp(data_root=tmp_path / "data", tmp_dir=tmp_path / "tmp")
    with pytest.raises(RuntimeError, match="stopped before model call"):
        app.refresh(entry.slug, candidate.source_identity[:12])
    assert commands[0].provider == "openai"
    assert commands[0].force is False


@pytest.mark.parametrize("component", ["python", "httpx", "openpyxl"])
def test_pomeroy_acceptance_rejects_runtime_or_library_change(tmp_path, monkeypatch, component):
    import schedules.direct_sources as direct
    candidate, artifact, _ = _pomeroy_candidate(tmp_path, monkeypatch)
    assert _pomeroy_eligible(candidate, artifact, direct_opt_in=True, today=date(2026, 9, 7)).ok
    if component == "python":
        monkeypatch.setattr(direct.platform, "python_version", lambda: "99.0.0")
    else:
        original_version = direct.version
        monkeypatch.setattr(direct, "version", lambda name: "99.0.0" if name == component else original_version(name))
    assert not _pomeroy_eligible(candidate, artifact, direct_opt_in=True, today=date(2026, 9, 7)).ok
    assert artifact["details"]["direct_source"]["configuration"] != direct.direct_configuration()


def test_unchanged_direct_extraction_retains_ready_artifact_receipt(tmp_path, monkeypatch):
    import schedules.pipeline as pipeline
    from schedules.direct_sources import DirectExtraction, DirectFetchResult
    from schedules.models import Unchanged
    from schedules.review import draft_envelope
    from schedules.report import write_report

    candidate, artifact, artifact_file = _pomeroy_candidate(tmp_path, monkeypatch)
    reviewed = draft_envelope(candidate=candidate, today=date(2026, 9, 7), attested_by="ci")
    reviewed_file = candidate.review_dir / "reviewed.json"
    reviewed_file.write_text(json.dumps(reviewed))
    extraction = DirectExtraction(
        fetch_result=DirectFetchResult(candidate.source_path, artifact["pdf_sha256"], True, artifact["source_pdf_url"]),
        payload=artifact["payload"], model=artifact["model"], notes=[],
        source=artifact["details"]["direct_source"],
    )
    monkeypatch.setattr(pipeline, "extract_direct", lambda entry: extraction)
    monkeypatch.setattr(pipeline, "reviewed_path", lambda *args: reviewed_file)
    monkeypatch.setattr(pipeline, "artifact_path", lambda *args: artifact_file)
    monkeypatch.setattr(pipeline, "relative_to_repo", lambda path: str(path.relative_to(tmp_path)))
    entry = PoolEntry("pomeroy-pool", artifact["source_pdf_url"], "https://www.prrcsf.org/pool", source_kind="pomeroy_html", auto_publish=True)
    result = pipeline._process_direct_entry(entry, artifact["payload"], policy=pipeline.ReusePolicy(True, True, True))
    assert isinstance(result, Unchanged)
    assert result.provider == "direct"
    assert result.model == "pomeroy-html-v1"
    assert result.artifact_paths["reviewed-snapshot"] == str(reviewed_file)
    report = tmp_path / "extraction-report-direct.md"
    write_report([result], report)
    receipt = json.loads(report.with_suffix(".json").read_text())
    assert receipt["ready_direct"] == {"pomeroy-pool": str(artifact_file.relative_to(tmp_path))}
    assert json.loads(reviewed_file.read_text()) == reviewed


def _browser_html_candidate(tmp_path, monkeypatch, slug="stonestown-ymca"):
    from schedules.registry import APPROVED_DIRECT_SOURCES
    import schedules.direct_sources as direct
    candidate, artifact, path = _pomeroy_candidate(tmp_path, monkeypatch)
    new_dir = tmp_path / "data" / slug / candidate.review_dir.name
    new_dir.parent.mkdir()
    candidate.review_dir.rename(new_dir)
    kind, url = APPROVED_DIRECT_SOURCES[slug]
    artifact.update(provider="direct", model="browser-html", source_pdf_url=url)
    artifact["details"]["direct_source"].update(url=url, requested_url=url)
    artifact["payload"] = _payload(n=0, start="2026-09-07", end="2026-09-20", basis="facility_hours")
    artifact["payload"]["access_hours"] = [{"day": day, "start": "07:00", "end": "18:00", "label": "Facility hours"} for day in DAYS]
    (new_dir / path.name).unlink()
    path = new_dir / "direct-browser-html.json"
    path.write_text(json.dumps(artifact))
    monkeypatch.setattr(direct, "verify_direct_artifact", lambda *args, **kwargs: {"ok": True, "issues": []})
    candidate = find_review_candidates(data_root=tmp_path / "data")[0]
    return candidate, artifact, path, kind, url


def _browser_html_eligible(candidate, artifact, kind, url, **overrides):
    options = dict(candidate=candidate, payload=artifact["payload"], prior_sessions_count=16,
                   latest_effective_start="2026-05-17", source_kind=kind,
                   source_status="access_hours_only", blocking_slugs=frozenset(), quarantined_shas=frozenset(),
                   has_prior_schedule_window=True, source_pdf_path=candidate.source_path,
                   pin_url=url, direct_opt_in=True, today=date(2026, 9, 7))
    return publish_eligible(**(options | overrides))


@pytest.mark.parametrize("slug", ["stonestown-ymca", "embarcadero-ymca", "chinatown-ymca", "presidio-ymca-letterman", "sfsu-mashouf"])
def test_verified_browser_access_hours_can_replace_sessions_only_for_approved_sources(tmp_path, monkeypatch, slug):
    candidate, artifact, _, kind, url = _browser_html_candidate(tmp_path, monkeypatch, slug)
    assert _browser_html_eligible(candidate, artifact, kind, url).ok
    assert not _browser_html_eligible(candidate, artifact, kind, url, direct_opt_in=False).ok
    assert not _browser_html_eligible(candidate, artifact, kind, url, pin_url=url + "?changed=1").ok
    assert _browser_html_eligible(candidate, artifact, kind, url, source_status="published").code == "sessions_dropped_to_zero"
    import schedules.direct_sources as direct
    monkeypatch.setattr(direct, "verify_direct_artifact", lambda *args, **kwargs: {"ok": False, "issues": ["Source configuration or facts differ"]})
    assert _browser_html_eligible(candidate, artifact, kind, url).code == "source_coverage_failed"


def test_jccsf_cannot_silently_become_access_hours(tmp_path, monkeypatch):
    candidate, artifact, _, kind, url = _browser_html_candidate(tmp_path, monkeypatch, "jccsf")
    assert _browser_html_eligible(candidate, artifact, kind, url).code == "sessions_dropped_to_zero"


@pytest.mark.parametrize("ready", [False, True])
def test_browser_html_refresh_uses_current_direct_receipt_and_preserves_provenance(tmp_path, monkeypatch, ready):
    pin_publish_clock(monkeypatch, date(2026, 9, 7))
    import schedules.publish as module
    from schedules.review import draft_envelope
    candidate, artifact, path, kind, url = _browser_html_candidate(tmp_path, monkeypatch)
    reviewed = draft_envelope(candidate=candidate, today=date(2026, 9, 7), attested_by="ci")
    assert reviewed["direct_source"] == artifact["details"]["direct_source"]
    (candidate.review_dir / "reviewed.json").write_text(json.dumps(reviewed))
    assert find_review_candidates(data_root=tmp_path / "data") == []
    artifact["details"]["direct_source"]["configuration"] = {"changed": True}
    path.write_text(json.dumps(artifact))
    assert len(find_review_candidates(data_root=tmp_path / "data")) == 1
    content = tmp_path / "content"
    content.mkdir()
    _seed_content(content, candidate.slug)
    reports = tmp_path / "tmp"
    reports.mkdir()
    monkeypatch.setattr(module, "TMP_DIR", reports)
    monkeypatch.setattr(module, "auto_project_enabled", lambda: True)
    monkeypatch.setattr(module, "load_quarantine", lambda: frozenset())
    entry = PoolEntry(candidate.slug, url, url, source_kind=kind, source_status="access_hours_only", auto_publish=True)
    monkeypatch.setattr(module, "load_registry", lambda: [entry])
    (reports / "extraction-report-direct.json").write_text(json.dumps({"ready_direct": {
        candidate.slug: f"data/{candidate.slug}/{candidate.review_dir.name}/{path.name}"
    } if ready else {}}))
    count, _ = publish_pending_all(data_root=tmp_path / "data", content_spots_dir=content, today=date(2026, 9, 7))
    assert count == int(ready)
    report = json.loads((reports / "publish-pending.json").read_text())
    assert {row["code"] for row in report["refused"]} == (set() if ready else {"direct_extraction_incomplete"})
    current = json.loads((candidate.review_dir / "reviewed.json").read_text())
    assert current["direct_source"] == (artifact["details"]["direct_source"] if ready else reviewed["direct_source"])


def test_access_transition_finalize_requires_independent_evidence(tmp_path, monkeypatch):
    pin_publish_clock(monkeypatch, date(2026, 9, 7))
    from schedules.review import draft_envelope
    import schedules.direct_sources as direct
    candidate, artifact, _, _, _ = _browser_html_candidate(tmp_path, monkeypatch)
    reviewed = draft_envelope(candidate=candidate, today=date(2026, 9, 7), attested_by="ci")
    target = candidate.review_dir / "reviewed.json"
    target.write_text(json.dumps(reviewed))
    content = tmp_path / "content"
    content.mkdir()
    _seed_content(content, candidate.slug)
    before = (content / f"{candidate.slug}.md").read_bytes()
    monkeypatch.setattr(direct, "verify_direct_artifact", lambda *args, **kwargs: {"ok": False, "issues": ["Unverified source"]})
    with pytest.raises(FinalizeError):
        finalize_draft(reviewed_json_path=target, content_spots_dir=content)
    assert (content / f"{candidate.slug}.md").read_bytes() == before


@pytest.mark.parametrize('existing_review', [False, True])
def test_invalid_closure_projection_rolls_back_candidate_and_reports_finalize_error(tmp_path, monkeypatch, existing_review):
    pin_publish_clock(monkeypatch, date(2026, 9, 7))
    candidate, artifact, path = _pomeroy_candidate(tmp_path, monkeypatch)
    artifact['payload']['closures'][0].pop('reason_code', None)
    path.write_text(json.dumps(artifact))
    candidate = find_review_candidates(data_root=tmp_path / 'data')[0]
    content = tmp_path / 'content'
    content.mkdir()
    _seed_content(content, candidate.slug)
    content_path = content / f'{candidate.slug}.md'
    content_before = content_path.read_bytes()
    reviewed_path = candidate.review_dir / 'reviewed.json'
    if existing_review:
        reviewed_path.write_text('{"prior": "review"}\n')
    with pytest.raises(FinalizeError, match='reviewed reason_code'):
        publish_candidate(candidate=candidate, content_spots_dir=content,
                          attested_at=date(2026, 9, 7), eligibility=Eligibility(ok=True, code=None))
    assert content_path.read_bytes() == content_before
    if existing_review:
        assert reviewed_path.read_text() == '{"prior": "review"}\n'
    else:
        assert not reviewed_path.exists()


@pytest.mark.parametrize('valid_original', [False, True])
def test_expired_grid_without_extraction_is_covered_only_by_verified_original(iso, monkeypatch, valid_original):
    source = Path(__file__).parents[1] / 'data/sava-pool/2026-09-01-4d9a6f5e805d/source.pdf'
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    expired_dir = iso.data / 'sava-pool' / f'2026-09-01-{digest[:12]}'
    expired_dir.mkdir(parents=True)
    (expired_dir / 'source.pdf').write_bytes(content if valid_original else b'changed bytes')
    attested_dir = iso.data / 'sava-pool' / f'2026-08-29-{SHA[:12]}'
    attested_dir.mkdir()
    (attested_dir / 'reviewed.json').write_text(json.dumps({
        'slug': 'sava-pool', 'pdf_sha256': SHA, 'reviewed_at': '2026-08-29', 'attested_by': 'human',
        'source_pdf_url': SAVA_FALL2, 'payload': _payload(start='2026-08-29', end='2026-12-12')}))
    _seed_content(iso.content, 'sava-pool')
    monkeypatch.setattr('schedules.publish.load_registry', lambda: [_sava_entry()])
    decision = _sava_sequential_decision()
    decision['candidates'][0].update(view_id=29806, href='https://sfrecpark.org/DocumentCenter/View/29806',
        source='persisted', window_start='2026-08-18', window_end='2026-08-28',
        window_source='page-1', grid_confirmed=True, pdf_sha256=digest)
    (iso.tmp / 'discovery-decisions.json').write_text(json.dumps([decision]))
    count, report = publish_pending_all(data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 9, 9))
    assert count == 0
    refused = json.loads(report.with_name('publish-pending.json').read_text())['refused']
    assert bool(refused) is not valid_original
    if refused:
        assert refused[0]['code'] == 'sequential_incomplete'
    assert not (expired_dir / 'reviewed.json').exists()


def _ucsf_candidate(tmp_path, slug="ucsf-bakar", observed=date(2026, 12, 24)):
    from schedules.direct_sources import direct_configuration
    from schedules.direct_sources.providers.ucsf import _extract_ucsf_bakar, _extract_ucsf_fitness
    from schedules.registry import UCSF_SOURCES
    content = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    directory = tmp_path / "data" / slug / f"{observed}-{digest[:12]}"
    directory.mkdir(parents=True)
    (directory / "source.html").write_bytes(content)
    (directory / "source.sha256").write_text(digest + "\n")
    kind, url = UCSF_SOURCES[slug]
    extractor = _extract_ucsf_bakar if slug == "ucsf-bakar" else _extract_ucsf_fitness
    model = "ucsf-bakar-html-v1" if slug == "ucsf-bakar" else "ucsf-fitness-html-v1"
    artifact = {"provider": "direct", "model": model, "pdf_sha256": digest, "source_pdf_url": url,
                "payload": extractor(content.decode(), observed), "details": {"direct_source": {
                    "sha256": digest, "url": url, "requested_url": url, "observed_on": observed.isoformat(),
                    "freshness_days": 14, "configuration": direct_configuration()}}}
    path = directory / f"direct-{model}.json"
    path.write_text(json.dumps(artifact))
    return find_review_candidates(data_root=tmp_path / "data")[0], artifact, path, kind, url


@pytest.mark.parametrize("slug", ["ucsf-bakar", "ucsf-millberry"])
def test_ucsf_publication_recomputes_holidays_and_caps_printed_year(tmp_path, slug):
    candidate, artifact, _, kind, url = _ucsf_candidate(tmp_path, slug)
    assert _browser_html_eligible(candidate, artifact, kind, url, today=date(2026, 12, 24)).ok
    assert _browser_html_eligible(candidate, artifact, kind, url, today=date(2027, 1, 1)).ok
    assert not _browser_html_eligible(candidate, artifact, kind, url, today=date(2027, 1, 2)).ok
    assert not _browser_html_eligible(candidate, artifact, kind, url, today=date(2026, 12, 24), direct_opt_in=False).ok
    assert artifact["payload"]["schedule_basis"] == "facility_hours"
    assert artifact["payload"]["sessions"] == []


@pytest.mark.parametrize("change", ["hours", "closures", "exceptions", "hash", "url", "configuration", "facility", "window"])
def test_ucsf_tampered_candidate_cannot_publish(tmp_path, change):
    candidate, artifact, path, kind, url = _ucsf_candidate(tmp_path)
    if change == "hours":
        artifact["payload"]["access_hours"][0]["end"] = "22:00"
    elif change in {"closures", "exceptions"}:
        artifact["payload"]["closures" if change == "closures" else "access_exceptions"] = []
    elif change == "hash":
        candidate.source_path.write_bytes(b"changed original")
    elif change == "url":
        artifact["details"]["direct_source"]["url"] += "?wrong"
    elif change == "configuration":
        artifact["details"]["direct_source"]["configuration"] = {}
    elif change == "facility":
        artifact["model"] = "ucsf-fitness-html-v1"
    else:
        artifact["payload"]["effective_end"] = "2027-01-06"
    path.write_text(json.dumps(artifact))
    assert not _browser_html_eligible(candidate, artifact, kind, url, today=date(2026, 12, 24)).ok


@pytest.mark.parametrize("notice", ["Millberry pool closed for maintenance", "Bakar modified hours 10:00 am-2:00 pm"])
def test_ucsf_closure_notice_outside_calendar_holds(notice):
    from schedules.direct_sources.providers.ucsf import _extract_ucsf_bakar
    from schedules.direct_sources.errors import DirectSourceError
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    with pytest.raises(DirectSourceError, match="outside the calendar"):
        _extract_ucsf_bakar(html.replace("<article", f"<p>{notice}</p><article", 1), date(2026, 9, 9))


def test_ucsf_partial_day_extension_outside_regular_hours_holds():
    from schedules.direct_sources.providers.ucsf import _extract_ucsf_fitness
    from schedules.direct_sources.errors import DirectSourceError
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    with pytest.raises(DirectSourceError, match="exceed regular"):
        _extract_ucsf_fitness(html.replace("December 26-31 (Winter Holiday): 8:00 am-2:00 pm", "December 26-31 (Winter Holiday): 8:00 am-5:00 pm"), date(2026, 12, 24))


def test_ucsf_extraction_retains_original_notice_for_existing_closure_review(tmp_path, monkeypatch):
    from schedules import direct_sources, paths
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.direct_sources.errors import CapturedClosureReviewRequired
    from schedules.registry import load_registry
    entry = next(entry for entry in load_registry() if entry.slug == "ucsf-bakar")
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    html = html.replace("<article", "<p>Bakar pool closed for maintenance</p><article", 1)
    monkeypatch.setattr(direct_sources, "fetch_text", lambda url: DirectTextResponse(html, html.encode(), url))
    monkeypatch.setattr(paths, "relative_to_repo", lambda path: str(path.relative_to(tmp_path)))
    with pytest.raises(CapturedClosureReviewRequired) as failure:
        direct_sources.extract_direct(entry, cache_root=tmp_path / "data")
    review = failure.value.review
    original = tmp_path / review["source_path"]
    assert original.read_bytes() == html.encode()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == review["source_sha256"]
    assert "Bakar pool closed for maintenance" in review["notices"][0]["text"]
    assert review["slug"] == entry.slug


@pytest.mark.parametrize("slug", ["fitness-sf-fillmore", "city-sports-20th-ave", "equinox-sports-club-sf", "bay-club-gateway"])
@pytest.mark.parametrize("change", [None, "hours", "original", "url", "configuration", "expired"])
def test_verified_club_source_publication_checks_original_hours_and_freshness(tmp_path, slug, change):
    from schedules.direct_sources import _HTML_EXTRACTORS, direct_configuration, observation_window
    from schedules.registry import HTTP_ACCESS_SOURCES
    kind, url = HTTP_ACCESS_SOURCES[slug]
    extractor, model, _ = _HTML_EXTRACTORS[kind]
    content = (Path(__file__).parent / f"fixtures/html-facts/{slug}.html").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    directory = tmp_path / "data" / slug / f"2026-09-09-{digest[:12]}"
    directory.mkdir(parents=True)
    original = directory / "source.html"
    original.write_bytes(content)
    (directory / "source.sha256").write_text(digest + "\n")
    artifact = {"provider": "direct", "model": model, "pdf_sha256": digest, "source_pdf_url": url,
                "payload": observation_window(extractor(content.decode()), "2026-09-09"), "details": {"direct_source": {
                    "sha256": digest, "url": url, "requested_url": url, "observed_on": "2026-09-09",
                    "freshness_days": 14, "configuration": direct_configuration()}}}
    if change == "hours":
        artifact["payload"]["access_hours"][0]["start"] = "01:00"
    elif change == "original":
        original.write_bytes(b"wrong capture")
    elif change == "url":
        artifact["details"]["direct_source"]["url"] += "&wrong=1"
    elif change == "configuration":
        artifact["details"]["direct_source"]["configuration"] = {}
    (directory / f"direct-{model}.json").write_text(json.dumps(artifact))
    candidate = find_review_candidates(data_root=tmp_path / "data")[0]
    result = _browser_html_eligible(candidate, artifact, kind, url,
                                   today=date(2026, 9, 23) if change == "expired" else date(2026, 9, 9))
    assert result.ok == (change is None)
    assert artifact["payload"]["sessions"] == []


@pytest.mark.parametrize("slug", ["equinox-sports-club-sf", "bay-club-gateway"])
def test_new_club_closure_holds_retain_original_for_review(tmp_path, monkeypatch, slug):
    from schedules import direct_sources, paths
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.direct_sources.errors import CapturedClosureReviewRequired
    from schedules.registry import load_registry
    entry = next(entry for entry in load_registry() if entry.slug == slug)
    html = (Path(__file__).parent / f"fixtures/html-facts/{slug}.html").read_text()
    html += "<p>Facility closed until further notice</p>"
    monkeypatch.setattr(direct_sources, "fetch_text", lambda url: DirectTextResponse(html, html.encode(), url))
    monkeypatch.setattr(paths, "relative_to_repo", lambda path: str(path.relative_to(tmp_path)))
    with pytest.raises(CapturedClosureReviewRequired) as failure:
        direct_sources.extract_direct(entry, cache_root=tmp_path / "data")
    review = failure.value.review
    assert (tmp_path / review["source_path"]).read_bytes() == html.encode()
    assert review["source_sha256"] == hashlib.sha256(html.encode()).hexdigest()
    assert any("closed until further notice" in notice["text"] for notice in review["notices"])
