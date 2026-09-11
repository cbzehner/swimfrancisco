"""Tests for the extract pipeline.

Two layers live here. The pure helpers that gate the pipeline's
operator-trust properties — honest exit codes, source-mode partitioning,
report paths — are called directly. Everything above them runs through
``run_pipeline`` against ``_stub_extract_pipeline``, a minimal world in
which discover, the PDF fetch, and the provider call are all faked, so the
adoption, caching, and force behaviour is exercised end to end without
network or provider APIs.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from schedules.discover import DiscoverError
from schedules.models import Aborted, Extracted, FetchResult, PoolResult, ProviderResult, Skipped, Unchanged
from schedules.models import PoolEntry
from schedules.paths import REPORT_PATHS
from schedules.pipeline import (
    DirectRun,
    DiscoverAndExpand,
    ExpandFromDecisions,
    PdfRun,
    PinOverride,
    _session_grid_hrefs,
    compute_exit_code,
    run_pipeline,
    select_registry_entries,
)
from schedules.report import discovery_notes_from_decisions, write_report
from schedules.review import DecisionSet


def _slugs(slugs: list[str] | None) -> tuple[str, ...] | None:
    return tuple(slugs) if slugs is not None else None


def _pdf_run(
    *,
    slugs: list[str] | None = None,
    force: bool = False,
    discover: bool = False,
    url: str | None = None,
    provider: str = "openai",
    decisions: DecisionSet | None = None,
) -> PdfRun:
    if url is not None:
        urls: DiscoverAndExpand | ExpandFromDecisions | PinOverride = PinOverride(url)
    elif discover:
        urls = DiscoverAndExpand()
    else:
        urls = ExpandFromDecisions(decisions or DecisionSet.from_items([]))
    return PdfRun(provider=provider, slugs=_slugs(slugs), force=force, urls=urls)


def _skipped(slug: str) -> Skipped:
    return Skipped(slug=slug, official_page_url="", pdf_url="", source_status="published")


def _unchanged(slug: str) -> Unchanged:
    return Unchanged(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        provider="openai",
        model="gpt",
        pdf_sha256="x",
        page_count=1,
        sessions_count=0,
        closures_count=0,
        effective_start="2026-01-01",
    )


def _proposed(slug: str) -> Extracted:
    return Extracted(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        provider="openai",
        model="gpt",
        pdf_sha256="x",
        page_count=1,
        sessions_count=5,
        prior_sessions_count=5,
        closures_count=0,
        effective_start="2026-01-01",
        cost_estimate="$0.01",
    )


def _failed(slug: str) -> Aborted:
    return Aborted(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        error="boom",
        prior_sessions_count=0,
        prior_closures_count=0,
        prior_schedule_effective=None,
    )


class TestComputeExitCode:
    def test_zero_for_all_success(self) -> None:
        results: list[PoolResult] = [_proposed("a"), _proposed("b")]
        assert compute_exit_code(results) == 0

    def test_zero_for_unchanged_and_skipped(self) -> None:
        results: list[PoolResult] = [_unchanged("a"), _skipped("b")]
        assert compute_exit_code(results) == 0

    def test_nonzero_when_any_pool_failed(self) -> None:
        results: list[PoolResult] = [_proposed("a"), _failed("b")]
        assert compute_exit_code(results) == 1

    def test_nonzero_when_all_failed(self) -> None:
        results: list[PoolResult] = [_failed("a")]
        assert compute_exit_code(results) == 1

    def test_zero_for_empty(self) -> None:
        assert compute_exit_code([]) == 0


def test_report_preserves_structured_closure_holds_without_error_logs(tmp_path):
    review = {"slug": "test-pool", "source_sha256": "a" * 64, "issues": ["unresolved_closure_scope"], "notices": []}
    result = replace(_failed("test-pool"), closure_review=review, error="private transport details")
    report = tmp_path / "extraction-report-openai.md"
    write_report([result, _failed("other-pool")], report)
    payload = json.loads(report.with_suffix(".json").read_text())
    assert payload == {"closure_reviews": [review], "ready_direct": {}, "ready_openai": []}
    assert "private transport details" not in report.with_suffix(".json").read_text()


def _entry(slug: str, source_kind: str) -> PoolEntry:
    return PoolEntry(
        slug=slug,
        pdf_url="https://example.test/source",
        official_page_url="https://example.test/pool",
        source_kind=source_kind,  # type: ignore[arg-type]
    )


def test_source_modes_partition_registry_without_overlap() -> None:
    registry = [
        _entry("direct-one", "jccsf_html"),
        _entry("pdf-one", "sfrecpark_pdf"),
        _entry("direct-two", "koret_google_sheet"),
        _entry("pdf-two", "sfrecpark_pdf"),
    ]

    assert [entry.slug for entry in select_registry_entries(registry, source_mode="direct", slugs=None)] == [
        "direct-one",
        "direct-two",
    ]
    assert [entry.slug for entry in select_registry_entries(registry, source_mode="openai", slugs=None)] == [
        "pdf-one",
        "pdf-two",
    ]


def test_source_mode_rejects_slug_from_other_partition() -> None:
    registry = [_entry("direct-one", "jccsf_html"), _entry("pdf-one", "sfrecpark_pdf")]

    try:
        select_registry_entries(registry, source_mode="openai", slugs=["direct-one"])
    except ValueError as exc:
        assert "mismatched" in str(exc)
    else:
        raise AssertionError("expected a mismatched source slug to fail")


def test_each_source_mode_processes_its_partition_exactly_once(monkeypatch, tmp_path) -> None:
    registry = [
        _entry("direct-one", "jccsf_html"),
        _entry("pdf-one", "sfrecpark_pdf"),
        _entry("direct-two", "koret_google_sheet"),
        _entry("pdf-two", "sfrecpark_pdf"),
    ]
    calls: list[tuple[str, str]] = []
    reports: dict[str, list[str]] = {}

    monkeypatch.setattr("schedules.pipeline.load_registry", lambda: registry)
    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("prompt")

    def process(entry, *, command, prompt):
        provider = "direct" if isinstance(command, DirectRun) else command.provider
        calls.append((provider, entry.slug))
        return _skipped(entry.slug)

    def report(results, *, path):
        reports[path.name] = [result.slug for result in results]
        path.with_suffix(".json").parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".json").write_text("{}")
        return path

    monkeypatch.setattr("schedules.pipeline._process_entry", process)
    monkeypatch.setattr("schedules.pipeline.write_report", report)

    run_pipeline(DirectRun(slugs=None, force=False))
    run_pipeline(_pdf_run(provider="openai"))

    assert calls == [
        ("direct", "direct-one"),
        ("direct", "direct-two"),
        ("openai", "pdf-one"),
        ("openai", "pdf-two"),
    ]
    assert reports == {
        "extraction-report-direct.md": ["direct-one", "direct-two"],
        "extraction-report-openai.md": ["pdf-one", "pdf-two"],
    }


def test_source_modes_have_distinct_report_paths() -> None:
    assert len(set(REPORT_PATHS.values())) == 2
    assert REPORT_PATHS["openai"].name == "extraction-report-openai.md"
    assert REPORT_PATHS["direct"].name == "extraction-report-direct.md"


OLD_URL = "https://sfrecpark.org/DocumentCenter/View/29599"
NEW_URL = "https://sfrecpark.org/DocumentCenter/View/29800"
GARFIELD_ADOPTED = "https://sfrecpark.org/DocumentCenter/View/29799"
SAVA_SUMMER = "https://sfrecpark.org/DocumentCenter/View/29571"
SAVA_ADOPTED = "https://sfrecpark.org/DocumentCenter/View/29815"
FLYER_URL = "https://sfrecpark.org/DocumentCenter/View/29808"


def _pdf_entry(slug: str, pdf_url: str, *, status: str = "published", notes: str | None = None) -> PoolEntry:
    return PoolEntry(
        slug=slug,
        pdf_url=pdf_url,
        official_page_url=f"https://sfrecpark.org/facilities/facility/details/{slug}",
        source_status=status,  # type: ignore[arg-type]
        source_kind="sfrecpark_pdf",
        notes=notes,
    )


def _stub_extract_pipeline(monkeypatch, tmp_path: Path, registry: list[PoolEntry]) -> dict:
    """Minimal extract world: discover, fetch, and LLM are all faked."""
    state = {"registry": list(registry), "fetched": [], "discover_calls": 0}
    report_path = tmp_path / "report.md"
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("prompt")
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-fake")

    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", prompt_path)
    monkeypatch.setattr("schedules.pipeline.TMP_DIR", tmp_path)
    monkeypatch.setattr("schedules.pipeline.load_registry", lambda: list(state["registry"]))
    monkeypatch.setattr(
        "schedules.pipeline.write_report",
        lambda results, path=None: write_report(results, path=report_path),
    )
    monkeypatch.setattr("schedules.pipeline.extract_page_texts", lambda _bytes: [""])
    monkeypatch.setattr("schedules.pipeline.analyze_page_texts", lambda _pages: [])
    monkeypatch.setattr("schedules.pipeline.source_notes_for_signals", lambda _sig: [])
    monkeypatch.setattr("schedules.pipeline.check_delta", lambda _payload, _prior: [])
    monkeypatch.setattr("schedules.pipeline.inspect_pdf_source", lambda _bytes: None)
    monkeypatch.setattr(
        "schedules.pipeline.source_publication_coverage",
        lambda _source, _payload, **kwargs: {"ok": True, "issues": []},
    )
    monkeypatch.setattr(
        "schedules.pipeline.read_schedule_snapshot",
        lambda _path: {"sessions": [], "closures": [], "effective_start": None},
    )
    monkeypatch.setattr("schedules.pipeline.reviewed_path", lambda *args, **kwargs: tmp_path / "missing-reviewed.json")
    monkeypatch.setattr("schedules.pipeline.skip_if_fresh", lambda **kwargs: False)
    monkeypatch.setattr(
        "schedules.pipeline.save_artifact_bundle",
        lambda **kwargs: {"openai": str(tmp_path / "artifact.json")},
    )
    monkeypatch.setattr("schedules.pipeline.carry_forward_review", lambda **kwargs: None)

    def fake_fetch(slug, url, **kwargs):
        state["fetched"].append((slug, url))
        return FetchResult(
            path=source_pdf,
            sha256="a" * 64,
            bytes=source_pdf.read_bytes(),
            from_cache=True,
            page_count=1,
        )

    monkeypatch.setattr("schedules.pipeline.fetch_pdf", fake_fetch)

    def fake_extract(provider, pdf_bytes, prompt, schema):
        return _provider_result()

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", fake_extract)
    return state


def _extracted_payload() -> dict:
    return {
        "effective_start": "2026-08-18",
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
        ],
        "closures": [],
    }


def _provider_result() -> ProviderResult:
    return ProviderResult(payload=_extracted_payload(), model="openai-test", usage={})


def _fake_discover(state: dict, *, new_url: str | None = None, decisions: list | None = None, tmp_path: Path):
    def discover(entries, **kwargs):
        state["discover_calls"] += 1
        if new_url is not None:
            state["registry"] = [
                replace(entry, pdf_url=new_url) if entry.source_kind == "sfrecpark_pdf" else entry
                for entry in state["registry"]
            ]
        payload = decisions
        if payload is None and new_url is not None:
            payload = [
                {
                    "slug": entries[0].slug,
                    "action": "adopt",
                    "old_url": entries[0].pdf_url,
                    "new_url": new_url,
                    "kind": "session_grid",
                    "reason": "session_grid",
                    "blocking": False,
                    "candidates": [
                        {
                            "view_id": 29800,
                            "href": new_url,
                            "anchor_text": "Hamilton Pool Fall 2026",
                            "kind": "session_grid",
                            "filename": "Hamilton Pool Fall 2026.pdf",
                            "source": "table",
                        }
                    ],
                    "extra_candidates": [],
                }
            ]
        if payload is not None:
            (tmp_path / "discovery-decisions.json").write_text(json.dumps(payload) + "\n")
        return []

    return discover


def test_local_provider_discovers_once_then_fetches_rolled_url(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, new_url=NEW_URL, tmp_path=tmp_path),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["hamilton-pool"], discover=True),
    )

    assert exit_code == 0
    assert state["discover_calls"] == 1
    assert state["fetched"] == [("hamilton-pool", NEW_URL)]
    assert results[0].pdf_url == NEW_URL
    assert any(note.kind == "url_rolled" for note in results[0].review_notes)


def test_same_id_still_uses_unchanged_shortcut(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": "a" * 64,
                "reviewed_at": "2026-04-19",
                "source_pdf_url": OLD_URL,
                "payload": {
                    "effective_start": "2026-03-17",
                    "schedule_basis": "swim_schedule",
                    "sessions": [
                        {"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}
                    ],
                    "closures": [],
                },
            }
        )
    )
    cached = tmp_path / "openai-cached.json"
    cached.write_text(json.dumps({
        "model": "openai-test",
        "payload": json.loads(reviewed.read_text())["payload"],
    }))
    monkeypatch.setattr("schedules.pipeline.reviewed_path", lambda *args, **kwargs: reviewed)
    monkeypatch.setattr("schedules.pipeline.artifact_path", lambda *args, **kwargs: cached)
    monkeypatch.setattr("schedules.pipeline.skip_if_fresh", lambda **kwargs: True)
    monkeypatch.setattr("schedules.pipeline.verify_artifact", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, new_url=None, tmp_path=tmp_path),
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("provider must not run on the unchanged shortcut")

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", boom)

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["hamilton-pool"], discover=True),
    )

    assert exit_code == 0
    assert state["discover_calls"] == 1
    assert state["fetched"] == [("hamilton-pool", OLD_URL)]
    assert isinstance(results[0], Unchanged)


def test_force_bypasses_reviewed_fast_path(monkeypatch, tmp_path) -> None:
    """--force must invoke the provider even when reviewed.json exists.

    Same world as the unchanged shortcut above, so the only difference is
    the flag: a reviewed snapshot the SHA matches, and a verified cached
    artifact that would otherwise short-circuit the run.
    """
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": "a" * 64,
                "reviewed_at": "2026-04-19",
                "source_pdf_url": OLD_URL,
                "payload": _extracted_payload(),
            }
        )
    )
    cached = tmp_path / "openai-cached.json"
    cached.write_text(json.dumps({"model": "openai-test", "payload": _extracted_payload()}))
    monkeypatch.setattr("schedules.pipeline.reviewed_path", lambda *args, **kwargs: reviewed)
    monkeypatch.setattr("schedules.pipeline.artifact_path", lambda *args, **kwargs: cached)
    monkeypatch.setattr("schedules.pipeline.skip_if_fresh", lambda **kwargs: True)
    monkeypatch.setattr("schedules.pipeline.verify_artifact", lambda *args, **kwargs: {"ok": True})
    providers = []

    def counting_extract(provider, pdf_bytes, prompt, schema):
        providers.append(provider)
        return _provider_result()

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", counting_extract)

    exit_code, _, results = run_pipeline(_pdf_run(slugs=["hamilton-pool"], force=True))

    assert exit_code == 0
    assert providers == ["openai"], "--force must invoke the provider even when reviewed.json exists"
    assert results[0].provider == "openai"


def test_direct_mode_never_calls_discover(monkeypatch, tmp_path) -> None:
    registry = [_entry("direct-one", "jccsf_html")]
    monkeypatch.setattr("schedules.pipeline.load_registry", lambda: registry)
    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("prompt")
    monkeypatch.setattr("schedules.pipeline._process_entry", lambda *args, **kwargs: _skipped("direct-one"))
    monkeypatch.setattr("schedules.pipeline.write_report", lambda results, path=None: path)

    def boom(*_args, **_kwargs):
        raise AssertionError("discover_all must not run in --direct mode")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)

    run_pipeline(DirectRun(slugs=None, force=False))


def test_empty_decisions_fetches_working_tree_url(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)

    def boom(*_args, **_kwargs):
        raise AssertionError("discover_all must not run with apply_discover=False")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)

    run_pipeline(_pdf_run(slugs=["hamilton-pool"]))

    assert state["fetched"] == [("hamilton-pool", OLD_URL)]


def test_url_override_skips_discover_and_does_not_rewrite_registry(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("garfield-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    before = [entry.pdf_url for entry in state["registry"]]

    def boom(*_args, **_kwargs):
        raise AssertionError("discover_all must not run with --url")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)
    (tmp_path / "discovery-decisions.json").write_text(
        json.dumps(
            [
                {
                    "slug": "garfield-pool",
                    "action": "flag",
                    "reason": "stale",
                    "blocking": True,
                }
            ]
        )
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["garfield-pool"], url=FLYER_URL),
    )

    assert exit_code == 0
    assert results[0].review_notes == []
    assert state["discover_calls"] == 0
    assert state["fetched"] == [("garfield-pool", FLYER_URL)]
    assert [entry.pdf_url for entry in state["registry"]] == before
    assert results[0].pdf_url == FLYER_URL


def test_force_still_discovers_once(monkeypatch, tmp_path) -> None:
    registry = [
        _pdf_entry("hamilton-pool", OLD_URL),
        _pdf_entry("coffman-pool", "https://sfrecpark.org/DocumentCenter/View/29563"),
    ]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, new_url=NEW_URL, tmp_path=tmp_path),
    )

    run_pipeline(
        _pdf_run(slugs=["hamilton-pool", "coffman-pool"], force=True, discover=True),
    )

    assert state["discover_calls"] == 1


def test_garfield_adopt_then_extract_fetches_adopted_url(monkeypatch, tmp_path) -> None:
    notes = (
        "discover: 2026-08-19 extra id=29808:closure_notice:table "
        "band_session_grid id=29799:session_grid:persisted"
    )
    registry = [_pdf_entry("garfield-pool", GARFIELD_ADOPTED, notes=notes)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(
            state,
            tmp_path=tmp_path,
            decisions=[
                {
                    "slug": "garfield-pool",
                    "action": "unchanged",
                    "old_url": GARFIELD_ADOPTED,
                    "new_url": GARFIELD_ADOPTED,
                    "kind": "session_grid",
                    "reason": "current_session_grid",
                    "blocking": False,
                    "candidates": [
                        {
                            "view_id": 29799,
                            "href": GARFIELD_ADOPTED,
                            "kind": "session_grid",
                            "filename": "Garfield Pool Fall 2026.pdf",
                            "source": "band",
                        }
                    ],
                    "extra_candidates": [],
                }
            ],
        ),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["garfield-pool"], discover=True),
    )

    assert exit_code == 0
    assert state["fetched"] == [("garfield-pool", GARFIELD_ADOPTED)]
    assert not isinstance(results[0], Skipped)


def test_sava_adopt_then_extract_fetches_adopted_url(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("sava-pool", SAVA_ADOPTED)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, tmp_path=tmp_path),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["sava-pool"], discover=True),
    )

    assert exit_code == 0
    assert state["fetched"] == [("sava-pool", SAVA_ADOPTED)]
    assert not isinstance(results[0], Skipped)
    assert results[0].source_status == "published"


def test_sequential_extract_fetches_each_collapsed_window(monkeypatch, tmp_path) -> None:
    fall1 = "https://sfrecpark.org/DocumentCenter/View/29815"
    fall2 = "https://sfrecpark.org/DocumentCenter/View/29805"
    registry = [_pdf_entry("sava-pool", fall1)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    before = [entry.pdf_url for entry in state["registry"]]
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(
            state,
            tmp_path=tmp_path,
            decisions=[
                {
                    "slug": "sava-pool",
                    "action": "unchanged",
                    "old_url": fall1,
                    "new_url": fall1,
                    "kind": "session_grid",
                    "reason": "sequential_windows",
                    "blocking": False,
                    "candidates": [
                        {
                            "view_id": 29815,
                            "href": fall1,
                            "kind": "session_grid",
                            "source": "table",
                            "window_start": "2026-08-18",
                            "window_end": "2026-08-28",
                        },
                        {
                            "view_id": 29805,
                            "href": fall2,
                            "kind": "session_grid",
                            "source": "band",
                            "window_start": "2026-08-29",
                            "window_end": "2026-12-12",
                        },
                    ],
                    "extra_candidates": [],
                }
            ],
        ),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["sava-pool"], discover=True),
    )

    assert exit_code == 0
    assert state["fetched"] == [("sava-pool", fall1), ("sava-pool", fall2)]
    assert [entry.pdf_url for entry in state["registry"]] == before
    assert {result.pdf_url for result in results} == {fall1, fall2}


def test_equal_range_duplicate_is_not_fetched() -> None:
    fall1 = "https://sfrecpark.org/DocumentCenter/View/29815"
    duplicate = "https://sfrecpark.org/DocumentCenter/View/29806"
    entry = _pdf_entry("sava-pool", fall1)
    hrefs = _session_grid_hrefs(
        entry,
        DecisionSet.from_items(
            [
            {
                "slug": "sava-pool",
                "candidates": [
                    {
                        "view_id": 29815,
                        "href": fall1,
                        "kind": "session_grid",
                        "source": "table",
                        "window_start": "2026-08-18",
                        "window_end": "2026-08-28",
                    },
                    {
                        "view_id": 29806,
                        "href": duplicate,
                        "kind": "session_grid",
                        "source": "band",
                        "window_start": "2026-08-18",
                        "window_end": "2026-08-28",
                    },
                ],
            }
            ]
        ),
    )
    assert hrefs == [fall1]


def test_split_part_adopt_does_not_extract(monkeypatch, tmp_path) -> None:
    cool = "https://sfrecpark.org/DocumentCenter/View/29778"
    registry = [_pdf_entry("north-beach-pool", cool, status="missing_current_schedule")]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, tmp_path=tmp_path),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["north-beach-pool"], discover=True),
    )

    assert exit_code == 0
    assert state["fetched"] == []
    assert isinstance(results[0], Skipped)


def test_flag_does_not_skip_published_extract(monkeypatch, tmp_path) -> None:
    notes = "discover: 2026-08-19 flag overlapping_windows id=29815:session_grid:table id=29805:session_grid:band"
    registry = [_pdf_entry("sava-pool", SAVA_SUMMER, notes=notes)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    fall1 = "https://sfrecpark.org/DocumentCenter/View/29815"
    fall2 = "https://sfrecpark.org/DocumentCenter/View/29805"
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(
            state,
            tmp_path=tmp_path,
            decisions=[
                {
                    "slug": "sava-pool",
                    "action": "flag",
                    "old_url": SAVA_SUMMER,
                    "new_url": None,
                    "kind": "session_grid",
                    "reason": "overlapping_windows",
                    "blocking": True,
                    "candidates": [
                        {
                            "view_id": 29815,
                            "href": fall1,
                            "kind": "session_grid",
                            "source": "table",
                            "window_start": "2026-08-18",
                            "window_end": "2026-12-26",
                        },
                        {
                            "view_id": 29805,
                            "href": fall2,
                            "kind": "session_grid",
                            "source": "band",
                            "window_start": "2026-08-29",
                            "window_end": "2026-12-12",
                        },
                    ],
                    "extra_candidates": [],
                }
            ],
        ),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["sava-pool"], discover=True),
    )

    assert exit_code == 0
    assert ("sava-pool", fall1) in state["fetched"]
    assert ("sava-pool", fall2) in state["fetched"]
    assert ("sava-pool", SAVA_SUMMER) in state["fetched"]
    assert not isinstance(results[0], Skipped)
    assert any(note.kind == "discovery_flagged" for note in results[0].review_notes)


def test_discovery_notes_from_decisions_file(tmp_path) -> None:
    path = tmp_path / "discovery-decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "slug": "hamilton-pool",
                    "action": "adopt",
                    "old_url": OLD_URL,
                    "new_url": NEW_URL,
                    "blocking": False,
                    "candidates": [
                        {
                            "view_id": 29800,
                            "filename": "Hamilton Pool Fall 2026.pdf",
                        }
                    ],
                },
                {
                    "slug": "sava-pool",
                    "action": "flag",
                    "reason": "multiple_windows",
                    "blocking": True,
                    "candidates": [{"view_id": 29815}, {"view_id": 29805}],
                },
            ]
        )
    )
    notes = discovery_notes_from_decisions(DecisionSet.load(path))
    assert notes["hamilton-pool"][0].kind == "url_rolled"
    assert notes["hamilton-pool"][0].severity == "info"
    assert "29599 → 29800" in notes["hamilton-pool"][0].message
    assert "Hamilton Pool Fall 2026.pdf" in notes["hamilton-pool"][0].message
    assert notes["sava-pool"][0].kind == "discovery_flagged"
    assert notes["sava-pool"][0].severity == "warning"
    assert "multiple_windows" in notes["sava-pool"][0].message
    assert "29815" in notes["sava-pool"][0].message
    assert "29805" in notes["sava-pool"][0].message


def test_invalid_decisions_json_yields_no_notes(tmp_path) -> None:
    path = tmp_path / "discovery-decisions.json"
    path.write_text("{not-json")
    assert discovery_notes_from_decisions(DecisionSet.load(path)) == {}


def test_only_slug_passes_full_rec_park_set_into_discover(monkeypatch, tmp_path) -> None:
    registry = [
        _pdf_entry("sava-pool", SAVA_SUMMER),
        _pdf_entry("hamilton-pool", OLD_URL),
        _pdf_entry(
            "north-beach-pool",
            "https://sfrecpark.org/DocumentCenter/View/29778",
            status="missing_current_schedule",
        ),
    ]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    seen: dict = {}

    def fake_discover(entries, **kwargs):
        seen["slugs_arg"] = kwargs.get("slugs")
        seen["entry_slugs"] = [entry.slug for entry in entries]
        state["discover_calls"] += 1
        return []

    monkeypatch.setattr("schedules.pipeline.discover_all", fake_discover)

    run_pipeline(_pdf_run(slugs=["sava-pool"], discover=True))

    assert state["discover_calls"] == 1
    assert seen["slugs_arg"] == ["sava-pool"]
    assert seen["entry_slugs"] == [
        "sava-pool",
        "hamilton-pool",
        "north-beach-pool",
    ]
    assert state["fetched"] == [("sava-pool", SAVA_SUMMER)]


def test_discover_error_exits_one_and_keeps_report(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    report = tmp_path / "discovery-report.md"
    report.write_text("# kept\n")

    def boom(*_args, **_kwargs):
        raise DiscoverError("every Rec & Park facility page failed to fetch")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)

    with pytest.raises(DiscoverError, match="every Rec & Park facility page failed"):
        run_pipeline(_pdf_run(slugs=["hamilton-pool"], discover=True))

    assert state["fetched"] == []
    assert report.read_text() == "# kept\n"


def test_discovery_notes_attach_to_skipped_and_aborted(monkeypatch, tmp_path) -> None:
    cool = "https://sfrecpark.org/DocumentCenter/View/29778"
    skipped_registry = [
        _pdf_entry("north-beach-pool", cool, status="missing_current_schedule")
    ]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, skipped_registry)
    flag_decision = [
        {
            "slug": "north-beach-pool",
            "action": "flag",
            "reason": "split_part",
            "blocking": True,
            "candidates": [{"view_id": 29778}, {"view_id": 29779}],
        }
    ]
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, tmp_path=tmp_path, decisions=flag_decision),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(slugs=["north-beach-pool"], discover=True),
    )

    assert exit_code == 0
    assert isinstance(results[0], Skipped)
    assert any(note.kind == "discovery_flagged" for note in results[0].review_notes)

    aborted_registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, aborted_registry)
    (tmp_path / "discovery-decisions.json").write_text(
        json.dumps(
            [
                {
                    "slug": "hamilton-pool",
                    "action": "flag",
                    "reason": "empty_table",
                    "blocking": True,
                    "candidates": [{"view_id": 29599}],
                }
            ]
        )
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("fetch failed")

    monkeypatch.setattr("schedules.pipeline.fetch_pdf", boom)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, tmp_path=tmp_path),
    )

    exit_code, _, results = run_pipeline(
        _pdf_run(
            slugs=["hamilton-pool"],
            decisions=DecisionSet.load(tmp_path / "discovery-decisions.json"),
        )
    )

    assert isinstance(results[0], Aborted)
    assert any(note.kind == "discovery_flagged" for note in results[0].review_notes)


def test_invalid_decisions_json_does_not_break_direct(monkeypatch, tmp_path) -> None:
    (tmp_path / "discovery-decisions.json").write_text("{not-json")
    monkeypatch.setattr("schedules.pipeline.TMP_DIR", tmp_path)
    monkeypatch.setattr("schedules.pipeline.load_registry", lambda: [_entry("direct-one", "jccsf_html")])
    monkeypatch.setattr("schedules.pipeline.PROMPT_PATH", tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("prompt")
    monkeypatch.setattr(
        "schedules.pipeline._process_entry",
        lambda *args, **kwargs: _skipped("direct-one"),
    )
    monkeypatch.setattr("schedules.pipeline.write_report", lambda results, path=None: path)

    exit_code, _, results = run_pipeline(DirectRun(slugs=None, force=False))

    assert exit_code == 0
    assert [result.slug for result in results] == ["direct-one"]



def test_paired_extraction_reuses_unchanged_member_and_configuration(tmp_path, north_beach_pair, monkeypatch):
    import hashlib
    from schedules import pipeline, paths, artifacts
    from schedules.models import ProviderResult
    from schedules.paths import PROMPT_PATH
    from schedules.providers.openai_provider import extraction_configuration
    entry, components = north_beach_pair
    root = tmp_path / "data"
    content = tmp_path / "content"
    content.mkdir()
    (content / (entry.slug + ".md")).write_text(Path("content/spots/north-beach-pool.md").read_text())
    monkeypatch.setattr(pipeline, "CONTENT_SPOTS_DIR", content)
    monkeypatch.setattr(pipeline, "load_registry", lambda: [entry])
    monkeypatch.setattr(pipeline, "REPORT_PATHS", {"openai": tmp_path / "report.md"})
    monkeypatch.setattr(pipeline, "artifact_path", lambda *args: paths.artifact_path(*args, root=root))
    monkeypatch.setattr(pipeline, "reviewed_path", lambda *args: paths.reviewed_path(*args, root=root))
    monkeypatch.setattr(pipeline, "save_artifact_bundle", lambda **kwargs: artifacts.save_artifact_bundle(**kwargs, root=root))
    monkeypatch.setattr(pipeline, "skip_if_fresh", lambda **kwargs: artifacts.skip_if_fresh(**kwargs, root=root))
    documents = {part["artifact"]["source_pdf_url"]: part["document"] for part in components}
    def fetch(slug, url):
        document = documents[url]
        digest = hashlib.sha256(document).hexdigest()
        parent = paths.review_dir(slug, "2026-09-06", digest, root=root)
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / "source.pdf"
        path.write_bytes(document)
        return FetchResult(path, digest, document, False, 1)
    monkeypatch.setattr(pipeline, "fetch_pdf", fetch)
    calls = []
    def extract(provider, document, prompt, schema):
        index = 0 if document.startswith(components[0]["document"]) else 1
        calls.append(index)
        artifact = components[index]["artifact"]
        details = artifact["details"] | {"configuration": extraction_configuration(prompt)}
        return ProviderResult(artifact["payload"], artifact["model"], {}, details)
    monkeypatch.setattr(pipeline, "extract_with_provider", extract)
    command = PdfRun("openai", (entry.slug,), False, ExpandFromDecisions(DecisionSet.from_items([])))
    assert pipeline.run_pipeline(command)[0] == 0
    assert calls == [0, 1]
    assert pipeline.run_pipeline(command)[0] == 0
    assert calls == [0, 1]
    documents[entry.pool_sources[1].url] += b"\n% changed original bytes\n"
    assert pipeline.run_pipeline(command)[0] == 0
    assert calls == [0, 1, 1]
    changed_prompt = tmp_path / "prompt.md"
    changed_prompt.write_text(PROMPT_PATH.read_text() + "\nKeep physical pools distinct.\n")
    monkeypatch.setattr(pipeline, "PROMPT_PATH", changed_prompt)
    assert pipeline.run_pipeline(command)[0] == 0
    assert calls == [0, 1, 1, 0, 1]
    assert pipeline.run_pipeline(command)[0] == 0
    assert calls == [0, 1, 1, 0, 1]
    assert not list(root.glob("*/*/reviewed.json"))


@pytest.mark.parametrize("failed_pool", ["cool", "warm"])
def test_pair_failure_never_builds_bundle(tmp_path, north_beach_pair, monkeypatch, failed_pool):
    from schedules import pipeline
    entry, _ = north_beach_pair
    monkeypatch.setattr(pipeline, "load_registry", lambda: [entry])
    monkeypatch.setattr(pipeline, "REPORT_PATHS", {"openai": tmp_path / "report.md"})
    def process(work, **kwargs):
        if work.pdf_url == next(source.url for source in entry.pool_sources if source.pool == failed_pool):
            return Aborted(entry.slug, entry.official_page_url, work.pdf_url, "published", "failed", 0, 0, None)
        return _unchanged(entry.slug)
    monkeypatch.setattr(pipeline, "_process_entry", process)
    monkeypatch.setattr(pipeline, "save_pool_bundle", lambda *args: pytest.fail("incomplete bundle"))
    assert pipeline.run_pipeline(PdfRun("openai", (entry.slug,), False, ExpandFromDecisions(DecisionSet.from_items([]))))[0] == 1


@pytest.mark.parametrize('state', ['rejected', 'retry_failure', 'valid', 'identity_error', 'schema_error'])
def test_openai_cache_reuses_only_independently_verified_results(tmp_path, north_beach_pair, monkeypatch, state):
    import copy
    from schedules import artifacts, paths, pipeline
    from schedules.models import ProviderResult
    from schedules.paths import PROMPT_PATH
    from schedules.schema import EXTRACTION_SCHEMA
    from schedules.providers.openai_provider import source_fact_payload, inspect_pdf_source, verify_artifact

    paired_entry, components = north_beach_pair
    component = components[0]
    good = component['artifact']
    entry = replace(paired_entry, pdf_url=good['source_pdf_url'], pool_sources=())
    prompt = PROMPT_PATH.read_text().strip()
    root = tmp_path / 'data'
    capture = paths.review_dir(entry.slug, '2026-09-06', good['pdf_sha256'], root=root)
    capture.mkdir(parents=True)
    original = capture / 'source.pdf'
    original.write_bytes(component['document'])
    snapshot = capture / 'reviewed.json'
    snapshot.write_text(json.dumps({'slug': entry.slug, 'pdf_sha256': good['pdf_sha256'],
                                   'source_pdf_url': entry.pdf_url, 'reviewed_at': '2026-09-06',
                                   'payload': good['payload']}))
    prior_bytes = snapshot.read_bytes()
    cached = copy.deepcopy(good)
    if state in {'rejected', 'retry_failure'}:
        cached['details']['source_facts']['sessions'][0]['excluded_dates'] = ['2026-09-08']
        cached['payload'] = source_fact_payload(cached['details']['source_facts'], inspect_pdf_source(component['document']))
        assert not verify_artifact(cached, component['document'], prompt)['ok']
    artifacts.save_artifact_bundle(slug=entry.slug, date='2026-09-06', provider='openai', model=good['model'],
                                   source_pdf_url=entry.pdf_url, pdf_sha256=good['pdf_sha256'], prompt=prompt,
                                   schema=EXTRACTION_SCHEMA, payload=cached['payload'], usage={}, cost_estimate='mocked',
                                   details=cached['details'], root=root)
    cached_path = paths.artifact_path(entry.slug, '2026-09-06', good['pdf_sha256'], 'openai', good['model'], root=root)
    if state in {'identity_error', 'schema_error'}:
        stored = json.loads(cached_path.read_text())
        if state == 'identity_error':
            stored['pdf_sha256'] = '0' * 64
        else:
            stored['details']['source_facts']['sessions'] = 'invalid'
        cached_path.write_text(json.dumps(stored))
    cached_bytes = cached_path.read_bytes()
    if state == 'valid':
        budget = tmp_path / 'budget.json'
        budget.write_text(json.dumps({'limit_microusd': 0, 'requests': []}))
        monkeypatch.setenv('SCHEDULES_API_BUDGET_FILE', str(budget))
        monkeypatch.setenv('SCHEDULES_API_BUDGET_USD', '0')
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(pipeline, 'read_schedule_snapshot', lambda _: good['payload'])
    monkeypatch.setattr(pipeline, 'fetch_pdf', lambda *args: FetchResult(original, good['pdf_sha256'], component['document'], True, 1))
    monkeypatch.setattr(pipeline, 'artifact_path', lambda *args: paths.artifact_path(*args, root=root))
    monkeypatch.setattr(pipeline, 'reviewed_path', lambda *args: paths.reviewed_path(*args, root=root))
    monkeypatch.setattr(pipeline, 'save_artifact_bundle', lambda **kwargs: artifacts.save_artifact_bundle(**kwargs, root=root))
    monkeypatch.setattr(pipeline, 'skip_if_fresh', lambda **kwargs: artifacts.skip_if_fresh(**kwargs, root=root))
    monkeypatch.setattr(pipeline, 'carry_forward_review', lambda **kwargs: None)
    calls = []
    def extract(*args):
        calls.append(args[0])
        if state == 'retry_failure':
            raise ValueError('Accounted provider retry failed')
        return ProviderResult(good['payload'], good['model'], {}, good['details'])
    monkeypatch.setattr(pipeline, 'extract_with_provider', extract)
    result = pipeline._process_entry(entry, command=_pdf_run(provider='openai'), prompt=prompt)
    assert snapshot.read_bytes() == prior_bytes
    if state == 'rejected':
        assert isinstance(result, Extracted) and not result.catastrophic
        assert calls == ['openai']
        assert verify_artifact(json.loads(cached_path.read_text()), component['document'], prompt)['ok']
        again = pipeline._process_entry(entry, command=_pdf_run(provider='openai'), prompt=prompt)
        assert isinstance(again, Unchanged)
        assert calls == ['openai']
    elif state == 'valid':
        assert isinstance(result, Unchanged)
        assert not calls
        assert json.loads(budget.read_text()) == {'limit_microusd': 0, 'requests': []}
    else:
        assert isinstance(result, Aborted)
        assert calls == (['openai'] if state == 'retry_failure' else [])
        assert cached_path.read_bytes() == cached_bytes


@pytest.mark.parametrize('damage', [None, 'hash', 'printed_window', 'anchor_only', 'unconfirmed', 'missing_bytes', 'future'])
def test_expired_discovery_grid_requires_independent_retained_original(tmp_path, monkeypatch, damage):
    import hashlib
    from datetime import date
    from schedules import paths
    from schedules.window_dates import verified_expired_grid_ids
    content = (Path(__file__).parents[1] / 'data/sava-pool/2026-09-01-4d9a6f5e805d/source.pdf').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    directory = tmp_path / 'sava-pool' / f'2026-09-01-{digest[:12]}'
    directory.mkdir(parents=True)
    (directory / 'source.pdf').write_bytes(content)
    old = {'view_id': 29806, 'href': 'https://sfrecpark.org/DocumentCenter/View/29806',
           'kind': 'session_grid', 'source': 'persisted', 'window_start': '2026-08-18',
           'window_end': '2026-08-28', 'window_source': 'page-1', 'grid_confirmed': True, 'pdf_sha256': digest}
    current = {'view_id': 30037, 'href': 'https://sfrecpark.org/DocumentCenter/View/30037',
               'kind': 'session_grid', 'source': 'table', 'window_start': '2026-08-29', 'window_end': '2026-12-12'}
    if damage == 'hash': old['pdf_sha256'] = '0' * 64
    if damage == 'printed_window': old['window_end'] = '2026-08-27'
    if damage == 'anchor_only': old['window_source'] = 'anchor'
    if damage == 'unconfirmed': old['grid_confirmed'] = False
    if damage == 'missing_bytes': (directory / 'source.pdf').unlink()
    today = date(2026, 8, 17) if damage == 'future' else date(2026, 9, 9)
    decision = {'slug': 'sava-pool', 'reason': 'sequential_windows', 'candidates': [old, current]}
    assert verified_expired_grid_ids('sava-pool', decision, today, data_root=tmp_path) == ({29806} if damage is None else set())
    monkeypatch.setattr(paths, 'DATA_DIR', tmp_path)
    monkeypatch.setattr('schedules._time.pacific_today', lambda: today)
    entry = PoolEntry('sava-pool', current['href'], 'https://sfrecpark.org/sava')
    hrefs = _session_grid_hrefs(entry, DecisionSet.from_items([decision]))
    assert current['href'] in hrefs
    assert (old['href'] not in hrefs) is (damage is None)
