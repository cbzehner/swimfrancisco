"""Frozen and synthetic sources reproducing schedule review holds."""
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from schedules.direct_sources import verify_direct_artifact
from schedules.direct_sources.errors import DirectSourceError
from schedules.direct_sources.html_facts import HtmlClosureReviewRequired
from schedules.direct_sources.providers.koret import _extract_koret
from schedules.direct_sources.providers.pomeroy import _pomeroy_closures
from schedules.direct_sources.providers.fitness_clubs import _extract_city_sports, _extract_bayclub_gateway, _extract_equinox


def test_koret_closure_only_workbook_does_not_resurrect_hidden_hours(tmp_path):
    workbook = Workbook()
    notice = workbook.active
    notice.title = "Pool Closure Notice"
    notice["A1"] = "Pool Closure Notice"
    notice["A4"] = "Attention Koret Patrons:\nThe Pool is Closed\nDue to Repairs and Maintance\nAnticipated Reopen: January 2027\nDate TBD"
    hidden = workbook.create_sheet("Monday")
    hidden["A1"] = "Hours: 6am-8pm"
    hidden.sheet_state = "hidden"
    path = tmp_path / "source.xlsx"
    workbook.save(path)
    with pytest.raises(DirectSourceError, match="review"):
        _extract_koret(path)  # No invalid closure model or invented reopening date.


@pytest.mark.parametrize("capture,sha256,pdf_sha256,notice", [
    ("2026-10-22-7a48aa48b21c", "7a48aa48b21c1009cddecd3002917e80d3aef52a7532e447a340ca8931d26d50",
     "c94402db2734cfe74dec979017091a6e03946ffd24fced6d8dd48fb34eba5a25",
     "The soonest the pool will reopen is 11/9"),
    ("2026-11-07-443781804a7b", "443781804a7bd0b3e7f5c235ff84ffc0bd0c625c03668fc7229ae9df6425ffb8",
     "8c8e5d4d359df918598e972b1c37cb8e644660c5429b92856752ce5da1dabf4b",
     "Anticipated Reopen: January 2027\nDate TBD"),
])
def test_koret_withdrawal_evidence_stays_held(capture, sha256, pdf_sha256, notice):
    directory = Path(__file__).parents[1] / "data/koret-center" / capture
    path = directory / "source.xlsx"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256
    assert (directory / "source.sha256").read_text().strip() == sha256
    assert hashlib.sha256((directory / "source.pdf").read_bytes()).hexdigest() == pdf_sha256
    assert not (directory / "reviewed.json").exists()  # Withdrawal is not a new attestation.
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        assert [sheet.title for sheet in workbook if sheet.sheet_state == "visible"] == ["Pool Closure Notice"]
        text = workbook["Pool Closure Notice"]["A4"].value
        assert "The Pool is Closed" in text
        assert notice in text
        assert any(sheet.sheet_state == "hidden" for sheet in workbook)
    finally:
        workbook.close()
    with pytest.raises(DirectSourceError, match="closure-only workbook requires review"):
        _extract_koret(path)


def test_pomeroy_explicit_multi_day_holiday_checks_every_weekday():
    html = "Upcoming Pool Closure Dates: Thursday, Friday and Saturday 11.26-11.28 - Thanksgiving Therapeutic Swimming"
    closures, evidence = _pomeroy_closures(html, date(2026, 11, 20))
    assert closures == [{"start": "2026-11-26", "end": "2026-11-28", "reason": "Thanksgiving", "reason_code": "holiday"}]
    assert evidence
    assert _pomeroy_closures(html, date(2026, 11, 6))[0] == []  # Outside observation lifetime.


@pytest.mark.parametrize("notice", [
    "Thursday, Friday and Sunday 11.26-11.28 - Thanksgiving",
    "Thursday, Friday and Saturday 11.28-11.26 - Thanksgiving",
    "Thursday, Friday and Saturday 11.26-11.28 - Pool hours TBD",
])
def test_pomeroy_ambiguous_multi_day_holiday_is_not_guessed(notice):
    with pytest.raises(DirectSourceError):
        _pomeroy_closures(f"Upcoming Pool Closure Dates: {notice} Therapeutic Swimming", date(2026, 11, 20))


