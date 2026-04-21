from schedules.signals import analyze_page_texts, source_notes_for_payload


def test_analyze_page_texts_detects_multi_grid():
    signals = analyze_page_texts(
        [
            "TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY\n^ LAP SWIM ^\n3:30 PM - 6:00 PM",
            "TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY\nFAMILY SWIM\n9:00 AM - 10:30 AM",
        ]
    )
    assert signals.page_count == 2
    assert signals.grid_header_pages == [1, 2]

    notes = source_notes_for_payload(
        signals,
        {
            "sessions": [{"day": "saturday", "type": "lap_swim", "start": "15:30", "end": "18:00"}],
            "closures": [],
            "schedule_effective": "2026-03-17",
        },
    )
    messages = [note.message for note in notes]
    assert any("repeated day-grid pages" in message for message in messages)
