from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, time, timedelta

import pytest
from openpyxl import Workbook

from schedules._time import pacific_today
from schedules.direct_sources import (
    DirectSourceError,
    _extract_24_hour_fitness,
    _extract_city_sports,
    _extract_equinox,
    _extract_fitness_sf,
    _extract_koret,
    _extract_pomeroy,
    _extract_ucsf_bakar,
    _extract_ucsf_fitness,
)
from schedules.direct_sources.parsing import _resolve_yearless_date


def test_cache_bytes_preserves_encoding_and_rejects_corruption(tmp_path):
    from schedules.direct_sources.http import _cache_bytes
    content = b"first\r\nsecond\xff"
    digest = hashlib.sha256(content).hexdigest()
    capture = _cache_bytes(tmp_path, digest, "html", content)
    assert not capture.from_cache
    path = capture.path
    assert path.read_bytes() == content
    reused = _cache_bytes(tmp_path, digest, "html", content)
    assert (reused.path, reused.sha256, reused.content, reused.from_cache) == (path, digest, content, True)
    path.write_bytes(b"corrupt")
    with pytest.raises(DirectSourceError, match="prefix collision"):
        _cache_bytes(tmp_path, digest, "html", content)


def test_cache_bytes_reuses_a_capture_from_an_earlier_day(tmp_path):
    """Identical bytes are one capture, no matter which day they arrive on."""
    from schedules.direct_sources.http import _cache_bytes
    content = b"<p>hours</p>"
    digest = hashlib.sha256(content).hexdigest()
    yesterday = (pacific_today() - timedelta(days=1)).isoformat()
    earlier = tmp_path / f"{yesterday}-{digest[:12]}"
    earlier.mkdir()
    (earlier / "source.html").write_bytes(content)
    capture = _cache_bytes(tmp_path, digest, "html", content)
    assert (capture.path, capture.from_cache) == (earlier / "source.html", True)
    assert [directory.name for directory in sorted(tmp_path.iterdir())] == [earlier.name]


def _cfemail_page(payload: str) -> bytes:
    """A Cloudflare-obfuscated page; the payload rotates on every response."""
    return (
        f'<html><body><p>Lap swim 6am-8pm</p>'
        f'<a href="/cdn-cgi/l/email-protection#{payload}">'
        f'<span class="__cf_email__" data-cfemail="{payload}">[email&#160;protected]</span></a>'
        f'</body></html>'
    ).encode()