def test_named_non_aquatic_cancellation_can_have_an_empty_reason():
    original = (Path(__file__).parent / "fixtures/html-facts/city-sports-20th-ave.html").read_text()
    html = original.replace("</sup></span>Maintenance", "</sup></span>-", 1)
    assert html != original
    payload = _extract_city_sports(html)
    assert payload["schedule_basis"] == "facility_hours"
    assert payload["sessions"] == payload["closures"] == []


def test_gateway_explicit_holiday_reduces_facility_hours_not_swim_sessions():
    original = (Path(__file__).parent / "fixtures/html-facts/bay-club-gateway.html").read_text()
    marker = 'class="text16regular-main orange w-condition-invisible w-dyn-bind-empty w-richtext">'
    html = original.replace(marker, marker + '<p>Thanksgiving Day (Thu, Nov 26): 6:00 am - 2:00 pm</p>', 1)
    payload = _extract_bayclub_gateway(html, observed_on=date(2026, 11, 20))
    assert payload["sessions"] == payload["closures"] == []
    assert [(row["date"], row["start"], row["end"]) for row in payload["access_exceptions"]] == [("2026-11-26", "06:00", "14:00")]
    assert _extract_bayclub_gateway(html, observed_on=date(2026, 11, 6))["access_exceptions"] == []
    for bad in [html.replace("Thu, Nov 26", "Fri, Nov 26"), html.replace("6:00 am - 2:00 pm", "5:00 am - 2:00 pm"), html.replace("Thanksgiving Day", '<img src="unknown.png">Thanksgiving Day', 1)]:
        with pytest.raises(DirectSourceError):
            _extract_bayclub_gateway(bad, observed_on=date(2026, 11, 20))


def test_gateway_repeated_week_is_checked_and_conflicting_daily_summary_is_held():
    # Standalone summary: the older page has no hero or derivation script.
    original = (Path(__file__).parent / "fixtures/html-facts/bay-club-gateway.html").read_text()
    week = re.search(r'<div class="club_hours_info w-richtext">(.*?)</div>', original, re.S)[1]
    html = original.replace('</body>', f'<div data-club-hours="" class="club_hero_hours w-richtext">{week}</div><p data-club-today="">6:00 am - 9:00 pm</p></body>')
    assert _extract_bayclub_gateway(html, observed_on=date(2026, 11, 6))["access_hours"]
    with pytest.raises(HtmlClosureReviewRequired, match="daily summary"):
        _extract_bayclub_gateway(html.replace('data-club-today="">6:', 'data-club-today="">5:'), observed_on=date(2026, 11, 6))
    with pytest.raises(DirectSourceError, match="disagree"):
        _extract_bayclub_gateway(html.replace('data-club-hours="" class="club_hero_hours w-richtext">', 'data-club-hours="" class="club_hero_hours w-richtext">', 1).replace(week, week.replace('6:00 am', '5:00 am'), 1), observed_on=date(2026, 11, 6))


@pytest.fixture
def gateway_widget_capture():
    path = Path(__file__).parents[1] / "data/bay-club-gateway/2026-10-30-bdecb5882d8b/source.html"
    content = path.read_bytes()
    digest = "bdecb5882d8b9cea9855c3c3fbb53bd42b892197e054c94fa1e1d4028893c0a8"
    assert hashlib.sha256(content).hexdigest() == digest
    assert path.with_suffix(".sha256").read_text().strip() == digest
    return content


@pytest.mark.parametrize("observed,holiday", [
    (date(2026, 10, 30), False), (date(2026, 10, 31), False),
    (date(2026, 11, 1), False), (date(2026, 11, 12), False),
    (date(2026, 11, 13), True), (date(2026, 11, 26), True),
    (date(2026, 11, 27), False),
])
def test_gateway_derived_widget_does_not_override_complete_week_or_holiday(gateway_widget_capture, observed, holiday):
    html = gateway_widget_capture.decode()
    assert 'data-club-today="" class="club_hero_card_text">5:00 am – 9:00 pm' in html
    payload = _extract_bayclub_gateway(html, observed_on=observed)
    assert payload["schedule_basis"] == "facility_hours"
    assert payload["sessions"] == payload["closures"] == []
    assert [(r["start"], r["end"]) for r in payload["access_hours"]] == [("06:00", "21:00")] * 5 + [("07:00", "20:00")] * 2
    assert [(r["date"], r["start"], r["end"]) for r in payload["access_exceptions"]] == (
        [("2026-11-26", "06:00", "14:00")] if holiday else [])


