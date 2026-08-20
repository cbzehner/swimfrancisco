"""Tests for pipeline pure helpers.

The pipeline itself has heavy external dependencies (network, provider APIs,
filesystem). These tests cover the pure helper that gates its operator-trust
property: honest exit codes — partial failures must not exit 0.

Full-integration tests are out of scope; the invariant lives in the helper
and is exercised here.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from schedules.discover import DiscoverError
from schedules.models import Aborted, Extracted, FetchResult, PoolResult, Skipped, Unchanged
from schedules.models import PoolEntry
from schedules.paths import REPORT_PATHS
from schedules.pipeline import compute_exit_code, run_pipeline, select_registry_entries
from schedules.report import discovery_notes_from_decisions, write_report


def _skipped(slug: str) -> Skipped:
    return Skipped(slug=slug, official_page_url="", pdf_url="", source_status="published")


def _unchanged(slug: str) -> Unchanged:
    return Unchanged(
        slug=slug,
        official_page_url="",
        pdf_url="",
        source_status="published",
        provider="anthropic",
        model="claude",
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
        provider="anthropic",
        model="claude",
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
    assert [entry.slug for entry in select_registry_entries(registry, source_mode="gemini", slugs=None)] == [
        "pdf-one",
        "pdf-two",
    ]


def test_source_mode_rejects_slug_from_other_partition() -> None:
    registry = [_entry("direct-one", "jccsf_html"), _entry("pdf-one", "sfrecpark_pdf")]

    try:
        select_registry_entries(registry, source_mode="anthropic", slugs=["direct-one"])
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

    def process(entry, *, provider, compare_with, force, prompt):
        calls.append((provider, entry.slug))
        return _skipped(entry.slug)

    def report(results, *, path):
        reports[path.name] = [result.slug for result in results]
        return path

    monkeypatch.setattr("schedules.pipeline._process_entry", process)
    monkeypatch.setattr("schedules.pipeline.write_report", report)

    for mode in ("direct", "gemini", "anthropic"):
        run_pipeline(slugs=None, source_mode=mode, compare_with=None, force=False)

    assert calls == [
        ("direct", "direct-one"),
        ("direct", "direct-two"),
        ("gemini", "pdf-one"),
        ("gemini", "pdf-two"),
        ("anthropic", "pdf-one"),
        ("anthropic", "pdf-two"),
    ]
    assert reports == {
        "extraction-report-direct.md": ["direct-one", "direct-two"],
        "extraction-report-gemini.md": ["pdf-one", "pdf-two"],
        "extraction-report-anthropic.md": ["pdf-one", "pdf-two"],
    }


def test_source_modes_have_distinct_report_paths() -> None:
    assert len(set(REPORT_PATHS.values())) == 3
    assert REPORT_PATHS["direct"].name == "extraction-report-direct.md"
    assert REPORT_PATHS["gemini"].name == "extraction-report-gemini.md"
    assert REPORT_PATHS["anthropic"].name == "extraction-report-anthropic.md"


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
    monkeypatch.setattr("schedules.pipeline.normalize_pdf_text", lambda _pages: "")
    from schedules.models import GroundingResult

    monkeypatch.setattr(
        "schedules.pipeline.grounding_from_text",
        lambda _text, _payload: GroundingResult(sessions=[], grounded_count=0, total=0),
    )
    monkeypatch.setattr("schedules.pipeline.source_notes_for_signals", lambda _sig: [])
    monkeypatch.setattr("schedules.pipeline.check_delta", lambda _payload, _prior: [])
    monkeypatch.setattr(
        "schedules.pipeline.read_schedule_snapshot",
        lambda _path: {"sessions": [], "closures": [], "effective_start": None},
    )
    monkeypatch.setattr("schedules.pipeline.reviewed_path", lambda *args, **kwargs: tmp_path / "missing-reviewed.json")
    monkeypatch.setattr("schedules.pipeline.skip_if_fresh", lambda **kwargs: False)
    monkeypatch.setattr(
        "schedules.pipeline.save_artifact_bundle",
        lambda **kwargs: {"gemini": str(tmp_path / "artifact.json")},
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
        from schedules.models import ProviderResult

        return ProviderResult(
            payload={
                "effective_start": "2026-08-18",
                "schedule_basis": "swim_schedule",
                "sessions": [
                    {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                    for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
                ],
                "closures": [],
            },
            model="gemini-test",
            usage={},
            cost_estimate="test",
        )

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", fake_extract)
    return state


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
        slugs=["hamilton-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
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
                    "sessions": [
                        {"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}
                    ],
                    "closures": [],
                },
            }
        )
    )
    monkeypatch.setattr("schedules.pipeline.reviewed_path", lambda *args, **kwargs: reviewed)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, new_url=None, tmp_path=tmp_path),
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("provider must not run on the unchanged shortcut")

    monkeypatch.setattr("schedules.pipeline.extract_with_provider", boom)

    exit_code, _, results = run_pipeline(
        slugs=["hamilton-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
    )

    assert exit_code == 0
    assert state["discover_calls"] == 1
    assert state["fetched"] == [("hamilton-pool", OLD_URL)]
    assert isinstance(results[0], Unchanged)


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

    run_pipeline(
        slugs=None,
        source_mode="direct",
        compare_with=None,
        force=False,
        apply_discover=True,
    )


def test_no_discover_fetches_working_tree_url(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)

    def boom(*_args, **_kwargs):
        raise AssertionError("discover_all must not run with apply_discover=False")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)

    run_pipeline(
        slugs=["hamilton-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=False,
    )

    assert state["fetched"] == [("hamilton-pool", OLD_URL)]


def test_url_override_skips_discover_and_does_not_rewrite_registry(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("garfield-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    before = [entry.pdf_url for entry in state["registry"]]

    def boom(*_args, **_kwargs):
        raise AssertionError("discover_all must not run with --url")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)

    exit_code, _, results = run_pipeline(
        slugs=["garfield-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
        override_url=FLYER_URL,
    )

    assert exit_code == 0
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
        slugs=["hamilton-pool", "coffman-pool"],
        source_mode="gemini",
        compare_with=None,
        force=True,
        apply_discover=True,
    )

    assert state["discover_calls"] == 1


def test_bakeoff_does_not_call_discover(monkeypatch, tmp_path) -> None:
    registry = [_pdf_entry("hamilton-pool", OLD_URL)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    before = list(state["registry"])

    def boom(*_args, **_kwargs):
        raise AssertionError("bakeoff must not write the registry")

    monkeypatch.setattr("schedules.pipeline.discover_all", boom)

    run_pipeline(
        slugs=["hamilton-pool"],
        source_mode="gemini",
        compare_with="anthropic",
        force=False,
        apply_discover=True,
    )

    assert state["registry"] == before
    assert state["fetched"] == [("hamilton-pool", OLD_URL)]


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
        slugs=["garfield-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
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
        slugs=["sava-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
    )

    assert exit_code == 0
    assert state["fetched"] == [("sava-pool", SAVA_ADOPTED)]
    assert not isinstance(results[0], Skipped)
    assert results[0].source_status == "published"


def test_split_part_adopt_does_not_extract(monkeypatch, tmp_path) -> None:
    cool = "https://sfrecpark.org/DocumentCenter/View/29778"
    registry = [_pdf_entry("north-beach-pool", cool, status="missing_current_schedule")]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
    monkeypatch.setattr(
        "schedules.pipeline.discover_all",
        _fake_discover(state, tmp_path=tmp_path),
    )

    exit_code, _, results = run_pipeline(
        slugs=["north-beach-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
    )

    assert exit_code == 0
    assert state["fetched"] == []
    assert isinstance(results[0], Skipped)


def test_flag_does_not_skip_published_extract(monkeypatch, tmp_path) -> None:
    notes = "discover: 2026-08-19 flag multiple_windows id=29815:session_grid:table id=29805:session_grid:band"
    registry = [_pdf_entry("sava-pool", SAVA_SUMMER, notes=notes)]
    state = _stub_extract_pipeline(monkeypatch, tmp_path, registry)
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
                    "reason": "multiple_windows",
                    "blocking": True,
                    "candidates": [
                        {"view_id": 29815, "kind": "session_grid", "source": "table"},
                        {"view_id": 29805, "kind": "session_grid", "source": "band"},
                    ],
                    "extra_candidates": [],
                }
            ],
        ),
    )

    exit_code, _, results = run_pipeline(
        slugs=["sava-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
    )

    assert exit_code == 0
    assert state["fetched"] == [("sava-pool", SAVA_SUMMER)]
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
    notes = discovery_notes_from_decisions(path)
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
    assert discovery_notes_from_decisions(path) == {}


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

    run_pipeline(
        slugs=["sava-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
    )

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
        run_pipeline(
            slugs=["hamilton-pool"],
            source_mode="gemini",
            compare_with=None,
            force=False,
            apply_discover=True,
        )

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
        slugs=["north-beach-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=True,
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
        slugs=["hamilton-pool"],
        source_mode="gemini",
        compare_with=None,
        force=False,
        apply_discover=False,
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

    exit_code, _, results = run_pipeline(
        slugs=None,
        source_mode="direct",
        compare_with=None,
        force=False,
        apply_discover=True,
    )

    assert exit_code == 0
    assert [result.slug for result in results] == ["direct-one"]
