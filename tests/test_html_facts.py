import re
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from jsonschema import validate

from schedules.direct_sources.errors import DirectSourceError
from schedules.direct_sources.html_facts import (
    HtmlClosureReviewRequired, html_source_payload, inspect_html_source,
)
from schedules.schema import EXTRACTION_SCHEMA

FIXTURES = Path(__file__).parent / 'fixtures' / 'html-facts'
OBSERVED = date(2026, 9, 8)


def inventory(slug, transform=lambda value: value):
    return inspect_html_source(slug, transform((FIXTURES / f'{slug}.html').read_text()))


def payload(slug, observed=OBSERVED, transform=lambda value: value):
    source = inventory(slug, transform)
    return html_source_payload(source, observed)


@pytest.mark.parametrize('slug,basis', [
    ('jccsf', 'swim_schedule'), ('sfsu-mashouf', 'pool_hours'),
    ('embarcadero-ymca', 'pool_hours'), ('presidio-ymca-letterman', 'temporarily_closed'),
])
def test_frozen_originals_pass_independent_validation(slug, basis):
    source = inventory(slug)
    result = html_source_payload(source, OBSERVED)
    validate(result, EXTRACTION_SCHEMA)
    assert result['schedule_basis'] == basis
    assert result['effective_start'] == '2026-09-08'
    assert result['effective_end'] <= '2026-09-21'


@pytest.mark.parametrize('slug,reason', [
    ('stonestown-ymca', 'Printed weekday conflicts'),
    ('chinatown-ymca', 'conflicting holiday'),
])
def test_ambiguous_closures_hold_before_publication(slug, reason):
    with pytest.raises(HtmlClosureReviewRequired, match=reason) as caught:
        html_source_payload(inventory(slug), OBSERVED)
    assert caught.value.issues
    assert caught.value.notices
    assert all(set(notice) == {'text', 'scope', 'source_line'} for notice in caught.value.notices)


def test_changed_jccsf_hours_are_read_from_source():
    rows = payload('jccsf')['sessions']
    assert any(row['day'] == 'monday' and row['type'] == 'family_swim' and row['start'] == '13:30' for row in rows)
    assert any(row['day'] == 'tuesday' and row['type'] == 'family_swim' and row['start'] == '12:30' for row in rows)
    assert any(row['day'] == 'thursday' and row['type'] == 'family_swim' and row['start'] == '13:00' for row in rows)
    assert any(row['day'] == 'friday' and row['type'] == 'family_swim' and row['end'] == '12:00' for row in rows)


def test_third_sunday_closes_both_pools_at_six():
    rows = [row for row in payload('jccsf')['sessions'] if row['day'] == 'sunday']
    tails = [row for row in rows if row['end'] == '18:45']
    assert {row['pool'] for row in tails} == {'lap', 'rec'}
    assert all(row['start'] == '18:00' and row['excluded_dates'] == ['2026-09-20'] for row in tails)
    assert {row['pool'] for row in rows if row['end'] == '18:00'} == {'lap', 'rec'}


def test_third_sunday_recomputed_without_changing_source_inventory():
    source = inventory('jccsf')
    original = deepcopy(source)
    result = html_source_payload(source, date(2026, 10, 10))
    assert {tuple(row.get('excluded_dates', [])) for row in result['sessions']} == {(), ('2026-10-18',)}
    assert source == original


def test_letterman_never_extends_closed_hours_after_printed_end():
    assert payload('presidio-ymca-letterman')['effective_end'] == '2026-09-13'
    assert payload('presidio-ymca-letterman', date(2026, 9, 13))['effective_end'] == '2026-09-13'
    with pytest.raises(DirectSourceError, match='lacks a current'):
        payload('presidio-ymca-letterman', date(2026, 9, 14))
    with pytest.raises(DirectSourceError):
        payload('presidio-ymca-letterman', date(2027, 9, 8))


def test_sfsu_natatorium_hours_exclude_footer_facility_hours():
    result = payload('sfsu-mashouf')
    assert result['sessions'] == []
    assert [(row['day'], row['start'], row['end']) for row in result['access_hours']] == [
        ('monday', '10:00', '20:00'), ('tuesday', '10:00', '20:00'),
        ('wednesday', '10:00', '20:00'), ('thursday', '10:00', '20:00'),
        ('friday', '12:00', '16:00'), ('saturday', '12:00', '16:00'),
    ]
    assert result['closures'] == []


def test_explicit_printed_year_is_preserved_and_never_rolled_forward():
    source = inventory('sfsu-mashouf')
    closure = next(row for row in source['lines'] if 'closed' in row['text'])
    assert 'August 15, 2026 through August 23, 2026' in closure['text']
    assert html_source_payload(source, date(2027, 8, 16))['closures'] == []