@pytest.mark.parametrize("change", [
    "missing_script", "commented_script", "duplicate_script", "inert_script", "external_script",
    "script_before_hero", "script_in_template", "changed_timezone", "early_return", "retargeted_hero",
    "additional_actor", "additional_actor_uppercase", "additional_actor_attribute", "duplicate_actor_attributes",
    "missing_hero", "missing_source", "missing_target", "duplicate_hero_attribute",
    "duplicate_target_attribute", "additional_target", "earlier_source", "source_outside_hero",
    "target_outside_hero", "different_card", "outer_card", "source_on_visible_week", "source_in_template",
    "malformed_target", "target_media", "target_closed", "target_invalid_range",
])
def test_gateway_unsupported_widget_holds_even_when_placeholder_agrees(gateway_widget_capture, change):
    # Agreement must not accidentally accept unsupported derivation on weekdays.
    html = gateway_widget_capture.decode().replace('>5:00 am – 9:00 pm</p>', '>6:00 am – 9:00 pm</p>', 1)
    scripts = [m[0] for m in re.finditer(r'<script>(.*?)</script>', html, re.S) if 'var DAYS =' in m[1]]
    assert len(scripts) == 1
    script = scripts[0]
    target = re.search(r'<p\b[^>]*data-club-today=""[^>]*>.*?</p>', html, re.S)[0]
    source = re.search(r'<div\b[^>]*data-club-hours=""[^>]*>.*?</div>', html, re.S)[0]
    changes = {
        "missing_script": lambda: html.replace(script, ''),
        "commented_script": lambda: html.replace(script, f'<!--{script}-->'),
        "duplicate_script": lambda: html.replace(script, script + script),
        "inert_script": lambda: html.replace(script, script.replace('<script>', '<script type="application/json">', 1)),
        "external_script": lambda: html.replace(script, script.replace('<script>', '<script src="https://example.invalid/widget.js">', 1)),
        "script_before_hero": lambda: html.replace(script, '').replace('<section data-club-hero=""', script + '<section data-club-hero=""', 1),
        "script_in_template": lambda: html.replace(script, f'<template>{script}</template>'),
        "changed_timezone": lambda: html.replace(script, script.replace('America/Los_Angeles', 'UTC')),
        "early_return": lambda: html.replace(script, script.replace('var DAYS =', 'return;\nvar DAYS =', 1)),
        "retargeted_hero": lambda: html.replace(script, script.replace("querySelector('[data-club-hero]')", "querySelector('[data-other-hero]')", 1)),
        "additional_actor": lambda: html.replace(script, script + "<script>document.querySelector('[data-club-today]');</script>"),
        "additional_actor_uppercase": lambda: html.replace(script, script + "<script>document.querySelector('[DATA-CLUB-TODAY]');</script>"),
        "additional_actor_attribute": lambda: html.replace(script, script + '<script src="https://example.invalid/widget.js?target=data-club-today"></script>'),
        "duplicate_actor_attributes": lambda: html.replace(script, script + '<script src="/widget.js?target=data-club-today" src="/other.js"></script>'),
        "missing_hero": lambda: html.replace('data-club-hero=""', 'data-other-hero=""', 1),
        "missing_source": lambda: html.replace('data-club-hours=""', 'data-other-hours=""', 1),
        "missing_target": lambda: html.replace('data-club-today=""', 'data-other-today=""', 1),
        "duplicate_hero_attribute": lambda: html.replace('data-club-hero=""', 'data-club-hero="" data-club-hero="other"', 1),
        "duplicate_target_attribute": lambda: html.replace('data-club-today=""', 'data-club-today="" data-club-today="other"', 1),
        "additional_target": lambda: html.replace(target, target + '<span data-club-today="other">6:00 am – 9:00 pm</span>', 1),
        "earlier_source": lambda: html.replace('<section data-club-hero=""', '<div data-club-hours="other"></div><section data-club-hero=""', 1),
        "source_outside_hero": lambda: html.replace(source, '').replace('</body>', source + '</body>', 1),
        "target_outside_hero": lambda: html.replace(target, '').replace('</body>', target + '</body>', 1),
        "different_card": lambda: html.replace(target, '').replace('>Find us</div>', '>Find us</div>' + target, 1),
        "outer_card": lambda: html.replace('<div class="club_hero_card_item"><div class="club_hero_card_label">Open today',
            '<div class="other_card"><div class="club_hero_card_label">Open today', 1).replace(
            '<section data-club-hero=""', '<div class="club_hero_card_item"><section data-club-hero=""', 1).replace(
            '</section><section class="main_section">', '</section></div><section class="main_section">', 1),
        "source_on_visible_week": lambda: html.replace('data-club-hours=""', '', 1).replace('<div class="club_hours_info', '<div data-club-hours="" class="club_hours_info', 1),
        "source_in_template": lambda: html.replace(source, '<template>' + source + '</template>', 1),
        "malformed_target": lambda: html.replace(target, target.replace('</p>', '</span></p>'), 1),
        "target_media": lambda: html.replace(target, target.replace('</p>', '<img src="notice.png"></p>'), 1),
        "target_closed": lambda: html.replace(target, target.replace('6:00 am – 9:00 pm', 'Pool closed until further notice'), 1),
        "target_invalid_range": lambda: html.replace(target, target.replace('6:00 am – 9:00 pm', '25:00 am – 9:00 pm'), 1),
    }
    changed = changes[change]()
    assert changed != html, change
    printed_notice = {"target_closed": "Pool closed until further notice",
                      "target_invalid_range": "25:00 am – 9:00 pm"}.get(change)
    issue = 'Unsupported Gateway derived daily summary' if printed_notice else 'Unsupported Gateway derived-hours widget'
    with pytest.raises(HtmlClosureReviewRequired, match=f'^{issue}$') as error:
        _extract_bayclub_gateway(changed, observed_on=date(2026, 10, 30))
    if printed_notice:
        assert error.value.notices[0]['text'] == printed_notice


