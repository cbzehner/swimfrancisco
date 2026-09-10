from pathlib import Path

import pytest

from schedules.direct_sources.errors import DirectSourceError
from schedules.direct_sources.html_facts import HtmlClosureReviewRequired
from schedules.direct_sources.providers.fitness_clubs import _extract_bayclub_gateway, _extract_city_sports, _extract_equinox, _extract_fitness_sf
from schedules.merge import _normalized_schedule_payload

FIXTURES = Path(__file__).parent / 'fixtures' / 'html-facts'


def source(slug):
    return (FIXTURES / f'{slug}.html').read_text()


@pytest.mark.parametrize('slug,extractor', [('fitness-sf-fillmore', _extract_fitness_sf), ('city-sports-20th-ave', _extract_city_sports)])
def test_original_club_sources_produce_complete_facility_hours_and_merge(slug, extractor):
    payload = extractor(source(slug))
    normalized = _normalized_schedule_payload(payload)
    assert normalized['schedule_basis'] == 'facility_hours'
    assert len(normalized['access_hours']) == 7
    assert normalized['sessions'] == []
    assert normalized['closures'] == []


def test_fitness_sf_midnight_hours_preserve_existing_schema_boundary():
    payload = _extract_fitness_sf(source('fitness-sf-fillmore'))
    assert [(row['start'], row['end']) for row in payload['access_hours']] == [('05:00', '23:59')] * 4 + [('05:00', '23:00')] + [('07:00', '20:00')] * 2


def test_fitness_repeated_hours_disagreement_holds():
    html = source('fitness-sf-fillmore').replace('Fri: 5 am - 11 pm', 'Fri: 6 am - 11 pm', 1)
    with pytest.raises(DirectSourceError, match='disagree'):
        _extract_fitness_sf(html)


@pytest.mark.parametrize('replacement', ['<p>Thanksgiving: Closed</p>', '<img src="holiday-hours.png">'])
def test_fitness_populated_holiday_content_requires_review(replacement):
    html = source('fitness-sf-fillmore').replace('w-dyn-bind-empty w-richtext"></div>', f'w-dyn-bind-empty w-richtext">{replacement}</div>', 1)
    with pytest.raises(HtmlClosureReviewRequired) as caught:
        _extract_fitness_sf(html)
    assert caught.value.notices


def test_fitness_missing_holiday_placeholder_holds():
    html = source('fitness-sf-fillmore').replace('hour-rtb holiday right', 'removed holiday right', 1)
    with pytest.raises(DirectSourceError, match='holiday hours sections'):
        _extract_fitness_sf(html)


@pytest.mark.parametrize('hours', ['25 am - 11 pm', '5 am - 11', '5 pm - 3 pm', '5 am - 11 pm, 1 am - 2 am'])
def test_fitness_invalid_or_unaccounted_ranges_hold(hours):
    html = source('fitness-sf-fillmore').replace('5 am - 11 pm', hours)
    with pytest.raises(DirectSourceError):
        _extract_fitness_sf(html)


def test_city_main_and_repeated_hours_must_agree():
    html = source('city-sports-20th-ave').replace('5:00am - 11:00pm', '6:00am - 11:00pm', 1)
    with pytest.raises(DirectSourceError, match='disagree'):
        _extract_city_sports(html)


def test_city_zumba_cancellation_does_not_close_the_pool_or_facility():
    assert _extract_city_sports(source('city-sports-20th-ave'))['closures'] == []


def test_city_pool_class_cancellation_requires_review():
    html = source('city-sports-20th-ave').replace('Zumba® Class</a></strong> (Cindy)<i>', 'Pool Swim</a></strong> (Cindy)<i>', 1)
    with pytest.raises(HtmlClosureReviewRequired, match='aquatic'):
        _extract_city_sports(html)


def test_city_unknown_cancellation_legend_holds():
    html = source('city-sports-20th-ave').replace('</sup></span>Maintenance', '</sup></span>Pool closure', 1)
    with pytest.raises(DirectSourceError, match='unknown legend'):
        _extract_city_sports(html)


