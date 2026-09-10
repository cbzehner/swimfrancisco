from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, timedelta


from ..models import DAY_ORDER
from .errors import DirectSourceError
from .parsing import _html_text, _payload, _squash

_IDENTITIES = {
    'jccsf': 'Gallanter Family Aquatics Center',
    'embarcadero-ymca': 'Embarcadero YMCA',
    'stonestown-ymca': 'Stonestown Family YMCA',
    'chinatown-ymca': 'Chinatown YMCA',
    'presidio-ymca-letterman': 'Letterman Pool & Gym',
    'sfsu-mashouf': 'Natatorium Hours of Operation',
}
_DAY = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
_DATE = rf'\b(?:{_DAY},?\s+)?(?:(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])(?:/\d{{4}})?|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{{1,2}}(?:,?\s+\d{{4}})?)\b'


def _blocks(html: str) -> list[tuple[str, str, int, int]]:
    return [(m.group(1).lower(), m.group(2), m.start(), m.end()) for m in re.finditer(
        r'<(h[1-6]|p|li)\b[^>]*>(.*?)</\1\s*>', html, flags=re.I | re.S)]


def inspect_html_source(slug: str, html: str) -> dict:
    if len(html) > 4 * 1024 * 1024 or len(html.encode('utf-8')) > 4 * 1024 * 1024:
        raise DirectSourceError('HTML source exceeds the four MiB inventory limit')
    if slug not in _IDENTITIES or _IDENTITIES[slug] not in _html_text(html):
        raise DirectSourceError('HTML source facility identity does not match the approved source')
    rows: list[dict] = []

    def add(section: str, scope: str, text: str) -> None:
        text = _squash(text)
        if text:
            if len(rows) >= 500:
                raise DirectSourceError('HTML source exceeds the 500-line inventory limit')
            identity = hashlib.sha256(f'{section}\n{scope}\n{text}'.encode()).hexdigest()[:16]
            occurrence = sum(row['id'].startswith(identity + '-') for row in rows)
            rows.append({'id': f'{identity}-{occurrence + 1}', 'section': section, 'scope': scope, 'text': text})

    blocks = _blocks(html)
    if slug == 'jccsf':
        section = ''
        scopes = {'Upcoming Closures': 'swim_school', 'Aquatics Center Hours': 'lap',
            'Rec Pool Hours': 'rec', 'Recreation & Family Swim': 'rec', 'Adult Swim': 'adult_swim'}
        for tag, raw, start, end in blocks:
            text = _html_text(raw)
            if tag.startswith('h'):
                section = text if text in scopes else ''
            elif section:
                for part in re.split(r'<br\s*/?>', raw, flags=re.I):
                    clean = _html_text(part)
                    if clean:
                        # Keep dated school closures as one statement, including printed years.
                        if section == 'Upcoming Closures':
                            add(section, 'swim_school', text)
                            break
                        add(section, scopes[section], clean)
    elif slug == 'sfsu-mashouf':
        section = ''
        for tag, raw, start, end in blocks:
            text = _html_text(raw)
            if tag.startswith('h'):
                section = text if text == 'Natatorium Hours of Operation' else ''
            elif section:
                add(section, 'pool', text)
    else:
        section_match = re.search(r'<section\b[^>]*\bid=["\']hours["\'][^>]*>(.*?)</section>', html, re.I | re.S)
        if not section_match:
            raise DirectSourceError('Missing YMCA hours section')
        section = ''
        scope = 'facility'
        hours = section_match.group(1)
        # Non-greedy paragraphs also retain the YMCA's nested <p><p> holiday markup.
        tokens = list(re.finditer(r'<h[24]\b[^>]*>(.*?)</h[24]>|<div\b[^>]*class=["\'][^"\']*tr-accordion_day-hour__list[^"\']*["\'][^>]*>(.*?)</div>|<p\b[^>]*>(.*?)</p>', hours, re.I | re.S))
        for token in tokens:
            heading, day_row, paragraph = token.groups()
            if heading is not None:
                new_section = _html_text(heading)
                if token.group(0).lower().startswith('<h4') and new_section != 'Holiday Hours':
                    continue
                section = new_section
                if section not in {'Holiday Hours', 'Facility Hours', 'Fitness Center Hours', 'Letterman Pool & Gym Hours', 'Pool Hours', 'YKids Hours', 'Annex Hours'}:
                    raise DirectSourceError('Unsupported YMCA hours section identity')
                if section != 'Holiday Hours':
                    scope = 'pool' if section == 'Pool Hours' else ('facility' if section in {'Facility Hours', 'Fitness Center Hours', 'Letterman Pool & Gym Hours'} else 'other')
            elif day_row is not None:
                cells = re.findall(r'<span\b[^>]*>(.*?)</span>', day_row, re.I | re.S)
                if len(cells) != 2:
                    raise DirectSourceError('Unsupported YMCA hours row structure')
                add(section, scope, ': '.join(_html_text(cell) for cell in cells))
            elif section == 'Holiday Hours':
                add(section, scope, _html_text(paragraph))
    if not rows:
        raise DirectSourceError('Missing supported HTML hours rows')
    visible = re.sub(r'<(script|style)\b.*?</\1>', '', html, flags=re.I | re.S)
    visible = re.sub(r'\s+', ' ', visible)
    visible = re.sub(r'</(?:p|li|div|h[1-6]|section|button)>|<br\s*/?>', '\n', visible, flags=re.I)
    for fragment in visible.splitlines():
        text = _html_text(fragment)
        if not re.search(r'\b(?:closed|closure|closes|reopen|maintenance)\b', text, re.I):
            continue
        if any(text in row['text'] or text in row['text'].replace(': ', ' ') for row in rows):
            continue
        subject = re.search(r'\b(?:pool|pools|facility|natatorium|aquatics|swim)\b', text, re.I)
        if text == 'If either the pools or the hot tub is closed, please do not enter the water for any reason.':
            add('Safety policy', 'other', text)
        elif subject:
            add('Source notice', 'facility' if re.search(r'facility', text, re.I) else 'pool', text)
        elif re.search(r'closed-toe|closed containers|hot tub|member lounge|computer lab', text, re.I):
            add('Other amenities and policies', 'other', text)
        else:
            add('Unscoped closure notice', 'other', text)
    return {'slug': slug, 'lines': rows}


