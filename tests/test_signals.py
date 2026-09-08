from schedules.signals import analyze_page_texts, source_notes_for_signals

import copy
import json
import zipfile

import pytest

from schedules._time import printed_time_range
from schedules.eval import load_benchmark_reference
from schedules.grounding import source_closure_coverage, source_coverage, source_publication_coverage, source_window_coverage
from schedules.signals import PdfSource, SourceNotice
from schedules.paths import REPO_ROOT
from schedules.signals import inspect_pdf_source, program_types


MANIFEST = REPO_ROOT / "tests/fixtures/schedule-benchmark.json"
REFERENCE_IDS = json.loads(MANIFEST.read_text())["comparisons"]["literal-pool-labels"]["references"]


@pytest.fixture(scope="module", params=REFERENCE_IDS)
def source_reference(request):
    reference = load_benchmark_reference(MANIFEST, request.param, repo_root=REPO_ROOT)
    return inspect_pdf_source((REPO_ROOT / reference["source_pdf"]).read_bytes()), reference


def test_coordinate_inventory_covers_preserved_reference_sessions(source_reference):
    source, reference = source_reference
    coverage = source_coverage(source, reference["expected"], visual_pages=frozenset({1}))
    assert coverage["ok"], coverage
    assert coverage["expected_count"] == len(reference["expected"]["sessions"])
    assert all(coverage["session_cells"])
    assert len({cell.id for cell in source.cells}) == len(source.cells)
    assert all(cell.bounds[0] < cell.bounds[2] and cell.bounds[1] < cell.bounds[3] for cell in source.cells)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "day", "type", "start", "end", "pool"])
def test_inventory_rejects_each_missing_or_changed_session(source_reference, damage):
    source, reference = source_reference
    for index in range(len(reference["expected"]["sessions"])):
        payload = copy.deepcopy(reference["expected"])
        row = payload["sessions"][index]
        if damage == "missing":
            payload["sessions"].pop(index)
        elif damage == "duplicate":
            payload["sessions"].append(copy.deepcopy(row))
        elif damage == "day":
            row["day"] = "monday" if row["day"] != "monday" else "tuesday"
        elif damage == "type":
            row["type"] = "family_swim" if row["type"] != "family_swim" else "lap_swim"
        elif damage == "pool":
            row["pool"] = "wrong allocation"
        else:
            row[damage] = "00:01"
        assert not source_coverage(source, payload, visual_pages=frozenset({1}))["ok"], (reference["id"], index, damage)


def test_broken_text_requires_a_visual_input(source_reference):
    source, reference = source_reference
    if reference["id"] == "balboa-interim":
        assert any(issue.endswith(":unbalanced_text") for issue in source.issues)
        assert not source_coverage(source, reference["expected"])["ok"]
        assert source_coverage(source, reference["expected"], visual_pages=frozenset({1}))["ok"]


def test_printed_window_matches_reference_and_rejects_date_changes(source_reference):
    source, reference = source_reference
    payload = reference["expected"]
    assert source_window_coverage(source, payload)["ok"]
    for field in ("effective_start", "effective_end"):
        assert not source_window_coverage(source, payload | {field: "2099-01-01"})["ok"]
        assert not source_window_coverage(source, payload | {field: None})["ok"]


def test_printed_window_does_not_borrow_year_from_a_holiday_note():
    text = "Schedule June 9-August 15\nTUESDAY WEDNESDAY THURSDAY\nClosed July 4, 2026"
    source = PdfSource(text, (), (), 1, ())
    payload = {"effective_start": "2026-06-09", "effective_end": "2026-08-15"}
    assert not source_window_coverage(source, payload)["ok"]


def test_mission_holdout_matches_frozen_visual_transcription():
    reference = load_benchmark_reference(MANIFEST, "mission-fall-holdout", repo_root=REPO_ROOT)
    source = inspect_pdf_source((REPO_ROOT / reference["source_pdf"]).read_bytes())
    assert source_coverage(source, reference["expected"])["ok"]
    assert source_window_coverage(source, reference["expected"])["ok"]
    assert len(reference["expected"]["sessions"]) == 25
    assert len(reference["expected"]["closures"]) == 5


