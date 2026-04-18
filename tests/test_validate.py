from schedules.validate import validate


def test_validate_accepts_reasonable_payload():
    payload = {
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "tuesday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "wednesday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "thursday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
            {"day": "friday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
        ],
        "closures": [],
        "schedule_effective": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is True
    assert result.stats == {"sessions": 5, "closures": 0}


def test_validate_flags_bad_ranges():
    payload = {
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "07:00"}],
        "closures": [{"start": "2026-04-18", "end": "2026-04-17", "reason": "maintenance"}],
        "schedule_effective": "not-a-date",
    }
    result = validate(payload)
    assert result.ok is False
    assert len(result.violations) == 4