def test_ymca_pool_offsets_and_explicit_holiday_closing():
    result = payload('embarcadero-ymca', date(2026, 11, 20))
    assert result['sessions'] == []
    assert result['access_hours'][0]['start'] == '06:00'
    assert result['access_hours'][0]['end'] == '20:30'
    assert [(row['date'], row['start'], row['end']) for row in result['access_exceptions']] == [
        ('2026-11-26', '07:30', '13:30'), ('2026-11-27', '07:30', '13:30'),
    ]


def test_ymca_facility_holiday_closure_applies_to_pool():
    result = payload('embarcadero-ymca', date(2026, 11, 10))
    assert result['closures'][0]['start'] == '2026-11-11'
    assert result['closures'][0]['end'] == '2026-11-11'
    assert 'All Staff Training' in result['closures'][0]['reason']


def test_yearless_holiday_rollover_uses_printed_weekday():
    result = payload('embarcadero-ymca', date(2026, 12, 30))
    assert any(row['date'] == '2027-01-01' and row['end'] == '15:30' for row in result['access_exceptions'])


def test_unchanged_text_ignores_html_byte_churn():
    assert inventory('sfsu-mashouf') == inventory('sfsu-mashouf', lambda text: '<!-- unrelated build 42 -->' + text.replace('class="', 'data-test="ignored" class="'))


def test_new_notice_outside_hours_is_not_silently_ignored():
    source = inventory('sfsu-mashouf', lambda text: text.replace('</body>', '<div>The pool closes early on Tuesdays for maintenance.</div></body>'))
    assert any('closes early' in row['text'] for row in source['lines'])
    with pytest.raises(HtmlClosureReviewRequired):
        html_source_payload(source, OBSERVED)


def test_wrong_source_and_duplicate_weekday_rows_hold():
    with pytest.raises(DirectSourceError, match='identity'):
        inspect_html_source('sfsu-mashouf', '<h1>Wrong pool</h1>')
    source = inventory('sfsu-mashouf', lambda text: text.replace('Friday - Saturday:', 'Monday - Saturday:'))
    with pytest.raises(DirectSourceError, match='all seven'):
        html_source_payload(source, OBSERVED)


def test_unsupported_recurring_opening_change_holds():
    source = inventory('jccsf', lambda text: text.replace('*3rd Sunday of the Month: 7:00 am', '*3rd Sunday of the Month: 8:00 am'))
    with pytest.raises(DirectSourceError, match='opening-time'):
        html_source_payload(source, OBSERVED)


@pytest.mark.parametrize('notice', [
    '<div>Closed September 20 for maintenance.</div>',
    '<div>Closed facility September 20 for maintenance.</div>',
    '<div>The pools will be closed September 20.</div>',
])
def test_unknown_global_closure_notice_requires_review(notice):
    source = inventory('sfsu-mashouf', lambda text: text.replace('</body>', notice + '</body>'))
    with pytest.raises(HtmlClosureReviewRequired):
        html_source_payload(source, OBSERVED)


def test_swim_school_section_does_not_override_literal_facility_closure():
    source = inventory('jccsf', lambda text: text.replace('Swim School is closed for Rosh Hashanah.', 'Closed facility for Rosh Hashanah.'))
    with pytest.raises(HtmlClosureReviewRequired, match='scope conflicts'):
        html_source_payload(source, OBSERVED)


def test_new_ymca_pool_hours_section_is_not_treated_as_unrelated():
    with pytest.raises(DirectSourceError, match='section identity'):
        inventory('stonestown-ymca', lambda text: text.replace('<h2>Annex Hours</h2>', '<h2>Children Pool Hours</h2>'))


# Original response bytes and receipt hashes from hosted capture run 34310713112.
@pytest.mark.parametrize('slug,source_url,sha256', [
    ('jccsf', 'https://www.jccsf.org/fitness/aquatics/', '47635a4d4d68c71d695d2b68ceae4dfcbf53df0896262d9716a27905d8217167'),
    ('embarcadero-ymca', 'https://www.ymcasf.org/location/embarcadero-ymca/', 'f4ee39e1e23f8bad5e075b131a06ee414ebfbaaa1bfe483a3e6768369614a633'),
    ('stonestown-ymca', 'https://www.ymcasf.org/location/stonestown-family-ymca/', 'ace19aeda3b06386e1003a67ec0ef697c88a1d94b68f7b6d9637893f8cad4d97'),
    ('chinatown-ymca', 'https://www.ymcasf.org/location/chinatown-ymca/', '2af597fab2759abbf12d2913d0cb0c4b959d822f6e8b20a91fd1ee5b185a12b9'),
    ('presidio-ymca-letterman', 'https://www.ymcasf.org/location/presidio-community-ymca/letterman-pool-gym/', 'f0f8836ffee8872e392984ce84e164dab037258978a071df34c99d033e833724'),
    ('sfsu-mashouf', 'https://campusrec.sfsu.edu/Aquatics', '7c086f2f60cd34190cdcd7c66b5ef3ec2fc6848c43b4c77f871c0c8fb81a9ca3'),
])
def test_frozen_original_capture_bytes(slug, source_url, sha256):
    import hashlib

    assert source_url.startswith('https://')
    assert hashlib.sha256((FIXTURES / f'{slug}.html').read_bytes()).hexdigest() == sha256