def test_coffman_list_omits_only_independently_closed_thanksgiving():
    from dataclasses import replace
    from schedules.grounding import source_excluded_dates
    from schedules.providers.openai_provider import source_request

    source = inspect_pdf_source((REPO_ROOT / "data/coffman-pool/2026-08-20-0345cb25881b/source.pdf").read_bytes())
    assert not source.issues
    assert list(source_excluded_dates(source).values()) == [["2026-08-27", "2026-09-24", "2026-10-22"]]
    source_request(source, "extract", {})
    without_holiday = replace(source, notices=tuple(notice for notice in source.notices if "Thanksgiving" not in notice.text))
    with pytest.raises(ValueError, match="conflicting_recurring_closure_dates"):
        source_excluded_dates(without_holiday)


@pytest.mark.parametrize("reference_id", ["north-beach-expired", "garfield-maintenance"])
def test_closure_inventory_rejects_each_omission_and_change(reference_id):
    reference = load_benchmark_reference(MANIFEST, reference_id, repo_root=REPO_ROOT)
    source = inspect_pdf_source((REPO_ROOT / reference["source_pdf"]).read_bytes())
    assert source_closure_coverage(source, reference["expected"])["ok"]
    for index in range(len(reference["expected"]["closures"])):
        for damage in ("missing", "duplicate", "start", "end", "time"):
            payload = copy.deepcopy(reference["expected"])
            row = payload["closures"][index]
            if damage == "missing":
                payload["closures"].pop(index)
            elif damage == "duplicate":
                payload["closures"].append(copy.deepcopy(row))
            elif damage == "time":
                row.update(start_time="12:00", end_time="14:00")
            else:
                row[damage] = "2099-01-01"
            assert not source_publication_coverage(source, payload)["ok"], (index, damage)


def test_archived_missing_holiday_is_rejected_without_changing_benchmark_answers():
    with zipfile.ZipFile(REPO_ROOT / "benchmarks/pdf/physical-pool-labels-2026-09-05.zip") as archive:
        rows = json.loads(archive.read("results.json"))
    row = next(row for row in rows if row["reference"] == "north-beach-expired" and row["repetition"] == 2)
    reference = load_benchmark_reference(MANIFEST, row["reference"], repo_root=REPO_ROOT)
    source = inspect_pdf_source((REPO_ROOT / reference["source_pdf"]).read_bytes())
    assert source_coverage(source, row["payload"])["ok"]
    result = source_publication_coverage(source, row["payload"])
    assert not result["ok"]
    assert result["closures"]["missing"] == [["2026-07-04", "2026-07-04", None, None]]


@pytest.mark.parametrize("reference_id", ["balboa-fall", "balboa-interim", "rossi-spring"])
def test_unresolved_cell_closures_remain_held(reference_id):
    reference = load_benchmark_reference(MANIFEST, reference_id, repo_root=REPO_ROOT)
    source = inspect_pdf_source((REPO_ROOT / reference["source_pdf"]).read_bytes())
    result = source_closure_coverage(source, reference["expected"])
    assert not result["ok"]
    assert any("unresolved_closure" in issue for issue in result["issues"])


def _notice_source(text, window="August 18-December 12, 2026"):
    return PdfSource(f"Schedule {window}", (), (), 1, (SourceNotice("test-notice", text, True),))


@pytest.mark.parametrize("text, expected", [
    ("All pools will be closed on 8/22/26 and 12/12/26 from 8:30 am – 12:30pm for training",
     [["2026-08-22", "2026-08-22", "08:30", "12:30"], ["2026-12-12", "2026-12-12", "08:30", "12:30"]]),
    ("Pool will be closed for maintenance from 11/23 to 11/29/26",
     [["2026-11-23", "2026-11-29", None, None]]),
    ("All pools will be closed every 4th Thursday of the month from 12p-2p for training",
     [[day, day, "12:00", "14:00"] for day in ["2026-08-27", "2026-09-24", "2026-10-22", "2026-11-26"]]),
])
def test_independent_notice_dates_and_times(text, expected):
    source = _notice_source(text)
    assert source_closure_coverage(source, {})["expected"] == expected
    closures = [dict(zip(("start", "end", "start_time", "end_time"), row)) for row in expected]
    assert source_closure_coverage(source, {"closures": closures})["ok"]
    assert not source_closure_coverage(source, {"closures": closures[:-1]})["ok"]
    for row in closures:
        if row["start_time"]:
            row["start_time"] = None
            row["end_time"] = None
            assert not source_closure_coverage(source, {"closures": closures})["ok"]


