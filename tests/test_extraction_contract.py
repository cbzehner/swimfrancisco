"""Contract tests for the extraction prompt and schema.

The closure contract (v2) is: closures are facility-wide. By default they
are all-day (start..end inclusive, no time fields). Single-day closures MAY
carry optional `start_time` / `end_time` (24-hour HH:MM) to mark a
partial-day window — both must appear together, and they're not allowed on
multi-day ranges. Pool-scoped closures remain out of scope.

The original v1 contract (no times at all) was lifted in 2026-05 to model
SF Rec & Park's recurring partial-day "Aquatics Division Training"
windows, which were previously rounded to all-day and over-reported pool
unavailability. These tests guard the v2 boundaries.
"""

from __future__ import annotations

import json

import pytest

from conftest import api_usage_result
from schedules.paths import PROMPT_PATH
from schedules.providers import openai_provider
from schedules.schema import EXTRACTION_SCHEMA
from schedules.signals import PdfSource, SourceCell


def test_prompt_forbids_timed_sfusd_rows_in_closures() -> None:
    prompt = PROMPT_PATH.read_text()
    assert (
        "Record these as a closure entry for that day and time" not in prompt
    ), "prompt still instructs providers to encode SFUSD slots as timed closures"
    assert (
        "Do not encode timed school-only bookings in closures[]" in prompt
    ), "prompt is missing the explicit guard against timed school bookings in closures"


def test_prompt_distinguishes_physical_pool_labels_from_program_lane_counts() -> None:
    prompt = PROMPT_PATH.read_text()
    assert "A program name followed by a lane count is not a pool allocation" in prompt
    assert "When shared programs have only numeric lane counts, use null for each program" in prompt


def test_prompt_separates_session_cancellations_from_facility_closures() -> None:
    prompt = PROMPT_PATH.read_text()
    assert "Never copy facility holiday, maintenance, or training closure dates into session excluded_dates" in prompt
    assert "A date list inside a session cell does not limit a separate facility recurring closure" in prompt


