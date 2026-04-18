from schedules.delta import check_delta


def test_delta_flags_large_changes_and_missing_types():
    extracted = {
        "sessions": [{"day": "monday", "type": "family_swim", "start": "10:00", "end": "11:00"}],
        "schedule_effective": "2026-03-01",
    }
    prior = {
        "sessions_count": 10,
        "session_types": ["lap_swim", "family_swim"],
        "schedule_effective": "2026-03-17",
    }
    result = check_delta(extracted, prior)
    assert result.hard_block is False
    assert any("session count changed" in flag for flag in result.flags)
    assert any("lap_swim" in flag for flag in result.flags)
    assert any("regressed" in flag for flag in result.flags)


def test_delta_hard_blocks_drop_to_zero():
    extracted = {"sessions": [], "schedule_effective": "2026-03-17"}
    prior = {"sessions_count": 8, "session_types": ["lap_swim"], "schedule_effective": "2026-03-17"}
    result = check_delta(extracted, prior)
    assert result.hard_block is True

