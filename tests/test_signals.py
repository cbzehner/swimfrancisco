from schedules.signals import analyze_page_texts, source_notes_for_signals

import copy
import json

import pytest

from schedules._time import printed_time_range
from schedules.eval import load_benchmark_reference
from schedules.grounding import source_coverage, source_window_coverage
from schedules.signals import PdfSource
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
    source = PdfSource(text, (), (), 1)
    payload = {"effective_start": "2026-06-09", "effective_end": "2026-08-15"}
    assert not source_window_coverage(source, payload)["ok"]


@pytest.mark.parametrize("start,end,expected", [
    ("7", "8 AM", ("07:00", "08:00")),
    ("10:15", "1:00 PM", ("10:15", "13:00")),
    ("12", "1 PM", ("12:00", "13:00")),
    ("11:45", "1 PM", ("11:45", "13:00")),
    ("10:30am", "Noon", ("10:30", "12:00")),
    ("5:30", "7 PM", ("17:30", "19:00")),
    ("11pm", "midnight", ("23:00", "23:59")),
    ("14:00", "16:00", ("14:00", "16:00")),
])
def test_printed_ranges_resolve_shared_meridiems(start, end, expected):
    assert printed_time_range(start, end) == expected


@pytest.mark.parametrize("start,end", [("7", "8"), ("25:00", "3pm"), ("9:70am", "11am"), ("4pm", "3pm")])
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
