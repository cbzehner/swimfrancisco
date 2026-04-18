from schedules.models import ReviewNote
from schedules.state import build_state_entry, entry_for, load_state, notes_for_entry, save_state


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = {
        "balboa-pool": build_state_entry(
            pdf_sha256="abc123",
            provider="gemini",
            model="gemini-3.1-flash-lite-preview",
            notes=[ReviewNote(kind="manual_review", message="manual review")],
            artifact_paths={"gemini": "data/artifacts/balboa/abc123/gemini.json"},
            pdf_page_count=1,
            pdf_text_sha256="textsha",
            reviewed_snapshot_sha256="adjsha",
        )
    }
    save_state(state, path)
    loaded = load_state(path)
    assert entry_for("balboa-pool", path=path) == loaded["balboa-pool"]
    assert loaded["balboa-pool"]["pdf_sha256"] == "abc123"
    assert loaded["balboa-pool"]["reviewed_snapshot_sha256"] == "adjsha"
    assert notes_for_entry(loaded["balboa-pool"])[0].message == "manual review"


def test_state_entry_carries_only_provenance():
    entry = build_state_entry(
        pdf_sha256="abc",
        provider="anthropic",
        model="claude",
        notes=[],
        artifact_paths={},
        pdf_page_count=2,
        pdf_text_sha256="txt",
    )
    # Fields derivable from content/spots/*.md must NOT live in state.
    assert "sessions_count" not in entry
    assert "session_types" not in entry
    assert "schedule_effective" not in entry
    assert "invariants_passed" not in entry
    assert "pdf_url" not in entry
