from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

import httpx

from .models import PoolEntry
from .paths import DATA_DIR

DAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class DirectSourceError(RuntimeError):
    """Raised when a non-PDF source cannot be fetched or parsed."""


@dataclass(frozen=True)
class DirectFetchResult:
    path: Path
    sha256: str
    text: str
    from_cache: bool
    response_url: str


@dataclass(frozen=True)
class DirectExtraction:
    fetch_result: DirectFetchResult
    payload: dict
    model: str
    notes: list[str]


def extract_direct(entry: PoolEntry) -> DirectExtraction:
    if entry.source_kind == "twenty_four_hour_fitness_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_24_hour_fitness),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_24_hour_fitness(fetched.text),
            model="twenty-four-hour-fitness-html-v1",
            notes=["24 Hour Fitness exposes gym hours, not pool lane availability; these are access hours only."],
        )
    if entry.source_kind == "bay_club_gateway_html":
        fetched = fetch_text(entry.slug, entry.pdf_url, extension="html")
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_bay_club_gateway(fetched.text),
            model="bay-club-gateway-html-v1",
            notes=["Bay Club Gateway public pages do not expose lap-lane availability; these are access hours only when present."],
        )
    if entry.source_kind == "jccsf_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_jccsf),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_jccsf(fetched.text),
            model="jccsf-html-v1",
            notes=["JCCSF lap swim is modeled from Aquatics Center hours; lane-count breakdown remains linked on the official page."],
        )
    if entry.source_kind == "koret_google_sheet":
        fetched = fetch_koret_workbook(entry.slug, entry.pdf_url)
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_koret(fetched.text),
            model="koret-google-sheet-v1",
            notes=["Koret sessions represent official pool hours; the sheet still carries lane-level restrictions and team bookings."],
        )
    if entry.source_kind == "pomeroy_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_pomeroy),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_pomeroy(fetched.text),
            model="pomeroy-html-v1",
            notes=["Pomeroy lap sessions are slow therapeutic lap swim, not vigorous lap training."],
        )
    if entry.source_kind == "city_sports_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_city_sports),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_city_sports(fetched.text),
            model="city-sports-html-v1",
            notes=["City Sports exposes club hours and lap-pool amenities, not lane availability; these are access hours only."],
        )
    if entry.source_kind == "equinox_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_equinox),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_equinox(fetched.text),
            model="equinox-html-v1",
            notes=["Equinox exposes club hours and an indoor-pool amenity, not lane availability; these are access hours only."],
        )
    if entry.source_kind == "fitness_sf_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_fitness_sf),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_fitness_sf(fetched.text),
            model="fitness-sf-html-v1",
            notes=["FITNESS SF exposes club hours and pool policies, not lane availability; these are access hours only."],
        )
    if entry.source_kind == "sfsu_aquatics_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_sfsu_aquatics),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_sfsu_aquatics(fetched.text),
            model="sfsu-aquatics-html-v1",
            notes=["SFSU exposes natatorium hours, not public lane availability; these are access hours only."],
        )
    if entry.source_kind == "ucsf_fitness_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_ucsf_fitness),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_ucsf_fitness(fetched.text),
            model="ucsf-fitness-html-v1",
            notes=["UCSF exposes facility hours and pool amenities, but not lane availability; these are access hours only."],
        )
    if entry.source_kind == "ucsf_bakar_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_ucsf_bakar),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_ucsf_bakar(fetched.text),
            model="ucsf-bakar-html-v1",
            notes=["UCSF Bakar exposes facility hours and pool amenities, but not pool lane availability; these are access hours only."],
        )
    if entry.source_kind == "ymca_location_html":
        fetched = fetch_text(
            entry.slug,
            entry.pdf_url,
            extension="html",
            fingerprint=_payload_fingerprint(_extract_ymca_location),
        )
        return DirectExtraction(
            fetch_result=fetched,
            payload=_extract_ymca_location(fetched.text),
            model="ymca-location-html-v1",
            notes=["YMCA location pages expose facility hours and link to a separate pool schedule; these are access hours only."],
        )
    raise DirectSourceError(f"{entry.slug}: unsupported direct source kind {entry.source_kind!r}")


