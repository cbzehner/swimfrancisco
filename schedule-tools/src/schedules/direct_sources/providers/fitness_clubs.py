from __future__ import annotations

import json
import re
from datetime import date, timedelta
from html import unescape

from ..._time import pacific_today
from ...models import DAY_ORDER
from ..errors import DirectSourceError
from ..html_facts import HtmlClosureReviewRequired
from ..parsing import (
    _access_hour,
    _expand_days,
    _html_text,
    _parse_hours_range,
    _payload,
    _require_text,
)


def _extract_24_hour_fitness(html: str) -> dict:
    text = _html_text(html)
    if "temporarily closed for renovation" in text.lower():
        match = re.search(r"welcome you back on\s+(\d{2})/(\d{2})/(\d{4})", text, flags=re.IGNORECASE)
        closures: list[dict] = []
        if match:
            month, day, year = match.groups()
            reopen = date(int(year), int(month), int(day))
            end = reopen - timedelta(days=1)
            closures.append({
                "start": pacific_today().isoformat(),
                "end": end.isoformat(),
                "reason": "Temporarily closed for renovation",
            })
        return _payload("temporarily_closed", [], closures=closures)
    _require_text(text, "Gym Hours")
    access_hours: list[dict] = []
    for days_text, hours_text in re.findall(
        r'<span class="ih-days">([^<]+)</span>\s*<span class="ih-hours">([^<]+)</span>',
        html,
        flags=re.IGNORECASE,
    ):
        start, end = _parse_hours_range(unescape(hours_text))
        for day in _expand_days(days_text):
            access_hours.append(_access_hour(day, start, end, "Gym hours", f"{days_text}: {hours_text}"))
    if not access_hours:
        raise DirectSourceError("24 Hour Fitness page did not expose gym hours.")
    return _payload("facility_hours", [], access_hours=access_hours)


def _extract_bayclub_gateway(html: str) -> dict:
    text = _html_text(html)
    for identity in ('Bay Club Gateway', '370 Drumm Street', 'two heated pools'):
        _require_text(text, identity)
    if len(re.findall(r'<h1\b[^>]*>The Gateway</h1>', html, re.I)) != 1:
        raise DirectSourceError('Missing or duplicate Gateway club identity')
    blocks = list(re.finditer(r'<div\b[^>]*class="club_hours_info w-richtext"[^>]*>(.*?)</div>', html, re.I | re.S))
    notices = list(re.finditer(r'<div\b[^>]*class="text16regular-main orange[^"]*"[^>]*>(.*?)</div>', html, re.I | re.S))
    if len(blocks) != 1 or len(notices) != 1:
        raise DirectSourceError('Missing or duplicate Gateway hours or notice section')
    if notices[0].group(1).strip():
        _club_hold('Gateway has a populated club notice', _html_text(notices[0].group(1)) or 'Club-notice media')
    rows = []
    for paragraph in re.findall(r'<p\b[^>]*>(.*?)</p>', blocks[0].group(1), re.I | re.S):
        row = re.fullmatch(r'(Sun|Mon|Tue|Wed|Thu|Fri|Sat):\s*(.+)', _html_text(paragraph).replace('\u200d', '').strip(), re.I)
        if not row:
            raise DirectSourceError('Unsupported Gateway weekly hours row')
        rows.append(row.groups())
    if _html_text(re.sub(r'<p\b[^>]*>.*?</p>', '', blocks[0].group(1), flags=re.I | re.S)):
        raise DirectSourceError('Unaccounted Gateway hours content')
    access = _club_week(rows)
    remainder = html
    for match in sorted([blocks[0], notices[0]], key=lambda match: match.start(), reverse=True):
        remainder = remainder[:match.start()] + remainder[match.end():]
    template = re.search(r'<div class="details_info_cancelled"><div>CANCELLED</div>(.*?)</div></div><div class="div_flex-down x-left">', remainder, re.S)
    if template and _html_text(template.group(0)) == 'CANCELLED Location: placeholder Instructor: placeholder':
        remainder = remainder[:template.start()] + remainder[template.end():]
    if re.search(r'\b(?:closed|closure|closes|reopen|unavailable|maintenance|cancelled|canceled|special hours|holiday hours)\b', _html_text(remainder), re.I):
        _club_hold('Unaccounted Gateway closure or special-hours notice', _html_text(remainder))
    for kind in ('classes', 'events'):
        remainder = re.sub(r'<div id="' + kind + r'-template"[^>]*>.*?<a href="#" class="button clubs_' + kind + r' w-button">Learn More</a></div>', '', remainder, flags=re.S)
    _check_remaining_club_notices(remainder)
    return _payload('facility_hours', [], access_hours=access)