def test_partial_day_notice_is_not_published_as_all_day_closure():
    source = inventory('sfsu-mashouf', lambda text: text.replace('</body>', '<div>The Natatorium will be closed from 9 am to 11 am on September 20, 2026.</div></body>'))
    with pytest.raises(HtmlClosureReviewRequired, match='partial-day'):
        html_source_payload(source, OBSERVED)


def test_recurring_extension_is_not_silently_omitted():
    source = inventory('jccsf', lambda text: text.replace('*3rd Sunday of the Month: 7:00 am – 6:00 pm', '*3rd Sunday of the Month: 7:00 am – 8:00 pm'))
    with pytest.raises(HtmlClosureReviewRequired, match='opening-time'):
        html_source_payload(source, OBSERVED)


@pytest.mark.parametrize('keep_offset', [True, False])
def test_independent_ymca_pool_group_is_not_shifted_or_labeled_facility(keep_offset):
    extra = '<h2>Pool Hours</h2>' + ''.join(
        f'<div class="tr-accordion_day-hour__list"><span>{day}</span><span>9 am – 5 pm</span></div>'
        for day in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
    )

    def change(text):
        if not keep_offset:
            text = re.sub(r'<div class="tr-accordion_day-hour__list">\s*<span>Pool\s+Hours</span>.*?</div>', '', text, flags=re.S)
        return text.replace('<h2>Facility Hours</h2>', extra + '<h2>Facility Hours</h2>')

    source = inventory('embarcadero-ymca', change)
    with pytest.raises(DirectSourceError, match='weekly hours groups'):
        html_source_payload(source, OBSERVED)


def test_changed_ymca_primary_hours_scope_requires_explicit_support():
    source = inventory('embarcadero-ymca', lambda text: text.replace('<h2>Facility Hours</h2>', '<h2>Pool Hours</h2>'))
    with pytest.raises(DirectSourceError, match='weekly hours groups'):
        html_source_payload(source, OBSERVED)


def test_raw_source_size_is_bounded_before_inventory():
    with pytest.raises(DirectSourceError, match='four MiB'):
        inspect_html_source('jccsf', 'x' * (4 * 1024 * 1024 + 1))
    with pytest.raises(DirectSourceError, match='four MiB'):
        inspect_html_source('jccsf', 'é' * (3 * 1024 * 1024))


def test_relevant_inventory_line_count_is_bounded():
    with pytest.raises(DirectSourceError, match='500-line'):
        inventory('sfsu-mashouf', lambda text: text.replace('</body>', ''.join(f'<p>The pool will be closed on September 20. Notice {number}.</p>' for number in range(501)) + '</body>'))


@pytest.mark.parametrize('tag', ['p', 'div', 'button'])
def test_notice_scan_keeps_complete_text_across_html_whitespace(tag):
    notice = f'<{tag}>The pool will be closed from\nSeptember 12, 2026 through\nSeptember 13, 2026 for maintenance.</{tag}>'
    source = inventory('sfsu-mashouf', lambda text: text.replace('</body>', notice + '</body>'))
    notice_rows = [row for row in source['lines'] if 'September 12' in row['text']]
    assert len(notice_rows) == 1
    assert notice_rows[0]['text'] == 'The pool will be closed from September 12, 2026 through September 13, 2026 for maintenance.'
    result = html_source_payload(source, OBSERVED)
    assert result['closures'][0]['start'] == '2026-09-12'
    assert result['closures'][0]['end'] == '2026-09-13'


def test_availability_24_7_is_not_inventoried_as_a_date():
    notice = '<div>The pool will be closed from 09/12/2026 through 09/13/2026, 24/7 for maintenance.</div>'
    source = inventory('sfsu-mashouf', lambda text: text.replace('</body>', notice + '</body>'))
    result = html_source_payload(source, OBSERVED)
    assert result['closures'][0]['start'] == '2026-09-12'
    assert result['closures'][0]['end'] == '2026-09-13'