@pytest.mark.parametrize("text", [
    "Training August 22", "Pool may be closed September 7", "Small pool will be closed September 7",
    "Pool will be closed until September 7",
    "Pool will be closed September 7 morning", "Pool will be closed September 7 after lunch",
    "Pool will be closed every fourth Thursday", "Pool will be closed every 4th Thursday of the month",
    "Pool will be closed every 4th Thursday of the month from 12p-2p (8/27)",
    "Pool will be closed from 11/23 to 11/29/26 from 9am-11am",
])
def test_unclear_notice_is_never_silently_accepted(text):
    result = source_closure_coverage(_notice_source(text), {})
    assert not result["ok"]
    assert any(issue.startswith("test-notice:") for issue in result["issues"])


@pytest.mark.parametrize("start,end,expected", [
    ("7", "8 AM", ("07:00", "08:00")),
    ("10:15", "1:00 PM", ("10:15", "13:00")),
    ("12", "1 PM", ("12:00", "13:00")),
    ("11:45", "1 PM", ("11:45", "13:00")),
    ("10:30am", "Noon", ("10:30", "12:00")),
    ("5:30", "7 PM", ("17:30", "19:00")),
    ("11pm", "midnight", ("23:00", "23:59")),
    ("14:00", "16:00", ("14:00", "16:00")),
    ("2:00pm", "3:30", ("14:00", "15:30")),
    ("12:00 p.m.", "1:15", ("12:00", "13:15")),
])
def test_printed_ranges_resolve_shared_meridiems(start, end, expected):
    assert printed_time_range(start, end) == expected


@pytest.mark.parametrize("start,end", [("7", "8"), ("25:00", "3pm"), ("9:70am", "11am"), ("4pm", "3pm"),
    ("11am", "1"), ("11pm", "1"), ("2pm", "2"), ("2pm", "0:30"), ("14:00", "3:30")])
def test_ambiguous_or_invalid_printed_ranges_are_held(start, end):
    with pytest.raises(ValueError):
        printed_time_range(start, end)


@pytest.mark.parametrize("label,expected", [
    ("S enior/Therapy swim", ("senior_swim",)),
    ("L A P SWIM", ("lap_swim",)),
    ("Senior Lap Swim", ("senior_swim",)),
    ("Family/Lap Swim", ("family_swim", "lap_swim")),
    ("SELF GUIDED EXERCISE", ()),
    ("Senior Swim Team", ()),
    ("Lap Swim / Swim Team", ("lap_swim",)),
])
def test_program_tokens_preserve_shared_programs_and_handle_letter_spacing(label, expected):
    assert program_types(label) == expected


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


@pytest.mark.parametrize("text,expected", [
    ("Pool will be closed November 26 and 27", [("2026-11-26", "2026-11-26", None, None), ("2026-11-27", "2026-11-27", None, None)]),
    ("Pool will be closed Nov. 26th & 27th for Thanksgiving", [("2026-11-26", "2026-11-26", None, None), ("2026-11-27", "2026-11-27", None, None)]),
    ("Pool will be closed 11/26-27 for Thanksgiving", [("2026-11-26", "2026-11-27", None, None)]),
    ("Closed for In-Service August 22, 9am-1pm December 12, 9am-2pm", [("2026-08-22", "2026-08-22", "09:00", "13:00"), ("2026-12-12", "2026-12-12", "09:00", "14:00")]),
])
def test_clear_city_notice_syntax_has_exact_independent_intervals(text, expected):
    source = _notice_source(text)
    result = source_closure_coverage(source, {})
    assert result["expected"] == [list(row) for row in expected]
    assert result["issues"] == ["source_closure_mismatch"]


@pytest.mark.parametrize("capture,dates,count", [
    ("hamilton-pool/2026-08-20-c8e193806d9e", ["2026-08-27", "2026-09-24", "2026-10-22"], 3),
    ("martin-luther-king-jr-pool/2026-08-20-838c12e25ad1", ["2026-08-27", "2026-09-24"], 2),
    ("martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a", ["2026-10-22"], 2),
    ("mission-community-pool/2026-09-02-67f2a420e8fc", ["2026-08-27", "2026-09-24"], 1),
])
def test_frozen_city_cells_cancel_whole_sessions_independently(capture, dates, count):
    from schedules.grounding import source_excluded_dates, source_exclusion_coverage, source_slots

    source = inspect_pdf_source((REPO_ROOT / "data" / capture / "source.pdf").read_bytes())
    exclusions = source_excluded_dates(source)
    assert len(exclusions) == count
    assert all(value == dates for value in exclusions.values())
    sessions = [dict(day=slot.cell.day, type=slot.type, start=slot.start, end=slot.end,
                     pool=slot.pool, excluded_dates=exclusions.get(slot.cell.id, []))
                for slot in source_slots(source)]
    assert source_exclusion_coverage(source, {"sessions": sessions})["ok"]
    for index, session in enumerate(sessions):
        if not session["excluded_dates"]:
            continue
        for replacement in ([], dates[:-1], ["2026-09-25"]):
            damaged = copy.deepcopy(sessions)
            damaged[index]["excluded_dates"] = replacement
            assert not source_exclusion_coverage(source, {"sessions": damaged})["ok"]