def test_ambiguous_source_requires_its_original_rendered_page() -> None:
    cell = SourceCell("p1-c1-b1", 1, "monday", "Family Swim 3:30pm-5:30pm (s (small pool)", (0, 0, 100, 100))
    source = PdfSource("schedule", (cell,), ("p1-c1-b1:unbalanced_text",), 1, ())
    with pytest.raises(ValueError, match="rendered page"):
        openai_provider.source_request(source, "extract", {})
    request = openai_provider.source_request(source, "extract", {1: b"image-bytes"})
    part = request["input"][0]["content"][-1]
    assert part["detail"] == "original"
    assert part["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("credentials", ["configured", "missing_key"])
def test_unresolved_closure_scope_stops_before_spend(monkeypatch, credentials):
    from schedules.paths import REPO_ROOT

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")

    def unexpected_call(*args, **kwargs):
        pytest.fail("An unresolved source reached the paid API")

    if credentials == "missing_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setattr(openai_provider, "render_source_pages", unexpected_call)
    monkeypatch.setattr(openai_provider, "source_request", unexpected_call)
    monkeypatch.setattr(openai_provider, "call_api", unexpected_call)
    pdf = REPO_ROOT / "data/balboa-pool/2026-08-20-d6f218710372/source.pdf"
    with pytest.raises(openai_provider.ClosureReviewRequired, match="Unresolved source closures") as held:
        openai_provider.extract(pdf.read_bytes(), PROMPT_PATH.read_text(), EXTRACTION_SCHEMA)
    assert held.value.issues
    assert all({"id", "text", "facility"}.issubset(notice) for notice in held.value.notices)


@pytest.mark.parametrize("pages,selected", [(0, {1}), (13, {1}), (1, {0}), (1, {2})])
def test_render_rejects_unsupported_page_selection_before_decoding(monkeypatch, pages, selected):
    from contextlib import nullcontext
    from types import SimpleNamespace

    monkeypatch.setattr(openai_provider.pdfplumber, "open", lambda _: nullcontext(SimpleNamespace(pages=[None] * pages)))
    with pytest.raises(ValueError, match="outside the supported source"):
        openai_provider.render_source_pages(b"pdf", frozenset(selected))


@pytest.mark.parametrize("width,height,count", [(2001, 500, 1), (500, 2001, 1), (2000, 2000, 2)])
def test_render_rejects_oversized_evidence_before_decoding(monkeypatch, width, height, count):
    from contextlib import nullcontext
    from types import SimpleNamespace

    document = SimpleNamespace(pages=[SimpleNamespace(width=width, height=height)] * count)
    monkeypatch.setattr(openai_provider.pdfplumber, "open", lambda _: nullcontext(document))
    with pytest.raises(ValueError, match="dimensions|megapixel"):
        openai_provider.render_source_pages(b"pdf", frozenset(range(1, count + 1)))


@pytest.mark.parametrize("http_status,timed_out,expected_calls", [
    (500, False, 2), (503, False, 2), (408, False, 2), (None, True, 2),
    (401, False, 1), (403, False, 1), (429, False, 1), (400, False, 1),
])
def test_production_retry_is_bounded(monkeypatch, http_status, timed_out, expected_calls):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    source = PdfSource("Schedule August 11-August 29, 2026", (), (), 1, ())
    monkeypatch.setattr(openai_provider, "inspect_pdf_source", lambda _: source)
    monkeypatch.setattr(openai_provider, "time", type("Clock", (), {"sleep": staticmethod(lambda _: None)}))
    calls = []

    def call(*args):
        calls.append(args)
        return {"api_response": None, "status": "timeout" if timed_out else "execution_error",
                "timed_out": timed_out, "http_status": http_status}

    monkeypatch.setattr(openai_provider, "call_api", call)
    with pytest.raises(ValueError, match="Extraction failed"):
        openai_provider.extract(b"pdf", "extract", EXTRACTION_SCHEMA)
    assert len(calls) == expected_calls


def test_production_maps_raw_labels_and_preserves_failed_coverage(monkeypatch):
    from schedules.schema import SOURCE_FACTS_SCHEMA

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    cell = SourceCell("p1-c1-b1", 1, "monday", "Family Swim 3:30pm-5:30pm (small pool)", (0, 0, 100, 100))
    source = PdfSource("Schedule August 11-August 29, 2026", (cell,), (), 1, ())
    monkeypatch.setattr(openai_provider, "inspect_pdf_source", lambda _: source)
    facts = {"effective_start": "2026-08-11", "effective_end": "2026-08-29", "schedule_basis": "swim_schedule",
             "sessions": [{"day": "monday", "type": "family_swim", "start": "15:30", "end": "17:30",
                           "pool_label_raw": "Wrong Pool", "evidence": cell.text, "notes": None, "excluded_dates": None}],
             "closures": [], "access_hours": None, "access_exceptions": None}

    def call(request, *args):
        assert request["model"] == openai_provider.API_MODEL
        assert request["text"]["format"]["schema"] == openai_provider.api_transport_schema(SOURCE_FACTS_SCHEMA)
        return api_usage_result(status="completed", output=[{
            "type": "message", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(facts)}],
        }]) | {"http_status": 200, "timed_out": False}

    monkeypatch.setattr(openai_provider, "call_api", call)
    result = openai_provider.extract(b"pdf", "extract", EXTRACTION_SCHEMA)
    assert result.payload["sessions"][0]["pool"] == "wrong"
    assert result.details["source_facts"]["sessions"][0]["pool_label_raw"] == "Wrong Pool"
    assert not result.details["source_coverage"]["ok"]
    assert result.details["source_window"]["ok"]
    assert result.details["final_response"] == json.dumps(facts)



def test_north_beach_originals_pass_independent_coverage(north_beach_pair):
    entry, components = north_beach_pair
    for component, count in zip(components, (15, 20), strict=True):
        artifact = component["artifact"]
        assert len(artifact["payload"]["sessions"]) == count
        assert openai_provider.verify_artifact(artifact, component["document"], PROMPT_PATH.read_text())["ok"]


