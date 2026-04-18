import json
from pathlib import Path
from unittest.mock import MagicMock

from schedules import pipeline as pipeline_mod
from schedules.models import (
    FetchResult,
    GroundingResult,
    PdfSignals,
    PoolEntry,
    ProviderResult,
    ValidationResult,
)
from schedules.reviewed_snapshots import (
    REVIEWED_SNAPSHOT_VERSION,
    canonicalize_payload,
    find_snapshots_for_slug,
    load_reviewed_snapshot,
    write_ratified_snapshot,
)


def _envelope(slug, pdf_sha256, payload):
    return {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-01-01",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "payload": payload,
    }


def test_find_snapshots_for_slug_returns_empty_when_missing(tmp_path):
    assert find_snapshots_for_slug("hamilton-pool", root=tmp_path / "missing") == []


def test_find_snapshots_for_slug_lists_all(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    payload = {
        "schedule_effective": "2026-01-01",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
        ],
        "closures": [],
    }
    for sha in ("a" * 64, "b" * 64):
        path = root / "hamilton-pool" / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_envelope("hamilton-pool", sha, payload)))
    assert len(find_snapshots_for_slug("hamilton-pool", root=root)) == 2


def test_write_ratified_snapshot_round_trips(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    payload = {
        "schedule_effective": "2026-01-01",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
        ],
        "closures": [],
    }
    new_sha = "c" * 64
    source_sha = "a" * 64
    path = write_ratified_snapshot(
        slug="hamilton-pool",
        pdf_sha256=new_sha,
        source_pdf_url="https://example.com/schedule.pdf",
        payload=payload,
        reviewed_against=[{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        ratified_from_sha256=source_sha,
        root=root,
    )
    loaded, fingerprint, _ = load_reviewed_snapshot("hamilton-pool", new_sha, root=root)
    assert loaded["reviewed_by"] == "ratification"
    assert loaded["ratified_from_sha256"] == source_sha
    assert canonicalize_payload(loaded["payload"]) == canonicalize_payload(payload)
    assert fingerprint and len(fingerprint) == 64
    assert path.exists()


# --- pipeline-level ratification tests ---

_RATIFY_PAYLOAD = {
    "schedule_effective": "2026-01-01",
    "sessions": [
        {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
    ],
    "closures": [],
}


def _ratify_envelope(slug, sha, payload, *, reviewed_by=None):
    env = {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": sha,
        "reviewed_at": "2026-01-01",
        "source_pdf_url": "https://example.test/old.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "flash"}],
        "payload": payload,
    }
    if reviewed_by is not None:
        env["reviewed_by"] = reviewed_by
    return env


def _install_pipeline_stubs(monkeypatch, tmp_path, *, payload, envelopes_by_sha, new_sha, snapshot_order=None, bad_shas=()):
    """Stub every external pipeline dependency. Returns (entry, write_spy, save_state_calls)."""
    entry = PoolEntry(
        slug="demo-pool",
        pdf_url="https://example.test/demo.pdf",
        official_page_url="https://example.test/demo",
    )

    monkeypatch.setattr(pipeline_mod, "load_registry", lambda: [entry])
    monkeypatch.setattr(pipeline_mod, "load_state", lambda: {})
    save_state_calls: list = []
    monkeypatch.setattr(pipeline_mod, "save_state", lambda state: save_state_calls.append(state))

    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("prompt")
    monkeypatch.setattr(pipeline_mod, "PROMPT_PATH", prompt_file)

    fetch_result = FetchResult(
        path=tmp_path / "demo.pdf",
        sha256=new_sha,
        bytes=b"fakepdf",
        from_cache=True,
        page_count=1,
        response_url="https://example.test/demo.pdf",
    )
    monkeypatch.setattr(pipeline_mod, "fetch_pdf", lambda *a, **kw: fetch_result)
    monkeypatch.setattr(
        pipeline_mod,
        "read_schedule_snapshot",
        lambda path: {"sessions": [], "closures": [], "schedule_effective": "2026-01-01"},
    )
    monkeypatch.setattr(pipeline_mod, "extract_page_texts", lambda b: ["text"])
    monkeypatch.setattr(
        pipeline_mod,
        "analyze_page_texts",
        lambda pt: PdfSignals(page_count=1, text_sha256="t" * 64, grid_header_pages=[], timed_lesson_line_count=0),
    )
    monkeypatch.setattr(pipeline_mod, "normalize_pdf_text", lambda pt: "normalized")
    monkeypatch.setattr(pipeline_mod, "source_notes_for_payload", lambda s, p: [])
    monkeypatch.setattr(pipeline_mod, "check_delta", lambda p, prior: [])
    monkeypatch.setattr(
        pipeline_mod,
        "grounding_from_text",
        lambda text, p: GroundingResult(sessions=[], grounded_count=0, total=0),
    )
    monkeypatch.setattr(pipeline_mod, "save_artifact_bundle", lambda **kw: {})
    monkeypatch.setattr(
        pipeline_mod,
        "validate",
        lambda p, prior_sessions_count: ValidationResult(
            ok=True,
            violations=[],
            stats={"sessions": len(p.get("sessions") or []), "closures": 0},
            catastrophic=False,
        ),
    )

    merge_mock = MagicMock(
        return_value=MagicMock(
            prior_sessions_count=0,
            new_sessions_count=1,
            prior_closures_count=0,
            new_closures_count=0,
            written=True,
        )
    )
    monkeypatch.setattr(pipeline_mod, "merge", merge_mock)

    def fake_load(slug, sha, root=None):
        if sha == new_sha:
            return None, None, None
        if sha in bad_shas:
            raise ValueError(f"malformed envelope at {sha}")
        if sha in envelopes_by_sha:
            return envelopes_by_sha[sha], "fp", Path(f"{slug}/{sha}.json")
        raise ValueError(f"unexpected sha {sha}")
    monkeypatch.setattr(pipeline_mod, "load_reviewed_snapshot", fake_load)

    order = snapshot_order if snapshot_order is not None else [*bad_shas, *envelopes_by_sha.keys()]
    snapshot_paths = [Path(f"{entry.slug}/{sha}.json") for sha in order]
    monkeypatch.setattr(pipeline_mod, "find_snapshots_for_slug", lambda slug, root=None: snapshot_paths)

    monkeypatch.setattr(
        pipeline_mod,
        "extract_with_provider",
        lambda prov, pdf, prompt, schema: ProviderResult(payload=payload, model="test-model", usage={}, cost_estimate="$0.01"),
    )

    write_spy = MagicMock(return_value=tmp_path / "ratified.json")
    monkeypatch.setattr(pipeline_mod, "write_ratified_snapshot", write_spy)
    monkeypatch.setattr(pipeline_mod, "write_report", lambda results, path=None: tmp_path / "report.md")
    monkeypatch.setattr(pipeline_mod, "relative_to_repo", lambda path: str(path))

    return entry, write_spy, save_state_calls


def test_pipeline_ratification_no_write_under_dry_run(monkeypatch, tmp_path):
    human_sha = "a" * 64
    envelopes = {human_sha: _ratify_envelope("demo-pool", human_sha, _RATIFY_PAYLOAD)}
    _, write_spy, save_state_calls = _install_pipeline_stubs(
        monkeypatch, tmp_path, payload=_RATIFY_PAYLOAD, envelopes_by_sha=envelopes, new_sha="b" * 64,
    )
    _, _, results = pipeline_mod.run_pipeline(
        slugs=None, provider="gemini", compare_with=None, force=False, dry_run=True,
    )
    assert write_spy.call_count == 0
    assert save_state_calls == []
    [result] = results
    kinds = {note.kind for note in result.review_notes}
    assert "ratified" in kinds


def test_pipeline_ratification_no_write_under_compare_mode(monkeypatch, tmp_path):
    human_sha = "a" * 64
    envelopes = {human_sha: _ratify_envelope("demo-pool", human_sha, _RATIFY_PAYLOAD)}
    _, write_spy, save_state_calls = _install_pipeline_stubs(
        monkeypatch, tmp_path, payload=_RATIFY_PAYLOAD, envelopes_by_sha=envelopes, new_sha="b" * 64,
    )
    _, _, results = pipeline_mod.run_pipeline(
        slugs=None, provider="gemini", compare_with="anthropic", force=False, dry_run=False,
    )
    # compare_with is observational — never writes, for content or for ratified snapshots.
    assert write_spy.call_count == 0
    assert save_state_calls == []


def test_pipeline_ratification_writes_on_live_run(monkeypatch, tmp_path):
    human_sha = "a" * 64
    envelopes = {human_sha: _ratify_envelope("demo-pool", human_sha, _RATIFY_PAYLOAD)}
    _, write_spy, _ = _install_pipeline_stubs(
        monkeypatch, tmp_path, payload=_RATIFY_PAYLOAD, envelopes_by_sha=envelopes, new_sha="b" * 64,
    )
    pipeline_mod.run_pipeline(
        slugs=None, provider="gemini", compare_with=None, force=False, dry_run=False,
    )
    assert write_spy.call_count == 1
    assert write_spy.call_args.kwargs["ratified_from_sha256"] == human_sha


def test_pipeline_ratification_prefers_human_over_ratified_ancestor(monkeypatch, tmp_path):
    human_sha = "1" * 64
    ratification_sha = "2" * 64
    envelopes = {
        ratification_sha: _ratify_envelope("demo-pool", ratification_sha, _RATIFY_PAYLOAD, reviewed_by="ratification"),
        human_sha: _ratify_envelope("demo-pool", human_sha, _RATIFY_PAYLOAD),
    }
    # Force the ratification-born snapshot to be visited first; human preference must still win.
    _, write_spy, _ = _install_pipeline_stubs(
        monkeypatch,
        tmp_path,
        payload=_RATIFY_PAYLOAD,
        envelopes_by_sha=envelopes,
        new_sha="9" * 64,
        snapshot_order=[ratification_sha, human_sha],
    )
    pipeline_mod.run_pipeline(
        slugs=None, provider="gemini", compare_with=None, force=False, dry_run=False,
    )
    assert write_spy.call_count == 1
    assert write_spy.call_args.kwargs["ratified_from_sha256"] == human_sha


def test_pipeline_ratification_emits_malformed_note_and_continues(monkeypatch, tmp_path):
    human_sha = "1" * 64
    bad_sha = "f" * 64
    envelopes = {human_sha: _ratify_envelope("demo-pool", human_sha, _RATIFY_PAYLOAD)}
    _, write_spy, _ = _install_pipeline_stubs(
        monkeypatch,
        tmp_path,
        payload=_RATIFY_PAYLOAD,
        envelopes_by_sha=envelopes,
        new_sha="9" * 64,
        snapshot_order=[bad_sha, human_sha],
        bad_shas=(bad_sha,),
    )
    _, _, results = pipeline_mod.run_pipeline(
        slugs=None, provider="gemini", compare_with=None, force=False, dry_run=False,
    )
    [result] = results
    kinds = {note.kind for note in result.review_notes}
    # Malformed envelope surfaced as a warning review note rather than silently swallowed.
    assert "reviewed_snapshot_malformed" in kinds
    # Ratification still succeeded against the healthy snapshot.
    assert "ratified" in kinds
    assert write_spy.call_args.kwargs["ratified_from_sha256"] == human_sha