def _workbook_bytes(creator: str, hours: str = "Hours: 6am-8pm", *, merge: str = "B2:C2",
                    hidden_notice: bool = False) -> bytes:
    """A Koret-shaped export. The merge covers empty cells inside the used range,
    so a different merge changes no cell value and no sheet dimension."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Monday"
    sheet["A1"] = hours
    sheet["A2"] = time(6, 0)
    sheet["E5"] = "notes"
    sheet.merge_cells(merge)
    notice = book.create_sheet("Long Course Notice")
    notice["A1"] = "Short course from 9/10"
    if hidden_notice:
        notice.sheet_state = "hidden"
    book.properties.creator = creator
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_canonical_html_identity_ignores_rotating_cfemail(tmp_path):
    from schedules.artifacts import canonical_source_sha256
    from schedules.direct_sources.http import _cache_bytes
    first, second = _cfemail_page("a1b2c3d4"), _cfemail_page("9f8e7d6c")
    assert first != second
    assert canonical_source_sha256("html", first) == canonical_source_sha256("html", second)

    stored = _cache_bytes(tmp_path, hashlib.sha256(first).hexdigest(), "html", first)
    reused = _cache_bytes(tmp_path, hashlib.sha256(second).hexdigest(), "html", second)
    assert reused.from_cache
    assert (reused.path, reused.content, reused.sha256) == (stored.path, first, stored.sha256)
    assert [directory.name for directory in sorted(tmp_path.iterdir())] == [stored.path.parent.name]


def test_canonical_xlsx_identity_ignores_export_nondeterminism(tmp_path):
    from schedules.artifacts import canonical_source_sha256
    from schedules.direct_sources.http import _cache_bytes
    first, second = _workbook_bytes("first export"), _workbook_bytes("second export")
    assert first != second
    assert canonical_source_sha256("xlsx", first) == canonical_source_sha256("xlsx", second)

    stored = _cache_bytes(tmp_path, hashlib.sha256(first).hexdigest(), "xlsx", first)
    reused = _cache_bytes(tmp_path, hashlib.sha256(second).hexdigest(), "xlsx", second)
    assert (reused.path, reused.content, reused.from_cache) == (stored.path, first, True)
    assert [directory.name for directory in sorted(tmp_path.iterdir())] == [stored.path.parent.name]


def test_canonical_xlsx_identity_covers_everything_the_parser_reads():
    """Merges and hidden sheets change the schedule the parser sees, not just the cells."""
    from schedules.artifacts import canonical_source_sha256
    from schedules.artifacts import workbook_facts
    plain, elsewhere, hidden = (
        _workbook_bytes("export"),
        _workbook_bytes("export", merge="C2:D2"),
        _workbook_bytes("export", hidden_notice=True),
    )
    cells = lambda content: {title: sheet["cells"] for title, sheet in workbook_facts(content).items()}
    assert cells(plain) == cells(elsewhere) == cells(hidden)
    assert len({canonical_source_sha256("xlsx", book) for book in (plain, elsewhere, hidden)}) == 3


def test_canonical_identity_keeps_pdf_and_csv_on_raw_bytes():
    from schedules.artifacts import canonical_source_sha256
    body = b"%PDF-1.4 lap swim"
    assert canonical_source_sha256("pdf", body) == hashlib.sha256(body).hexdigest()
    assert canonical_source_sha256("csv", b"day,start\n") == hashlib.sha256(b"day,start\n").hexdigest()


def test_cache_bytes_reuses_the_latest_capture_of_the_same_document(tmp_path):
    """Retention keeps the newest capture, so reuse has to land there too."""
    from schedules.direct_sources.http import _cache_bytes
    older, newer = _cfemail_page("11111111"), _cfemail_page("22222222")
    for content, day in ((older, "2026-09-07"), (newer, "2026-09-08")):
        directory = tmp_path / f"{day}-{hashlib.sha256(content).hexdigest()[:12]}"
        directory.mkdir()
        (directory / "source.html").write_bytes(content)
        (directory / "source.sha256").write_text(hashlib.sha256(content).hexdigest())
    reused = _cache_bytes(tmp_path, hashlib.sha256(_cfemail_page("33333333")).hexdigest(),
                          "html", _cfemail_page("33333333"))
    assert (reused.from_cache, reused.content) == (True, newer)
    assert reused.path.parent.name.startswith("2026-09-08")


def test_cache_bytes_keeps_a_changed_document_apart(tmp_path):
    from schedules.direct_sources.http import _cache_bytes
    first, second = _cfemail_page("a1b2c3d4"), _cfemail_page("a1b2c3d4").replace(b"6am-8pm", b"7am-9pm")
    _cache_bytes(tmp_path, hashlib.sha256(first).hexdigest(), "html", first)
    changed = _cache_bytes(tmp_path, hashlib.sha256(second).hexdigest(), "html", second)
    assert not changed.from_cache
    assert len(list(tmp_path.iterdir())) == 2


def test_cache_bytes_rejects_semantic_hash(tmp_path):
    from schedules.direct_sources.http import _cache_bytes
    with pytest.raises(DirectSourceError, match="source bytes"):
        _cache_bytes(tmp_path, hashlib.sha256(b"hours").hexdigest(), "html", b"<p>hours</p>")


@pytest.mark.parametrize("status", [401, 403, 404])
def test_fetch_text_does_not_retry_permanent_errors(monkeypatch, status):
    import httpx
    from schedules.direct_sources import http
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"server": "official", "set-cookie": "private"}, text="secret body")
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(DirectSourceError) as error:
        http.fetch_text("https://example.org/pool?token=private")
    assert len(requests) == 1
    assert f"HTTP {status}" in str(error.value)
    assert "official" in str(error.value)
    assert "private" not in str(error.value)
    assert "secret body" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("failure", [408, 429, 500, 502, 503, 504, "timeout"])
def test_fetch_text_retries_transient_errors_and_keeps_bytes(monkeypatch, failure):
    import httpx
    from schedules.direct_sources import http
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(failure)
        return httpx.Response(200, content=b"caf\xe9\r\n", headers={"content-type": "text/html; charset=iso-8859-1"})
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: client)
    sleeps = []
    monkeypatch.setattr("schedules.fetch.time.sleep", sleeps.append)
    result = http.fetch_text("https://example.org/pool")
    assert len(requests) == 2
    assert sleeps == [0.25]
    assert result.content == b"caf\xe9\r\n"
    assert result.text == "café\r\n"
    assert result.response_url == "https://example.org/pool"


def test_fetch_text_transient_attempts_are_bounded(monkeypatch):
    import httpx
    from schedules.direct_sources import http
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(503)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr("schedules.fetch.time.sleep", lambda delay: None)
    with pytest.raises(DirectSourceError, match="HTTP 503"):
        http.fetch_text("https://example.org/pool")
    assert len(requests) == 3


def _koret_workbook(tmp_path, sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    path = tmp_path / "koret.xlsx"
    workbook.save(path)
    return path


# ---- yearless dates in source text roll forward, never backward -------------


def test_resolve_yearless_date_keeps_same_year_for_near_future():
    assert _resolve_yearless_date(4, 30, today=date(2026, 4, 1)) == date(2026, 4, 30)


def test_resolve_yearless_date_keeps_same_year_for_recent_past():
    assert _resolve_yearless_date(4, 1, today=date(2026, 4, 20)) == date(2026, 4, 1)


def test_resolve_yearless_date_rolls_forward_for_distant_past():
    assert _resolve_yearless_date(1, 15, today=date(2026, 12, 20)) == date(2027, 1, 15)


def test_koret_google_sheet_extractor_reads_weekday_and_weekend_hours(tmp_path):
    sheets = {
        day: [[day], ["Hours: 6am - 9pm"], [time(6), "slow"], [time(20), "slow"]]
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    }
    sheets["Weekend"] = [[None, "Saturday"], [time(8), "slow"], [time(17), "slow"], ["Sunday"], [time(8), "slow"], [time(17), "slow"]]
    sheets["Long Course Notice"] = [["Long Course Notice"]]
    payload = _extract_koret(_koret_workbook(tmp_path, sheets))

    assert any(s["day"] == "monday" and s["start"] == "06:00" and s["end"] == "21:00" for s in payload["sessions"])
    assert any(s["day"] == "saturday" and s["start"] == "08:00" and s["end"] == "18:00" for s in payload["sessions"])
    assert any(s["day"] == "sunday" and s["start"] == "08:00" and s["end"] == "18:00" for s in payload["sessions"])


def test_koret_weekend_stated_hours_win_over_the_lane_grid(tmp_path):
    """The Weekend sheet states "Hours 8am-4pm" with no colon, over a grid whose
    lanes stay assigned until 5pm for the USF squads. Closing time is 4pm; the
    Sunday banner carries "(Summer Hours)" but no range and must not be read as
    one."""
    sheets = {
        day: [[day], ["Hours: 7am-7pm (Summer Hours)"], [time(6), "slow"], [time(20), "slow"]]
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    }
    sheets["Weekend"] = [
        [None, "Saturday"],
        [None, "Hours 8am-4pm (Summer Hours)"],
        [time(8), "slow"],
        [time(17), "slow"],
        ["Sunday"],
        ["KORET CLOSED (Summer Hours)"],
        [time(8), "slow"],
        [time(17), "slow"],
    ]
    payload = _extract_koret(_koret_workbook(tmp_path, sheets))

    saturday = [s for s in payload["sessions"] if s["day"] == "saturday"]
    assert [(s["start"], s["end"]) for s in saturday] == [("08:00", "16:00")]
    assert "8am-4pm" in saturday[0]["evidence"]
    assert not [s for s in payload["sessions"] if s["day"] == "sunday"]


def test_koret_google_sheet_extractor_splits_hours_around_closed_grid_rows(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Monday"
    sheet.append(["Monday"])
    sheet.append(["Hours: 7am-7pm"])
    sheet.append([])
    sheet.append([None, "Lane 1", "Lane 2", "Lane 3", "Lane 4", "Lane 5", "Lane 6", "Lane 7", "Lane 8"])
    sheet.append([time(7), "fast"])
    sheet.append([time(8), "fast"])
    sheet.append([])
    sheet.append([time(9), "Closed for bulk head transition"])
    sheet.append([time(10)])
    sheet.append([time(11), "fast"])
    sheet.merge_cells("B8:I9")
    for day in ("Tuesday", "Wednesday", "Thursday", "Friday"):
        other = workbook.create_sheet(day)
        other.append([day])
        other.append(["Hours: 7am-7pm"])
    weekend = workbook.create_sheet("Weekend")
    weekend.append([None, "Saturday"])
    weekend.append(["Sunday"])
    workbook.create_sheet("Long Course Notice")
    path = tmp_path / "koret.xlsx"
    workbook.save(path)
    payload = _extract_koret(path)

    assert [(session["start"], session["end"]) for session in payload["sessions"] if session["day"] == "monday"] == [
        ("07:00", "09:00"),
        ("11:00", "19:00"),
    ]


def test_koret_google_sheet_extractor_reads_dated_notice_closure(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules._time.pacific_today", lambda: date(2026, 8, 12))
    sheets = {
        day: [[day], ["Hours: 7am-7pm"]]
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    }
    sheets["Weekend"] = [[None, "Saturday"], ["Sunday"]]
    sheets["Long Course Notice"] = [["Long Course Notice"], ["On 7/13 the pool will be closed from 8:30-10:30 to change back to short course."]]
    payload = _extract_koret(_koret_workbook(tmp_path, sheets))

    assert payload["closures"] == [{
        "start": "2026-07-13",
        "end": "2026-07-13",
        "start_time": "08:30",
        "end_time": "10:30",
        "reason": "Change from long course to short course",
    }]


def test_koret_notice_closure_rolls_year_forward(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules._time.pacific_today", lambda: date(2026, 12, 20))
    sheets = {
        day: [[day], ["Hours: 7am-7pm"]]
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    }
    sheets["Weekend"] = [[None, "Saturday"], ["Sunday"]]
    sheets["Long Course Notice"] = [["Long Course Notice"], ["On 1/5 the pool will be closed from 8:30-10:30 to change back to short course."]]
    payload = _extract_koret(_koret_workbook(tmp_path, sheets))

    assert payload["closures"][0]["start"] == "2027-01-05"


def test_koret_closed_banner_weekday_emits_closure_and_keeps_sessions(tmp_path):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday"):
        sheet = workbook.create_sheet(day)
        sheet.append([day])
        sheet.append(["Hours: 7am-7pm"])
    friday = workbook.create_sheet("Friday")
    friday.append(["Friday"])
    friday.append(["Closed Juneteenth"])
    friday.append(["Hours: 7am-7pm"])
    friday.merge_cells("A2:I2")
    weekend = workbook.create_sheet("Weekend")
    weekend.append([None, "Saturday"])
    weekend.append(["Sunday"])
    workbook.create_sheet("Long Course Notice")
    path = tmp_path / "koret.xlsx"
    workbook.save(path)

    payload = _extract_koret(path)

    today = pacific_today()
    expected = (today + timedelta(days=(4 - today.weekday()) % 7)).isoformat()
    assert {"start": expected, "end": expected, "reason": "Juneteenth"} in payload["closures"]
    assert any(session["day"] == "friday" for session in payload["sessions"])


def test_koret_ordinal_closures_only_accept_real_saturdays(tmp_path):
    sheets = {
        day: [[day], ["Hours: 7am-7pm"]]
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    }
    sheets["Weekend"] = [[None, "Saturday"], [time(8), "slow"], [time(16), "slow"], ["Sunday"], ["Saturday CLOSED 31ST"]]
    payload = _extract_koret(_koret_workbook(tmp_path, sheets))

    for closure in payload["closures"]:
        assert date.fromisoformat(closure["start"]).weekday() == 5


def test_koret_closed_block_reaching_last_grid_row_is_subtracted(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Monday"
    sheet.append(["Monday"])
    sheet.append(["Hours: 7am-7pm"])
    sheet.append([None, "Lane 1", "Lane 2", "Lane 3", "Lane 4", "Lane 5", "Lane 6", "Lane 7", "Lane 8"])
    sheet.append([time(7), "fast"])
    sheet.append([time(8), "fast"])
    sheet.append([time(9), "Closed for cleaning"])
    sheet.append([time(10)])
    sheet.merge_cells("B6:I7")
    for day in ("Tuesday", "Wednesday", "Thursday", "Friday"):
        other = workbook.create_sheet(day)
        other.append([day])
        other.append(["Hours: 7am-7pm"])
    weekend = workbook.create_sheet("Weekend")
    weekend.append([None, "Saturday"])
    weekend.append(["Sunday"])
    workbook.create_sheet("Long Course Notice")
    path = tmp_path / "koret.xlsx"
    workbook.save(path)

    payload = _extract_koret(path)

    assert [(session["start"], session["end"]) for session in payload["sessions"] if session["day"] == "monday"] == [
        ("07:00", "09:00"),
    ]


def test_pomeroy_html_extractor_handles_table_rowspans():
    payload = _extract_pomeroy(
        """
        <h1>Upcoming Pool Closure Dates:</h1>
        <p><span>Monday, May 25th - Memorial Day</span></p>
        <h2>Therapeutic Swimming</h2>
        <table class="PoolSchedule">
          <thead><tr><th>Monday</th><th>Tuesday</th><th>Wednesday</th></tr></thead>
          <tbody>
            <tr>
              <td rowspan="2">1pm - 2:55pm<br><span>Open Swim</span></td>
              <td>8am - 8:55am<br><span>Lap Swim</span></td>
              <td>8am - 8:55am<br><span>Lap Swim</span></td>
            </tr>
            <tr>
              <td>9am - 9:55am<br><span>Open Swim</span></td>
              <td>6pm - 6:55pm<br><span>Lap Swim</span></td>
            </tr>
          </tbody>
        </table>
        """
    )

    assert {
        (s["day"], s["type"], s["start"], s["end"])
        for s in payload["sessions"]
    } == {
        ("monday", "family_swim", "13:00", "14:55"),
        ("tuesday", "lap_swim", "08:00", "08:55"),
        ("tuesday", "family_swim", "09:00", "09:55"),
        ("wednesday", "lap_swim", "08:00", "08:55"),
        ("wednesday", "lap_swim", "18:00", "18:55"),
    }
    assert all(closure["reason"] == "Memorial Day" for closure in payload["closures"])


def test_24_hour_fitness_extractor_reads_access_hours():
    payload = _extract_24_hour_fitness(
        """
        <h2>Gym Hours</h2>
        <span class="ih-days">Monday - Thursday</span>
        <span class="ih-hours">05:00 AM - 10:00 PM</span>
        <span class="ih-days">Friday</span>
        <span class="ih-hours">05:00 AM - 09:00 PM</span>
        <span class="ih-days">Saturday - Sunday</span>
        <span class="ih-hours">06:00 AM - 08:00 PM</span>
        """
    )

    assert payload["sessions"] == []
    assert payload["schedule_basis"] == "facility_hours"
    assert len(payload["access_hours"]) == 7
    assert any(a["day"] == "thursday" and a["end"] == "22:00" for a in payload["access_hours"])


def test_24_hour_fitness_extractor_models_temporary_closure():
    payload = _extract_24_hour_fitness(
        """
        <h2>Gym Hours</h2>
        <p>Under Renovation This club is temporarily closed for renovation.
        We can't wait to welcome you back on 05/23/2026 when our improvements are complete.</p>
        """
    )

    assert payload["schedule_basis"] == "temporarily_closed"
    assert payload["sessions"] == []
    assert payload["access_hours"] == []
    assert payload["closures"][0]["reason"] == "Temporarily closed for renovation"


def test_24_hour_fitness_extractor_models_reopened_facility_hours():
    payload = _extract_24_hour_fitness(
        """
        <h2>Recently Renovated!</h2>
        <p>Reimagined. Reopened. Ready for you.</p>
        <p>Indoor Lap Pool</p>
        <h2>Gym Hours</h2>
        <span class="ih-days">Monday</span>
        <span class="ih-hours">05:00 AM - 11:59 PM</span>
        <span class="ih-days">Tuesday - Thursday</span>
        <span class="ih-hours">12:00 AM - 11:59 PM</span>
        <span class="ih-days">Friday</span>
        <span class="ih-hours">12:00 AM - 09:00 PM</span>
        <span class="ih-days">Saturday - Sunday</span>
        <span class="ih-hours">05:00 AM - 09:00 PM</span>
        """
    )

    assert payload["schedule_basis"] == "facility_hours"
    assert payload["sessions"] == []
    assert payload["closures"] == []
    assert len(payload["access_hours"]) == 7
    assert any(a["day"] == "monday" and a["end"] == "23:59" for a in payload["access_hours"])
    assert any(a["day"] == "wednesday" and a["start"] == "00:00" for a in payload["access_hours"])


def test_city_sports_rejects_hours_without_complete_independent_source_tables():
    with pytest.raises(DirectSourceError):
        _extract_city_sports("""<h1>SAN FRANCISCO - 20TH AVE</h1><p>lap pool</p>
            <p>HOURS Mon - Thu 5:00am - 11:00pm Fri 5:00am - 10:00pm
            Sat - Sun 8:00am - 8:00pm Special Club Hours</p>""")


def test_equinox_rejects_incomplete_location_hours():
    with pytest.raises(DirectSourceError):
        _extract_equinox("""<h1>Equinox Sports Club San Francisco</h1><p>Indoor Pool</p>
            "openingHoursSpecification": [
              {"dayOfWeek": ["Monday","Tuesday"],"opens": "05:00","closes": "22:00"},
              {"dayOfWeek": ["Saturday","Sunday"],"opens": "07:00","closes": "18:00"}]
            """)


def test_fitness_sf_rejects_partial_location_hours_without_full_source_evidence():
    with pytest.raises(DirectSourceError):
        _extract_fitness_sf("""<h1>FITNESS SF Fillmore</h1>
            <p>25-yard, 5-lane swimming pool</p>
            <p>Mon - Thu: 5 am - 12 am Fri: 5 am - 11 pm Sat - Sun: 7 am - 8 pm 1-415-348-6377</p>""")


@pytest.mark.parametrize("extractor, weekend_end", [(_extract_ucsf_bakar, "18:00"), (_extract_ucsf_fitness, "16:00")])
def test_ucsf_combined_calendar_preserves_facility_identity(extractor, weekend_end):
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    payload = extractor(html, date(2026, 9, 1))
    assert payload["schedule_basis"] == "facility_hours"
    assert payload["sessions"] == []
    assert len(payload["access_hours"]) == 7
    assert next(row for row in payload["access_hours"] if row["day"] == "sunday")["end"] == weekend_end
    assert payload["closures"][0]["start"] == "2026-09-07"


@pytest.mark.parametrize("observed, end, closed, exceptions", [
    (date(2026, 11, 20), "2026-12-03", ["2026-11-26"], ["2026-11-27"]),
    (date(2026, 12, 24), "2027-01-01", ["2026-12-24", "2026-12-25", "2027-01-01"],
     [f"2026-12-{day}" for day in range(26, 32)]),
])
def test_ucsf_closures_partial_days_and_printed_rollover(observed, end, closed, exceptions):
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    payload = _extract_ucsf_bakar(html, observed)
    assert payload["effective_end"] == end
    assert [row["start"] for row in payload["closures"]] == closed
    assert [row["date"] for row in payload["access_exceptions"]] == exceptions
    assert all((row["start"], row["end"]) == ("08:00", "14:00") for row in payload["access_exceptions"])


@pytest.mark.parametrize("old, new", [
    ("(Bakar and Millberry)", "(Bakar)"),
    ("Monday-Friday", "Monday-Thursday"),
    ("January 19 (MLK", "January 1 (MLK"),
    ("2027 New Year's", "2026 New Year's"),
    ("Open Regular Hours", "Open Regular Hours except pool closed"),
    ("8:00 am-2:00 pm", "8:00 am-2:00 pm pool only"),
    ("<p>November 11 (Veterans Day): Open Regular Hours</p>", ""),
])
def test_ucsf_unsupported_scope_dates_or_missing_rows_hold(old, new):
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    assert old in html
    with pytest.raises(DirectSourceError):
        _extract_ucsf_bakar(html.replace(old, new), date(2026, 9, 9))


@pytest.mark.parametrize("observed", [date(2025, 12, 31), date(2027, 1, 2)])
def test_ucsf_expired_or_future_year_schedule_never_extends(observed):
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures/html-facts/ucsf-holiday-2026.html").read_text()
    with pytest.raises(DirectSourceError):
        _extract_ucsf_bakar(html, observed)


def test_koret_cache_identity_includes_original_zip_bytes(monkeypatch, tmp_path):
    import httpx
    from schedules.direct_sources import http

    first_bytes = _workbook_bytes("first export")
    second_bytes = _workbook_bytes("second export")
    changed_bytes = _workbook_bytes("first export", hours="Hours: 7am-9pm")
    current = [first_bytes]
    def respond(request):
        return httpx.Response(200, content=current[0] if request.url.params["format"] == "xlsx" else b"%PDF-1.4")

    client_class = httpx.Client
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(respond)))
    url = "https://docs.google.com/spreadsheets/d/official/edit"
    first = http.fetch_koret_workbook("koret-center", url, cache_root=tmp_path)
    assert first.sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert first.path.read_bytes() == first_bytes
    assert "format=xlsx" in first.response_url
    assert http.fetch_koret_workbook("koret-center", url, cache_root=tmp_path).from_cache

    # A re-export of the same cells keeps the original capture and its identity.
    current[0] = second_bytes
    assert second_bytes != first_bytes
    reused = http.fetch_koret_workbook("koret-center", url, cache_root=tmp_path)
    assert (reused.path, reused.sha256, reused.from_cache) == (first.path, first.sha256, True)
    assert reused.path.read_bytes() == first_bytes

    current[0] = changed_bytes
    changed = http.fetch_koret_workbook("koret-center", url, cache_root=tmp_path)
    assert changed.sha256 != first.sha256
    assert not changed.from_cache

    first.path.write_bytes(b"corrupt")
    current[0] = first_bytes
    with pytest.raises(DirectSourceError, match="prefix collision"):
        http.fetch_koret_workbook("koret-center", url, cache_root=tmp_path)


def test_koret_rejects_an_unreadable_workbook_export(monkeypatch, tmp_path):
    import httpx
    from schedules.direct_sources import http
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", b"<workbook/>")
    client_class = httpx.Client
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=output.getvalue()))))
    with pytest.raises(DirectSourceError, match="not a valid XLSX"):
        http.fetch_koret_workbook("koret-center", "https://docs.google.com/spreadsheets/d/official/edit",
                                  cache_root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_fetch_text_reports_sanitized_redirect_destination(monkeypatch):
    import httpx
    import traceback
    from schedules.direct_sources import http

    def respond(request):
        if request.url.path == "/pool":
            return httpx.Response(302, headers={"location": "https://official.example/denied?token=private"})
        return httpx.Response(403, headers={"cf-mitigated": "challenge", "set-cookie": "private"}, text="private")

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(DirectSourceError) as error:
        http.fetch_text("https://official.example/pool")
    diagnostic = "".join(traceback.format_exception(error.value))
    assert "https://official.example/denied" in diagnostic
    assert "challenge" in diagnostic
    assert "token=" not in str(error.value)
    assert "private" not in str(error.value)
    assert "HTTPStatusError" not in diagnostic


def _pomeroy_original():
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "data/pomeroy-pool/2026-08-12-5348b4b7f7e3/source.html").read_text()


def test_pomeroy_independent_inventory_covers_original_and_expiry():
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    result = verify_pomeroy(html, payload, observed)
    assert result["ok"], result["issues"]
    assert len(result["cells"]) == 22
    assert sum(cell["included"] for cell in result["cells"]) == 16
    assert len(result["restrictions"]) == 2
    later = date(2026, 9, 8)
    later_payload = _extract_pomeroy(html, observed_on=later)
    assert later_payload["closures"] == []
    assert verify_pomeroy(html, later_payload, later)["closure_notices"][0]["date"] is None


@pytest.mark.parametrize("change", ["omit", "duplicate", "time", "evidence", "closure"])
def test_pomeroy_independent_inventory_rejects_payload_changes(change):
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    if change == "omit":
        payload["sessions"].pop()
    elif change == "duplicate":
        payload["sessions"].append(payload["sessions"][0].copy())
    elif change == "closure":
        payload["closures"] = []
    else:
        payload["sessions"][0]["start" if change == "time" else "evidence"] = "changed"
    assert not verify_pomeroy(html, payload, observed)["ok"]


@pytest.mark.parametrize("old,new", [
    ("Aquatic Exercise</span>", "Private Lessons</span>"),
    ("Slow lap swimming only.", "Fast lap swimming allowed."),
    ("No lanes, can be 1-on-1 with participants.", "Members only."),
    ("Monday, September 7th - Labor Day", "Tuesday, September 7th - Labor Day"),
    ("Monday, September 7th - Labor Day", "Closed until further notice"),
    ("Monday, September 7th - Labor Day", "Monday, September 7th - Labor Day Pool closes at noon"),
])
def test_pomeroy_independent_inventory_holds_unknown_source_changes(old, new):
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    assert old in html
    assert not verify_pomeroy(html.replace(old, new), payload, observed)["ok"]


def test_pomeroy_inventory_holds_closure_outside_known_block():
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    assert not verify_pomeroy(html + "<p>Pool closed tomorrow</p>", payload, observed)["ok"]


def test_pomeroy_inventory_resolves_year_rollover_without_guessing_stale_years():
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original().replace("Monday, September 7th - Labor Day", "Friday, January 1st - New Year's Day")
    observed = date(2026, 12, 28)
    payload = _extract_pomeroy(html, observed_on=observed)
    assert payload["closures"][0]["start"] == "2027-01-01"
    assert verify_pomeroy(html, payload, observed)["ok"]
    explicit = html.replace("January 1st -", "January 1st, 2027 -")
    assert verify_pomeroy(explicit, payload, observed)["ok"]


@pytest.mark.parametrize("field,value", [
    ("excluded_dates", ["2026-09-07"]),
    ("pool", "deep"),
    ("physical_pool", "cool"),
    ("source_sha256", "a" * 64),
    ("source_cell", "p1-r1-c1"),
    ("pool_label_raw", "Deep Pool"),
])
def test_pomeroy_inventory_rejects_extra_session_fields(field, value):
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    payload["sessions"][0][field] = value
    assert not verify_pomeroy(html, payload, observed)["ok"]


@pytest.mark.parametrize("notice", [
    "Therapeutic swimming is by appointment only.",
    "Advance booking compulsory",
    "Schedule effective September 1, 2026.",
    "Schedule valid through September 6, 2026.",
    "Schedule valid until September 6, 2026.",
    "Schedule ending September 6, 2026.",
    "Schedule expires September 6, 2026.",
])
def test_pomeroy_inventory_holds_added_restrictions_or_effective_dates(notice):
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    assert not verify_pomeroy(html + f"<p>{notice}</p>", payload, observed)["ok"]


def test_pomeroy_inventory_rejects_access_exceptions():
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    payload["access_exceptions"] = [{"date": "2026-09-07", "start": "10:00", "end": "11:00"}]
    assert not verify_pomeroy(html, payload, observed)["ok"]


@pytest.mark.parametrize("link", [
    '<a href="/new-pool-schedule.pdf">Pool schedule</a>',
    '<a href="/schedule.xlsx">Download</a>',
    '<a href="/hours.pdf">Pool timetable</a>',
    '<a href="https://docs.google.com/spreadsheets/d/official/edit">Weekly hours</a>',
])
def test_pomeroy_inventory_holds_separate_linked_schedule(link):
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    assert not verify_pomeroy(html + link, payload, observed)["ok"]


def test_pomeroy_inventory_allows_application_link():
    from schedules.direct_sources.providers.pomeroy import verify_pomeroy
    html = _pomeroy_original()
    observed = date(2026, 9, 7)
    payload = _extract_pomeroy(html, observed_on=observed)
    assert verify_pomeroy(html + '<a href="/application.pdf">Application form</a>', payload, observed)["ok"]


@pytest.fixture
def browser_capture(tmp_path):
    import hashlib
    from datetime import datetime, timezone
    from schedules.models import PoolEntry
    root = tmp_path
    directory = root / 'tmp/browser-capture/jccsf'
    directory.mkdir(parents=True)
    (root / 'scripts').mkdir()
    (root / 'scripts/capture-schedules.mjs').write_text('capture implementation')
    package = root / 'node_modules/playwright-core'
    package.mkdir(parents=True)
    (package / 'package.json').write_text('{"version":"1.60.0"}')
    files = {'source': ('source.html', b'<html><body>Official pool schedule</body></html>'),
             'rendered': ('rendered.html', b'<html><body>Rendered schedule</body></html>'),
             'screenshot': ('screenshot.png', b'\x89PNG\r\n\x1a\nfixture')}
    for filename, content in files.values():
        (directory / filename).write_bytes(content)
    entry = PoolEntry(slug='jccsf', pdf_url='https://www.jccsf.org/fitness/aquatics/',
                      official_page_url='https://www.jccsf.org/fitness/aquatics/',
                      source_kind='jccsf_html', capture_method='cloudflare_browser')
    receipt = {'method': 'cloudflare_browser', 'requested_url': entry.pdf_url, 'url': entry.pdf_url,
               'captured_at': datetime.now(timezone.utc).isoformat(), 'status': 200,
               'configuration': {'script_sha256': hashlib.sha256((root / 'scripts/capture-schedules.mjs').read_bytes()).hexdigest(),
                                 'playwright_version': '1.60.0'},
               'hashes': {key: hashlib.sha256(value[1]).hexdigest() for key, value in files.items()},
               'browser_version': '128'}
    (directory / 'capture.json').write_text(json.dumps(receipt))
    (directory.parent / 'results.json').write_text(json.dumps({'closed': True, 'results': [{'slug': entry.slug, 'status': 'captured'}]}))
    return root, directory, entry, receipt


def test_browser_capture_uses_original_bytes_and_keeps_provenance(browser_capture, monkeypatch):
    from schedules import direct_sources
    from schedules.direct_sources.browser import read_browser_capture
    root, directory, entry, receipt = browser_capture
    monkeypatch.setattr('schedules.direct_sources.browser.read_browser_capture', lambda entry: read_browser_capture(entry, root=root))
    monkeypatch.setattr(direct_sources, 'fetch_text', lambda *_: pytest.fail('Browser source must never use HTTP fallback'))
    from schedules.direct_sources import html_facts
    inventory = {'lines': [{'id': 'row', 'text': 'Official pool schedule'}]}
    monkeypatch.setattr(html_facts, 'inspect_html_source', lambda slug, text: inventory)
    monkeypatch.setattr(html_facts, 'html_source_payload', lambda *_: {'sessions': [], 'closures': [], 'schedule_basis': 'swim_schedule'})
    result = direct_sources.extract_direct(entry, cache_root=root / 'data')
    assert result.fetch_result.path.read_bytes() == (directory / 'source.html').read_bytes()
    assert result.source['configuration']['capture'] == receipt
    assert result.model == 'browser-html'


@pytest.mark.parametrize('failure', ['missing', 'source_hash', 'rendered_hash', 'screenshot_hash', 'url', 'status', 'stale', 'future', 'script', 'version', 'unclosed', 'failed', 'duplicate', 'symlink'])
def test_browser_capture_rejects_invalid_evidence_without_http_fallback(browser_capture, monkeypatch, failure):
    from schedules import direct_sources
    from schedules.direct_sources.browser import read_browser_capture
    root, directory, entry, receipt = browser_capture
    if failure == 'missing':
        (directory / 'capture.json').unlink()
    elif failure.endswith('_hash'):
        receipt['hashes'][failure.removesuffix('_hash')] = '0' * 64
    elif failure == 'url':
        receipt['url'] = 'https://example.org/'
    elif failure == 'status':
        receipt['status'] = 403
    elif failure in {'stale', 'future'}:
        receipt['captured_at'] = '2000-01-01T00:00:00Z' if failure == 'stale' else '2999-01-01T00:00:00Z'
    elif failure == 'script':
        receipt['configuration']['script_sha256'] = '0' * 64
    elif failure == 'version':
        receipt['configuration']['playwright_version'] = 'unknown'
    elif failure in {'unclosed', 'failed', 'duplicate'}:
        items = [{'slug': entry.slug, 'status': 'failed' if failure == 'failed' else 'captured'}]
        (directory.parent / 'results.json').write_text(json.dumps({'closed': failure != 'unclosed', 'results': items * (2 if failure == 'duplicate' else 1)}))
    elif failure == 'symlink':
        source = directory / 'source.html'
        content = source.read_bytes()
        source.unlink()
        (root / 'elsewhere.html').write_bytes(content)
        source.symlink_to(root / 'elsewhere.html')
    if failure != 'missing':
        (directory / 'capture.json').write_text(json.dumps(receipt))
    monkeypatch.setattr('schedules.direct_sources.browser.read_browser_capture', lambda entry: read_browser_capture(entry, root=root))
    monkeypatch.setattr(direct_sources, 'fetch_text', lambda *_: pytest.fail('No fallback on capture failure'))
    with pytest.raises(DirectSourceError, match='valid current Cloudflare capture required'):
        direct_sources.extract_direct(entry, cache_root=root / 'data')


def test_browser_capture_extracts_undecodable_byte_leniently(browser_capture, monkeypatch):
    """The stored bytes stay the evidence; the extractor sees a repaired byte, not a rejected capture."""
    from schedules import direct_sources
    from schedules.direct_sources.browser import read_browser_capture
    from schedules.direct_sources import html_facts
    root, directory, entry, receipt = browser_capture
    content = b'<html><body>Official pool schedule \xff more</body></html>'
    (directory / 'source.html').write_bytes(content)
    receipt['hashes']['source'] = hashlib.sha256(content).hexdigest()
    (directory / 'capture.json').write_text(json.dumps(receipt))
    monkeypatch.setattr('schedules.direct_sources.browser.read_browser_capture', lambda entry: read_browser_capture(entry, root=root))
    monkeypatch.setattr(direct_sources, 'fetch_text', lambda *_: pytest.fail('Browser source must never use HTTP fallback'))
    seen = []
    monkeypatch.setattr(html_facts, 'inspect_html_source',
                        lambda slug, text: seen.append(text) or {'lines': [{'id': 'row', 'text': 'Official pool schedule'}]})
    monkeypatch.setattr(html_facts, 'html_source_payload', lambda *_: {'sessions': [], 'closures': [], 'schedule_basis': 'swim_schedule'})
    result = direct_sources.extract_direct(entry, cache_root=root / 'data')
    assert seen == ['<html><body>Official pool schedule � more</body></html>']
    assert result.fetch_result.path.read_bytes() == content


def test_access_verification_of_undecodable_capture_does_not_raise_unicode_decode_error(tmp_path, monkeypatch):
    """Verification must fail, if at all, with the module's own error — never a bare UnicodeDecodeError."""
    from schedules import direct_sources
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.models import PoolEntry
    content = b'<html><body>Fri: 5 am - 11 pm \xff</body></html>'
    monkeypatch.setattr(direct_sources, 'fetch_text',
                        lambda url: DirectTextResponse('', content, 'https://fitnesssf.com/location/fillmore'))
    monkeypatch.setitem(direct_sources._HTML_EXTRACTORS, 'fitness_sf_html',
                        (lambda text: {'sessions': [], 'closures': []}, 'fitness-sf-html-v1', 'Access hours only.'))
    entry = PoolEntry(slug='fitness-sf-fillmore', pdf_url='https://fitnesssf.com/location/fillmore',
                      official_page_url='https://fitnesssf.com/location/fillmore', source_kind='fitness_sf_html')
    result = direct_sources.extract_direct(entry, cache_root=tmp_path / 'data')
    artifact = {'provider': 'direct', 'model': result.model, 'source_pdf_url': entry.pdf_url,
                'pdf_sha256': result.fetch_result.sha256, 'payload': result.payload,
                'details': {'direct_source': result.source}}
    today = date.fromisoformat(result.source['observed_on'])
    try:
        outcome = direct_sources.verify_direct_artifact(artifact, result.fetch_result.path, today=today)
    except UnicodeDecodeError:
        pytest.fail('Verification leaked a bare UnicodeDecodeError instead of DirectSourceError')
    except DirectSourceError:
        pass
    else:
        assert outcome['ok']