def _club_range(text: str) -> tuple[str, str]:
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[-–—]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)', text, re.I)
    if not match or any(not 1 <= int(match[index]) <= 12 for index in (1, 4)) or any(int(match[index] or 0) > 59 for index in (2, 5)):
        raise DirectSourceError('Unsupported or invalid printed club hours range')
    start, end = _parse_hours_range(text.replace('—', '-'))
    if start >= end:
        raise DirectSourceError('Unsupported overnight club hours range')
    return start, end


def _club_week(rows: list[tuple[str, str]]) -> list[dict]:
    hours = []
    seen = set()
    for days, raw in rows:
        start, end = _club_range(raw)
        for day in _expand_days(days):
            if day not in DAY_ORDER or day in seen:
                raise DirectSourceError('Unknown or duplicate club weekday')
            seen.add(day)
            hours.append(_access_hour(day, start, end, 'Club hours', f'{days}: {raw}'))
    if seen != set(DAY_ORDER):
        raise DirectSourceError('Club hours do not account for all seven weekdays')
    return sorted(hours, key=lambda row: DAY_ORDER.index(row['day']))


def _club_identity(hours: list[dict]) -> list[tuple[str, str, str]]:
    return [(row['day'], row['start'], row['end']) for row in hours]


def _check_remaining_club_notices(html: str) -> None:
    text = _html_text(html)
    if re.search(r'\b(?:closed|closure|closes|reopen|unavailable|maintenance|cancelled|canceled|special club hours|special hours|holiday hours)\b', text, re.I):
        _club_hold('Unaccounted club closure, cancellation, or special-hours notice', text)
    if re.search(r'(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\s*(?:[-–&,:]|\d)', text, re.I):
        raise DirectSourceError('Unaccounted club weekday or hours statement')


def _extract_fitness_sf(html: str) -> dict:
    if len(html.encode('utf-8')) > 4 * 1024 * 1024:
        raise DirectSourceError('Club source exceeds four MiB')
    text = _html_text(html)
    _require_text(text, '1455 Fillmore Street')
    if 'pool' not in text.lower():
        raise DirectSourceError('FITNESS SF source does not identify the pool amenity')
    matches = list(re.finditer(r'<div\b[^>]*class="([^"]*\bhour-rtb\b[^"]*)"[^>]*>(.*?)</div>', html, re.I | re.S))
    regular = []
    holidays = 0
    for match in matches:
        classes, content = match.groups()
        if 'holiday' in classes.split():
            if 'w-dyn-bind-empty' not in classes.split() or content.strip():
                _club_hold('FITNESS SF has unsupported populated holiday hours', _html_text(content) or 'Populated holiday-hours media')
            holidays += 1
            continue
        rows = []
        for paragraph in re.findall(r'<p\b[^>]*>(.*?)</p>', content, re.I | re.S):
            row = re.fullmatch(r'(Mon\s*-\s*Thu|Fri|Sat\s*-\s*Sun):\s*(.+)', _html_text(paragraph), re.I)
            if not row:
                raise DirectSourceError('Unsupported FITNESS SF weekly hours row')
            rows.append(row.groups())
        if _html_text(re.sub(r'<p\b[^>]*>.*?</p>', '', content, flags=re.I | re.S)):
            raise DirectSourceError('Unaccounted FITNESS SF hours content')
        regular.append(_club_week(rows))
    if not regular or holidays != len(regular):
        raise DirectSourceError('Missing FITNESS SF regular or holiday hours sections')
    if any(_club_identity(hours) != _club_identity(regular[0]) for hours in regular[1:]):
        raise DirectSourceError('Repeated FITNESS SF hours sections disagree')
    remainder = html
    for match in reversed(matches):
        remainder = remainder[:match.start()] + remainder[match.end():]
    remainder = re.sub(r'<h1\b[^>]*>Holiday Hours</h1>', '', remainder, flags=re.I)
    _check_remaining_club_notices(remainder)
    return _payload('facility_hours', [], access_hours=regular[0])