def test_all_closed_ymca_can_use_pool_closure_without_slug_exception():
    source = {
        'slug': 'embarcadero-ymca',
        'lines': [{'id': day, 'section': 'Facility Hours', 'scope': 'facility', 'text': f'{day.title()}: Closed'}
            for day in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')]
        + [{'id': 'pool-notice', 'section': 'Source notice', 'scope': 'pool',
            'text': 'The pool will be closed from September 1, 2026 through September 13, 2026 for maintenance.'}],
    }
    result = html_source_payload(source, OBSERVED)
    assert result['schedule_basis'] == 'temporarily_closed'
    assert result['effective_end'] == '2026-09-13'
    source['lines'][0]['text'] = 'Monday: 9 am - 5 pm'
    with pytest.raises(DirectSourceError, match='facility access hours'):
        html_source_payload(source, OBSERVED)


@pytest.mark.parametrize('hours', [
    '25 a.m. - 8 p.m.',
    '10 a.m. - 8',
    '10 p.m. - 8 p.m.',
    '10 a.m. - 8 p.m., 10 a.m. - 8 p.m.',
    '10 a.m. - 8 p.m., 7 a.m. - 9 a.m.',
])
def test_invalid_ambiguous_duplicate_or_overlapping_printed_ranges_hold(hours):
    source = inventory('sfsu-mashouf', lambda text: text.replace('10 a.m. - 8 p.m.', hours))
    with pytest.raises(DirectSourceError):
        html_source_payload(source, OBSERVED)


def test_missing_source_weekdays_hold():
    source = inventory('sfsu-mashouf', lambda text: re.sub(r'<li><strong>Friday - Saturday:.*?</li>', '', text))
    with pytest.raises(DirectSourceError, match='all seven'):
        html_source_payload(source, OBSERVED)


def test_identical_simultaneous_intervals_in_two_pools_remain_distinct():
    rows = payload('jccsf', transform=lambda text: text.replace(
        'Monday &amp; Wednesday: 5:30 am – Noon, 1:30 – 9:45 pm',
        'Monday &amp; Wednesday: 5:30 am – 9:45 pm',
    ))['sessions']
    matching = [row for row in rows if row['day'] == 'monday' and row['start'] == '05:30' and row['end'] == '21:45']
    assert {row['pool'] for row in matching} == {'lap', 'rec'}
    assert {row['type'] for row in matching} == {'lap_swim', 'family_swim'}


def test_rec_pool_intervals_cannot_exceed_printed_aquatics_center_hours():
    source = inventory('jccsf', lambda text: text.replace('Monday – Friday: 5:30 am – 9:45 pm', 'Monday – Friday: 5:30 am – Noon'))
    with pytest.raises(DirectSourceError, match='conflict with Aquatics Center'):
        html_source_payload(source, OBSERVED)


@pytest.mark.parametrize('slug', ['jccsf', 'sfsu-mashouf', 'embarcadero-ymca', 'presidio-ymca-letterman'])
def test_supported_capture_payloads_pass_actual_merge_normalization(slug):
    from schedules.merge import _normalized_schedule_payload

    result = payload(slug)
    normalized = _normalized_schedule_payload(result)
    assert normalized['schedule_basis'] == result['schedule_basis']
    if slug == 'presidio-ymca-letterman':
        assert normalized['closures'][0]['reason_code'] == 'maintenance'
        assert normalized['closures'][0]['end'] == '2026-09-13'
        assert normalized['closures'][0]['source_notices'][0]['text'] == result['closures'][0]['reason']


@pytest.mark.parametrize('observed,closed_date,reason_code', [
    (date(2026, 11, 10), '2026-11-11', 'staff_training'),
    (date(2026, 12, 20), '2026-12-25', 'holiday'),
])
def test_future_ymca_closures_have_grounded_codes_and_normalize(observed, closed_date, reason_code):
    from schedules.merge import _normalized_schedule_payload

    normalized = _normalized_schedule_payload(payload('embarcadero-ymca', observed))
    assert any(row['start'] == closed_date and row['reason_code'] == reason_code for row in normalized['closures'])


@pytest.mark.parametrize('reason', ['', 'for maintenance and a holiday'])
def test_unknown_or_conflicting_closure_reason_holds(reason):
    notice = f'<div>The pool will be closed from September 12, 2026 through September 13, 2026 {reason}.</div>'
    source = inventory('sfsu-mashouf', lambda text: text.replace('</body>', notice + '</body>'))
    with pytest.raises(HtmlClosureReviewRequired, match='closure reason'):
        html_source_payload(source, OBSERVED)