def _days(text: str) -> list[str]:
    names = [match.group(0).lower() for match in re.finditer(_DAY, text, re.I)]
    if not names or len(names) != len(set(names)):
        raise DirectSourceError('Missing or duplicate source weekdays')
    if re.search(rf'{_DAY}\s*[-–]\s*{_DAY}', text, re.I):
        if len(names) != 2 or DAY_ORDER.index(names[0]) > DAY_ORDER.index(names[1]):
            raise DirectSourceError('Unsupported source weekday range')
        return list(DAY_ORDER[DAY_ORDER.index(names[0]):DAY_ORDER.index(names[1]) + 1])
    remainder = re.sub(_DAY, '', text, flags=re.I)
    if re.sub(r'[\s,&:*]|\band\b', '', remainder, flags=re.I):
        raise DirectSourceError('Unsupported source weekday phrase')
    return names


def _ranges(text: str) -> list[dict]:
    normalized = text.lower().replace('a.m.', 'am').replace('p.m.', 'pm')
    normalized = re.sub(r'\bnoon\b', '12:00 pm', normalized)
    normalized = re.sub(r'\bmidnight\b', '12:00 am', normalized)
    clock = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?'
    pattern = re.compile(clock + r'\s*[-–]\s*' + clock)
    matches = list(pattern.finditer(normalized))
    if not matches:
        raise DirectSourceError('Missing source hours range')
    out = []
    for match in matches:
        sh, sm, sa, eh, em, ea = match.groups()
        if not ea:
            raise DirectSourceError('Ambiguous source meridiem')
        sa = sa or ('am' if 'noon' in text.lower() and int(eh) == 12 and ea == 'pm' else ea)
        clocks = []
        for hour, minute, meridiem in [(sh, sm, sa), (eh, em, ea)]:
            if not 1 <= int(hour) <= 12 or not 0 <= int(minute or 0) <= 59:
                raise DirectSourceError('Invalid printed source clock')
            clocks.append(f'{int(hour) % 12 + (12 if meridiem == "pm" else 0):02d}:{int(minute or 0):02d}')
        if clocks[0] >= clocks[1]:
            raise DirectSourceError('Ambiguous or overnight source range')
        out.append({'start': clocks[0], 'end': clocks[1]})
    remainder = pattern.sub('', normalized)
    if re.sub(r'[\s,*]', '', remainder):
        raise DirectSourceError('Unaccounted text in source hours range')
    if len({(row['start'], row['end']) for row in out}) != len(out):
        raise DirectSourceError('Duplicate printed source range')
    for left, right in zip(out, out[1:]):
        if left['end'] > right['start']:
            raise DirectSourceError('Overlapping source ranges')
    return out