def _city_hours_table(table: str) -> list[dict]:
    rows = []
    for raw in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.I | re.S):
        cells = re.findall(r'<(?:td|th)\b[^>]*>(.*?)</(?:td|th)>', raw, re.I | re.S)
        if len(cells) == 1 and _html_text(cells[0]) == 'Location Hours: ( Holiday hours may vary.)':
            continue
        if len(cells) != 2:
            raise DirectSourceError('Unsupported City Sports hours table row')
        rows.append(tuple(_html_text(cell) for cell in cells))
    return _club_week(rows)


def _city_class_replacements(calendar: str) -> str:
    remaining = calendar
    for cell in re.findall(r'<td\b[^>]*>(.*?)</td>', calendar, re.I | re.S):
        notices = list(re.finditer(r'<div\b[^>]*class="subClsOldClsInfoTxt"[^>]*>(.*?)</div>', cell, re.I | re.S))
        if not notices:
            continue
        replacement = re.search(r'<a class="subClassLink" href="/Pages/ClassDescription.aspx\?id=\d+">([^<]+)</a>', cell)
        old = re.fullmatch(r'<span>([^<]+)</span><span>Temporarily</span><span>Unavailable</span>', notices[0].group(1), re.I)
        if len(notices) != 1 or not replacement or not old or replacement.end() > notices[0].start():
            _club_hold('Unrecognized City Sports class replacement notice', _html_text(cell))
        names = (unescape(old[1]).strip(), unescape(replacement[1]).strip())
        if not all(names) or names[0] == names[1] or re.search(
            r'\b(?:pool|aqua|aquatic|swim|facility|club|closed|closure|cancelled|canceled|maintenance|unavailable)\b',
            ' '.join(names), re.I,
        ):
            _club_hold('City Sports aquatic or unscoped class replacement requires review', _html_text(cell))
        remaining = remaining.replace(cell, cell.replace(notices[0].group(0), ''), 1)
    return remaining