def test_rossi_footer_retains_exact_notice_without_contact_numbers():
    from schedules.grounding import source_closure_inventory

    source = inspect_pdf_source((REPO_ROOT / "data/rossi-pool/2026-08-20-cb8abdbbedda/source.pdf").read_bytes())
    closures = source_closure_inventory(source)
    maintenance = next(row for row in closures if row["reason_code"] == "maintenance")
    assert (maintenance["start"], maintenance["end"]) == ("2026-11-02", "2026-11-21")
    assert maintenance["source_notices"][0]["text"] == "Closed for annual maintenance\n11/2-11/21 reopen 11/22"
    assert len(closures) == 9


def test_garfield_holiday_inherited_month_preserves_every_date():
    from schedules.grounding import source_closure_inventory

    source = inspect_pdf_source((REPO_ROOT / "data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf").read_bytes())
    closures = source_closure_inventory(source)
    assert [row["start"] for row in closures if row["reason_code"] == "holiday"] == ["2026-10-12", "2026-11-11", "2026-11-26", "2026-11-27"]
    assert [(row["start"], row["start_time"], row["end_time"]) for row in closures if row["reason_code"] == "staff_training"] == [("2026-09-24", "11:00", "14:00"), ("2026-10-22", "11:00", "14:00")]


@pytest.mark.parametrize("text", [
    "Closed every 4th Thursday of the month except September",
    "Closed every 4th Thursday of the month before noon",
    "Closed (9/25)",
    "Closed (9/24 & 9/24) unless training ends early",
])
def test_uncertain_cell_conditions_still_hold(text):
    from schedules.signals import SourceCell
    from schedules.grounding import source_excluded_dates

    cell = SourceCell("cell", 1, "thursday", "Lap Swim 11am-1pm " + text, (0, 0, 10, 10))
    notice = SourceNotice("notice", cell.text, False, session_cell=cell.id)
    source = PdfSource("Schedule September 1-December 12, 2026", (cell,), (), 1, (notice,))
    with pytest.raises(ValueError):
        source_excluded_dates(source)


@pytest.mark.parametrize("capture", ["2026-09-06-6c2b2e77fb23", "2026-09-06-ac196df42a14"])
def test_north_beach_printed_maintenance_spelling_has_same_reason_code(capture):
    from schedules.grounding import source_closure_inventory

    source = inspect_pdf_source((REPO_ROOT / "data/north-beach-pool" / capture / "source.pdf").read_bytes())
    closure = next(row for row in source_closure_inventory(source) if row["start"] == "2026-10-13")
    assert closure["end"] == "2026-10-31"
    assert closure["reason_code"] == "maintenance"
    spelling = "MAINTENANCE" if capture.endswith("6c2b2e77fb23") else "MAINTENCE"
    assert spelling in closure["source_notices"][0]["text"].upper()


@pytest.mark.parametrize("support", [
    "Pool will be closed November 26 for Thanksgiving",
    "Pool will be closed November 23-29 for maintenance",
])
def test_recurring_notice_uses_explicit_list_when_omission_is_fully_closed(support):
    from schedules.grounding import source_closure_inventory

    source = _notice_source("Pool will be closed every 4th Thursday from 12pm-2pm for training (8/27, 9/24, 10/22)")
    source = PdfSource(source.text, (), (), 1, source.notices + (SourceNotice("independent", support, True),))
    inventory = source_closure_inventory(source)
    training = [row for row in inventory if row["reason_code"] == "staff_training"]
    assert [row["start"] for row in training] == ["2026-08-27", "2026-09-24", "2026-10-22"]
    assert all(row["source_notices"][0]["id"] == "test-notice" for row in training)


