from schedules.review import compare_payloads


def test_compare_payloads_flags_pool_only_session_disagreement():
    # Providers agree on (day, type, start, end) but disagree on the pool zone
    # label. Before the session key included `pool`, this was invisible.
    primary = {
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "shallow"},
        ],
        "closures": [],
        "schedule_effective": "2026-03-17",
    }
    secondary = {
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "deep"},
        ],
        "closures": [],
        "schedule_effective": "2026-03-17",
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
        "schedule_effective": "2026-03-17",
    }
    secondary = {
        "sessions": [
            {"day": "friday", "type": "family_swim", "start": "15:30", "end": "17:00"},
        ],
        "closures": [],
        "schedule_effective": "2026-03-17",
    }
    flags = compare_payloads("gemini", primary, "anthropic", secondary)
    kinds = {flag.kind for flag in flags}
    assert "provider_session_diff" in kinds


def test_compare_payloads_flags_provider_differences():
    primary = {
        "sessions": [{"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30"}],
        "closures": [],
        "schedule_effective": "2026-03-17",
    }
    secondary = {
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "thursday", "type": "lessons", "start": "15:30", "end": "18:00"},
        ],
        "closures": [{"start": "2026-06-06", "end": "2026-06-06", "reason": "training"}],
        "schedule_effective": "2026-03-18",
    }
    flags = compare_payloads("gemini", primary, "anthropic", secondary)
    kinds = {flag.kind for flag in flags}
    assert "provider_session_count_disagreement" in kinds
    assert "provider_session_diff" in kinds
    assert "provider_closure_diff" in kinds
    assert "provider_schedule_effective_diff" in kinds