@pytest.mark.parametrize("member", [0, 1])
@pytest.mark.parametrize("damage", ["omission", "duplicate", "exclusion", "window", "closure", "configuration"])
def test_north_beach_each_original_rejects_bad_model_output(north_beach_pair, member, damage):
    import copy
    from schedules.schema import pool_label_payload
    _, components = north_beach_pair
    component = components[member]
    artifact = copy.deepcopy(component["artifact"])
    facts = artifact["details"]["source_facts"]
    if damage == "omission":
        facts["sessions"].pop()
    elif damage == "duplicate":
        facts["sessions"].append(facts["sessions"][0])
    elif damage == "exclusion":
        next(row for row in facts["sessions"] if row.get("excluded_dates"))["excluded_dates"] = []
    elif damage == "window":
        facts["effective_end"] = "2026-12-13"
    elif damage == "closure":
        facts["closures"].pop()
    else:
        artifact["details"]["configuration"]["reasoning"] = "low"
    if damage == "closure":
        with pytest.raises(ValueError, match="omit"):
            openai_provider.source_fact_payload(facts, openai_provider.inspect_pdf_source(component["document"]))
        return
    artifact["payload"] = openai_provider.source_fact_payload(facts, openai_provider.inspect_pdf_source(component["document"]))
    if damage == "configuration":
        with pytest.raises(ValueError, match="stale"):
            openai_provider.verify_artifact(artifact, component["document"], PROMPT_PATH.read_text())
    else:
        assert not openai_provider.verify_artifact(artifact, component["document"], PROMPT_PATH.read_text())["ok"]



def test_paired_pool_closure_never_becomes_facility_wide(north_beach_pair):
    from dataclasses import replace
    from schedules.signals import inspect_pdf_source, SourceNotice
    from schedules.grounding import source_closure_coverage
    _, components = north_beach_pair
    source = inspect_pdf_source(components[1]["document"])
    source = replace(source, notices=(SourceNotice("p1-notice", "Warm Pool will be CLOSED on September 24 from 12pm-2pm", True, physical_pool="warm"),))
    closure = {"start": "2026-09-24", "end": "2026-09-24", "start_time": "12:00", "end_time": "14:00", "reason": "Training"}
    assert not source_closure_coverage(source, {"closures": [closure]})["ok"]
    assert source_closure_coverage(source, {"closures": [closure | {"physical_pool": "warm"}]})["ok"]
    assert not source_closure_coverage(source, {"closures": [closure | {"physical_pool": "cool"}]})["ok"]


def test_session_exclusions_resolve_year_rollover_without_guessing(monkeypatch):
    from datetime import date
    from schedules import grounding
    from schedules.signals import SourceNotice
    cell = SourceCell("p1-c1-b1", 1, "thursday", "Lap Swim 11am-2pm (CLOSED 12/31 & 1/7)", (0, 0, 100, 100))
    source = PdfSource("North Beach Pool", (cell,), (), 1, (SourceNotice("p1-exclusion", cell.text, False, session_cell=cell.id),))
    monkeypatch.setattr(grounding, "source_window", lambda _: (date(2026, 12, 1), date(2027, 1, 31)))
    assert grounding.source_excluded_dates(source) == {cell.id: ["2026-12-31", "2027-01-07"]}
    monkeypatch.setattr(grounding, "source_window", lambda _: (date(2026, 12, 1), date(2028, 1, 31)))
    with pytest.raises(ValueError, match="ambiguous_exclusion_date"):
        grounding.source_excluded_dates(source)



@pytest.mark.parametrize("member", [0, 1])
def test_paired_original_uses_production_request_with_mocked_model_response(north_beach_pair, monkeypatch, member):
    from schedules.schema import SOURCE_FACTS_SCHEMA
    _, components = north_beach_pair
    component = components[member]
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    def transport(value, schema):
        if isinstance(value, dict):
            return {key: transport(value.get(key), child) for key, child in schema["properties"].items()}
        if isinstance(value, list):
            return [transport(item, schema["items"]) for item in value]
        return value
    response = transport(component["artifact"]["details"]["source_facts"], SOURCE_FACTS_SCHEMA)
    def call(request, *args):
        assert request["model"] == "gpt-5.5-2026-04-23"
        assert request["reasoning"] == {"effort": "medium"}
        assert "uniqueItems" not in json.dumps(request["text"]["format"]["schema"])
        assert "whole-session cancellations" in request["input"]
        return api_usage_result(status="completed", output=[{"type": "message", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(response)}]}]) | {"http_status": 200, "timed_out": False}
    monkeypatch.setattr(openai_provider, "call_api", call)
    result = openai_provider.extract(component["document"], PROMPT_PATH.read_text().strip(), EXTRACTION_SCHEMA)
    assert result.payload == component["artifact"]["payload"]
    assert result.details["source_coverage"]["ok"] and result.details["source_closures"]["ok"]