@pytest.mark.parametrize("damage", ["missing", "partial", "pool_specific", "recurring", "uncertain", "wrong_day", "extra", "duplicate"])
def test_recurring_notice_cannot_borrow_inadequate_or_conflicting_evidence(damage):
    from schedules.grounding import source_closure_inventory

    text = "Pool will be closed every 4th Thursday from 12pm-2pm for training (8/27, 9/24, 10/22)"
    if damage == "wrong_day": text = text.replace("9/24", "9/25")
    if damage == "extra": text = text.replace("10/22", "10/22, 12/24")
    if damage == "duplicate": text = text.replace("9/24", "9/24, 9/24")
    notice = SourceNotice("independent", "Pool will be closed November 26 for Thanksgiving", True)
    if damage == "partial": notice = SourceNotice("independent", "Pool will be closed November 26 from 12pm-2pm for Thanksgiving", True)
    if damage == "pool_specific": notice = SourceNotice("independent", notice.text, True, physical_pool="cool")
    if damage == "recurring": notice = SourceNotice("independent", "Pool will be closed every 4th Thursday from 12pm-2pm", True)
    if damage == "uncertain": notice = SourceNotice("independent", "Pool may be closed November 26", True)
    source = _notice_source(text)
    notices = source.notices if damage == "missing" else source.notices + (notice,)
    with pytest.raises(ValueError):
        source_closure_inventory(PdfSource(source.text, (), (), 1, notices))


def test_sava_fall_preserves_literal_outside_window_training_without_extension():
    from schedules.grounding import source_closure_inventory, source_window

    source = inspect_pdf_source((REPO_ROOT / "data/sava-pool/2026-08-20-946a112b3f43/source.pdf").read_bytes())
    inventory = source_closure_inventory(source)
    training = [row for row in inventory if row["reason_code"] == "staff_training"]
    assert {(row["start"], row["start_time"], row["end_time"]) for row in training} == {
        ("2026-12-22", "09:00", "11:00"), ("2026-09-24", "12:00", "14:00"), ("2026-10-22", "12:00", "14:00")}
    assert tuple(day.isoformat() for day in source_window(source)) == ("2026-08-29", "2026-12-12")
    assert any("December 22" in item["text"] for row in training for item in row["source_notices"])


@pytest.mark.parametrize("text", [
    "Pool will be closed the morning of September 7",
    "Pool will be closed the morning of September 7 from 9pm-11pm",
    "Pool will be closed the morning of September 7 from 11am-1pm",
])
def test_morning_without_matching_precise_morning_clock_remains_held(text):
    from schedules.grounding import source_closure_inventory

    with pytest.raises(ValueError):
        source_closure_inventory(_notice_source(text))


def test_expired_sava_duplicate_notice_remains_held():
    from schedules.grounding import source_closure_inventory, source_window

    source = inspect_pdf_source((REPO_ROOT / "data/sava-pool/2026-09-01-4d9a6f5e805d/source.pdf").read_bytes())
    assert tuple(day.isoformat() for day in source_window(source)) == ("2026-08-18", "2026-08-28")
    with pytest.raises(ValueError):
        source_closure_inventory(source)


def test_garfield_shared_time_cells_preserve_distinct_program_allocations():
    from collections import Counter
    from schedules.grounding import source_slots

    source = inspect_pdf_source((REPO_ROOT / "data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf").read_bytes())
    slots = source_slots(source)
    assert Counter(slot.type for slot in slots) == {"lap_swim": 15, "family_swim": 14, "senior_swim": 4}
    sunday = [slot for slot in slots if slot.cell.day == "sunday" and slot.start == "12:30"]
    assert {(slot.type, slot.pool, slot.end) for slot in sunday} == {("lap_swim", "main", "14:00"), ("family_swim", "small", "14:00")}
    assert all("\nW\n" not in slot.cell.text for slot in sunday)


@pytest.mark.parametrize("text", [
    "Lap Swim (Main Pool) (Small Pool) Rec/Family Swim 1pm-2pm",
    "(Main Pool) Lap Swim Rec/Family Swim (Small Pool) 1pm-2pm",
    "Lap Swim (Main Pool) Lap Swim (Small Pool) 1pm-2pm",
    "Lap Swim (Main Pool) Rec/Family Swim (Small Pool) (Therapy Pool) 1pm-2pm",
])
def test_multi_program_allocations_require_unique_attached_labels(text):
    from schedules.signals import SourceCell
    from schedules.grounding import source_slots

    cell = SourceCell("test", 1, "thursday", text, (0, 0, 100, 100))
    with pytest.raises(ValueError, match="ambiguous_pool_allocation"):
        source_slots(PdfSource("", (cell,), (), 1, ()))