def test_http_capture_replaces_an_undecodable_byte_instead_of_failing(tmp_path, monkeypatch):
    """The stored bytes stay the evidence; only the text handed to the extractor is repaired."""
    from schedules import direct_sources
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.models import PoolEntry
    content = b'<html><body>Lap swim \xff 6am</body></html>'
    monkeypatch.setattr(direct_sources, 'fetch_text',
                        lambda url: DirectTextResponse('', content, 'https://www.fitnesssf.com/pool'))
    seen = []
    monkeypatch.setitem(direct_sources._HTML_EXTRACTORS, 'fitness_sf_html',
                        (lambda text: seen.append(text) or {'sessions': [], 'closures': []},
                         'fitness-sf-html-v1', 'Access hours only.'))
    entry = PoolEntry(slug='fitness-sf', pdf_url='https://www.fitnesssf.com/pool',
                      official_page_url='https://www.fitnesssf.com/pool', source_kind='fitness_sf_html')
    result = direct_sources.extract_direct(entry, cache_root=tmp_path / 'data')
    assert seen == ['<html><body>Lap swim \ufffd 6am</body></html>']
    assert result.fetch_result.path.read_bytes() == content


def test_browser_parser_failure_retains_original_source_and_capture(browser_capture, monkeypatch):
    from schedules import direct_sources
    from schedules.direct_sources.browser import read_browser_capture
    root, directory, entry, _ = browser_capture
    monkeypatch.setattr('schedules.direct_sources.browser.read_browser_capture', lambda entry: read_browser_capture(entry, root=root))
    def fail(slug, text):
        raise DirectSourceError('Changed schedule requires review')
    monkeypatch.setattr('schedules.direct_sources.html_facts.inspect_html_source', fail)
    with pytest.raises(DirectSourceError, match='Changed schedule'):
        direct_sources.extract_direct(entry, cache_root=root / 'data')
    assert len(list((root / 'data/jccsf').glob('*/source.html'))) == 1
    assert (directory / 'capture.json').exists()


