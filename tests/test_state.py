from schedules.models import ReviewFlag
from schedules.state import build_state_entry, entry_for, flags_for_entry, load_state, save_state


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = {
        "balboa-pool": build_state_entry(
            pdf_url="https://example.com/balboa.pdf",
            pdf_sha256="abc123",
            sessions_count=7,
            session_types=["lap_swim", "family_swim"],
            schedule_effective="2026-03-17",
            provider="gemini",
            model="gemini-3.1-flash-lite-preview",
            invariants_passed=True,
            flags=[ReviewFlag(kind="manual_review", message="manual review")],
            artifact_paths={"gemini": "data/artifacts/balboa/abc123/gemini.json"},
            pdf_page_count=1,
            pdf_text_sha256="textsha",
            adjudication_sha256="adjsha",
        )
    }
    save_state(state, path)
    loaded = load_state(path)
    assert entry_for("balboa-pool", path=path) == loaded["balboa-pool"]
    assert loaded["balboa-pool"]["sessions_count"] == 7
    assert loaded["balboa-pool"]["adjudication_sha256"] == "adjsha"
    assert flags_for_entry(loaded["balboa-pool"])[0].message == "manual review"