def test_closure_display_code_comes_from_original_notice(north_beach_pair):
    import copy
    _, components = north_beach_pair
    component = components[0]
    artifact = copy.deepcopy(component['artifact'])
    facts = artifact['details']['source_facts']
    source = openai_provider.inspect_pdf_source(component['document'])
    expected = artifact['payload']['closures'][0]
    facts['closures'][0]['reason'] = 'A different model summary of the same closure'
    payload = openai_provider.source_fact_payload(facts, source)
    assert payload['closures'][0]['reason'] == facts['closures'][0]['reason']
    assert payload['closures'][0]['reason_code'] == expected['reason_code']
    assert payload['closures'][0]['source_notices'] == expected['source_notices']
    artifact['payload'] = payload
    assert openai_provider.verify_artifact(artifact, component['document'], PROMPT_PATH.read_text())['ok']
    artifact['payload']['closures'][0]['reason_code'] = 'holiday'
    with pytest.raises(ValueError, match='differs'):
        openai_provider.verify_artifact(artifact, component['document'], PROMPT_PATH.read_text())


def test_mlk_named_registered_lessons_are_not_public_sessions():
    from schedules.paths import REPO_ROOT
    from schedules.signals import inspect_pdf_source, program_types
    from schedules.grounding import source_slots

    source = inspect_pdf_source((REPO_ROOT / 'data/martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a/source.pdf').read_bytes())
    lessons = [cell for cell in source.cells if 'Bayview Safety Swim' in cell.text]
    assert len(lessons) == 4
    assert {cell.day for cell in lessons} == {'tuesday', 'wednesday', 'thursday', 'friday'}
    assert not source.issues
    assert all(program_types(cell.text) == () for cell in lessons)
    slots = source_slots(source)
    assert len(slots) == 23
    assert not {slot.cell.id for slot in slots} & {cell.id for cell in lessons}


def test_garfield_school_group_booking_is_not_public_family_swim():
    from schedules.paths import REPO_ROOT
    from schedules.signals import inspect_pdf_source, program_types

    source = inspect_pdf_source((REPO_ROOT / 'data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf').read_bytes())
    bookings = [cell for cell in source.cells if 'School Groups' in cell.text]
    assert len(bookings) == 1
    assert bookings[0].day == 'wednesday'
    assert program_types(bookings[0].text) == ()
    assert not any(issue.startswith(bookings[0].id + ':') for issue in source.issues)
    assert program_types('Rec/Family Swim (Small Pool) 2:00pm-3:45pm') == ('family_swim',)
    assert program_types('Senior/SFUSD 9am-11am') == ('senior_swim',)


@pytest.mark.parametrize('capture,heading,replacement', [
    ('martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a', 'Bayview Safety Swim\n& Splash', 'Bayview Safety Swim'),
    ('martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a', 'Bayview Safety Swim\n& Splash', 'Bayview Safety Swim & Splash Special'),
    ('garfield-pool/2026-08-20-7f5c0074e8dd', 'Rec/Family Swim\nSchool Groups', 'Rec/Family Swim School Group'),
    ('garfield-pool/2026-08-20-7f5c0074e8dd', 'Rec/Family Swim\nSchool Groups', 'Rec/Family Swim School Groups and Guests'),
    ('garfield-pool/2026-08-20-7f5c0074e8dd', 'Rec/Family Swim\nSchool Groups', 'Rec/Family Swim School Groups / Lap Swim / Water Exercise'),
    ('martin-luther-king-jr-pool/2026-08-20-2e1c7d942a7a', 'Bayview Safety Swim\n& Splash', 'Bayview Safety Swim & Splash / Senior Swim / Lessons'),
])
def test_changed_registered_program_names_remain_unknown(monkeypatch, capture, heading, replacement):
    from dataclasses import replace
    from schedules.paths import REPO_ROOT
    from schedules import signals

    original = signals._column_cells
    changed = []
    def changed_cells(page, header):
        cells = original(page, header)
        for cell in cells:
            if heading in cell.text:
                changed.append(cell.id)
        return [replace(cell, text=cell.text.replace(heading, replacement)) for cell in cells]
    monkeypatch.setattr(signals, '_column_cells', changed_cells)
    source = signals.inspect_pdf_source((REPO_ROOT / 'data' / capture / 'source.pdf').read_bytes())
    assert changed
    assert all(cell_id + ':unknown_program' in source.issues for cell_id in changed)