_PUBLISHABLE_HTML_SLUGS = ('jccsf', 'sfsu-mashouf', 'embarcadero-ymca', 'presidio-ymca-letterman', 'chinatown-ymca')

@pytest.fixture
def integrated_html_capture(tmp_path, monkeypatch):
    from copy import deepcopy
    from pathlib import Path
    from schedules.direct_sources.http import DirectTextResponse
    from schedules.providers import openai_provider
    from schedules.registry import load_registry
    captures = {}
    for slug in _PUBLISHABLE_HTML_SLUGS:
        entry = next(item for item in load_registry() if item.slug == slug)
        fixture = 'chinatown-ymca-reopened' if slug == 'chinatown-ymca' else slug
        content = (Path(__file__).parent / 'fixtures/html-facts' / f'{fixture}.html').read_bytes()
        receipt = {'method': 'cloudflare_browser', 'requested_url': entry.pdf_url,
                   'url': entry.pdf_url, 'status': 200, 'captured_at': '2026-09-08T18:00:00Z',
                   'hashes': {'source': hashlib.sha256(content).hexdigest()},
                   'configuration': {'script_sha256': 'f' * 64, 'playwright_version': 'test'}}
        captures[slug] = (DirectTextResponse(content.decode(), content, entry.pdf_url), receipt)
    monkeypatch.setattr('schedules.direct_sources.browser.read_browser_capture', lambda entry: deepcopy(captures[entry.slug]))
    monkeypatch.setattr(openai_provider, 'call_api', lambda *args, **kwargs: pytest.fail('HTML must not call the model'))
    return captures