def _parse_line(line: dict) -> dict:
    text, scope, section = line['text'], line['scope'], line['section']
    fact = {'line_id': line['id'], 'kind': 'context', 'scope': scope, 'days': [], 'ranges': [], 'date_texts': [], 'recurrence': ''}
    if text.startswith('The Lap Pool is available for lap swimming during Aquatics Center hours.'):
        return fact | {'kind': 'rule'}
    if section == 'Unscoped closure notice':
        raise DirectSourceError('Closure notice lacks an explicit supported scope')
    if scope in {'other', 'swim_school', 'adult_swim'}:
        actionable = re.search(r'\b(?:closed|closure|closes|reopen)\b', text, re.I)
        subject = re.search(r'\b(?:pool|pools|facility|aquatics|natatorium)\b', text, re.I)
        if scope == 'swim_school' and actionable and 'Swim School is closed' not in text:
            raise DirectSourceError('Closure scope conflicts with swim-school section')
        if actionable and subject and section != 'Safety policy':
            raise DirectSourceError('Closure scope conflicts with source section')
        return fact
    if text.startswith(('View our current full', 'Pool capacity is 50 swimmers.')):
        return fact
    if text == 'Pool Hours: Opens 30 min after, closes 30 min before facility':
        return fact | {'kind': 'rule'}
    if re.fullmatch(r'\*3rd Sunday of the Month:.*', text):
        return fact | {'kind': 'exception', 'days': ['sunday'], 'ranges': _ranges(text.split(':', 1)[1]), 'recurrence': 'third_sunday'}
    if section == 'Holiday Hours':
        dates = re.findall(_DATE, text, re.I)
        if len(dates) != 1:
            raise DirectSourceError('Unsupported or conflicting holiday notice')
        tail = text[text.index(dates[0]) + len(dates[0]):].strip()
        tail = re.sub(r'^\([^)]*\)\s*', '', tail)
        if re.fullmatch(r'CLOSED\.?', tail, re.I):
            return fact | {'kind': 'closure', 'date_texts': dates}
        parts = re.split(r'\s+Pool (?:Hours:|Closes at)\s*', tail, flags=re.I)
        ranges = _ranges(parts[0])
        if len(parts) > 2:
            raise DirectSourceError('Unsupported holiday pool override')
        if len(parts) == 2:
            if 'Pool Closes at' in tail:
                closing = _ranges('12:01 am - ' + parts[1])[0]['end']
                ranges.append({'start': '', 'end': closing})
            else:
                ranges.extend(_ranges(parts[1]))
        return fact | {'kind': 'exception', 'ranges': ranges, 'date_texts': dates}
    if re.match(rf'^{_DAY}', text, re.I) and ':' in text:
        day_text, hours = text.split(':', 1)
        days = _days(day_text)
        if re.fullmatch(r'(?:Closed|Temporary Facility Maintenance Closure|Temporary Closure for Facility Maintenance)', hours.strip(), re.I):
            return fact | {'kind': 'closed_day', 'days': days}
        return fact | {'kind': 'weekly_hours', 'days': days, 'ranges': _ranges(hours)}
    if re.search(r'\b(?:closure|closed)\b', text, re.I):
        if re.search(r'\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|noon|midnight)', text, re.I):
            raise DirectSourceError('Unsupported partial-day source closure notice')
        dates = re.findall(_DATE, text, re.I)
        if len(dates) not in {1, 2} or not re.search(r'\b(?:from|through|starting|closure)', text, re.I):
            raise DirectSourceError('Unsupported source closure notice')
        return fact | {'kind': 'closure', 'date_texts': dates}
    raise DirectSourceError(f'Unsupported source hours statement: {text[:120]}')


