from schedules.signals import analyze_page_texts, source_notes_for_payload


def test_analyze_page_texts_detects_multi_grid_and_timed_lessons():
    signals = analyze_page_texts(
        [
            "TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY\n^ SWIM LESSONS ^\n3:30 PM - 6:00 PM",
            "TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY\nSWIM LESSONS LEVEL 1\n9:00 - 9:30 AM",
        ]
    )
    assert signals.page_count == 2
    assert signals.grid_header_pages == [1, 2]
    assert signals.timed_lesson_line_count == 2

    notes = source_notes_for_payload(
        signals,
        {
            "sessions": [{"day": "saturday", "type": "lessons", "start": "09:00", "end": "09:30"}],
            "closures": [],
            "schedule_effective": "2026-03-17",
        },
    )
    messages = [note.message for note in notes]
    assert any("repeated day-grid pages" in message for message in messages)
    assert any("timed lesson-like lines" in message for message in messages)