def _integrated_html_artifact(tmp_path, slug):
    from schedules.direct_sources import extract_direct
    from schedules.registry import load_registry
    entry = next(item for item in load_registry() if item.slug == slug)
    result = extract_direct(entry, cache_root=tmp_path / 'data')
    artifact = {'provider': 'direct', 'model': result.model, 'source_pdf_url': entry.pdf_url,
                'pdf_sha256': result.fetch_result.sha256, 'payload': result.payload,
                'details': {'direct_source': result.source}}
    path = result.fetch_result.path.parent / 'direct-browser-html.json'
    path.write_text(json.dumps(artifact))
    return entry, result, artifact


@pytest.mark.parametrize('slug', sorted(_PUBLISHABLE_HTML_SLUGS))
def test_frozen_html_capture_and_publication_verifier_agree(tmp_path, integrated_html_capture, slug):
    from schedules.direct_sources import verify_direct_artifact
    _, result, artifact = _integrated_html_artifact(tmp_path, slug)
    assert verify_direct_artifact(artifact, result.fetch_result.path, today=date(2026, 9, 8))['ok']
    _, reused, fresh = _integrated_html_artifact(tmp_path, slug)
    assert verify_direct_artifact(fresh, reused.fetch_result.path, today=date(2026, 9, 8))['ok']
    assert reused.fetch_result.from_cache


