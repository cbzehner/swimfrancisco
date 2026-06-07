from schedules.diff import compare_payloads


def test_compare_payloads_flags_pool_only_session_disagreement():
    # Providers agree on day/type/time but disagree on the pool zone
    # label. Before the session key included `pool`, this was invisible.
    primary = {
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "shallow"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    secondary = {
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "deep"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    flags = compare_payloads("gemini", primary, "anthropic", secondary)
    kinds = {flag.kind for flag in flags}
    assert "provider_session_diff" in kinds, (
        "pool-only disagreement must surface as a session diff"
    )


def test_compare_payloads_flags_notes_only_session_disagreement():
    # Same as above but for `notes`. Per-session caveats that differ across
    # providers are worth surfacing.
    primary = {
        "sessions": [
            {"day": "friday", "type": "family_swim", "start": "15:30", "end": "17:00", "notes": "closed 3rd thursday"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    secondary = {
        "sessions": [
            {"day": "friday", "type": "family_swim", "start": "15:30", "end": "17:00"},
        ],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    flags = compare_payloads("gemini", primary, "anthropic", secondary)
    kinds = {flag.kind for flag in flags}
    assert "provider_session_diff" in kinds


def test_compare_payloads_flags_provider_differences():
    primary = {
        "sessions": [{"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30"}],
        "closures": [],
        "effective_start": "2026-03-17",
    }
    secondary = {
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "thursday", "type": "senior_swim", "start": "15:30", "end": "18:00"},
        ],
        "closures": [{"start": "2026-06-06", "end": "2026-06-06", "reason": "training"}],
        "effective_start": "2026-03-18",
    }
    flags = compare_payloads("gemini", primary, "anthropic", secondary)
    kinds = {flag.kind for flag in flags}
    assert "provider_session_count_disagreement" in kinds
    assert "provider_session_diff" in kinds
    assert "provider_closure_diff" in kinds
    assert "provider_schedule_effective_diff" in kinds


def test_compare_payloads_flags_timed_closure_disagreement():
    primary = {
        "sessions": [],
        "closures": [
            {
                "start": "2026-05-21",
                "end": "2026-05-21",
                "reason": "Staff training",
                "start_time": "11:00",
                "end_time": "15:00",
            }
        ],
        "effective_start": "2026-03-17",
    }
    secondary = {
        "sessions": [],
        "closures": [
            {
                "start": "2026-05-21",
                "end": "2026-05-21",
                "reason": "Staff training",
            }
        ],
        "effective_start": "2026-03-17",
    }

    flags = compare_payloads("gemini", primary, "anthropic", secondary)
    kinds = {flag.kind for flag in flags}
    assert "provider_closure_diff" in kinds
