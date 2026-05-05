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


def _five_weekday_sessions() -> list[dict]:
    return [
        {"day": d, "type": "lap_swim", "start": "06:00", "end": "07:00"}
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
    ]


def test_validate_accepts_partial_day_closure():
    payload = {
        "sessions": _five_weekday_sessions(),
        "closures": [{
            "start": "2026-05-21",
            "end": "2026-05-21",
            "start_time": "11:00",
            "end_time": "14:00",
            "reason": "Aquatics training",
        }],
        "schedule_effective": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is True


def test_validate_rejects_partial_day_closure_with_only_one_time():
    payload = {
        "sessions": _five_weekday_sessions(),
        "closures": [{
            "start": "2026-05-21",
            "end": "2026-05-21",
            "start_time": "11:00",
            "reason": "Aquatics training",
        }],
        "schedule_effective": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any("both start_time and end_time" in v for v in result.violations)


def test_validate_rejects_partial_day_closure_with_inverted_times():
    payload = {
        "sessions": _five_weekday_sessions(),
        "closures": [{
            "start": "2026-05-21",
            "end": "2026-05-21",
            "start_time": "15:00",
            "end_time": "11:00",
            "reason": "Aquatics training",
        }],
        "schedule_effective": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any("invalid time range" in v for v in result.violations)


def test_validate_rejects_partial_day_closure_on_multi_day_range():
    payload = {
        "sessions": _five_weekday_sessions(),
        "closures": [{
            "start": "2026-05-21",
            "end": "2026-05-22",
            "start_time": "11:00",
            "end_time": "14:00",
            "reason": "Aquatics training",
        }],
        "schedule_effective": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any("multi-day" in v for v in result.violations)