@pytest.mark.parametrize('mutation', ['configuration', 'payload', 'receipt', 'expired', 'future', 'bytes'])
def test_frozen_html_publication_rejects_changed_evidence(tmp_path, integrated_html_capture, mutation):
    from schedules.direct_sources import verify_direct_artifact
    _, result, artifact = _integrated_html_artifact(tmp_path, 'sfsu-mashouf')
    today = date(2026, 9, 8)
    if mutation == 'configuration':
        artifact['details']['direct_source']['configuration']['parser_sha256'] = '0' * 64
    elif mutation == 'payload':
        artifact['payload']['access_hours'][0]['end'] = '23:00'
    elif mutation == 'receipt':
        integrated_html_capture['sfsu-mashouf'][1]['captured_at'] = '2026-09-09T18:00:00Z'
    elif mutation == 'expired':
        today = date(2026, 9, 22)
    elif mutation == 'future':
        today = date(2026, 9, 7)
    else:
        result.fetch_result.path.write_bytes(b'changed')
    with pytest.raises(DirectSourceError):
        verify_direct_artifact(artifact, result.fetch_result.path, today=today)


def test_frozen_letterman_closure_cannot_publish_after_printed_end(tmp_path, integrated_html_capture):
    from schedules.publish import publish_eligible
    from schedules.review import find_review_candidates
    entry, result, artifact = _integrated_html_artifact(tmp_path, 'presidio-ymca-letterman')
    candidate = find_review_candidates(data_root=tmp_path / 'data')[0]
    options = dict(candidate=candidate, payload=result.payload, prior_sessions_count=0,
                   latest_effective_start='2026-05-17', source_kind=entry.source_kind,
                   source_status=entry.source_status, blocking_slugs=frozenset(), quarantined_shas=frozenset(),
                   has_prior_schedule_window=True, source_pdf_path=result.fetch_result.path,
                   pin_url=entry.pdf_url, direct_opt_in=True)
    assert publish_eligible(**options, today=date(2026, 9, 13)).ok
    assert not publish_eligible(**options, today=date(2026, 9, 14)).ok


