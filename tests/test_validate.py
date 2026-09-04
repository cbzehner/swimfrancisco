from schedules.validate import validate


def test_validate_accepts_reasonable_payload():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "06:00", "end": "07:00", "evidence": "Lap Swim 6-7am"},
            {"day": "tuesday", "type": "lap_swim", "start": "06:00", "end": "07:00", "evidence": "Lap Swim 6-7am"},
            {"day": "wednesday", "type": "lap_swim", "start": "06:00", "end": "07:00", "evidence": "Lap Swim 6-7am"},
            {"day": "thursday", "type": "lap_swim", "start": "06:00", "end": "07:00", "evidence": "Lap Swim 6-7am"},
            {"day": "friday", "type": "lap_swim", "start": "06:00", "end": "07:00", "evidence": "Lap Swim 6-7am"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is True
    assert result.stats == {"sessions": 5, "closures": 0, "access_hours": 0, "access_exceptions": 0}


def test_validate_accepts_access_hours_without_sessions():
    payload = {
        "schedule_basis": "facility_hours",
        "sessions": [],
        "access_hours": [
            {"day": "monday", "start": "05:30", "end": "20:30", "label": "Facility hours", "evidence": "Facility hours 5:30am-8:30pm"}
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is True
    assert result.stats == {"sessions": 0, "closures": 0, "access_hours": 1, "access_exceptions": 0}


def test_validate_accepts_access_exceptions():
    payload = {
        "sessions": [],
        "schedule_basis": "facility_hours",
        "access_hours": [
            {"day": "monday", "start": "06:30", "end": "19:45", "label": "Facility hours", "evidence": "Facility hours 6:30am-7:45pm"}
        ],
        "access_exceptions": [
            {
                "date": "2026-05-25",
                "start": "08:00",
                "end": "13:30",
                "label": "Holiday facility hours",
                "reason": "Memorial Day",
                "evidence": "Memorial Day hours 8am-1:30pm",
            }
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }

    result = validate(payload)

    assert result.ok is True
    assert result.stats == {"sessions": 0, "closures": 0, "access_hours": 1, "access_exceptions": 1}


def test_validate_accepts_temporarily_closed_without_sessions_or_access_hours():
    result = validate({
        "effective_start": "2026-05-17",
        "schedule_basis": "temporarily_closed",
        "sessions": [],
        "access_hours": [],
        "closures": [
            {"start": "2026-05-17", "end": "2026-05-22", "reason": "Renovation"}
        ],
    })

    assert result.ok


def test_validate_temporarily_closed_empty_sessions_not_catastrophic_with_prior():
    result = validate(
        {
            "effective_start": "2026-08-14",
            "schedule_basis": "temporarily_closed",
            "sessions": [],
            "access_hours": [],
            "closures": [
                {"start": "2026-08-14", "end": "2026-09-07", "reason": "Maintenance"}
            ],
        },
        prior_sessions_count=8,
    )

    assert result.catastrophic is False
    assert not any(v.code == "sessions_dropped_to_zero" for v in result.violations)
    assert result.ok


def test_validate_rejects_unknown_schedule_basis_value():
    result = validate({
        "effective_start": "2026-05-17",
        "schedule_basis": "made_up",
        "sessions": [],
        "closures": [],
    })

    assert any(
        v.code == "schema_violation" and "schedule_basis" in v.message
        for v in result.violations
    )


def test_validate_flags_bad_ranges():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "07:00", "evidence": "Lap Swim 7-7am"}],
        "closures": [{"start": "2026-04-18", "end": "2026-04-17", "reason": "maintenance"}],
        "effective_start": "not-a-date",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(v.code == "invalid_session_time_range" for v in result.violations)
    assert any(v.code == "invalid_closure_date_range" for v in result.violations)
    assert any(v.code == "invalid_schedule_effective_date" for v in result.violations)


def test_validate_rejects_invalid_effective_end_date():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": _five_weekday_sessions(),
        "closures": [],
        "effective_start": "2026-09-01",
        "effective_end": "2026-99-99",
    }

    result = validate(payload)

    assert result.ok is False
    assert any(
        violation.code == "invalid_schedule_effective_end_date"
        for violation in result.violations
    )


def test_validate_rejects_effective_end_before_start():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": _five_weekday_sessions(),
        "closures": [],
        "effective_start": "2026-09-01",
        "effective_end": "2026-08-31",
    }

    result = validate(payload)

    assert result.ok is False
    assert any(
        violation.code == "invalid_schedule_effective_date_range"
        for violation in result.violations
    )


def test_validate_rejects_impossible_closure_dates():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": _five_weekday_sessions(),
        "closures": [
            {"start": "2026-99-01", "end": "2026-99-02", "reason": "Maintenance"}
        ],
        "effective_start": "2026-09-01",
    }

    result = validate(payload)

    assert result.ok is False
    assert any(v.code == "invalid_closure_date_range" for v in result.violations)


def _five_weekday_sessions() -> list[dict]:
    return [
        {"day": d, "type": "lap_swim", "start": "06:00", "end": "07:00", "evidence": "Lap Swim 6-7am"}
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
    ]


def test_validate_accepts_partial_day_closure():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": _five_weekday_sessions(),
        "closures": [{
            "start": "2026-05-21",
            "end": "2026-05-21",
            "start_time": "11:00",
            "end_time": "14:00",
            "reason": "Aquatics training",
        }],
        "effective_start": "2026-03-17",
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
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(v.code == "incomplete_closure_time_range" for v in result.violations)


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
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(v.code == "invalid_closure_time_range" for v in result.violations)


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
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(v.code == "multi_day_closure_with_time_range" for v in result.violations)


def test_validate_rejects_bad_day_enum():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": "funday", "type": "lap_swim", "start": "06:00", "end": "07:00"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(
        v.code == "schema_violation" and "$.sessions[0].day" in v.message
        for v in result.violations
    )


def test_validate_rejects_bad_session_type():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": "monday", "type": "water_polo", "start": "06:00", "end": "07:00"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(
        v.code == "schema_violation" and "$.sessions[0].type" in v.message
        for v in result.violations
    )


def test_validate_rejects_malformed_time_string():
    payload = {
        "schedule_basis": "swim_schedule",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "9:00", "end": "10:00"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    result = validate(payload)
    assert result.ok is False
    assert any(
        v.code == "schema_violation" and "$.sessions[0].start" in v.message
        for v in result.violations
    )