def _resolve_date(text: str, observed: date) -> date:
    weekday = re.match(_DAY, text, re.I)
    printed = re.sub(rf'^{_DAY},?\s+', '', text, flags=re.I)
    numeric = re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', printed)
    if numeric:
        month, day, year = numeric.groups()
        month, day = int(month), int(day)
    else:
        named = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?', printed)
        if not named:
            raise DirectSourceError('Unsupported printed date')
        name, day, year = named.groups()
        month = list(calendar.month_name).index(name.title())
        day = int(day)
    try:
        if year:
            result = date(int(year), month, day)
        else:
            candidates = [date(observed.year + offset, month, day) for offset in (-1, 0, 1)]
            candidates = [candidate for candidate in candidates if -(366 if weekday else 183) <= (candidate - observed).days <= (366 if weekday else 183)]
            if weekday:
                candidates = [candidate for candidate in candidates if candidate.strftime('%A').lower() == weekday.group(0).lower()]
            if len(candidates) != 1:
                raise DirectSourceError('Ambiguous yearless source date')
            result = candidates[0]
    except ValueError as exc:
        raise DirectSourceError('Invalid printed date') from exc
    if weekday and result.strftime('%A').lower() != weekday.group(0).lower():
        raise DirectSourceError('Printed weekday conflicts with source date')
    return result


class HtmlClosureReviewRequired(DirectSourceError):
    def __init__(self, issue: str, inventory: dict):
        super().__init__(issue)
        self.issues = [issue]
        self.notices = [{'text': line['text'], 'scope': line['scope'], 'source_line': line['id']}
            for line in inventory['lines'] if re.search(r'closed|closure|reopen|holiday|3rd', line['text'], re.I)
            or line['section'] == 'Holiday Hours']


def html_source_payload(inventory: dict, observed_on: date) -> dict:
    try:
        return _derive_payload(inventory, observed_on)
    except DirectSourceError as exc:
        if any(re.search(r'closed|closure|reopen|holiday|3rd', line['text'], re.I)
               or line['section'] == 'Holiday Hours' for line in inventory['lines']):
            raise HtmlClosureReviewRequired(str(exc), inventory) from exc
        raise