@pytest.mark.parametrize("context", ["textarea", "title", "xmp", "iframe", "noembed", "noframes", "plaintext", "plaintext_prefix"])
def test_gateway_updater_in_text_context_requires_review(gateway_widget_capture, context):
    # These already hold on the pinned Python parser; guard against toolchain regressions.
    html = gateway_widget_capture.decode().replace('>5:00 am – 9:00 pm</p>', '>6:00 am – 9:00 pm</p>', 1)
    script = next(m[0] for m in re.finditer(r'<script>(.*?)</script>', html, re.S) if 'var DAYS =' in m[1])
    wrapped = '<plaintext></plaintext>' + script if context == 'plaintext_prefix' else f'<{context}>{script}</{context}>'
    with pytest.raises(HtmlClosureReviewRequired, match='^Unsupported Gateway derived-hours widget$'):
        _extract_bayclub_gateway(html.replace(script, wrapped), observed_on=date(2026, 10, 30))


def test_gateway_standalone_invalid_summary_keeps_its_hard_error():
    html = (Path(__file__).parent / "fixtures/html-facts/bay-club-gateway.html").read_text()
    html = html.replace('</body>', '<p data-club-today="">25:00 am – 9:00 pm</p></body>')
    with pytest.raises(DirectSourceError, match='^Unsupported or invalid printed club hours range$') as error:
        _extract_bayclub_gateway(html, observed_on=date(2026, 10, 30))
    assert type(error.value) is DirectSourceError  # Only the recognized widget gains review routing.


