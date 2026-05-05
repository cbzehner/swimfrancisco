from schedules.grounding import _normalize, _start_variants, grounding_from_text


def test_grounded_session_passes_all_three_checks():
    pdf_text = _normalize(
        "Lap Swim\n"
        "Monday 6:00 - 7:30 AM\n"
        "Senior Swim Wednesday 12:50 - 3:15 PM"
    )
    payload = {
        "sessions": [
            {
                "day": "monday",
                "type": "lap_swim",
                "start": "06:00",
                "end": "07:30",
                "evidence": "Lap Swim Monday 6:00 - 7:30 AM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    assert result.grounded_count == 1
    assert result.total == 1
    assert result.sessions[0].grounded is True


def test_evidence_absent_from_pdf_is_not_grounded():
    pdf_text = _normalize("Lap Swim Monday 6:00 - 7:30 AM")
    payload = {
        "sessions": [
            {
                "day": "wednesday",
                "type": "family_swim",
                "start": "11:45",
                "end": "12:45",
                "evidence": "Rec/Family Swim Wednesday 11:45 AM - 12:45 PM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    assert result.grounded_count == 0
    entry = result.sessions[0]
    assert entry.evidence_in_pdf is False
    assert entry.grounded is False


def test_start_time_not_in_evidence_is_not_grounded():
    pdf_text = _normalize("Lap Swim Monday 6:00 - 7:30 AM")
    payload = {
        "sessions": [
            {
                "day": "monday",
                "type": "lap_swim",
                "start": "09:00",
                "end": "10:00",
                "evidence": "Lap Swim Monday 6:00 - 7:30 AM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    entry = result.sessions[0]
    assert entry.evidence_in_pdf is True
    assert entry.start_in_evidence is False
    assert entry.grounded is False


def test_type_token_not_in_evidence_is_not_grounded():
    pdf_text = _normalize("Lap Swim Monday 6:00 - 7:30 AM")
    payload = {
        "sessions": [
            {
                "day": "monday",
                "type": "family_swim",
                "start": "06:00",
                "end": "07:30",
                "evidence": "Lap Swim Monday 6:00 - 7:30 AM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    entry = result.sessions[0]
    assert entry.evidence_in_pdf is True
    assert entry.start_in_evidence is True
    assert entry.type_in_evidence is False
    assert entry.grounded is False


def test_rec_family_evidence_grounds_as_family_swim():
    pdf_text = _normalize("REC/ FAMILY SWIM Monday 2:00 - 3:00 PM")
    payload = {
        "sessions": [
            {
                "day": "monday",
                "type": "family_swim",
                "start": "14:00",
                "end": "15:00",
                "evidence": "REC/ FAMILY SWIM Monday 2:00 - 3:00 PM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    assert result.grounded_count == 1


def test_missing_evidence_field_flags_without_crash():
    pdf_text = _normalize("anything goes here")
    payload = {
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "06:00", "end": "07:30"}
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    entry = result.sessions[0]
    assert entry.missing_evidence is True
    assert entry.grounded is False


def test_start_variants_cover_12h_and_on_the_hour():
    variants = _start_variants("13:00")
    assert "13:00" in variants
    assert "1:00pm" in variants
    assert "1:00 pm" in variants
    assert "1pm" in variants
    assert "1 pm" in variants


def test_start_variants_with_minutes_skip_hour_only_form():
    variants = _start_variants("11:45")
    assert "11:45" in variants
    assert "11:45am" in variants
    assert "11am" not in variants


def test_normalize_strips_periods_and_collapses_whitespace():
    assert _normalize("Lap  Swim   6:00 a.m.") == "lap swim 6:00 am"


def test_cross_line_pdf_text_grounds_evidence():
    # pypdf serializes calendar grids as program-label-band then time-band,
    # so verbatim cell text never appears as a contiguous substring. The
    # grounder must accept evidence whose tokens appear in order within a
    # window of the source text, even when intervening cells are interleaved.
    pdf_text = _normalize(
        "Lap Swim Lap Swim Lap Swim Lap Swim Rec/Family Swim\n"
        "11:00 AM - 1:00 PM 11:00 AM - 1:00 PM 11:30 AM - 1:30 PM "
        "11:00 AM - 1:00 PM 10:45 AM - 12:00 PM"
    )
    payload = {
        "sessions": [
            {
                "day": "tuesday",
                "type": "lap_swim",
                "start": "11:00",
                "end": "13:00",
                "evidence": "Lap Swim 11:00 AM - 1:00 PM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    entry = result.sessions[0]
    assert entry.evidence_in_pdf is True, "cross-line cell text must ground"
    assert entry.grounded is True


def test_ignore_only_evidence_is_not_grounded():
    # Model emits a row whose evidence references an ignore-list program
    # with no allowed-type token. This is a policy error and must fail.
    pdf_text = _normalize("MASTER'S SWIM TEAM Tuesday 5:30PM - 7:00PM")
    payload = {
        "sessions": [
            {
                "day": "tuesday",
                "type": "lap_swim",
                "start": "17:30",
                "end": "19:00",
                "evidence": "MASTER'S SWIM TEAM 5:30PM - 7:00PM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    entry = result.sessions[0]
    assert entry.grounded is False


def test_multi_program_cell_with_kept_type_is_grounded():
    # A single cell can list multiple co-existing programs ("LAP SWIM /
    # SELF GUIDED EXERCISE 9:00–11:00"). When the kept type is also present,
    # the row must ground despite the ignore-list token.
    pdf_text = _normalize(
        "LAP SWIM (4) SELF GUIDED EXERCISE (2) 9:00 AM - 11:00 AM"
    )
    payload = {
        "sessions": [
            {
                "day": "tuesday",
                "type": "lap_swim",
                "start": "09:00",
                "end": "11:00",
                "evidence": "LAP SWIM (4) SELF GUIDED EXERCISE (2) 9:00 AM - 11:00 AM",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    assert result.grounded_count == 1


def test_paraphrased_evidence_with_matching_type_and_time_is_not_grounded():
    # Evidence is plausible prose containing the right type+time tokens but is
    # NOT a verbatim substring of the PDF. The grounding check must reject it.
    pdf_text = _normalize("Lap Swim Monday 6:00 - 7:30 AM")
    payload = {
        "sessions": [
            {
                "day": "monday",
                "type": "lap_swim",
                "start": "06:00",
                "end": "07:30",
                "evidence": "Lap Swim Monday from 6am until 7:30am",
            }
        ]
    }
    result = grounding_from_text(pdf_text, payload)
    entry = result.sessions[0]
    assert entry.evidence_in_pdf is False
    assert entry.start_in_evidence is True
    assert entry.type_in_evidence is True
    assert entry.type_in_pdf_text is True
    assert entry.grounded is False, "paraphrased evidence must not pass grounding"