def test_city_unscoped_calendar_header_notice_holds():
    html = source('city-sports-20th-ave')
    html = html.replace('<thead>', '<thead><tr><td>The pool is closed.</td></tr>', 1)
    with pytest.raises(DirectSourceError):
        _extract_city_sports(html)


@pytest.mark.parametrize('slug,extractor', [('fitness-sf-fillmore', _extract_fitness_sf), ('city-sports-20th-ave', _extract_city_sports)])
@pytest.mark.parametrize('notice', ['The pool is closed until further notice.', 'Special Club Hours: Thanksgiving 8 am - 2 pm.', 'The pool is unavailable for maintenance.'])
def test_new_global_club_notice_requires_review(slug, extractor, notice):
    html = source(slug).replace('</body>', f'<p>{notice}</p></body>')
    with pytest.raises(HtmlClosureReviewRequired):
        extractor(html)


@pytest.mark.parametrize('slug,extractor', [('fitness-sf-fillmore', _extract_fitness_sf), ('city-sports-20th-ave', _extract_city_sports)])
def test_uninventoried_new_weekday_hours_hold(slug, extractor):
    html = source(slug).replace('</body>', '<p>Monday: 9 am - 2 pm</p></body>')
    with pytest.raises(DirectSourceError, match='Unaccounted club weekday'):
        extractor(html)