@pytest.mark.parametrize("change", [None, "configuration", "expired", "future", "payload", "bytes"])
def test_gateway_widget_artifact_round_trip_preserves_publication_guards(tmp_path, monkeypatch, gateway_widget_capture, change):
    from schedules import direct_sources
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.registry import load_registry

    entry = next(e for e in load_registry() if e.slug == "bay-club-gateway")
    assert entry.auto_publish  # Existing opt-in, not newly enabled by this correction.
    monkeypatch.setattr('schedules._time.pacific_today', lambda: date(2026, 10, 30))
    monkeypatch.setattr(direct_sources, 'fetch_text', lambda url: DirectTextResponse(
        gateway_widget_capture.decode(), gateway_widget_capture, url))
    result = direct_sources.extract_direct(entry, cache_root=tmp_path / "data")
    artifact = {"provider": "direct", "model": result.model, "source_pdf_url": entry.pdf_url,
                "pdf_sha256": result.fetch_result.sha256, "payload": result.payload,
                "details": {"direct_source": result.source}}
    assert result.fetch_result.path.read_bytes() == gateway_widget_capture
    assert (artifact["payload"]["effective_start"], artifact["payload"]["effective_end"]) == ("2026-10-30", "2026-11-12")
    today = date(2026, 10, 30)
    if change == "configuration":
        artifact["details"]["direct_source"]["configuration"] = {}
    elif change == "expired":
        today = date(2026, 11, 13)
    elif change == "future":
        today = date(2026, 10, 29)
    elif change == "payload":
        artifact["payload"]["access_hours"][0]["start"] = "01:00"
    elif change == "bytes":
        result.fetch_result.path.write_bytes(b"different original")
    if change is None:
        assert verify_direct_artifact(artifact, result.fetch_result.path, today=today)["ok"]
    else:
        with pytest.raises(DirectSourceError):
            verify_direct_artifact(artifact, result.fetch_result.path, today=today)


def test_gateway_changed_updater_cannot_reuse_a_previously_accepted_capture(tmp_path, monkeypatch, gateway_widget_capture):
    from schedules import direct_sources
    from schedules.direct_sources.errors import CapturedClosureReviewRequired
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.registry import load_registry

    changed = gateway_widget_capture.replace(b'America/Los_Angeles', b'UTC', 1)
    responses = iter([gateway_widget_capture, changed])
    def fetch(url):
        content = next(responses)
        return DirectTextResponse(content.decode(), content, url)
    monkeypatch.setattr(direct_sources, 'fetch_text', fetch)
    monkeypatch.setattr('schedules._time.pacific_today', lambda: date(2026, 10, 30))
    entry = next(e for e in load_registry() if e.slug == "bay-club-gateway")
    original = direct_sources.extract_direct(entry, cache_root=tmp_path / "data")
    with pytest.raises(CapturedClosureReviewRequired):
        direct_sources.extract_direct(entry, cache_root=tmp_path / "data")
    assert original.fetch_result.path.read_bytes() == gateway_widget_capture
    assert sorted(p.read_bytes() for p in (tmp_path / "data").rglob('source.html')) == sorted([gateway_widget_capture, changed])


def test_gateway_derived_widget_cannot_hide_a_notice_elsewhere_in_the_hero(gateway_widget_capture):
    html = gateway_widget_capture.decode().replace('<div aria-hidden="true" data-club-hours=""',
        '<p>The pool is closed for maintenance.</p><div aria-hidden="true" data-club-hours=""', 1)
    with pytest.raises(HtmlClosureReviewRequired, match="Unaccounted Gateway"):
        _extract_bayclub_gateway(html, observed_on=date(2026, 10, 30))


@pytest.mark.parametrize("apostrophe", ["'", "’"])
def test_gateway_new_year_holiday_resolves_across_the_year_boundary(apostrophe):
    original = (Path(__file__).parent / "fixtures/html-facts/bay-club-gateway.html").read_text()
    marker = 'class="text16regular-main orange w-condition-invisible w-dyn-bind-empty w-richtext">'
    html = original.replace(marker, marker + f'<p>New Year{apostrophe}s Day (Fri, Jan 1): 7:00 am - 2:00 pm</p>', 1)
    payload = _extract_bayclub_gateway(html, observed_on=date(2026, 12, 26))
    assert payload['access_exceptions'][0]['date'] == '2027-01-01'


def test_koret_closure_artifact_still_requires_manual_review(tmp_path):
    with pytest.raises(DirectSourceError, match="approved Pomeroy parser"):
        verify_direct_artifact({'provider': 'direct', 'model': 'koret-google-workbook-v1',
            'payload': {'schedule_basis': 'temporarily_closed'}}, tmp_path / 'source.xlsx', today=date(2026, 11, 6))


