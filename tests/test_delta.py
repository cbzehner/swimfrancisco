from schedules.delta import check_delta
from schedules.validate import validate


def test_delta_notes_large_changes_and_missing_types():
    extracted = {
        "sessions": [{"day": "monday", "type": "family_swim", "start": "10:00", "end": "11:00"}],
        "schedule_effective": "2026-03-01",
    }
    prior = {
        "sessions_count": 10,
        "session_types": ["lap_swim", "family_swim"],
        "schedule_effective": "2026-03-17",
    }
    notes = check_delta(extracted, prior)
    messages = [note.message for note in notes]
    assert any("session count changed" in message for message in messages)
    assert any("lap_swim" in message for message in messages)
    assert any("regressed" in message for message in messages)


def test_validate_flags_drop_to_zero_as_catastrophic():
    extracted = {"sessions": [], "closures": []}
    result = validate(extracted, prior_sessions_count=8)
    assert result.catastrophic is True
    assert any("sessions_count dropped to 0" in violation for violation in result.violations)