def _derive_payload(inventory: dict, observed: date) -> dict:
    if inventory['slug'] == 'chinatown-ymca':
        return _chinatown_payload(inventory, observed)
    facts = [_parse_line(line) for line in inventory['lines']]
    slug = inventory['slug']
    lines = {line['id']: line for line in inventory['lines']}
    weekly_scopes = {fact['scope'] for fact in facts if fact['kind'] in {'weekly_hours', 'closed_day'}}
    if slug not in {'jccsf', 'sfsu-mashouf'} and weekly_scopes != {'facility'}:
        raise DirectSourceError('Unsupported independent YMCA facility/pool weekly hours groups')
    pool_rule = any(fact['kind'] == 'rule' and 'Opens 30 min after' in lines[fact['line_id']]['text'] for fact in facts)
    basis = 'swim_schedule' if slug == 'jccsf' else ('pool_hours' if pool_rule or slug == 'sfsu-mashouf' else 'facility_hours')
    sessions, hours, exceptions, closures = [], [], [], []
    end = observed + timedelta(days=13)
    seen_days: dict[str, list[str]] = {}
    dated_closed = []
    recurring = []
    for fact in facts:
        line = lines[fact['line_id']]
        kind, scope, text = fact['kind'], fact['scope'], line['text']
        if kind in {'context', 'rule'}:
            continue
        if kind in {'weekly_hours', 'closed_day'}:
            seen_days.setdefault(scope, []).extend(fact['days'])
            if kind == 'closed_day':
                continue
            for day in fact['days']:
                for window in fact['ranges']:
                    start, finish = window['start'], window['end']
                    if pool_rule:
                        start, finish = _shift(start, 30), _shift(finish, -30)
                        if start >= finish:
                            raise DirectSourceError('Pool offset removes source access interval')
                    row = {'day': day, 'start': start, 'end': finish, 'evidence': text}
                    if basis == 'swim_schedule':
                        sessions.append(row | {'type': 'lap_swim' if scope == 'lap' else 'family_swim', 'pool': 'lap' if scope == 'lap' else 'rec'})
                    else:
                        hours.append(row | {'label': 'Pool hours' if basis == 'pool_hours' else 'Facility hours'})
        elif fact['recurrence']:
            recurring.append(fact)
        else:
            dates = [_resolve_date(value, observed) for value in fact['date_texts']]
            first, last = dates[0], dates[-1]
            if last < first:
                raise DirectSourceError('Source closure dates conflict')
            if kind == 'closure':
                if slug == 'jccsf' and scope != 'facility':
                    raise DirectSourceError('Pool-specific closure scope is not representable for this source')
                if len(dates) == 2:
                    dated_closed.append((first, last))
                if last >= observed and first <= end:
                    closures.append({'start': max(first, observed).isoformat(), 'end': min(last, end).isoformat(), 'reason': text, 'reason_code': _closure_reason(text),
                        'source_notices': [{'id': line['id'], 'text': text}]})
            elif kind == 'exception' and observed <= first <= end:
                window = fact['ranges'][0]
                start, finish = window['start'], window['end']
                if pool_rule:
                    start, finish = _shift(start, 30), _shift(finish, -30)
                    if len(fact['ranges']) > 1:
                        override = fact['ranges'][1]
                        start, finish = override['start'] or start, override['end']
                exceptions.append({'date': first.isoformat(), 'start': start, 'end': finish,
                    'label': 'Holiday pool hours' if basis == 'pool_hours' else 'Holiday facility hours', 'reason': text, 'evidence': text})
    required_scopes = ['lap', 'rec'] if basis == 'swim_schedule' else ['pool' if slug == 'sfsu-mashouf' else 'facility']
    for scope in required_scopes:
        if sorted(seen_days.get(scope, [])) != sorted(DAY_ORDER):
            raise DirectSourceError('Source does not independently account for all seven weekdays')
    if hours and basis == 'facility_hours' and any(fact['kind'] == 'closure' and fact['scope'] == 'pool' for fact in facts):
        raise DirectSourceError('Pool closure cannot safely publish as facility access hours')
    if not sessions and not hours:
        active = [(first, last) for first, last in dated_closed if first <= observed <= last]
        if len(active) != 1:
            raise DirectSourceError('Closed weekly source lacks a current unambiguous dated closure')
        basis = 'temporarily_closed'
        end = min(end, active[0][1])
    if slug == 'jccsf':
        if any(not any(center['pool'] == 'lap' and center['day'] == row['day']
                       and center['start'] <= row['start'] < row['end'] <= center['end']
                       for center in sessions) for row in sessions if row['pool'] == 'rec'):
            raise DirectSourceError('Recreation pool hours conflict with Aquatics Center hours')
        if not any(fact['kind'] == 'rule' and lines[fact['line_id']]['text'].startswith('The Lap Pool is available') for fact in facts):
            raise DirectSourceError('Source does not establish lap-swim availability')
        for fact in recurring:
            if fact['recurrence'] != 'third_sunday' or len(fact['ranges']) != 1:
                raise DirectSourceError('Unsupported recurring pool exception')
            closed_after = fact['ranges'][0]['end']
            opening = fact['ranges'][0]['start']
            sunday_lap = [row for row in sessions if row['day'] == 'sunday' and row['pool'] == 'lap']
            if len(sunday_lap) != 1 or sunday_lap[0]['start'] != opening or closed_after > sunday_lap[0]['end']:
                raise DirectSourceError('Unsupported recurring opening-time change')
            dates = [(observed + timedelta(days=offset)).isoformat() for offset in range((end-observed).days+1)
                if (observed + timedelta(days=offset)).weekday() == 6 and 15 <= (observed + timedelta(days=offset)).day <= 21]
            updated = []
            for session in sessions:
                if session['day'] == 'sunday' and session['end'] > closed_after:
                    if session['start'] < closed_after:
                        updated.append(session | {'end': closed_after})
                        session = session | {'start': closed_after}
                    session = session | {'excluded_dates': dates}
                updated.append(session)
            sessions = updated
    return _payload(basis, sessions, access_hours=hours, access_exceptions=exceptions, closures=closures) | {
        'effective_start': observed.isoformat(), 'effective_end': end.isoformat()}


