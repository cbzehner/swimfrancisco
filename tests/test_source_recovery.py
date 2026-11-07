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
    original = (Path(__file__).parent / "fixtures/html-facts/bay-club-gateway.html").read_text()
    week = re.search(r'<div class="club_hours_info w-richtext">(.*?)</div>', original, re.S)[1]
    html = original.replace('</body>', f'<div data-club-hours="" class="club_hero_hours w-richtext">{week}</div><p data-club-today="">6:00 am - 9:00 pm</p></body>')
    assert _extract_bayclub_gateway(html, observed_on=date(2026, 11, 6))["access_hours"]
    with pytest.raises(HtmlClosureReviewRequired, match="daily summary"):
        _extract_bayclub_gateway(html.replace('data-club-today="">6:', 'data-club-today="">5:'), observed_on=date(2026, 11, 6))
    with pytest.raises(DirectSourceError, match="disagree"):
        _extract_bayclub_gateway(html.replace('data-club-hours="" class="club_hero_hours w-richtext">', 'data-club-hours="" class="club_hero_hours w-richtext">', 1).replace(week, week.replace('6:00 am', '5:00 am'), 1), observed_on=date(2026, 11, 6))


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