@pytest.mark.parametrize('slug,url,digest', [
    ('fitness-sf-fillmore', 'https://fitnesssf.com/location/fillmore', 'eb19802b51f5715daf1067620e717a64b080bcac8d1258dcfe1a84c6679ceb68'),
    ('city-sports-20th-ave', 'https://www.citysportsfitness.com/Pages/clubhome.aspx?clubid=914', 'b84bc3fea43ae137f272d6369486c1def8fa9f922b3184a16bd6a984509d82e5'),
])
def test_frozen_original_september_ninth_capture_bytes(slug, url, digest):
    import hashlib

    assert url.startswith('https://')
    assert hashlib.sha256((FIXTURES / f'{slug}.html').read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('slug,extractor,expected', [
    ('equinox-sports-club-sf', _extract_equinox, [('05:00', '22:00')] * 4 + [('05:00', '21:00')] + [('07:00', '19:00')] * 2),
    ('bay-club-gateway', _extract_bayclub_gateway, [('06:00', '21:00')] * 5 + [('07:00', '20:00')] * 2),
])
def test_gateway_and_equinox_full_original_access_hours(slug, extractor, expected):
    payload = extractor(source(slug))
    assert payload['schedule_basis'] == 'facility_hours'
    assert payload['sessions'] == []
    assert [(row['start'], row['end']) for row in payload['access_hours']] == expected
    assert all(row['evidence'] for row in payload['access_hours'])
    assert len(_normalized_schedule_payload(payload)['access_hours']) == 7


@pytest.mark.parametrize('slug,extractor,address', [
    ('equinox-sports-club-sf', _extract_equinox, '747 Market Street'),
    ('bay-club-gateway', _extract_bayclub_gateway, '370 Drumm Street'),
])
def test_club_wrong_location_rejected(slug, extractor, address):
    with pytest.raises(DirectSourceError):
        extractor(source(slug).replace(address, '555 California Street'))


def test_equinox_repeated_header_disagreement_rejected():
    with pytest.raises(DirectSourceError, match='disagree'):
        _extract_equinox(source('equinox-sports-club-sf').replace('<time>5:00am</time>', '<time>6:00am</time>'))


@pytest.mark.parametrize('replacement', ['', '<dt>Mon</dt><dd>5:00am — 10:00pm</dd><dt>Mon</dt><dd>5:00am — 10:00pm</dd>', '<dt>Mon</dt><dd>25:00am — 10:00pm</dd>'])
def test_equinox_missing_duplicate_invalid_weekday_rejected(replacement):
    import re
    html = source('equinox-sports-club-sf')
    html = re.sub(r'<dt>Mon</dt><dd>5:00am<!-- --> — <!-- -->10:00pm<br/></dd>', lambda _: replacement, html, count=1)
    with pytest.raises(DirectSourceError):
        _extract_equinox(html)


@pytest.mark.parametrize('slug,extractor,marker', [
    ('equinox-sports-club-sf', _extract_equinox, 'class="ClubInfo_holiday-exception__CFwZw">'),
    ('bay-club-gateway', _extract_bayclub_gateway, 'class="text16regular-main orange w-condition-invisible w-dyn-bind-empty w-richtext">'),
])
@pytest.mark.parametrize('notice', ['<p>Pool closed tomorrow</p>', '<img src="hours.png">'])
def test_reserved_club_notice_content_requires_review(slug, extractor, marker, notice):
    with pytest.raises(HtmlClosureReviewRequired):
        extractor(source(slug).replace(marker, marker + notice, 1))


@pytest.mark.parametrize('slug,extractor', [('equinox-sports-club-sf', _extract_equinox), ('bay-club-gateway', _extract_bayclub_gateway)])
@pytest.mark.parametrize('notice', ['Pool unavailable for maintenance.', 'Holiday hours: Monday 9 am - 2 pm', 'Monday: 9 am - 2 pm'])
def test_gateway_equinox_global_notice_not_discarded(slug, extractor, notice):
    with pytest.raises(DirectSourceError):
        extractor(source(slug).replace('</body>', f'<p>{notice}</p></body>'))


def test_gateway_populated_cancellation_template_requires_review():
    with pytest.raises(HtmlClosureReviewRequired):
        _extract_bayclub_gateway(source('bay-club-gateway').replace('classes_details__location larger">placeholder', 'classes_details__location larger">Pool'))


@pytest.mark.parametrize('replacement', ['<p>Mon: 25 am - 9 pm</p>', '<p>Sun: 6 am - 9 pm</p>', ''])
def test_gateway_incomplete_duplicate_or_invalid_hours_hold(replacement):
    import re
    html = re.sub(r'<p>\u200d?<strong>Mon: </strong>6:00 am - 9:00 pm</p>', lambda _: replacement, source('bay-club-gateway'), count=1)
    with pytest.raises(DirectSourceError):
        _extract_bayclub_gateway(html)


CITY_REPLACEMENT_SOURCE = Path(__file__).resolve().parents[1] / 'data/city-sports-20th-ave/2026-09-08-759de370b994/source.html'


def test_retained_non_aquatic_class_replacement_does_not_close_facility():
    import hashlib

    raw = CITY_REPLACEMENT_SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '759de370b994006a409c932b80f8f9fa0af78af7c9ad7c6b9e75fe589dc2bac2'
    html = raw.decode()
    assert 'lbCancellationReason' not in html
    payload = _extract_city_sports(html)
    assert len(_normalized_schedule_payload(payload)['access_hours']) == 7
    assert payload['closures'] == []


@pytest.mark.parametrize('original,replacement', [
    ('<span>Zumba® Class</span><span>Temporarily</span>', '<span>Aqua Fit</span><span>Temporarily</span>'),
    ('class="subClassLink" href="/Pages/ClassDescription.aspx?id=9">Step Plus Abs', 'class="subClassLink" href="/Pages/ClassDescription.aspx?id=9">Pool Swim'),
    ('class="subClassLink"', 'class="unscopedLink"'),
    ('<span>Temporarily</span><span>Unavailable</span>', '<span>Cancelled until September 20</span>'),
    ('<span>Zumba® Class</span><span>Temporarily</span>', '<span>Facility</span><span>Temporarily</span>'),
])
def test_unsafe_or_unrecognized_class_replacement_holds(original, replacement):
    html = CITY_REPLACEMENT_SOURCE.read_text()
    assert original in html
    with pytest.raises(HtmlClosureReviewRequired):
        _extract_city_sports(html.replace(original, replacement, 1))


def test_class_replacement_cannot_hide_an_additional_unscoped_notice():
    html = CITY_REPLACEMENT_SOURCE.read_text().replace('<span>Unavailable</span></div>', '<span>Unavailable</span></div><p>The pool is unavailable.</p>', 1)
    with pytest.raises(HtmlClosureReviewRequired):
        _extract_city_sports(html)
