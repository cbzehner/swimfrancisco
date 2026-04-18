from schedules.delta import check_delta
from schedules.validate import validate


def test_delta_notes_large_changes_and_missing_types():
    extracted = {
        "sessions": [{"day": "monday", "type": "family_swim", "start": "10:00", "end": "11:00"}],
        "schedule_effective": "2026-03-01",
    }
    prior_snapshot = {
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"},
            {"day": "tuesday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "tuesday", "type": "family_swim", "start": "10:00", "end": "11:00"},
            {"day": "wednesday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "wednesday", "type": "family_swim", "start": "10:00", "end": "11:00"},
            {"day": "thursday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "friday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "saturday", "type": "family_swim", "start": "10:00", "end": "11:00"},
            {"day": "sunday", "type": "family_swim", "start": "10:00", "end": "11:00"},
        ],
        "closures": [],
        "schedule_effective": "2026-03-17",
    }
    notes = check_delta(extracted, prior_snapshot)
    messages = [note.message for note in notes]
    assert any("session count changed" in message for message in messages)
    assert any("lap_swim" in message for message in messages)
    assert any("regressed" in message for message in messages)


def test_delta_returns_no_notes_for_empty_prior():
    extracted = {"sessions": [{"type": "lap_swim"}], "schedule_effective": "2026-03-01"}
    notes = check_delta(extracted, {"sessions": [], "closures": [], "schedule_effective": None})
    assert notes == []


def test_validate_flags_drop_to_zero_as_catastrophic():
    extracted = {"sessions": [], "closures": []}
    result = validate(extracted, prior_sessions_count=8)
    assert result.catastrophic is True
    assert any("sessions_count dropped to 0" in violation for violation in result.violations)