def test_column_boundary_characters_belong_to_exactly_one_weekday():
    from schedules.signals import _column_cells

    class Page:
        width, height, page_number = 200, 100, 1
        def __init__(self, objects):
            self.objects = objects
        def filter(self, predicate):
            return Page([item for item in self.objects if predicate(item)])
        def crop(self, bounds):
            return Page([item for item in self.objects if item['x1'] > bounds[0] and item['x0'] < bounds[2]])
        def extract_text_lines(self, **kwargs):
            return [{'text': ' '.join(item['text'] for item in self.objects if item['object_type'] == 'char'),
                     'top': 20, 'bottom': 30}]

    page = Page([
        {'object_type': 'char', 'text': 'Lap Swim 9am-10am', 'x0': 20, 'x1': 80},
        {'object_type': 'char', 'text': 'Lap Swim 9am-10am', 'x0': 120, 'x1': 180},
        {'object_type': 'char', 'text': 'A', 'x0': 94, 'x1': 104},
        {'object_type': 'char', 'text': 'W', 'x0': 95, 'x1': 107},
        {'object_type': 'char', 'text': 'B', 'x0': 99, 'x1': 101},
        {'object_type': 'rect', 'x0': 0, 'x1': 200},
    ])
    header = [{'text': 'SUNDAY', 'x0': 40, 'x1': 60, 'bottom': 10},
              {'text': 'MONDAY', 'x0': 140, 'x1': 160, 'bottom': 10}]
    cells = _column_cells(page, header)
    assert [(cell.day, cell.text) for cell in cells] == [
        ('sunday', 'Lap Swim 9am-10am A'), ('monday', 'Lap Swim 9am-10am W B'),
    ]


def test_garfield_boundary_keeps_monday_water_exercise_out_of_sunday_cell():
    from collections import Counter
    from schedules.paths import REPO_ROOT
    from schedules.signals import inspect_pdf_source
    from schedules.grounding import source_slots

    source = inspect_pdf_source((REPO_ROOT / 'data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf').read_bytes())
    shared = next(cell for cell in source.cells if cell.id == 'p1-c1-b3')
    assert shared.text == 'Lap Swim (Main Pool)\nRec/Family Swim\n(Small Pool)\n12:30 pm-2:00 pm'
    assert any(cell.day == 'monday' and 'Water Exercise-Instructor Led' in cell.text for cell in source.cells)
    slots = source_slots(source)
    assert Counter(slot.type for slot in slots) == {'lap_swim': 15, 'family_swim': 14, 'senior_swim': 4}
    assert [(slot.type, slot.pool) for slot in slots if slot.cell.id == shared.id] == [
        ('family_swim', 'small'), ('lap_swim', 'main'),
    ]


