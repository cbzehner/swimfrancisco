from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.fetch import FetchResult
from schedules.models import GroundingResult, PoolEntry
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

SHA = "a" * 64
SHA2 = "b" * 64
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
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


def _grounding(grounded: int, total: int) -> GroundingResult:
    return GroundingResult(sessions=[], grounded_count=grounded, total=total)


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
    grounding: dict | None | object = Ellipsis,
    source_pdf: bool = True,
    fetch_date: str = "2026-08-19",
    source_pdf_url: str = "https://sfrecpark.org/DocumentCenter/View/29800",
) -> ReviewCandidate:
    payload = payload if payload is not None else _payload()
    review_dir = data / slug / f"{fetch_date}-{sha[:12]}"
    review_dir.mkdir(parents=True, exist_ok=True)
    artifact: dict = {
        "pdf_sha256": sha,
        "source_pdf_url": source_pdf_url,
        "payload": payload,
    }
    if grounding is Ellipsis:
        n = len(payload.get("sessions") or [])
        artifact["grounding"] = {"grounded_count": n, "total": n, "ratio": 1.0}
    elif grounding is not None:
        artifact["grounding"] = grounding
    (review_dir / "gemini-model.json").write_text(json.dumps(artifact))
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
    payload = json.loads((candidate.review_dir / "gemini-model.json").read_text())["payload"]
    defaults = {
        "candidate": candidate,
        "payload": payload,
        "grounding": _grounding(5, 5),
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
    return SimpleNamespace(data=data, content=content, tmp=tmp)


def test_unique_grid_eligible(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate))
    assert result.ok is True
    assert result.code is None


def test_grounding_0_89_refuses(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate, grounding=_grounding(89, 100)))
    assert result.ok is False
    assert result.code == "grounding_coverage_low"


def test_grounding_0_90_eligible(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate, grounding=_grounding(90, 100)))
    assert result.ok is True


def test_grounding_total_zero_eligible(iso):
    candidate = _write_candidate(iso.data, payload=_payload(n=0, basis="temporarily_closed"))
    result = publish_eligible(
        **_kwargs(
            candidate,
            payload=_payload(n=0, basis="temporarily_closed"),
            grounding=_grounding(0, 0),
        )
    )
    assert result.ok is True


def test_missing_grounding_refuses(iso):
    candidate = _write_candidate(iso.data)
    result = publish_eligible(**_kwargs(candidate, grounding=None))
    assert result.code == "grounding_unavailable"


def test_drop_to_zero_catastrophic_unless_temporarily_closed(iso):
    candidate = _write_candidate(iso.data)
    empty = {**_payload(n=0), "schedule_basis": "swim_schedule"}
    closed = {**_payload(n=0), "schedule_basis": "temporarily_closed"}
    dropped = publish_eligible(**_kwargs(candidate, payload=empty, prior_sessions_count=8))
    assert dropped.code == "sessions_dropped_to_zero"
    assert validate(empty, prior_sessions_count=8).catastrophic is True
    allowed = publish_eligible(
        **_kwargs(candidate, payload=closed, prior_sessions_count=8, grounding=_grounding(0, 0))
    )
    assert allowed.ok is True


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


def test_human_finalize_allows_quarantined_sha(iso):
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
    candidate = _write_candidate(iso.data)
    payload = _payload(start="2026-04-01")
    result = publish_eligible(
        **_kwargs(candidate, payload=payload, latest_effective_start="2026-08-18")
    )
    assert result.code == "effective_start_regressed"


def test_session_count_shift_is_eligible(iso):
    candidate = _write_candidate(iso.data)
    payload = _payload(n=7)
    result = publish_eligible(
        **_kwargs(candidate, payload=payload, prior_sessions_count=5, grounding=_grounding(7, 7))
    )
    assert result.ok is True


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


def test_publish_candidate_writes_ci_attestation(iso):
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


def test_second_run_has_no_candidate(iso):
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


