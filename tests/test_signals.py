from schedules.signals import analyze_page_texts, source_notes_for_signals


def test_analyze_page_texts_detects_multi_grid():
    signals = analyze_page_texts(
        [
            "TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY\n^ LAP SWIM ^\n3:30 PM - 6:00 PM",
            "TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY\nFAMILY SWIM\n9:00 AM - 10:30 AM",
        ]
    )
    assert signals == [1, 2]

    notes = source_notes_for_signals(signals)
    messages = [note.message for note in notes]
    assert any("repeated day-grid pages" in message for message in messages)