def test_garfield_grouped_thanksgiving_matches_original_single_dates():
    import copy
    from schedules.paths import REPO_ROOT

    source = openai_provider.inspect_pdf_source((REPO_ROOT / 'data/garfield-pool/2026-08-20-7f5c0074e8dd/source.pdf').read_bytes())
    # Closure facts from accounted response 34197948665, without transport nulls.
    facts = {'sessions': [], 'closures': [
        {'start': '2026-10-12', 'end': '2026-10-12', 'reason': 'Indigenous Peoples Day'},
        {'start': '2026-11-11', 'end': '2026-11-11', 'reason': 'Veterans Day'},
        {'start': '2026-11-26', 'end': '2026-11-27', 'reason': 'Thanksgiving'},
        {'start': '2026-09-24', 'end': '2026-09-24', 'reason': 'staff training', 'start_time': '11:00', 'end_time': '14:00'},
        {'start': '2026-10-22', 'end': '2026-10-22', 'reason': 'staff training', 'start_time': '11:00', 'end_time': '14:00'},
    ]}
    original = copy.deepcopy(facts)
    payload = openai_provider.source_fact_payload(facts, source)
    assert facts == original
    assert len(payload['closures']) == 6
    thanksgiving = [item for item in payload['closures'] if item['reason'] == 'Thanksgiving']
    assert [(item['start'], item['end']) for item in thanksgiving] == [('2026-11-26', '2026-11-26'), ('2026-11-27', '2026-11-27')]
    assert all(item['reason_code'] == 'holiday' for item in thanksgiving)
    assert thanksgiving[0]['source_notices'] == thanksgiving[1]['source_notices']
    assert 'Nov. 26 and 27' in thanksgiving[0]['source_notices'][0]['text']


@pytest.mark.parametrize('failure', ['omitted', 'extra', 'gap', 'scope', 'partial_model', 'partial_source', 'reason', 'notice', 'duplicate_source', 'duplicate_model', 'source_range'])
def test_grouped_closures_reject_inexact_source_unions(monkeypatch, failure):
    inventory = [
        {'start': day, 'end': day, 'reason_code': 'holiday', 'source_notices': [{'id': 'p1-notice-1', 'text': 'Closed November 26 and 27'}]}
        for day in ['2026-11-26', '2026-11-27']
    ]
    closure = {'start': '2026-11-26', 'end': '2026-11-27', 'reason': 'Thanksgiving'}
    if failure == 'omitted':
        closure['end'] = closure['start']
    elif failure == 'extra':
        closure['end'] = '2026-11-28'
    elif failure == 'gap':
        inventory[1].update(start='2026-11-28', end='2026-11-28')
        closure['end'] = '2026-11-28'
    elif failure == 'scope':
        inventory[1]['physical_pool'] = 'warm'
    elif failure == 'partial_model':
        closure.update(start_time='11:00', end_time='14:00')
    elif failure == 'partial_source':
        inventory[1].update(start_time='11:00', end_time='14:00')
    elif failure == 'reason':
        inventory[1]['reason_code'] = 'maintenance'
    elif failure == 'notice':
        inventory[1]['source_notices'] = [{'id': 'p1-notice-2', 'text': 'Closed November 27'}]
    elif failure == 'duplicate_source':
        inventory.append(inventory[0].copy())
    elif failure == 'source_range':
        inventory[0]['end'] = '2026-11-27'
    facts = {'sessions': [], 'closures': [closure] * (2 if failure == 'duplicate_model' else 1)}
    monkeypatch.setattr(openai_provider, 'source_closure_inventory', lambda source: inventory)
    with pytest.raises(ValueError, match='independently verified source notice'):
        openai_provider.source_fact_payload(facts, None)


@pytest.mark.parametrize('second_reason', ['Thanksgiving', 'A different model reason'])
def test_duplicate_grouped_closures_cannot_consume_other_notice(monkeypatch, second_reason):
    closure = {'start': '2026-11-26', 'end': '2026-11-27', 'reason': 'Thanksgiving'}
    inventory = [closure | {'reason_code': 'holiday', 'source_notices': [{'id': 'p1-notice-1', 'text': 'Closed November 26–27'}]}] + [
        {'start': day, 'end': day, 'reason_code': 'holiday', 'source_notices': [{'id': 'p1-notice-2', 'text': 'Closed November 26 and 27'}]}
        for day in ['2026-11-26', '2026-11-27']
    ]
    monkeypatch.setattr(openai_provider, 'source_closure_inventory', lambda source: inventory)
    facts = {'sessions': [], 'closures': [closure, closure | {'reason': second_reason}]}
    with pytest.raises(ValueError, match='Duplicate closure'):
        openai_provider.source_fact_payload(facts, None)