@pytest.mark.parametrize("damage", ["missing", "swapped", "duplicate", "alternate"])
def test_shared_program_allocations_reject_missing_swapped_or_conditional_sessions(damage):
    from schedules.signals import SourceCell

    text = "Lap Swim (Main Pool) Rec/Family Swim (Small Pool) 12:30pm-2pm"
    cell = SourceCell("cell", 1, "sunday", text, (0, 0, 100, 100))
    source = PdfSource("", (cell,), (), 1, ())
    sessions = [
        {"day": "sunday", "type": "lap_swim", "pool": "main", "start": "12:30", "end": "14:00"},
        {"day": "sunday", "type": "family_swim", "pool": "small", "start": "12:30", "end": "14:00"},
    ]
    assert source_coverage(source, {"sessions": sessions})["ok"]
    if damage == "missing": sessions.pop()
    if damage == "swapped": sessions[0]["pool"], sessions[1]["pool"] = "small", "main"
    if damage == "duplicate": sessions.append(dict(sessions[0]))
    if damage == "alternate":
        from dataclasses import replace
        source = replace(source, cells=(replace(cell, text=text.replace("Rec/Family", "or Rec/Family")),))
    assert not source_coverage(source, {"sessions": sessions})["ok"]


@pytest.mark.parametrize("support", [
    "Lap Pool will be closed November 26 for Thanksgiving",
    "Deep Pool will be closed November 26 for Thanksgiving",
    "Main Pool will be closed November 26 for Thanksgiving",
    "Pool will be closed November 26; reopen at 10am for Thanksgiving",
    "Pool will be closed November 26; reopen November 27",
    "Pool will be closed November 26 if staff training proceeds",
])
def test_recurrence_support_requires_explicit_unconditional_whole_facility_notice(support):
    from schedules.grounding import source_closure_inventory

    source = _notice_source("Pool will be closed every 4th Thursday from 12pm-2pm for training (8/27, 9/24, 10/22)")
    source = PdfSource(source.text, (), (), 1, source.notices + (SourceNotice("independent", support, True),))
    with pytest.raises(ValueError, match="conflicting_recurring_closure_dates"):
        source_closure_inventory(source)


@pytest.mark.parametrize("phrase", ["not in", "reserved for lessons", "only", "W", "or"])
def test_shared_allocation_does_not_ignore_intervening_qualifiers(phrase):
    from schedules.signals import SourceCell
    from schedules.grounding import source_slots

    cell = SourceCell("cell", 1, "sunday", f"Lap Swim {phrase} (Main Pool) Rec/Family Swim (Small Pool) 12:30pm-2pm", (0, 0, 100, 100))
    with pytest.raises(ValueError, match="ambiguous_pool_allocation"):
        source_slots(PdfSource("", (cell,), (), 1, ()))


@pytest.mark.parametrize("clock,allowed", [("10am-midnight", False), ("10am-12am", False), ("11pm-midnight", True), ("10am-10pm", True)])
def test_source_drop_in_session_duration_is_bounded_without_rewriting_midnight(clock, allowed):
    from schedules.signals import SourceCell
    from schedules.grounding import source_slots

    source = PdfSource("", (SourceCell("cell", 1, "thursday", "Lap Swim " + clock, (0, 0, 100, 100)),), (), 1, ())
    if allowed:
        assert len(source_slots(source)) == 1
    else:
        with pytest.raises(ValueError, match="unsupported_session_duration"):
            source_slots(source)


def test_sava_printed_daytime_to_midnight_session_holds_before_paid_call(tmp_path, monkeypatch):
    from schedules.paths import PROMPT_PATH
    from schedules.schema import EXTRACTION_SCHEMA
    from schedules.providers import openai_provider

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    ledger = tmp_path / "budget.json"
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(ledger))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "1")
    def unexpected_call(*args, **kwargs):
        pytest.fail("Ambiguous Sava midnight session reached the paid API")
    monkeypatch.setattr(openai_provider, "budgeted_call", unexpected_call)
    original = (REPO_ROOT / "data/sava-pool/2026-08-20-946a112b3f43/source.pdf").read_bytes()
    with pytest.raises(ValueError, match="unsupported_session_duration"):
        openai_provider.extract(original, PROMPT_PATH.read_text(), EXTRACTION_SCHEMA)
    assert not ledger.exists()