def _shift(value: str, minutes: int) -> str:
    hour, minute = map(int, value.split(':'))
    total = hour * 60 + minute + minutes
    if not 0 <= total < 24 * 60:
        raise DirectSourceError('Source offset crosses midnight')
    return f'{total // 60:02d}:{total % 60:02d}'


def _closure_reason(text: str) -> str:
    categories = [code for code, pattern in (
        ('maintenance', r'\bmaintenance\b'),
        ('staff_training', r'\b(?:staff training|all staff training|in-service training)\b'),
        ('holiday', r'\b(?:holidays?|thanksgiving|christmas|new year|independence day|labor day|veterans? day|indigenous|martin luther king|lunar new year|easter|memorial day|juneteenth)\b'),
    ) if re.search(pattern, text, re.I)]
    if len(categories) != 1:
        raise DirectSourceError('Unknown or conflicting source closure reason requires review')
    return categories[0]


def _holiday_status(text: str):
    return 'closed' if re.fullmatch(r'closed\.?', text, re.I) else _ranges(text)


def _chinatown_holiday(line: dict, observed: date) -> dict:
    text = line['text']
    dates = re.findall(_DATE, text, re.I)
    if text.startswith('Annual Facility Closure '):
        pattern = rf'Annual Facility Closure ({_DATE})\s*[-–]\s*({_DATE}) The facility will reopen at (.+?) on ({_DATE})'
        match = re.fullmatch(pattern, text, re.I)
        if not match:
            raise DirectSourceError('Unsupported annual closure and reopening notice')
        start, end, clock, reopening = match.groups()
        resolved = [_resolve_date(value, observed) for value in (start, end, reopening)]
        if not resolved[0] <= resolved[1] < resolved[2] or resolved[2] != resolved[1] + timedelta(days=1):
            raise DirectSourceError('Annual closure conflicts with printed reopening date')
        reopening_time = _ranges('12:01 am - ' + clock)[0]['end']
        return {'kind': 'annual_closure', 'start': resolved[0], 'end': resolved[1],
            'reopening': resolved[2], 'reopening_time': reopening_time, 'line': line}
    if len(dates) != 1 or not text.startswith(dates[0]):
        raise DirectSourceError('Unsupported or conflicting holiday notice')
    tail = text[len(dates[0]):].strip()
    tail = re.sub(r'^\([^)]*\)\s*', '', tail)
    parts = re.split(r'\bPool Hours:\s*', tail, flags=re.I)
    if len(parts) > 2:
        raise DirectSourceError('Duplicate explicit pool holiday statement')
    statuses = {}
    if len(parts) == 2:
        if parts[0].strip():
            statuses['facility'] = _holiday_status(parts[0].strip())
        statuses['pool'] = _holiday_status(parts[1].strip())
    else:
        statuses[line['scope']] = _holiday_status(tail)
    return {'kind': 'holiday', 'date': _resolve_date(dates[0], observed), 'statuses': statuses, 'line': line}