def fetch_text(
    slug: str,
    url: str,
    *,
    extension: str,
    cache_root: Path = DATA_DIR,
    timeout: float = 30.0,
    retries: int = 2,
    fingerprint: Callable[[str], str] | None = None,
) -> DirectFetchResult:
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    headers = {
        "User-Agent": "SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for attempt in range(retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                text = response.text
                fingerprint_text = fingerprint(text) if fingerprint is not None else text
                sha256 = hashlib.sha256(fingerprint_text.encode("utf-8")).hexdigest()
                path, from_cache = _cache_text(slug_dir, sha256, extension, text)
                return DirectFetchResult(
                    path=path,
                    sha256=sha256,
                    text=path.read_text(),
                    from_cache=from_cache,
                    response_url=str(response.url),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(0.25 * (attempt + 1))
    raise DirectSourceError(f"Failed to fetch {slug} from {url}: {last_error}") from last_error


def fetch_koret_workbook(slug: str, workbook_url: str, *, cache_root: Path = DATA_DIR) -> DirectFetchResult:
    sheet_id = _extract_google_sheet_id(workbook_url)
    combined: list[str] = []
    headers = {
        "User-Agent": "SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)",
        "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
        for sheet in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Weekend"):
            url = (
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
                f"?tqx=out:csv&sheet={sheet}"
            )
            response = client.get(url)
            response.raise_for_status()
            combined.append(f"--- {sheet} ---\n{response.text.strip()}\n")

    text = "\n".join(combined)
    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path, from_cache = _cache_text(slug_dir, sha256, "csv", text)
    return DirectFetchResult(
        path=path,
        sha256=sha256,
        text=path.read_text(),
        from_cache=from_cache,
        response_url=workbook_url,
    )


def _cache_text(slug_dir: Path, sha256: str, extension: str, text: str) -> tuple[Path, bool]:
    prefix = sha256[:12]
    matches = sorted(slug_dir.glob(f"*-{prefix}/source.{extension}"))
    for existing in matches:
        metadata = existing.parent / "source.sha256"
        if metadata.exists() and metadata.read_text().strip() == sha256:
            return existing, True
        if not metadata.exists() and hashlib.sha256(existing.read_bytes()).hexdigest() == sha256:
            metadata.write_text(f"{sha256}\n")
            return existing, True
        raise DirectSourceError(f"prefix collision under {slug_dir}: {prefix}")

    review_dir = slug_dir / f"{date.today().isoformat()}-{prefix}"
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"source.{extension}"
    path.write_text(text)
    (review_dir / "source.sha256").write_text(f"{sha256}\n")
    return path, False


def _payload_fingerprint(extractor: Callable[[str], dict]) -> Callable[[str], str]:
    def fingerprint(text: str) -> str:
        payload = dict(extractor(text))
        payload.pop("effective_start", None)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    return fingerprint


def _extract_google_sheet_id(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise DirectSourceError("Google Sheets URL does not include /spreadsheets/d/<id>")
    return match.group(1)


def _extract_jccsf(html: str) -> dict:
    text = _html_text(html)
    sessions = [
        *_weekly_hours_sessions(
            "lap_swim",
            {
                "monday": ("05:30", "21:45"),
                "tuesday": ("05:30", "21:45"),
                "wednesday": ("05:30", "21:45"),
                "thursday": ("05:30", "21:45"),
                "friday": ("05:30", "21:45"),
                "saturday": ("07:00", "18:45"),
                "sunday": ("07:00", "18:45"),
            },
            evidence="The Lap Pool is available for lap swimming during Aquatics Center hours.",
        ),
        *_weekly_hours_sessions(
            "family_swim",
            {
                "monday": ("05:30", "12:00"),
                "wednesday": ("05:30", "12:00"),
                "tuesday": ("05:30", "11:30"),
                "thursday": ("05:30", "12:00"),
                "friday": ("05:30", "12:00"),
                "saturday": ("07:00", "08:00"),
                "sunday": ("07:00", "08:00"),
            },
            evidence="Recreation & Family Swim morning hours.",
        ),
        *_weekly_hours_sessions(
            "family_swim",
            {
                "monday": ("13:30", "21:45"),
                "wednesday": ("13:30", "21:45"),
                "tuesday": ("12:30", "21:45"),
                "thursday": ("13:00", "21:45"),
                "friday": ("13:30", "21:45"),
                "saturday": ("14:00", "18:45"),
                "sunday": ("14:00", "18:45"),
            },
            evidence="Recreation & Family Swim afternoon/evening hours.",
        ),
    ]
    _require_text(text, "Aquatics Center Hours")
    _require_text(text, "The Lap Pool is available for lap swimming during Aquatics Center hours")
    return _payload("swim_schedule", sessions, closures=_closure_dates_from_text(text))


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
                "start": date.today().isoformat(),
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


def _extract_bay_club_gateway(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Bay Club Gateway")
    raise DirectSourceError("Bay Club Gateway public page does not expose usable club hours.")


def _extract_koret(text: str) -> dict:
    sessions: list[dict] = []
    for sheet_name, csv_text in _split_koret_sheets(text).items():
        rows = list(csv.reader(StringIO(csv_text)))
        if sheet_name == "Weekend":
            sessions.extend(_weekly_hours_sessions(
                "lap_swim",
                {"saturday": ("08:00", "18:00"), "sunday": ("08:00", "18:00")},
                evidence="Weekend sheet lists 8am-6pm pool hours.",
            ))
            continue
        day = sheet_name.lower()
        first_row = " ".join(cell for cell in rows[0] if cell).strip() if rows else ""
        start, end = _parse_hours_range(first_row)
        sessions.append(_session(day, "lap_swim", start, end, first_row))
    return _payload("pool_hours", sessions)


def _split_koret_sheets(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        marker = re.fullmatch(r"--- (.+) ---", line.strip())
        if marker:
            current = marker.group(1)
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in out.items() if lines}


def _extract_pomeroy(html: str) -> dict:
    table = _PoolScheduleParser.from_html(html)
    sessions: list[dict] = []
    for day, text in table.day_cells():
        lower = text.lower()
        if "lap swim" not in lower and "open swim" not in lower:
            continue
        session_type = "lap_swim" if "lap swim" in lower else "family_swim"
        start, end = _parse_hours_range(text)
        sessions.append(_session(day, session_type, start, end, text))
    if not sessions:
        raise DirectSourceError("Pomeroy PoolSchedule table did not yield any sessions.")
    return _payload("swim_schedule", sessions, closures=_closure_dates_from_html_lines(html))


def _extract_city_sports(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "SAN FRANCISCO - 20TH AVE")
    _require_text(text, "lap pool")
    match = re.search(
        r"HOURS\s+Mon\s*-\s*Thu\s+([^F]+?)\s+Fri\s+([^S]+?)\s+Sat\s*-\s*Sun\s+(.+?)(?:Special Club Hours|Free pass|Join this club)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("City Sports page did not expose club hours.")
    weekday_hours, friday_hours, weekend_hours = match.groups()
    weekday_start, weekday_end = _parse_hours_range(weekday_hours)
    friday_start, friday_end = _parse_hours_range(friday_hours)
    weekend_start, weekend_end = _parse_hours_range(weekend_hours)
    return _payload("facility_hours", [], access_hours=[
        *[
            _access_hour(day, weekday_start, weekday_end, "Club hours", f"Mon-Thu: {weekday_hours}")
            for day in ("monday", "tuesday", "wednesday", "thursday")
        ],
        _access_hour("friday", friday_start, friday_end, "Club hours", f"Fri: {friday_hours}"),
        _access_hour("saturday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
        _access_hour("sunday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
    ])


def _extract_equinox(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Equinox Sports Club San Francisco")
    _require_text(text, "Indoor Pool")
    matches = re.findall(
        r'"dayOfWeek":\s*\[([^\]]+)\]\s*,\s*"opens":\s*"(\d{2}:\d{2})"\s*,\s*"closes":\s*"(\d{2}:\d{2})"',
        html,
        flags=re.IGNORECASE,
    )
    if not matches:
        raise DirectSourceError("Equinox page did not expose openingHoursSpecification.")
    access_hours: list[dict] = []
    for days_json, start, end in matches:
        for day in re.findall(r'"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"', days_json):
            access_hours.append(_access_hour(day.lower(), start, end, "Club hours", f"{day}: {start}-{end}"))
    return _payload("facility_hours", [], access_hours=access_hours)


def _extract_fitness_sf(html: str) -> dict:
    text = _html_text(html)
    if "fillmore" not in text.lower():
        raise DirectSourceError("Expected source text not found: Fillmore")
    if "pool" not in text.lower():
        raise DirectSourceError("Expected source text not found: pool")
    match = re.search(
        r"Mon\s*-\s*Thu:\s*([^F]+?)\s+Fri:\s*([^S]+?)\s+Sat\s*-\s*Sun:\s*(.+?)(?:\s+1-415|\s+1455|\s+Holiday Hours)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("FITNESS SF page did not expose location hours.")
    weekday_hours, friday_hours, weekend_hours = match.groups()
    weekday_start, weekday_end = _parse_hours_range(weekday_hours)
    friday_start, friday_end = _parse_hours_range(friday_hours)
    weekend_start, weekend_end = _parse_hours_range(weekend_hours)
    return _payload("pool_hours", [], access_hours=[
        *[
            _access_hour(day, weekday_start, weekday_end, "Club hours", f"Mon-Thu: {weekday_hours}")
            for day in ("monday", "tuesday", "wednesday", "thursday")
        ],
        _access_hour("friday", friday_start, friday_end, "Club hours", f"Fri: {friday_hours}"),
        _access_hour("saturday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
        _access_hour("sunday", weekend_start, weekend_end, "Club hours", f"Sat-Sun: {weekend_hours}"),
    ])


def _extract_sfsu_aquatics(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Natatorium Hours of Operation")
    _require_text(text, "Lap Pool")
    weekday_start, weekday_end = _parse_hours_range("10am - 8pm")
    weekend_start, weekend_end = _parse_hours_range("12pm - 4pm")
    return _payload("pool_hours", [], access_hours=[
        *[
            _access_hour(day, weekday_start, weekday_end, "Natatorium hours", "Monday-Thursday: 10am-8pm")
            for day in ("monday", "tuesday", "wednesday", "thursday")
        ],
        _access_hour("friday", weekend_start, weekend_end, "Natatorium hours", "Friday-Saturday: Noon-4pm"),
        _access_hour("saturday", weekend_start, weekend_end, "Natatorium hours", "Friday-Saturday: Noon-4pm"),
    ])


def _extract_ucsf_fitness(html: str) -> dict:
    text = _html_text(html)
    match = re.search(
        r"Facility Hours:\s*Monday-Friday,\s*([^;]+);\s*Saturday-Sunday,\s*([^<]+?)(?:William|Millberry|2026|Parking|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("UCSF page did not expose facility hours.")
    weekday_hours, weekend_hours = match.groups()
    weekday_start, weekday_end = _parse_hours_range(weekday_hours)
    weekend_start, weekend_end = _parse_hours_range(weekend_hours)
    return _payload(
        "facility_hours",
        [],
        access_hours=[
            *[
                _access_hour(day, weekday_start, weekday_end, "Facility hours", f"Facility Hours: Monday-Friday, {weekday_hours}")
                for day in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            _access_hour("saturday", weekend_start, weekend_end, "Facility hours", f"Facility Hours: Saturday-Sunday, {weekend_hours}"),
            _access_hour("sunday", weekend_start, weekend_end, "Facility hours", f"Facility Hours: Saturday-Sunday, {weekend_hours}"),
        ],
    )


def _extract_ucsf_bakar(html: str) -> dict:
    return _extract_ucsf_fitness(html)


def _extract_ymca_location(html: str) -> dict:
    text = _html_text(html)
    _require_text(text, "Hours")
    access_hours = _extract_ymca_facility_hours(html, label="Facility hours")
    basis = "facility_hours"
    access_exceptions = _extract_ymca_holiday_access_exceptions(html, basis=basis)
    if "Pool Hours Opens 30 min after, closes 30 min before facility" in text:
        basis = "pool_hours"
        access_hours = [
            _access_hour(
                access_hour["day"],
                _shift_hhmm(access_hour["start"], minutes=30),
                _shift_hhmm(access_hour["end"], minutes=-30),
                "Pool hours",
                "Pool opens 30 min after, closes 30 min before facility",
            )
            for access_hour in access_hours
        ]
        access_exceptions = _extract_ymca_holiday_access_exceptions(html, basis=basis)
    if not access_hours:
        raise DirectSourceError("YMCA page did not expose location hours.")
    return _payload(
        basis,
        [],
        access_hours=access_hours,
        access_exceptions=access_exceptions,
        closures=_closure_dates_from_text(text),
    )


def _payload(
    schedule_basis: str,
    sessions: list[dict],
    *,
    access_hours: list[dict] | None = None,
    access_exceptions: list[dict] | None = None,
    closures: list[dict] | None = None,
) -> dict:
    return {
        "schedule_basis": schedule_basis,
        "effective_start": date.today().isoformat(),
        "sessions": sorted(sessions, key=lambda s: (DAY_ORDER.index(s["day"]), s["start"], s["end"], s["type"])),
        "access_hours": sorted(
            access_hours or [],
            key=lambda a: (DAY_ORDER.index(a["day"]), a["start"], a["end"], a["label"]),
        ),
        "access_exceptions": sorted(
            access_exceptions or [],
            key=lambda a: (a["date"], a["start"], a["end"], a["label"], a["reason"]),
        ),
        "closures": closures or [],
    }


def _weekly_hours_sessions(kind: str, hours: dict[str, tuple[str, str]], *, evidence: str) -> list[dict]:
    return [_session(day, kind, start, end, evidence) for day, (start, end) in hours.items()]


def _session(day: str, kind: str, start: str, end: str, evidence: str) -> dict:
    return {
        "day": day,
        "type": kind,
        "start": start,
        "end": end,
        "evidence": _squash(evidence),
    }


def _access_hour(day: str, start: str, end: str, label: str, evidence: str) -> dict:
    return {
        "day": day,
        "start": start,
        "end": end,
        "label": label,
        "evidence": _squash(evidence),
    }


def _access_exception(date_iso: str, start: str, end: str, label: str, reason: str, evidence: str) -> dict:
    return {
        "date": date_iso,
        "start": start,
        "end": end,
        "label": label,
        "reason": reason,
        "evidence": _squash(evidence),
    }


def _extract_day_hour_spans(html: str, *, label: str) -> list[dict]:
    access_hours: list[dict] = []
    for day, hours in re.findall(
        r"<span>\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*</span>\s*<span>\s*([^<]+)\s*</span>",
        html,
        flags=re.IGNORECASE,
    ):
        clean_hours = _squash(hours)
        if clean_hours.lower() == "closed":
            continue
        start, end = _parse_hours_range(clean_hours)
        access_hours.append(_access_hour(day.lower(), start, end, label, f"{day}: {clean_hours}"))
    return access_hours


def _extract_first_day_hour_block(html: str, *, label: str) -> list[dict]:
    access_hours: list[dict] = []
    seen_days: set[str] = set()
    for day, hours in re.findall(
        r"<span>\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*</span>\s*<span>\s*([^<]+)\s*</span>",
        html,
        flags=re.IGNORECASE,
    ):
        day_key = day.lower()
        if day_key in seen_days:
            break
        seen_days.add(day_key)
        clean_hours = _squash(hours)
        if clean_hours.lower() != "closed":
            start, end = _parse_hours_range(clean_hours)
            access_hours.append(_access_hour(day_key, start, end, label, f"{day}: {clean_hours}"))
        if len(seen_days) == 7:
            break
    return access_hours


def _extract_ymca_facility_hours(html: str, *, label: str) -> list[dict]:
    match = re.search(
        r"<h2>\s*Facility Hours\s*</h2>(.*?)(?:<h4>\s*Contact\s*</h4>|<h2>\s*Holiday Hours\s*</h2>)",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return _extract_first_day_hour_block(html, label=label)
    block = match.group(1)
    access_hours: list[dict] = []
    for days, hours in re.findall(
        r"<span>\s*([^<]*?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[^<]*?)\s*</span>\s*<span>\s*([^<]+)\s*</span>",
        block,
        flags=re.IGNORECASE,
    ):
        clean_hours = _squash(hours)
        if clean_hours.lower() == "closed":
            continue
        start, end = _parse_hours_range(clean_hours)
        for day in _expand_day_phrase(days):
            access_hours.append(_access_hour(day, start, end, label, f"{days}: {clean_hours}"))
    return sorted(access_hours, key=lambda a: (DAY_ORDER.index(a["day"]), a["start"], a["end"]))


def _extract_ymca_holiday_access_exceptions(html: str, *, basis: str) -> list[dict]:
    blocks = [
        _html_text(match.group(1))
        for match in re.finditer(
            r"<h[1-6][^>]*>\s*Holiday Hours\s*</h[1-6]>(.{0,1400})",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    if not blocks:
        return []
    year = date.today().year
    month_numbers = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    pattern = (
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*,?\s*"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*"
        r"\(([^)]+)\)\s*"
        r"(?P<facility_hours>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)\s*[-–]\s*"
        r"\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm))"
        r"(?:\s*Pool Hours:\s*"
        r"(?P<pool_hours>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)\s*[-–]\s*"
        r"\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)))?"
        r"(?:\s*Pool Closes at\s*"
        r"(?P<pool_closes>\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)))?"
    )
    exceptions: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for text in blocks:
        for holiday in re.finditer(pattern, text, flags=re.IGNORECASE):
            month = holiday.group(1)
            day = holiday.group(2)
            reason = holiday.group(3)
            facility_hours = holiday.group("facility_hours")
            pool_hours = holiday.group("pool_hours")
            pool_closes = holiday.group("pool_closes")
            start, end = _parse_hours_range(pool_hours or facility_hours)
            label = "Holiday facility hours"
            if basis == "pool_hours":
                label = "Holiday pool hours"
                if not pool_hours:
                    start = _shift_hhmm(start, minutes=30)
                    end = _parse_clock_time(pool_closes) if pool_closes else _shift_hhmm(end, minutes=-30)
            date_iso = date(year, month_numbers[month.lower()], int(day)).isoformat()
            key = (date_iso, start, end, label, reason)
            if key in seen:
                continue
            seen.add(key)
            exceptions.append(_access_exception(date_iso, start, end, label, reason, holiday.group(0)))
    return exceptions


def _expand_days(value: str) -> list[str]:
    normalized = _squash(value).lower()
    day_names = list(DAY_ORDER)
    aliases = {day[:3]: day for day in day_names}
    parts = [part.strip() for part in re.split(r"\s*-\s*", normalized) if part.strip()]
    if len(parts) == 1:
        return [aliases.get(parts[0][:3], parts[0])]
    if len(parts) == 2:
        start = aliases.get(parts[0][:3])
        end = aliases.get(parts[1][:3])
        if start in DAY_ORDER and end in DAY_ORDER:
            start_i = DAY_ORDER.index(start)
            end_i = DAY_ORDER.index(end)
            if start_i <= end_i:
                return list(DAY_ORDER[start_i : end_i + 1])
    raise DirectSourceError(f"Could not expand day range {value!r}")


def _expand_day_phrase(value: str) -> list[str]:
    normalized = _squash(value).lower().replace("&", " and ")
    normalized = re.sub(r"\s+", " ", normalized)
    if " and " in normalized and "-" not in normalized:
        days: list[str] = []
        for part in normalized.split(" and "):
            days.extend(_expand_days(part))
        return days
    return _expand_days(normalized)


def _parse_hours_range(text: str) -> tuple[str, str]:
    normalized_text = re.sub(r"\bnoon\b", "12pm", text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\bmidnight\b", "12am", normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\ba\.m\.", "am", normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\bp\.m\.", "pm", normalized_text, flags=re.IGNORECASE)
    match = re.search(
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError(f"Could not parse time range from {text!r}")
    start_h, start_m, start_ampm, end_h, end_m, end_ampm = match.groups()
    start = _to_hhmm(int(start_h), int(start_m or "0"), start_ampm)
    end = _to_hhmm(int(end_h), int(end_m or "0"), end_ampm)
    if end == "00:00" and start > end:
        end = "23:59"
    return (start, end)


def _parse_clock_time(text: str) -> str:
    normalized_text = re.sub(r"\ba\.m\.", "am", text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"\bp\.m\.", "pm", normalized_text, flags=re.IGNORECASE)
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", normalized_text, flags=re.IGNORECASE)
    if not match:
        raise DirectSourceError(f"Could not parse clock time from {text!r}")
    hour, minute, ampm = match.groups()
    return _to_hhmm(int(hour), int(minute or "0"), ampm)


def _to_hhmm(hour: int, minute: int, ampm: str) -> str:
    normalized = hour % 12
    if ampm.lower() == "pm":
        normalized += 12
    return f"{normalized:02d}:{minute:02d}"


def _shift_hhmm(value: str, *, minutes: int) -> str:
    shifted = datetime.strptime(value, "%H:%M") + timedelta(minutes=minutes)
    return shifted.strftime("%H:%M")


def _closure_dates_from_text(text: str) -> list[dict]:
    closures: list[dict] = []
    year = date.today().year
    month_numbers = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    for match in re.finditer(
        r"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+)?"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?\s*-\s*([A-Za-z][^\n.]+)",
        text,
        flags=re.IGNORECASE,
    ):
        month, day, reason = match.groups()
        iso = date(year, month_numbers[month.lower()], int(day)).isoformat()
        closures.append({"start": iso, "end": iso, "reason": _squash(reason)})
    return closures


def _closure_dates_from_html_lines(html: str) -> list[dict]:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</(?:p|li|div|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    closures: list[dict] = []
    for line in unescape(text).splitlines():
        closures.extend(_closure_dates_from_text(line))
    return closures


def _html_text(html: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return _squash(unescape(text))


def _require_text(text: str, needle: str) -> None:
    if needle not in text:
        raise DirectSourceError(f"Expected source text not found: {needle}")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


class _PoolScheduleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_pool_table = False
        self.in_row = False
        self.current_cell: dict | None = None
        self.current_row: list[dict] = []
        self.rows: list[list[dict]] = []

    @classmethod
    def from_html(cls, html: str) -> "_PoolScheduleTable":
        parser = cls()
        parser.feed(html)
        return _PoolScheduleTable(parser.rows)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and "PoolSchedule" in (attrs_dict.get("class") or ""):
            self.in_pool_table = True
            return
        if not self.in_pool_table:
            return
        if tag == "tr":
            self.in_row = True
            self.current_row = []
        elif tag in {"th", "td"} and self.in_row:
            self.current_cell = {
                "tag": tag,
                "class": attrs_dict.get("class") or "",
                "rowspan": int(attrs_dict.get("rowspan") or "1"),
                "text": "",
            }

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if not self.in_pool_table:
            return
        if tag in {"th", "td"} and self.current_cell is not None:
            self.current_cell["text"] = _squash(str(self.current_cell["text"]))
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.in_row:
            self.rows.append(self.current_row)
            self.current_row = []
            self.in_row = False
        elif tag == "table":
            self.in_pool_table = False


class _PoolScheduleTable:
    def __init__(self, rows: list[list[dict]]) -> None:
        self.rows = rows

    def day_cells(self) -> list[tuple[str, str]]:
        header = self.rows[0]
        days = [str(cell["text"]).lower() for cell in header]
        active_rowspans: dict[int, int] = {}
        out: list[tuple[str, str]] = []
        for row in self.rows[1:]:
            col = 0
            for cell in row:
                while active_rowspans.get(col, 0) > 0:
                    active_rowspans[col] -= 1
                    if active_rowspans[col] == 0:
                        del active_rowspans[col]
                    col += 1
                if col < len(days):
                    out.append((days[col], str(cell["text"])))
                rowspan = int(cell.get("rowspan") or 1)
                if rowspan > 1:
                    active_rowspans[col] = rowspan - 1
                col += 1
        return out