def test_chinatown_publication_rejects_conflict_date_even_with_fresh_capture(tmp_path, integrated_html_capture):
    from schedules.direct_sources import verify_direct_artifact
    integrated_html_capture['chinatown-ymca'][1]['captured_at'] = '2026-12-20T18:00:00Z'
    _, result, artifact = _integrated_html_artifact(tmp_path, 'chinatown-ymca')
    assert artifact['payload']['effective_end'] == '2026-12-31'
    assert verify_direct_artifact(artifact, result.fetch_result.path, today=date(2026, 12, 31))['ok']
    with pytest.raises(DirectSourceError, match='schedule window is expired'):
        verify_direct_artifact(artifact, result.fetch_result.path, today=date(2027, 1, 1))
    artifact['payload']['effective_end'] = '2027-01-02'
    with pytest.raises(DirectSourceError, match='differs from verified source facts'):
        verify_direct_artifact(artifact, result.fetch_result.path, today=date(2026, 12, 31))


def test_frozen_browser_sources_publish_atomically_per_candidate(tmp_path, integrated_html_capture, monkeypatch):
    from schedules import publish, review
    extracted = [_integrated_html_artifact(tmp_path, slug) for slug in _PUBLISHABLE_HTML_SLUGS]
    content = tmp_path / 'content'
    content.mkdir()
    for entry, _, _ in extracted:
        sessions = '\n'.join(
            f'[[extra.schedules.sessions]]\nday = "{day}"\ntype = "lap_swim"\nstart = "07:00"\nend = "08:00"'
            for day in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday'))
        (content / f'{entry.slug}.md').write_text(
            f'+++\ntitle = "{entry.slug}"\nslug = "{entry.slug}"\n[extra]\n'
            '[[extra.schedules]]\neffective_start = "2026-05-17"\neffective_end = "2026-08-11"\n'
            f'schedule_basis = "swim_schedule"\nclosures = []\n{sessions}\n+++\n')
    reports = tmp_path / 'reports'
    reports.mkdir()
    monkeypatch.setattr(publish, 'TMP_DIR', reports)
    monkeypatch.setattr(publish, 'auto_project_enabled', lambda: True)
    monkeypatch.setattr(publish, 'load_registry', lambda: [entry for entry, _, _ in extracted])
    monkeypatch.setattr(publish, 'load_quarantine', lambda: frozenset())
    monkeypatch.setattr(review, 'pacific_today', lambda: date(2026, 9, 8))
    options = dict(data_root=tmp_path / 'data', content_spots_dir=content, today=date(2026, 9, 8))
    assert publish.publish_pending_all(**options)[0] == 0
    assert not list((tmp_path / 'data').glob('*/*/reviewed.json'))
    (reports / 'extraction-report-direct.json').write_text(json.dumps({'ready_direct': {
        entry.slug: (result.fetch_result.path.parent / 'direct-browser-html.json').relative_to(tmp_path).as_posix()
        for entry, result, _ in extracted}}))
    assert publish.publish_pending_all(**options)[0] == len(_PUBLISHABLE_HTML_SLUGS)
    report = json.loads((reports / 'publish-pending.json').read_text())
    assert report['refused'] == []
    for entry, result, artifact in extracted:
        reviewed = json.loads((result.fetch_result.path.parent / 'reviewed.json').read_text())
        assert reviewed['direct_source'] == artifact['details']['direct_source']
        assert reviewed['payload'] == artifact['payload']
        projected = (content / f'{entry.slug}.md').read_text()
        if entry.slug == 'presidio-ymca-letterman':
            assert 'maintenance' in projected
            assert reviewed['payload']['effective_end'] == '2026-09-13'
        if entry.slug in {'sfsu-mashouf', 'embarcadero-ymca'}:
            assert reviewed['payload']['sessions'] == []
            assert reviewed['payload']['schedule_basis'] == 'pool_hours'
    published_bytes = {path: path.read_bytes() for path in content.glob('*.md')}
    assert publish.publish_pending_all(**options)[0] == 0
    assert all(path.read_bytes() == original for path, original in published_bytes.items())
    for _, receipt in integrated_html_capture.values():
        receipt['captured_at'] = '2026-09-09T18:00:00Z'
    for slug in _PUBLISHABLE_HTML_SLUGS:
        _integrated_html_artifact(tmp_path, slug)
    monkeypatch.setattr(review, 'pacific_today', lambda: date(2026, 9, 9))
    assert publish.publish_pending_all(**(options | {'today': date(2026, 9, 9)}))[0] == len(_PUBLISHABLE_HTML_SLUGS)
    for path in (tmp_path / 'data').glob('*/*/reviewed.json'):
        assert json.loads(path.read_text())['payload']['effective_start'] == '2026-09-09'


def test_browser_pipeline_writes_ready_direct_artifact_for_verified_access_transition(tmp_path, integrated_html_capture, monkeypatch):
    from schedules import artifacts, direct_sources, paths, pipeline
    from schedules.registry import load_registry
    from schedules.report import write_report
    entry = next(item for item in load_registry() if item.slug == 'sfsu-mashouf')
    monkeypatch.setattr(direct_sources, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(pipeline, 'reviewed_path', lambda *args: paths.reviewed_path(*args, root=tmp_path / 'data'))
    save = artifacts.save_artifact_bundle
    monkeypatch.setattr(pipeline, 'save_artifact_bundle', lambda **kwargs: save(**kwargs, root=tmp_path / 'data'))
    monkeypatch.setattr(artifacts, 'relative_to_repo', lambda path: path.relative_to(tmp_path).as_posix())
    prior = {'sessions': [{'day': 'monday', 'type': 'lap_swim', 'start': '07:00', 'end': '08:00'}],
             'closures': [], 'effective_start': '2026-05-17', 'effective_end': None}
    result = pipeline._process_direct_entry(entry, prior, policy=pipeline.ReusePolicy(False, False, False))
    assert result.provider == 'direct'
    assert result.model == 'browser-html'
    assert not result.catastrophic
    assert result.violations == []
    report = tmp_path / 'extraction-report-direct.md'
    write_report([result], report)
    receipt = json.loads(report.with_suffix('.json').read_text())
    assert receipt['ready_direct'] == {entry.slug: result.artifact_paths['direct']}
    artifact_path = tmp_path / receipt['ready_direct'][entry.slug]
    artifact = json.loads(artifact_path.read_text())
    assert artifact['usage'] == {}
    assert artifact['cost_estimate'] == 'deterministic'
    assert artifact['payload']['sessions'] == []
    assert artifact['payload']['access_hours']
    assert artifact['prompt_sha256'] == hashlib.sha256(f'direct:{entry.source_kind}'.encode()).hexdigest()
    assert direct_sources.verify_direct_artifact(artifact, artifact_path.parent / 'source.html', today=date(2026, 9, 8))['ok']


def test_koret_original_invalid_monday_hours_hold_whole_workbook():
    from pathlib import Path
    original = Path(__file__).parent / 'fixtures/koret-september.xlsx'
    assert hashlib.sha256(original.read_bytes()).hexdigest() == 'a2506a70e8567c8ad5cee1b369b2e0b23be8927afa760a870aadb807253d3c4b'
    with pytest.raises(DirectSourceError, match='Monday A2: invalid stated hours: Hours: 7am-7am'):
        _extract_koret(original)


def test_koret_original_sunday_deep_end_closure_does_not_close_other_lanes():
    from pathlib import Path
    from openpyxl import load_workbook
    from schedules.direct_sources.providers.koret import _weekend_schedule
    workbook = load_workbook(Path(__file__).parent / 'fixtures/koret-september.xlsx', data_only=True)
    sessions, closures = _weekend_schedule(workbook['Weekend'])
    assert [(row['day'], row['start'], row['end']) for row in sessions] == [
        ('saturday', '08:00', '18:00'), ('sunday', '08:00', '18:00')]
    assert closures == []
    assert workbook['Weekend']['L27'].value == 'Deep End Closed'


@pytest.mark.parametrize('hours', ['Hours: 7am-7am', 'Hours: 9pm-7am'])
def test_koret_invalid_headline_never_falls_back_to_grid(tmp_path, hours):
    sheets = {'Monday': [['Monday'], [hours], [time(6), 'slow'], [time(20), 'slow']]}
    with pytest.raises(DirectSourceError, match='invalid stated hours'):
        _extract_koret(_koret_workbook(tmp_path, sheets))


def test_koret_unresolved_sunday_closure_scope_holds(tmp_path):
    sheets = {'Weekend': [['Saturday'], ['Hours 8am-6pm'], ['Sunday'],
                         ['Hours 8am-6pm'], [time(8), 'Closed unless staffing permits']]}
    with pytest.raises(DirectSourceError, match='unresolved closure scope'):
        _extract_koret(_koret_workbook(tmp_path, sheets))