def test_closure_window_from_anchor_text(iso, monkeypatch):
    flyer_sha = "c" * 64
    flyer_dir = iso.data / "garfield-pool" / f"2026-08-20-{flyer_sha[:12]}"
    flyer_dir.mkdir(parents=True)
    source = flyer_dir / "source.pdf"
    source.write_bytes(b"%PDF-flyer\n")
    fetched_urls: list[str] = []

    def fake_fetch(slug, url, **_kwargs):
        fetched_urls.append(url)
        return FetchResult(
            path=source, sha256=flyer_sha, bytes=b"%PDF-flyer\n", from_cache=False, page_count=1
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


def test_closure_unparseable_title_does_not_fetch(iso, monkeypatch):
    monkeypatch.setattr(
        "schedules.publish.fetch_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
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
        json.dumps({"pdf_sha256": SHA, "payload": _payload(), "grounding": {"total": 5, "grounded_count": 5}})
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


def test_publish_pending_all_eligible_unique_grid(iso):
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
    assert "1 published, 0 refused" in report.read_text()


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
    assert refused[0]["code"] == "sibling_session_grids"
    assert not (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()


def test_unique_grid_refuses_not_current_pin(iso):
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


def test_grounding_0_89_does_not_write(iso):
    _write_candidate(
        iso.data,
        grounding={"grounded_count": 89, "total": 100, "ratio": 0.89},
    )
    _seed_content(iso.content, "hamilton-pool")
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "grounding_coverage_low"
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
    assert "1 published, 1 refused" in result.output
    payload = json.loads((iso.tmp / "publish-pending.json").read_text())
    assert "hamilton-pool" in payload["published"]
    assert {"slug": "koret-center", "code": "not_rec_park"} in payload["refused"]
    flagged = pager_flagged_set(refused=payload["refused"])
    assert flagged == []


def test_pager_flagged_set_omits_not_rec_park():
    flagged = pager_flagged_set(
        refused=[
            {"slug": "koret-center", "code": "not_rec_park"},
            {"slug": "rossi-pool", "code": "grounding_coverage_low"},
            {"slug": "balboa-pool", "code": "sequential_partial"},
        ],
        blocking=[{"slug": "sava-pool", "reason": "windows_unparsed"}],
    )
    assert flagged == [
        ("balboa-pool", "sequential_partial"),
        ("rossi-pool", "grounding_coverage_low"),
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


def test_sequential_partial_grounding_writes_nothing(iso, monkeypatch):
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
        grounding={"grounded_count": 89, "total": 100, "ratio": 0.89},
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
    assert "grounding_coverage_low" in (refused[0].get("code", "") + report.read_text())
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
    assert {item["code"] for item in refused} <= {"discovery_flagged", "sibling_session_grids"}
    assert refused
    assert not (
        iso.data / "garfield-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert not (
        iso.data / "garfield-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    assert (iso.content / "garfield-pool.md").read_bytes() == before


def test_unique_grid_dated_sibling_refuses_sibling_session_grids(iso, monkeypatch):
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
    before = (iso.content / "sava-pool.md").read_bytes()
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
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert {item["code"] for item in refused} == {"sibling_session_grids"}
    assert not (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert not (
        iso.data / "sava-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    assert (iso.content / "sava-pool.md").read_bytes() == before


def test_sequential_second_finalize_rolls_back_window_1(iso, monkeypatch):
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
    assert not (
        iso.data / "sava-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json"
    ).exists()
    assert not (
        iso.data / "sava-pool" / f"2026-08-20-{SHA2[:12]}" / "reviewed.json"
    ).exists()
    assert (iso.content / "sava-pool.md").read_bytes() == before


def test_drop_to_zero_does_not_write(iso):
    _write_candidate(iso.data, payload=_payload(n=0, basis="swim_schedule"))
    _seed_content(iso.content, "hamilton-pool", sessions=8)
    count, report = publish_pending_all(
        data_root=iso.data, content_spots_dir=iso.content, today=date(2026, 8, 20)
    )
    assert count == 0
    refused = json.loads(report.with_name("publish-pending.json").read_text())["refused"]
    assert refused[0]["code"] == "sessions_dropped_to_zero"
    assert not (iso.data / "hamilton-pool" / f"2026-08-19-{SHA[:12]}" / "reviewed.json").exists()