def _extract_city_sports(html: str) -> dict:
    if len(html.encode('utf-8')) > 4 * 1024 * 1024:
        raise DirectSourceError('Club source exceeds four MiB')
    text = _html_text(html)
    _require_text(text, 'SAN FRANCISCO - 20TH AVE')
    _require_text(text, 'lap pool')
    primary = re.search(r'<div\b[^>]*id="clubInfoHours"[^>]*>(.*?)</div>', html, re.I | re.S)
    repeated = re.search(r'<table\b[^>]*>\s*<thead>\s*<tr>\s*<th\b[^>]*>Location Hours:(.*?)</table>', html, re.I | re.S)
    if not primary or not repeated:
        raise DirectSourceError('Missing City Sports primary or repeated location hours')
    first = _city_hours_table(primary.group(1))
    second = _city_hours_table(repeated.group(0))
    if _club_identity(first) != _club_identity(second):
        raise DirectSourceError('City Sports primary and repeated location hours disagree')
    calendar = re.search(r'<table\b[^>]*id="tblSchedule"[^>]*>(.*?)</table>', html, re.I | re.S)
    legend = re.search(r'<span\b[^>]*id="lbCancellationReason"[^>]*>(.*?)</span>\s*</td>', html, re.I | re.S)
    if not calendar:
        raise DirectSourceError('Missing City Sports class schedule context')
    calendar_text = _city_class_replacements(calendar.group(1))
    cancelled = []
    for cell in re.findall(r'<td\b[^>]*>(.*?)</td>', calendar_text, re.I | re.S):
        if not re.search(r'cancelled|canceled|maintenance|closure|closed', _html_text(cell), re.I):
            continue
        if not re.search(r'<a href="/Pages/ClassDescription.aspx\?id=\d+">', cell):
            raise DirectSourceError('City Sports cancellation is not bound to a named class')
        if re.search(r'\b(?:pool|aqua|aquatic|swim|facility|club)\b', _html_text(cell), re.I):
            _club_hold('City Sports aquatic or facility cancellation requires review', _html_text(cell))
        if not re.search(r'Cancelled\s*<br\s*/?>\s*\d{1,2}/\d{1,2} only<sup>1</sup>', cell):
            raise DirectSourceError('Unsupported City Sports class cancellation scope')
        cancelled.append(cell)
    remaining_calendar = calendar_text
    for cell in cancelled:
        remaining_calendar = remaining_calendar.replace(cell, '')
    if re.search(r'closed|closure|maintenance|cancelled|canceled|unavailable|special hours', _html_text(remaining_calendar), re.I):
        _club_hold('Unaccounted notice in City Sports class schedule', _html_text(remaining_calendar))
    if cancelled and (not legend or _html_text(legend.group(1)) != 'Cancellation Reason(s): 1 Maintenance'):
        raise DirectSourceError('City Sports class cancellation has an unknown legend')
    if legend and not cancelled:
        raise DirectSourceError('City Sports maintenance legend has no matching class cancellation')
    kids = re.search(r'<table\b[^>]*>\s*<thead>\s*<tr>\s*<th\b[^>]*>Kids Klub Hours:(.*?)</table>', html, re.I | re.S)
    if kids and _html_text(kids.group(0)) != 'Kids Klub Hours: ( Holiday hours may vary.) Monday - Sunday Closed':
        raise DirectSourceError('Unsupported City Sports Kids Klub notice')
    spans = [primary.span(), repeated.span(), calendar.span()]
    if legend:
        spans.append(legend.span())
    if kids:
        spans.append(kids.span())
    remainder = html
    for start, end in sorted(spans, reverse=True):
        remainder = remainder[:start] + remainder[end:]
    remainder = remainder.replace('Some facilities and amenities may be temporarily closed or subject to occupancy limits or other restrictions.', '')
    _check_remaining_club_notices(remainder)
    return _payload('facility_hours', [], access_hours=first)


def _club_hold(issue: str, text: str) -> None:
    raise HtmlClosureReviewRequired(issue, {'lines': [{'id': 'club-notice', 'section': 'Holiday Hours', 'scope': 'facility', 'text': text}]})