def _chinatown_payload(inventory: dict, observed: date) -> dict:
    end = observed + timedelta(days=13)
    weekly = {'facility': {}, 'pool': {}}
    holidays = {}
    annual = []
    notices = []
    for line in inventory['lines']:
        if line['section'] == 'Holiday Hours':
            parsed = _chinatown_holiday(line, observed)
            if parsed['kind'] == 'annual_closure':
                annual.append(parsed)
                continue
            record = holidays.setdefault(parsed['date'], {'statuses': {}, 'lines': []})
            for scope, status in parsed['statuses'].items():
                if scope in record['statuses'] and record['statuses'][scope] != status:
                    raise DirectSourceError(f'Conflicting {scope} holiday statements on {parsed["date"]}')
                record['statuses'][scope] = status
            record['lines'].append(line)
            continue
        fact = _parse_line(line)
        if fact['kind'] in {'weekly_hours', 'closed_day'}:
            if fact['scope'] not in weekly:
                raise DirectSourceError('Unsupported Chinatown weekly hours scope')
            for day in fact['days']:
                if day in weekly[fact['scope']]:
                    raise DirectSourceError('Duplicate Chinatown weekly hours day')
                weekly[fact['scope']][day] = {'ranges': fact['ranges'], 'line': line}
        elif fact['kind'] == 'closure':
            notices.append((fact, line))
        elif fact['kind'] != 'context':
            raise DirectSourceError('Unsupported Chinatown pool-hours rule')
    if any(set(group) != set(DAY_ORDER) for group in weekly.values()):
        raise DirectSourceError('Chinatown requires complete facility and pool hours for all seven weekdays')
    for day, pool in weekly['pool'].items():
        if any(not any(facility['start'] <= window['start'] < window['end'] <= facility['end']
                       for facility in weekly['facility'][day]['ranges']) for window in pool['ranges']):
            raise DirectSourceError(f'Pool weekly hours conflict with facility hours on {day}')
    annual_windows = {(row['start'], row['end'], row['reopening'], row['reopening_time']) for row in annual}
    if len(annual_windows) > 1:
        raise DirectSourceError('Conflicting annual facility closure and reopening statements')
    if not any(row['ranges'] for row in weekly['pool'].values()):
        raise DirectSourceError('Closed weekly source lacks current pool hours after its printed reopening')
    if any(row['start'] <= observed <= row['end'] for row in annual):
        raise DirectSourceError('Weekly pool hours conflict with current annual facility closure')
    hours = [{'day': day, 'start': window['start'], 'end': window['end'], 'label': 'Pool hours',
              'evidence': record['line']['text']}
        for day, record in weekly['pool'].items() for window in record['ranges']]
    closures, exceptions = [], []
    for holiday, record in sorted(holidays.items()):
        if holiday < observed:
            continue
        facility, pool = record['statuses'].get('facility'), record['statuses'].get('pool')
        conflict = facility == 'closed' and pool not in (None, 'closed')
        conflict = conflict or isinstance(facility, list) and isinstance(pool, list) and any(
            not any(outer['start'] <= inner['start'] < inner['end'] <= outer['end'] for outer in facility)
            for inner in pool
        )
        if conflict:
            if holiday == observed:
                raise DirectSourceError(f'Pool holiday hours conflict with facility hours on {holiday}')
            end = min(end, holiday - timedelta(days=1))
            continue
        if holiday > end:
            continue
        text = ' '.join(dict.fromkeys(line['text'] for line in record['lines']))
        if facility == 'closed' or pool == 'closed':
            closures.append({'start': holiday.isoformat(), 'end': holiday.isoformat(), 'reason': text,
                'reason_code': _closure_reason(text), 'source_notices': [{'id': line['id'], 'text': line['text']} for line in record['lines']]})
        elif isinstance(pool, list):
            exceptions.extend({'date': holiday.isoformat(), 'start': window['start'], 'end': window['end'],
                'label': 'Holiday pool hours', 'reason': text, 'evidence': text} for window in pool)
        else:
            raise DirectSourceError(f'Missing explicit pool holiday hours on {holiday}')
    for fact, line in notices:
        dates = [_resolve_date(value, observed) for value in fact['date_texts']]
        if dates[-1] < dates[0]:
            raise DirectSourceError('Source closure dates conflict')
        if dates[-1] >= observed and dates[0] <= end:
            raise DirectSourceError('Current standalone Chinatown closure requires review')
    for row in annual:
        if row['start'] <= end and row['end'] >= observed:
            raise DirectSourceError('Annual closure inside publication window requires review')
    return _payload('pool_hours', [], access_hours=hours, access_exceptions=exceptions, closures=closures) | {
        'effective_start': observed.isoformat(), 'effective_end': end.isoformat()}