def equinox_holiday_source(*, relative_today=False, **changes):
    html = (Path(__file__).parent / "fixtures/html-facts/equinox-sports-club-sf-redesigned.html").read_text()
    if not relative_today:
        html = html.replace('<span>Today</span>', '<span>Thursday</span>', 1)
    match = re.search(r'(<script[^>]*id="__NEXT_DATA__"[^>]*>)(.*?)(</script>)', html, re.S)
    page = json.loads(match[2])
    row = {"id": "synthetic", "startDay": "11/26/2026", "startHour": 7, "startMinutes": 0,
           "endDay": "11/26/2026", "endHour": 15, "endMinutes": 0,
           "startTime": "2026-11-26T07:00:00", "endTime": "2026-11-26T15:00:00",
           "holidayType": "Club", "closed": False} | changes
    page["props"]["pageProps"]["facility"]["holidays"] = [{"name": "THANKSGIVING HOLIDAY HOURS", "holidayHours": [row]}]
    return html[:match.start(2)] + json.dumps(page) + html[match.end(2):]


def test_equinox_structured_club_holiday_is_a_dated_access_exception():
    payload = _extract_equinox(equinox_holiday_source(), observed_on=date(2026, 11, 20))
    assert payload["schedule_basis"] == "facility_hours"
    assert payload["sessions"] == payload["closures"] == []
    assert [(row["date"], row["start"], row["end"]) for row in payload["access_exceptions"]] == [("2026-11-26", "07:00", "15:00")]


def test_equinox_scope_hold_preserves_the_closure_review_path():
    with pytest.raises(HtmlClosureReviewRequired) as error:
        _extract_equinox(equinox_holiday_source(holidayType='Pool'), observed_on=date(2026, 11, 20))
    assert error.value.notices
    assert '"holidayType": "Pool"' in error.value.notices[0]['text']


@pytest.mark.parametrize('printed,closed,accepted', [
    ('5:00am – 10:00pm', False, False), ('7:00am – 3:00pm', False, True),
    ('Closed', True, True), ('5:00am – 10:00pm', True, False),
    ('Closed', False, False), ('7:00am – 3:00pm', True, False),
])
def test_equinox_today_is_reconciled_against_the_observed_holiday(printed, closed, accepted):
    changes = {'closed': True, 'startHour': 0, 'endHour': 0,
               'startTime': '2026-11-26T00:00:00', 'endTime': '2026-11-26T00:00:00'} if closed else {}
    html = equinox_holiday_source(relative_today=True, **changes)
    original = '<span>Today</span><span>5:00am – 10:00pm</span>'
    assert original in html
    html = html.replace(original, f'<span>Today</span><span>{printed}</span>', 1)
    if accepted:
        payload = _extract_equinox(html, observed_on=date(2026, 11, 26))
        assert bool(payload['closures']) is closed
        assert bool(payload['access_exceptions']) is not closed
    else:
        with pytest.raises(DirectSourceError):
            _extract_equinox(html, observed_on=date(2026, 11, 26))


@pytest.mark.parametrize('observed,accepted', [(date(2026, 11, 19), True), (date(2026, 11, 20), False)])
def test_equinox_today_date_is_reconciled_on_ordinary_days(observed, accepted):
    html = equinox_holiday_source(relative_today=True)
    if accepted:
        assert _extract_equinox(html, observed_on=observed)['access_hours']
    else:
        with pytest.raises(DirectSourceError, match='observed date'):
            _extract_equinox(html, observed_on=observed)


@pytest.mark.parametrize('printed,accepted', [('7:00am – 3:00pm', True), ('5:00am – 10:00pm', False)])
def test_equinox_daily_summary_uses_the_observed_date_not_any_weekday(printed, accepted):
    html = equinox_holiday_source()
    html = re.sub(r'(<body\b[^>]*>)', lambda match: match[1] + f'<p>Hours today {printed} Join Now</p>', html, count=1)
    if accepted:
        assert _extract_equinox(html, observed_on=date(2026, 11, 26))['access_exceptions']
    else:
        with pytest.raises(DirectSourceError):
            _extract_equinox(html, observed_on=date(2026, 11, 26))


@pytest.mark.parametrize("changes", [
    {"holidayType": "Pool"}, {"endDay": "11/27/2026"}, {"endTime": "2026-11-26T16:00:00"},
    {"startHour": 3, "startTime": "2026-11-26T03:00:00"}, {"closed": "false"},
    {"unknown": "Pool closure"},
])
def test_equinox_unsupported_or_conflicting_holiday_stays_held(changes):
    with pytest.raises(DirectSourceError):
        _extract_equinox(equinox_holiday_source(**changes), observed_on=date(2026, 11, 20))