def _equinox_clock(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d(?::00)?', value):
        raise DirectSourceError('Invalid Equinox structured clock')
    return value[:5]


def _equinox_structured_week(rows: list[dict]) -> list[dict]:
    hours = []
    seen = set()
    for row in rows:
        start, end = _equinox_clock(row['opens']), _equinox_clock(row['closes'])
        if start >= end or not isinstance(row['dayOfWeek'], list) or not row['dayOfWeek']:
            raise DirectSourceError('Unsupported Equinox structured hours interval')
        for raw_day in row['dayOfWeek']:
            day = raw_day.lower()
            if day not in DAY_ORDER or day in seen:
                raise DirectSourceError('Unknown or duplicate Equinox structured weekday')
            seen.add(day)
            hours.append(_access_hour(day, start, end, 'Club hours', f'{raw_day}: {start}–{end}'))
    if seen != set(DAY_ORDER):
        raise DirectSourceError('Equinox structured hours omit a weekday')
    return sorted(hours, key=lambda row: DAY_ORDER.index(row['day']))


def _equinox_service_week(hours: dict) -> list[dict]:
    rows = []
    for day, ranges in hours.items():
        if len(ranges) != 1 or len(_expand_days(day)) != 1:
            raise DirectSourceError('Unsupported Equinox service hours ranges')
        rows.append({'dayOfWeek': [_expand_days(day)[0]], 'opens': ranges[0]['startTime'], 'closes': ranges[0]['endTime']})
    return _equinox_structured_week(rows)


def _equinox_visible_week(rows: list[tuple[str, str]]) -> list[dict]:
    labels = [label.lower() for label, _ in rows]
    if 'today' in labels:
        named = [_expand_days(label)[0] for label in labels if label != 'today']
        missing = set(DAY_ORDER) - set(named)
        if labels.count('today') != 1 or len(rows) != 7 or len(missing) != 1:
            raise DirectSourceError('Ambiguous Equinox Today weekday')
        rows = [(next(iter(missing)) if label.lower() == 'today' else label, hours) for label, hours in rows]
        days = [_expand_days(label)[0] for label, _ in rows]
        if any((DAY_ORDER.index(right) - DAY_ORDER.index(left)) % 7 != 1 for left, right in zip(days, days[1:])):
            raise DirectSourceError('Equinox visible weekday order conflicts with Today')
    return _club_week(rows)


def _extract_equinox(html: str) -> dict:
    url = 'https://www.equinox.com/clubs/northern-california/sportsclubsanfrancisco'
    name = 'Equinox Sports Club San Francisco'
    if len(html.encode('utf-8')) > 4 * 1024 * 1024:
        raise DirectSourceError('Club source exceeds four MiB')
    try:
        canonical = [re.search(r'\bhref="([^"]+)"', tag, re.I)[1]
            for tag in re.findall(r'<link\b[^>]*>', html, re.I)
            if re.search(r'\brel="canonical"', tag, re.I)]
        if canonical != [url]:
            raise DirectSourceError('Equinox canonical source URL does not match')
        structured = [json.loads(raw) for raw in re.findall(r'<script\b[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.I | re.S)]
        clubs = [node for document in structured for node in document.get('@graph', []) if node.get('@type') == 'HealthClub' and node.get('url') == url]
        if len(clubs) != 1:
            raise DirectSourceError('Missing or duplicate primary Equinox structured identity')
        club = clubs[0]
        if club.get('name') != name or club.get('@id') != url + '#healthclub' or club['address'].get('streetAddress') != '747 Market Street' or club['address'].get('addressLocality') != 'San Francisco':
            raise DirectSourceError('Equinox primary club identity does not match')
        if club.get('specialOpeningHoursSpecification'):
            _club_hold('Equinox has structured special hours', json.dumps(club['specialOpeningHoursSpecification']))
        primary = _equinox_structured_week(club['openingHoursSpecification'])
        documents = re.findall(r'<script\b[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.I | re.S)
        if len(documents) != 1:
            raise DirectSourceError('Missing or duplicate Equinox facility data')
        page = json.loads(documents[0])['props']['pageProps']
        facility = page['facility']
        if facility.get('name') != name or page.get('slug') != 'clubs/northern-california/sportsclubsanfrancisco':
            raise DirectSourceError('Equinox facility data is for another club')
        if facility['holidays'] != []:
            _club_hold('Equinox has populated holiday hours', json.dumps(facility['holidays']))
        for field in ('banner', 'statusMessage', 'clubHTMLContent'):
            if facility.get(field):
                _club_hold('Equinox has a structured facility notice requiring review', json.dumps({field: facility[field]}))
        if (facility.get('clubMessageTitle'), facility.get('clubMessageBody')) != (
            'Destination Club', 'This club is only accessible to Equinox Destination Members.',
        ):
            _club_hold('Equinox has an unrecognized facility message', json.dumps({key: facility.get(key) for key in ('clubMessageTitle', 'clubMessageBody')}))
        banner = page['club']['fields'].get('notificationBanner') or {}
        _check_remaining_club_notices(json.dumps(banner.get('fields', {})))
        services = facility['facilityServiceHours']
        if sorted(service['serviceType'] for service in services) != ['Appointment Hours', 'Club', 'Spa']:
            raise DirectSourceError('Unsupported or duplicate Equinox service hours scope')
        for service in services:
            _equinox_service_week(service['hours'])
        club_services = [service for service in services if service['serviceType'] == 'Club']
        spa_services = [service for service in services if service['serviceType'] == 'Spa']
        if len(club_services) != 1 or len(spa_services) != 1:
            raise DirectSourceError('Missing or duplicate Equinox Club or Spa hours')
        repeated = [
            _equinox_service_week(club_services[0]['hours']),
            _equinox_service_week(facility['facilityFormattedServiceHours']['hours']),
            _club_week([(row['days'], row['hours']) for row in facility['serviceHours']]),
        ]
        if any(_club_identity(group) != _club_identity(primary) for group in repeated):
            raise DirectSourceError('Equinox primary and repeated club hours disagree')
        spa = _equinox_service_week(spa_services[0]['hours'])
        if _club_identity(spa) != _club_identity(_club_week([(row['days'], row['hours']) for row in facility['spaServiceHours']])):
            raise DirectSourceError('Equinox repeated spa hours disagree')
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise DirectSourceError('Malformed or incomplete Equinox structured source') from error
    primary_html = html
    for heading in re.finditer(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>', html, re.I | re.S):
        if _html_text(heading[1]).startswith('Other locations near '):
            primary_html = html[:heading.start()]
            break
    primary_text = _html_text(primary_html)
    _require_text(primary_text, '747 Market Street')
    if not re.search(r'\bindoor(?: saline lap)? pool\b', primary_text, re.I):
        raise DirectSourceError('Equinox primary source does not establish the indoor pool amenity')
    groups = [(match, re.findall(r'<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>', match[1], re.I | re.S))
        for match in re.finditer(r'<dl\b[^>]*>(.*?)</dl>', primary_html, re.I | re.S)]
    for match in re.finditer(r'<ul\b[^>]*>(.*?)</ul>', primary_html, re.I | re.S):
        rows = re.findall(r'<li\b[^>]*>\s*<span>([^<]+)</span>\s*<span>([^<]+)</span>\s*</li>', match[1], re.I | re.S)
        if rows and any(label.lower() == 'today' or label.lower()[:3] in {day[:3] for day in DAY_ORDER} for label, _ in rows):
            groups.append((match, rows))
    for notice in re.finditer(r'<div\b[^>]*class="[^"]*holiday-exception[^"]*"[^>]*>(.*?)</div>', primary_html, re.I | re.S):
        if notice[1].strip():
            _club_hold('Equinox has populated holiday hours', _html_text(notice[1]) or 'Holiday-hours media')
    consumed = []
    found = {'club': 0, 'spa': 0}
    for match, rows in sorted(groups, key=lambda group: group[0].start()):
        row_pattern = (r'<dt\b[^>]*>.*?</dt>\s*<dd\b[^>]*>.*?</dd>' if match.group(0).lower().startswith('<dl')
                       else r'<li\b[^>]*>\s*<span>[^<]+</span>\s*<span>[^<]+</span>\s*</li>')
        if not rows or _html_text(re.sub(row_pattern, '', match[1], flags=re.I | re.S)) or re.search(r'<(?:img|iframe|object|svg|canvas)\b', match[1], re.I):
            raise DirectSourceError('Unaccounted Equinox hours-group content')
        prefix = _html_text(primary_html[:match.start()]).lower()
        scope = 'spa' if prefix.rfind('spa hours') > max(prefix.rfind('club hours'), prefix.rfind('hours today')) else 'club'
        visible = _equinox_visible_week([(_html_text(day), _html_text(hours)) for day, hours in rows])
        if _club_identity(visible) != _club_identity(spa if scope == 'spa' else primary):
            raise DirectSourceError('Equinox primary and repeated visible hours disagree')
        consumed.append(match.span())
        found[scope] += 1
    if not all(found.values()):
        raise DirectSourceError('Missing complete Equinox visible Club or Spa hours')
    remainder = primary_html
    for start, end in sorted(consumed, reverse=True):
        remainder = remainder[:start] + remainder[end:]
    if re.search(r'\b(?:closed|closure|closes|reopen|unavailable|maintenance|cancelled|canceled|special hours|holiday hours)\b', _html_text(html), re.I):
        _club_hold('Equinox has an unaccounted whole-page closure or special-hours notice', _html_text(html))
    summaries = re.findall(r'Hours today\s+(.+?)(?=\s+Join Now|\s+Schedule a Visit|$)', _html_text(remainder), re.I)
    for summary in summaries:
        if _club_range(summary) not in {(row['start'], row['end']) for row in primary}:
            raise DirectSourceError('Equinox daily summary disagrees with weekly hours')
    _check_remaining_club_notices(remainder)
    return _payload('facility_hours', [], access_hours=primary)
