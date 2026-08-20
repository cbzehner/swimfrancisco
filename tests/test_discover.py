from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.direct_sources.http import BOT_USER_AGENT
from schedules.discover import (
    VIEW_ID_RE,
    ClassifiedDocument,
    DiscoverDecision,
    DiscoverError,
    DocumentLink,
    apply_discover_decision,
    choose_roll,
    classify_pdf,
    discover_all,
    discover_facility_documents,
    persisted_band_ids,
    rec_park_entries,
    rewrite_registry_pdf_url,
)
from schedules.models import PoolEntry
from schedules.registry import load_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "discover"
FIXTURE_REGISTRY = FIXTURE_DIR / "registry.toml"
REC_PARK_SLUGS = [
    "balboa-pool",
    "coffman-pool",
    "garfield-pool",
    "hamilton-pool",
    "martin-luther-king-jr-pool",
    "mission-community-pool",
    "north-beach-pool",
    "rossi-pool",
    "sava-pool",
]


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _pdf_with_text(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.1\n")
    offsets = [0]
    for index, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _grid_pdf() -> bytes:
    return _pdf_with_text("Monday Tuesday Wednesday Thursday Friday")


def _link(view_id: int, text: str) -> DocumentLink:
    return DocumentLink(
        view_id=view_id,
        href=f"https://sfrecpark.org/DocumentCenter/View/{view_id}",
        anchor_text=text,
    )


def _classified(
    view_id: int,
    kind: str,
    *,
    text: str = "",
    source: str = "table",
    filename: str | None = None,
    grid_confirmed: bool | None = None,
) -> ClassifiedDocument:
    return ClassifiedDocument(
        link=_link(view_id, text),
        kind=kind,  # type: ignore[arg-type]
        filename=filename,
        source=source,  # type: ignore[arg-type]
        grid_confirmed=grid_confirmed,
    )


def _entry(
    slug: str,
    *,
    view_id: int,
    status: str = "published",
    notes: str | None = None,
    page: str | None = None,
) -> PoolEntry:
    return PoolEntry(
        slug=slug,
        pdf_url=f"https://sfrecpark.org/DocumentCenter/View/{view_id}",
        official_page_url=page
        or f"https://sfrecpark.org/facilities/facility/details/{slug}",
        source_status=status,  # type: ignore[arg-type]
        source_kind="sfrecpark_pdf",
        notes=notes,
    )


def _copy_registry(tmp_path: Path) -> Path:
    dest = tmp_path / "registry.toml"
    dest.write_text(FIXTURE_REGISTRY.read_text())
    return dest


def _view_response(
    url: str, *, status: int, content: bytes, content_type: str, filename: str | None
):
    headers = {"Content-Type": content_type}
    if filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return httpx.Response(
        status, content=content, headers=headers, request=httpx.Request("GET", url)
    )


def _install_http(
    monkeypatch,
    *,
    pages: dict[str, str] | None = None,
    views: dict[int, dict] | None = None,
    requested: list[str] | None = None,
):
    pages = pages or {}
    views = views or {}
    requested = requested if requested is not None else []
    seen: dict = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            seen["headers"] = kwargs.get("headers")
            seen["timeout"] = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            requested.append(url)
            if "bayclubs.com" in url:
                raise AssertionError(f"bay-club must not be fetched: {url}")
            view_match = None
            match = VIEW_ID_RE.search(url)
            if match:
                view_match = int(match.group(1))
            if view_match is not None:
                spec = views.get(
                    view_match,
                    {"status": 404, "content": b"missing", "type": "text/plain"},
                )
                return _view_response(
                    url,
                    status=spec.get("status", 200),
                    content=spec.get("content", _pdf_bytes()),
                    content_type=spec.get("type", "application/pdf"),
                    filename=spec.get("filename"),
                )
            html = pages.get(url)
            if html is None:
                html = _fixture("empty-table.html")
            return httpx.Response(
                200,
                text=html,
                headers={"Content-Type": "text/html"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("schedules.discover.httpx.Client", FakeClient)
    return seen, requested


def _freeze_today(monkeypatch) -> None:
    monkeypatch.setattr("schedules.discover.pacific_today", lambda: date(2026, 8, 19))


def test_bot_user_agent_constant() -> None:
    assert BOT_USER_AGENT == "SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)"


def test_fetch_text_and_koret_use_shared_bot_user_agent() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "schedule-tools/src/schedules/direct_sources/http.py"
    ).read_text()
    assert source.count("BOT_USER_AGENT") >= 3
    assert (
        source.count("SwimFranciscoScheduleBot/0.1 (+https://swimfrancisco.com)") == 1
    )


def test_hamilton_fixture_collects_one_grid_and_ignores_deck_rules() -> None:
    links = discover_facility_documents(_fixture("hamilton-one-grid.html"))
    assert [link.view_id for link in links] == [29800]
    assert "Fall 2026" in links[0].anchor_text
    assert links[0].href == "https://sfrecpark.org/DocumentCenter/View/29800"


def test_north_beach_fixture_collects_two_split_links() -> None:
    links = discover_facility_documents(_fixture("north-beach-two-grids.html"))
    assert [link.view_id for link in links] == [29778, 29779]


def test_sava_fixture_collects_following_tr_link() -> None:
    links = discover_facility_documents(_fixture("sava-two-session-grids.html"))
    assert [link.view_id for link in links] == [29815]


def test_empty_table_returns_no_links() -> None:
    assert discover_facility_documents(_fixture("empty-table.html")) == []


def test_classify_session_grid_vs_flyer_vs_jpeg_vs_part() -> None:
    grid = classify_pdf(
        _link(29800, "Hamilton Pool _ Fall 2026 _ August 18 to December 12"),
        pool_slug="hamilton-pool",
        pdf_bytes=_pdf_bytes(),
        filename="Hamilton Pool _ Fall 2026 _ August 18 to December 12.pdf",
    )
    flyer = classify_pdf(
        _link(29808, "Garfield Pool Maintenance Closure 8-14_9-7 2026"),
        pool_slug="garfield-pool",
        pdf_bytes=_pdf_bytes(),
        filename="Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
    )
    jpeg = classify_pdf(
        _link(29807, "Zoo Budget"),
        pool_slug="garfield-pool",
        pdf_bytes=b"\xff\xd8\xff\xe0",
        filename="zoo-budget.jpg",
    )
    part = classify_pdf(
        _link(29802, "MLK Pool_Fall2026_pt1_Aug 18_Sep26"),
        pool_slug="martin-luther-king-jr-pool",
        pdf_bytes=_pdf_bytes(),
        filename="MLK Pool_Fall2026_pt1_Aug 18_Sep26.pdf",
    )
    assert grid.kind == "session_grid"
    assert flyer.kind == "closure_notice"
    assert jpeg.kind == "other"
    assert part.kind == "session_grid"


def test_fall12026_is_not_split_part() -> None:
    classified = classify_pdf(
        _link(29815, "Sava_Pool_Fall12026_Aug18toDec26_"),
        pool_slug="sava-pool",
        pdf_bytes=_pdf_bytes(),
        filename="Sava_Pool_Fall12026_Aug18toDec26_.pdf",
    )
    assert classified.kind == "session_grid"


def test_cool_warm_is_still_split_part() -> None:
    cool = classify_pdf(
        _link(29778, "North Beach Cool Pool Fall 2026"),
        pool_slug="north-beach-pool",
        pdf_bytes=_pdf_bytes(),
        filename="North Beach Cool Pool Fall 2026.pdf",
    )
    warm = classify_pdf(
        _link(29779, "North Beach Warm Pool Fall 2026"),
        pool_slug="north-beach-pool",
        pdf_bytes=_pdf_bytes(),
        filename="North Beach Warm Pool Fall 2026.pdf",
    )
    assert cool.kind == "split_part"
    assert warm.kind == "split_part"


def test_cool_warm_concatenated_is_split_part() -> None:
    cool = classify_pdf(
        _link(29778, "CoolPool Fall 2026"),
        pool_slug="north-beach-pool",
        pdf_bytes=_pdf_bytes(),
        filename="CoolPool_Fall2026.pdf",
    )
    warm = classify_pdf(
        _link(29779, "WarmPool Fall 2026"),
        pool_slug="north-beach-pool",
        pdf_bytes=_pdf_bytes(),
        filename="WarmPool_Fall2026.pdf",
    )
    assert cool.kind == "split_part"
    assert warm.kind == "split_part"


def test_rossi_concatenated_filename_is_session_grid() -> None:
    classified = classify_pdf(
        _link(29804, "RossiPool_Fall2026_Aug16toDec10"),
        pool_slug="rossi-pool",
        pdf_bytes=_pdf_bytes(),
        filename="RossiPool_Fall2026_Aug16toDec10.pdf",
    )
    assert classified.kind == "session_grid"


def test_page1_closed_cells_do_not_demote_fall_schedule_title(monkeypatch) -> None:
    monkeypatch.setattr(
        "schedules.discover.extract_page_texts",
        lambda _bytes: ["Closed every 4th Thursday"],
    )
    classified = classify_pdf(
        _link(29804, "RossiPool_Fall2026_Aug16toDec10"),
        pool_slug="rossi-pool",
        pdf_bytes=_pdf_bytes(),
        filename="RossiPool_Fall2026_Aug16toDec10.pdf",
    )
    assert classified.kind == "session_grid"


def test_rossian_does_not_match_rossi() -> None:
    classified = classify_pdf(
        _link(1, "Rossian Pool Fall 2026"),
        pool_slug="rossi-pool",
        pdf_bytes=_pdf_bytes(),
        filename="Rossian Pool Fall 2026.pdf",
    )
    assert classified.kind == "other"


def test_mlk_pt2_is_session_grid() -> None:
    classified = classify_pdf(
        _link(29803, "MLK Pool_Fall2026_pt2_Sep27_Dec12"),
        pool_slug="martin-luther-king-jr-pool",
        pdf_bytes=_pdf_bytes(),
        filename="MLK Pool_Fall2026_pt2_Sep27_Dec12.pdf",
    )
    assert classified.kind == "session_grid"


def test_closure_notice_wins_over_weekday_grid_header(monkeypatch) -> None:
    monkeypatch.setattr(
        "schedules.discover.extract_page_texts",
        lambda _bytes: ["Monday Tuesday Wednesday Thursday Friday"],
    )
    classified = classify_pdf(
        _link(29808, "Garfield Pool Maintenance Closure 8-14_9-7 2026"),
        pool_slug="garfield-pool",
        pdf_bytes=_pdf_bytes(),
        filename="Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
    )
    assert classified.kind == "closure_notice"


def test_choose_roll_adopts_unique_table_grid() -> None:
    entry = _entry("hamilton-pool", view_id=29599)
    decision = choose_roll(
        entry, [_classified(29800, "session_grid", text="Hamilton Pool Fall 2026")]
    )
    assert decision.action == "adopt"
    assert decision.blocking is False
    assert decision.new_url == "https://sfrecpark.org/DocumentCenter/View/29800"


def test_choose_roll_flags_unique_table_grid_without_page_header() -> None:
    entry = _entry("hamilton-pool", view_id=29599)
    decision = choose_roll(
        entry,
        [
            _classified(
                29800,
                "session_grid",
                text="Hamilton Pool Fall 2026",
                grid_confirmed=False,
            )
        ],
    )
    assert decision.action == "flag"
    assert decision.reason == "no_grid_header"
    assert decision.blocking is True
    assert decision.new_url is None


def test_choose_roll_unchanged_when_same_id() -> None:
    entry = _entry("hamilton-pool", view_id=29800)
    decision = choose_roll(entry, [_classified(29800, "session_grid")])
    assert decision.action == "unchanged"
    assert decision.blocking is False


def test_choose_roll_flags_split_and_signals_missing_status() -> None:
    entry = _entry("north-beach-pool", view_id=29778)
    decision = choose_roll(
        entry,
        [
            _classified(29778, "split_part", text="North Beach Cool Pool"),
            _classified(29779, "split_part", text="North Beach Warm Pool"),
        ],
    )
    assert decision.action == "flag"
    assert decision.reason == "split_part"
    assert decision.blocking is True
    assert decision.new_url is None


def test_choose_roll_multiple_windows_leave_published() -> None:
    entry = _entry("sava-pool", view_id=29571)
    decision = choose_roll(
        entry,
        [
            _classified(29815, "session_grid", source="table"),
            _classified(29805, "session_grid", source="band"),
        ],
    )
    assert decision.action == "flag"
    assert decision.reason == "multiple_windows"
    assert decision.blocking is True
    assert decision.extra_candidates == ()
    assert {item.link.view_id for item in decision.candidates} == {29815, 29805}
    assert entry.source_status == "published"


def test_choose_roll_mlk_pt1_pt2_flags_multiple_windows_leaves_published() -> None:
    entry = _entry("martin-luther-king-jr-pool", view_id=29578)
    decision = choose_roll(
        entry,
        [
            _classified(
                29802,
                "session_grid",
                text="MLK Pool_Fall2026_pt1",
                source="table",
            ),
            _classified(
                29803,
                "session_grid",
                text="MLK Pool_Fall2026_pt2",
                source="band",
            ),
        ],
    )
    assert decision.action == "flag"
    assert decision.reason == "multiple_windows"
    assert decision.blocking is True
    assert decision.new_url is None
    assert entry.source_status == "published"


def test_choose_roll_flags_band_only() -> None:
    entry = _entry("garfield-pool", view_id=29564)
    decision = choose_roll(
        entry,
        [
            _classified(29808, "closure_notice", source="table"),
            _classified(29799, "session_grid", source="band"),
        ],
    )
    assert decision.action == "flag"
    assert decision.reason == "band_session_grid"
    assert decision.blocking is True


def test_choose_roll_unchanged_when_current_is_classified_session_grid() -> None:
    entry = _entry("garfield-pool", view_id=29799)
    flyer = _classified(29808, "closure_notice", source="table")
    grid = _classified(29799, "session_grid", source="band")
    decision = choose_roll(entry, [flyer, grid])
    assert decision.action == "unchanged"
    assert decision.blocking is False
    assert [item.link.view_id for item in decision.extra_candidates] == [29808]
    assert all(item.kind != "session_grid" for item in decision.extra_candidates)


def test_choose_roll_flags_when_not_published() -> None:
    entry = _entry("north-beach-pool", view_id=29778, status="missing_current_schedule")
    decision = choose_roll(
        entry,
        [
            _classified(29778, "split_part"),
            _classified(29779, "split_part"),
        ],
    )
    assert decision.action == "flag"
    assert decision.blocking is True
    assert decision.new_url is None


def test_choose_roll_empty_table() -> None:
    entry = _entry("hamilton-pool", view_id=29599)
    decision = choose_roll(entry, [])
    assert decision.action == "flag"
    assert decision.reason == "empty_table"
    assert decision.blocking is True


def test_persisted_band_ids_reads_flag_and_adopt_not_extra() -> None:
    notes = (
        "discover: 2026-08-19 flag closure_notice "
        "id=29808:closure_notice:table band_session_grid id=29799:session_grid:band\n\n"
        "human note"
    )
    assert persisted_band_ids(notes) == frozenset({29799})
    extra = "discover: 2026-08-19 extra id=29808:closure_notice:table"
    assert persisted_band_ids(extra) == frozenset()
    adopt = (
        "discover: 2026-08-19 adopt session_grid "
        "band_session_grid id=29799:session_grid:persisted"
    )
    assert persisted_band_ids(adopt) == frozenset({29799})


def test_selection_is_exactly_nine_rec_park_pools() -> None:
    slugs = [entry.slug for entry in rec_park_entries(load_registry(FIXTURE_REGISTRY))]
    assert slugs == REC_PARK_SLUGS
    assert "bay-club-gateway" not in slugs


def test_apply_flag_hamilton_inserts_notes_after_official_page_url(
    tmp_path, monkeypatch
) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="hamilton-pool",
        action="flag",
        old_url="https://sfrecpark.org/DocumentCenter/View/29599",
        new_url=None,
        kind="closure_notice",
        reason="empty_table",
        candidates=(),
        extra_candidates=(),
        blocking=True,
    )
    apply_discover_decision(path, decision)
    text = path.read_text()
    assert (
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Hamilton-Pool-215"\n'
        'notes = """\n'
        "discover: 2026-08-19 flag empty_table\n"
        '"""'
    ) in text
    loaded = load_registry(path)
    hamilton = next(entry for entry in loaded if entry.slug == "hamilton-pool")
    coffman = next(entry for entry in loaded if entry.slug == "coffman-pool")
    assert hamilton.notes is not None and hamilton.notes.startswith(
        "discover: 2026-08-19 flag empty_table"
    )
    assert hamilton.pdf_url.endswith("/29599")
    assert coffman.pdf_url.endswith("/29563")
    assert coffman.notes is None


def test_apply_adopt_hamilton_rewrites_pdf_url(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="hamilton-pool",
        action="adopt",
        old_url="https://sfrecpark.org/DocumentCenter/View/29599",
        new_url="https://sfrecpark.org/DocumentCenter/View/29800",
        kind="session_grid",
        reason="session_grid",
        candidates=(_classified(29800, "session_grid"),),
        extra_candidates=(),
        blocking=False,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    hamilton = next(entry for entry in loaded if entry.slug == "hamilton-pool")
    mission = next(entry for entry in loaded if entry.slug == "mission-community-pool")
    assert hamilton.pdf_url.endswith("/29800")
    assert hamilton.notes is None
    assert hamilton.source_status == "published"
    assert mission.pdf_url.endswith("/29566")


def test_apply_north_beach_converts_single_line_notes(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    original = next(
        entry for entry in load_registry(path) if entry.slug == "north-beach-pool"
    )
    decision = DiscoverDecision(
        slug="north-beach-pool",
        action="flag",
        old_url=original.pdf_url,
        new_url=None,
        kind="split_part",
        reason="split_part",
        candidates=(
            _classified(29778, "split_part", text="Cool Pool"),
            _classified(29779, "split_part", text="Warm Pool"),
        ),
        extra_candidates=(),
        blocking=True,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    north = next(entry for entry in loaded if entry.slug == "north-beach-pool")
    assert north.source_status == "missing_current_schedule"
    assert north.pdf_url.endswith("/29778")
    assert north.notes is not None
    assert north.notes.startswith("discover: 2026-08-19 flag split_part")
    assert "id=29778:split_part:table" in north.notes
    assert "id=29779:split_part:table" in north.notes
    assert "Official page split the current North Beach" in north.notes
    assert 'notes = """' in path.read_text()


def test_apply_two_window_flag_leaves_published(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="sava-pool",
        action="flag",
        old_url="https://sfrecpark.org/DocumentCenter/View/29571",
        new_url=None,
        kind="session_grid",
        reason="multiple_windows",
        candidates=(
            _classified(29815, "session_grid", source="table"),
            _classified(29805, "session_grid", source="band"),
        ),
        extra_candidates=(),
        blocking=True,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    sava = next(entry for entry in loaded if entry.slug == "sava-pool")
    assert sava.source_status == "published"
    assert sava.pdf_url.endswith("/29571")
    assert sava.notes is not None
    assert "multiple_windows" in sava.notes
    assert "id=29815:session_grid:table" in sava.notes
    assert "id=29805:session_grid:band" in sava.notes
    assert " extra " not in sava.notes


def test_apply_split_part_sets_missing_current_schedule(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="north-beach-pool",
        action="flag",
        old_url="https://sfrecpark.org/DocumentCenter/View/29778",
        new_url=None,
        kind="split_part",
        reason="split_part",
        candidates=(_classified(29778, "split_part", text="North Beach Cool Pool"),),
        extra_candidates=(),
        blocking=True,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    north = next(entry for entry in loaded if entry.slug == "north-beach-pool")
    assert north.source_status == "missing_current_schedule"
    assert north.pdf_url.endswith("/29778")


def test_adopt_session_grid_sets_published(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="north-beach-pool",
        action="adopt",
        old_url="https://sfrecpark.org/DocumentCenter/View/29778",
        new_url="https://sfrecpark.org/DocumentCenter/View/29800",
        kind="session_grid",
        reason="operator_adopt",
        candidates=(_classified(29800, "session_grid"),),
        extra_candidates=(),
        blocking=False,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    north = next(entry for entry in loaded if entry.slug == "north-beach-pool")
    assert north.source_status == "published"
    assert north.pdf_url.endswith("/29800")
    assert north.notes is not None
    assert not north.notes.startswith("discover:")


def test_adopt_split_part_does_not_set_published(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="north-beach-pool",
        action="adopt",
        old_url="https://sfrecpark.org/DocumentCenter/View/29778",
        new_url="https://sfrecpark.org/DocumentCenter/View/29778",
        kind="split_part",
        reason="operator_adopt",
        candidates=(_classified(29778, "split_part"),),
        extra_candidates=(),
        blocking=False,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    north = next(entry for entry in loaded if entry.slug == "north-beach-pool")
    assert north.source_status == "missing_current_schedule"
    assert north.pdf_url.endswith("/29778")


def test_adopt_split_part_on_published_sets_missing(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    path = _copy_registry(tmp_path)
    decision = DiscoverDecision(
        slug="hamilton-pool",
        action="adopt",
        old_url="https://sfrecpark.org/DocumentCenter/View/29599",
        new_url="https://sfrecpark.org/DocumentCenter/View/29778",
        kind="split_part",
        reason="operator_adopt",
        candidates=(_classified(29778, "split_part", text="Cool Pool"),),
        extra_candidates=(),
        blocking=False,
    )
    apply_discover_decision(path, decision)
    loaded = load_registry(path)
    hamilton = next(entry for entry in loaded if entry.slug == "hamilton-pool")
    assert hamilton.source_status == "missing_current_schedule"
    assert hamilton.pdf_url.endswith("/29778")


def test_rewrite_registry_pdf_url(tmp_path) -> None:
    path = _copy_registry(tmp_path)
    rewrite_registry_pdf_url(
        path, "hamilton-pool", "https://sfrecpark.org/DocumentCenter/View/29800"
    )
    loaded = load_registry(path)
    hamilton = next(entry for entry in loaded if entry.slug == "hamilton-pool")
    assert hamilton.pdf_url.endswith("/29800")


def test_machine_line_upsert_is_idempotent_ignoring_date(tmp_path, monkeypatch) -> None:
    path = _copy_registry(tmp_path)
    text = path.read_text()
    text = text.replace(
        'slug = "garfield-pool"\npdf_url = "https://sfrecpark.org/DocumentCenter/View/29564"\n'
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214"\n',
        'slug = "garfield-pool"\npdf_url = "https://sfrecpark.org/DocumentCenter/View/29564"\n'
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214"\n'
        'notes = """\n'
        "discover: 2026-08-01 flag closure_notice id=29808:closure_notice:table "
        "band_session_grid id=29799:session_grid:band\n"
        '"""\n',
    )
    path.write_text(text)
    _freeze_today(monkeypatch)
    decision = DiscoverDecision(
        slug="garfield-pool",
        action="flag",
        old_url="https://sfrecpark.org/DocumentCenter/View/29564",
        new_url=None,
        kind="session_grid",
        reason="closure_notice",
        candidates=(
            _classified(29808, "closure_notice", source="table"),
            _classified(29799, "session_grid", source="band"),
        ),
        extra_candidates=(),
        blocking=True,
    )
    apply_discover_decision(path, decision)
    notes = next(
        entry for entry in load_registry(path) if entry.slug == "garfield-pool"
    ).notes
    assert notes is not None
    assert notes.startswith("discover: 2026-08-01 flag closure_notice")


def test_discover_all_hamilton_adopts(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "hamilton-pool")
    pages = {entry.official_page_url: _fixture("hamilton-one-grid.html")}
    views = {
        29800: {
            "filename": "Hamilton Pool _ Fall 2026 _ August 18 to December 12.pdf",
            "content": _grid_pdf(),
        },
        29599: {
            "filename": "Hamilton Pool Summer 2026.pdf",
            "content": _grid_pdf(),
        },
    }
    seen, requested = _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [entry],
        dry_run=False,
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert seen["headers"]["User-Agent"] == BOT_USER_AGENT
    assert [item.slug for item in decisions] == ["hamilton-pool"]
    assert decisions[0].action == "adopt"
    loaded = load_registry(registry)
    hamilton = next(item for item in loaded if item.slug == "hamilton-pool")
    assert hamilton.pdf_url.endswith("/29800")
    assert not any(
        url.endswith("/19019") or url.endswith("/19020") for url in requested
    )


def test_discover_all_north_beach_flags_without_url_write(
    tmp_path, monkeypatch
) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "north-beach-pool")
    pages = {entry.official_page_url: _fixture("north-beach-two-grids.html")}
    views = {
        29778: {
            "filename": "North Beach Cool Pool Fall 2026.pdf",
            "content": _pdf_bytes(),
        },
        29779: {
            "filename": "North Beach Warm Pool Fall 2026.pdf",
            "content": _pdf_bytes(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    before = entry.pdf_url
    decisions = discover_all(
        [entry],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert decisions[0].action == "flag"
    assert decisions[0].kind == "split_part"
    loaded = next(
        item for item in load_registry(registry) if item.slug == "north-beach-pool"
    )
    assert loaded.pdf_url == before
    assert loaded.source_status == "missing_current_schedule"


def test_discover_all_sava_two_windows_flag_not_extra(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    sava = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "sava-pool")
    north = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "north-beach-pool")
    pages = {
        sava.official_page_url: _fixture("sava-two-session-grids.html"),
        north.official_page_url: _fixture("empty-table.html"),
    }
    views = {
        29815: {
            "filename": "Sava_Pool_Fall12026_Aug18toDec26_.pdf",
            "content": _pdf_bytes(),
        },
        29805: {"filename": "Sava Pool Fall 2 2026.pdf", "content": _pdf_bytes()},
        29571: {"filename": "Sava Pool Summer 2026.pdf", "content": _pdf_bytes()},
        29778: {"filename": "North Beach Cool Pool.pdf", "content": _pdf_bytes()},
    }
    _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [north, sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
        slugs=["sava-pool"],
    )
    assert [item.slug for item in decisions] == ["sava-pool"]
    decision = decisions[0]
    assert decision.action == "flag"
    assert decision.reason == "multiple_windows"
    assert {
        item.link.view_id for item in decision.candidates if item.kind == "session_grid"
    } == {
        29815,
        29805,
    }
    assert all(item.kind != "session_grid" for item in decision.extra_candidates)
    assert all(item.link.view_id != 29805 for item in decision.extra_candidates)
    loaded = next(item for item in load_registry(registry) if item.slug == "sava-pool")
    assert loaded.source_status == "published"
    assert loaded.pdf_url.endswith("/29571")
    assert "id=29805:session_grid:band" in (loaded.notes or "")
    assert " extra " not in (loaded.notes or "")


def test_only_sava_still_uses_global_band_and_does_not_adopt_fall1(
    tmp_path, monkeypatch
) -> None:
    """--only sava-pool must still see band 29805 (Fall 2) from the global max_id."""
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    sava = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "sava-pool")
    pages = {sava.official_page_url: _fixture("sava-two-session-grids.html")}
    views = {
        29815: {
            "filename": "Sava_Pool_Fall12026_Aug18toDec26_.pdf",
            "content": _pdf_bytes(),
        },
        29805: {"filename": "Sava Pool Fall 2 2026.pdf", "content": _pdf_bytes()},
        29571: {"filename": "Sava Pool Summer 2026.pdf", "content": _pdf_bytes()},
        29778: {"filename": "North Beach Cool Pool.pdf", "content": _pdf_bytes()},
    }
    requested: list[str] = []
    _install_http(monkeypatch, pages=pages, views=views, requested=requested)
    decisions = discover_all(
        [sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
        slugs=["sava-pool"],
    )
    view_ids = [
        int(match.group(1)) for url in requested if (match := VIEW_ID_RE.search(url))
    ]
    assert 29805 in view_ids
    assert [item.slug for item in decisions] == ["sava-pool"]
    assert decisions[0].action == "flag"
    assert decisions[0].reason == "multiple_windows"
    assert {
        item.link.view_id for item in decisions[0].candidates if item.kind == "session_grid"
    } == {29815, 29805}
    loaded = next(item for item in load_registry(registry) if item.slug == "sava-pool")
    assert loaded.pdf_url.endswith("/29571")
    assert loaded.source_status == "published"


def test_discover_all_garfield_flyer_flags_unchanged_url(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "garfield-pool")
    pages = {entry.official_page_url: _fixture("garfield-flyer-only.html")}
    views = {
        29808: {
            "filename": "Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
            "content": _pdf_bytes(),
        },
        29564: {
            "filename": "Garfield Pool Summer 2026.pdf",
            "content": _grid_pdf(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [entry],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert decisions[0].action == "flag"
    assert decisions[0].kind == "closure_notice"
    assert decisions[0].blocking is True
    loaded = next(
        item for item in load_registry(registry) if item.slug == "garfield-pool"
    )
    assert loaded.pdf_url.endswith("/29564")
    assert loaded.source_status == "published"


def test_discover_all_empty_table_flags(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "hamilton-pool")
    pages = {entry.official_page_url: _fixture("empty-table.html")}
    views = {
        29599: {
            "filename": "Hamilton Pool Summer 2026.pdf",
            "content": _grid_pdf(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [entry],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert decisions[0].reason == "empty_table"
    loaded = next(
        item for item in load_registry(registry) if item.slug == "hamilton-pool"
    )
    assert loaded.pdf_url.endswith("/29599")


def test_band_walks_full_window_without_404_stop(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    north = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "north-beach-pool")
    garfield = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "garfield-pool")
    sava = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "sava-pool")
    requested: list[str] = []
    views = {
        29779: {"filename": "unrelated.pdf", "content": _pdf_bytes()},
        29785: {
            "type": "image/jpeg",
            "content": b"\xff\xd8\xff",
            "filename": "not-a-pool.jpg",
        },
        29799: {
            "filename": "Garfield Pool Fall 2026 Schedule.pdf",
            "content": _pdf_bytes(),
        },
        29805: {
            "filename": "Sava Pool Fall 2026 Schedule.pdf",
            "content": _pdf_bytes(),
        },
        29778: {"filename": "North Beach Cool Pool.pdf", "content": _pdf_bytes()},
        29564: {"filename": "Garfield Pool Summer.pdf", "content": _pdf_bytes()},
        29571: {"filename": "Sava Pool Summer.pdf", "content": _pdf_bytes()},
    }
    _install_http(monkeypatch, views=views, requested=requested)
    decisions = discover_all(
        [north, garfield, sava],
        dry_run=True,
        delay=0,
        registry_path=tmp_path / "unused.toml",
        report_dir=tmp_path,
    )
    view_ids = []
    for url in requested:
        match = VIEW_ID_RE.search(url)
        if match:
            view_ids.append(int(match.group(1)))
    window = set(range(29779, 29819))
    assert window.issubset(set(view_ids))
    assert 29799 in view_ids
    assert 29805 in view_ids
    by_slug = {item.slug: item for item in decisions}
    assert by_slug["garfield-pool"].action == "flag"
    assert by_slug["garfield-pool"].reason == "band_session_grid"
    assert any(
        item.link.view_id == 29799 for item in by_slug["garfield-pool"].candidates
    )
    assert by_slug["sava-pool"].action == "flag"
    assert any(item.link.view_id == 29805 for item in by_slug["sava-pool"].candidates)


def test_persist_after_max_jump(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    text = registry.read_text()
    text = text.replace(
        'pdf_url = "https://sfrecpark.org/DocumentCenter/View/29571"',
        'pdf_url = "https://sfrecpark.org/DocumentCenter/View/29815"',
    )
    text = text.replace(
        'slug = "garfield-pool"\npdf_url = "https://sfrecpark.org/DocumentCenter/View/29564"\n'
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214"\n',
        'slug = "garfield-pool"\npdf_url = "https://sfrecpark.org/DocumentCenter/View/29564"\n'
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214"\n'
        'notes = """\n'
        "discover: 2026-08-19 flag closure_notice id=29808:closure_notice:table "
        "band_session_grid id=29799:session_grid:band\n"
        '"""\n',
    )
    registry.write_text(text)
    loaded = load_registry(registry)
    garfield = next(item for item in loaded if item.slug == "garfield-pool")
    sava = next(item for item in loaded if item.slug == "sava-pool")
    assert sava.pdf_url.endswith("/29815")
    assert 29799 in persisted_band_ids(garfield.notes)
    pages = {
        garfield.official_page_url: _fixture("garfield-flyer-only.html"),
        sava.official_page_url: _fixture("sava-two-session-grids.html"),
    }
    views = {
        29799: {
            "filename": "Garfield Pool Fall 2026 Schedule.pdf",
            "content": _pdf_bytes(),
        },
        29808: {
            "filename": "Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
            "content": _pdf_bytes(),
        },
        29815: {
            "filename": "Sava_Pool_Fall12026_Aug18toDec26_.pdf",
            "content": _pdf_bytes(),
        },
        29564: {"filename": "Garfield Pool Summer.pdf", "content": _pdf_bytes()},
    }
    requested: list[str] = []
    _install_http(monkeypatch, pages=pages, views=views, requested=requested)
    decisions = discover_all(
        [garfield, sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    view_ids = [
        int(match.group(1)) for url in requested if (match := VIEW_ID_RE.search(url))
    ]
    assert 29799 in view_ids
    window = set(range(29816, 29856))
    assert window.issubset(set(view_ids))
    assert 29798 not in window
    garfield_decision = next(item for item in decisions if item.slug == "garfield-pool")
    assert garfield_decision.action == "flag"
    assert any(item.link.view_id == 29799 for item in garfield_decision.candidates)
    reloaded = next(
        item for item in load_registry(registry) if item.slug == "garfield-pool"
    )
    assert "id=29799:session_grid:" in (reloaded.notes or "")


def test_non_pdf_200_is_not_a_candidate(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "garfield-pool")
    views = {
        29570: {
            "type": "image/jpeg",
            "content": b"\xff\xd8\xff",
            "filename": "Garfield Pool Fall.jpg",
        },
        29564: {"filename": "Garfield Pool Summer.pdf", "content": _pdf_bytes()},
    }
    requested: list[str] = []
    _install_http(monkeypatch, views=views, requested=requested)
    decisions = discover_all(
        [entry],
        dry_run=True,
        delay=0,
        registry_path=tmp_path / "unused.toml",
        report_dir=tmp_path,
    )
    view_ids = [
        int(match.group(1)) for url in requested if (match := VIEW_ID_RE.search(url))
    ]
    assert 29570 in view_ids
    assert 29604 in view_ids  # max 29564 + 40; JPEG 200 must not stop the walk
    assert not any(item.link.view_id == 29570 for item in decisions[0].candidates)


def test_discover_all_excludes_bay_club(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    requested: list[str] = []
    _install_http(monkeypatch, requested=requested)
    decisions = discover_all(
        load_registry(FIXTURE_REGISTRY),
        dry_run=True,
        delay=0,
        registry_path=tmp_path / "unused.toml",
        report_dir=tmp_path,
    )
    assert [item.slug for item in decisions] == REC_PARK_SLUGS
    assert not any("bayclubs.com" in url for url in requested)
    assert not any("bay-club" in url for url in requested)


def test_discover_all_hard_error_when_every_page_fails(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "hamilton-pool")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            request = httpx.Request("GET", url)
            return httpx.Response(500, content=b"nope", request=request)

    monkeypatch.setattr("schedules.discover.httpx.Client", FakeClient)
    with pytest.raises(DiscoverError, match="every Rec & Park"):
        discover_all(
            [entry],
            dry_run=True,
            delay=0,
            registry_path=tmp_path / "unused.toml",
            report_dir=tmp_path,
        )
    assert (tmp_path / "discovery-report.md").exists()
    assert (tmp_path / "discovery-decisions.json").exists()


def test_discover_all_operator_adopt(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    sava = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "sava-pool")
    pages = {sava.official_page_url: _fixture("sava-two-session-grids.html")}
    views = {
        29815: {
            "filename": "Sava_Pool_Fall12026_Aug18toDec26_.pdf",
            "content": _pdf_bytes(),
        },
        29805: {"filename": "Sava Pool Fall 2 2026.pdf", "content": _pdf_bytes()},
        29571: {"filename": "Sava Pool Summer.pdf", "content": _pdf_bytes()},
    }
    _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
        adopt=("sava-pool", 29815),
    )
    assert decisions[0].action == "adopt"
    assert decisions[0].kind == "session_grid"
    loaded = next(item for item in load_registry(registry) if item.slug == "sava-pool")
    assert loaded.pdf_url.endswith("/29815")
    assert loaded.source_status == "published"


def test_dry_run_does_not_write_registry(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    before = registry.read_text()
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "hamilton-pool")
    pages = {entry.official_page_url: _fixture("hamilton-one-grid.html")}
    views = {
        29800: {"filename": "Hamilton Pool Fall 2026.pdf", "content": _grid_pdf()},
        29599: {"filename": "Hamilton Pool Summer.pdf", "content": _grid_pdf()},
    }
    _install_http(monkeypatch, pages=pages, views=views)
    discover_all(
        [entry],
        dry_run=True,
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert registry.read_text() == before
    assert (tmp_path / "discovery-report.md").exists()


def test_cli_discover_blocking(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("schedules.cli.TMP_DIR", tmp_path)
    (tmp_path / "discovery-decisions.json").write_text(
        json.dumps(
            [
                {"slug": "sava-pool", "blocking": True},
                {"slug": "hamilton-pool", "blocking": False},
                {"slug": "garfield-pool", "blocking": True},
            ]
        )
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["discover-blocking"])
    assert result.exit_code == 0
    assert result.output.splitlines() == ["sava-pool", "garfield-pool"]


def test_cli_discover_blocking_errors_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("schedules.cli.TMP_DIR", tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["discover-blocking"])
    assert result.exit_code == 1
    assert "discovery-decisions.json is missing" in result.output


def test_cli_discover_blocking_empty_when_no_flags(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("schedules.cli.TMP_DIR", tmp_path)
    (tmp_path / "discovery-decisions.json").write_text(
        json.dumps([{"slug": "hamilton-pool", "blocking": False}])
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["discover-blocking"])
    assert result.exit_code == 0
    assert result.output == ""


def test_discover_all_hamilton_without_grid_header_does_not_adopt(
    tmp_path, monkeypatch
) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "hamilton-pool")
    pages = {entry.official_page_url: _fixture("hamilton-one-grid.html")}
    views = {
        29800: {
            "filename": "Hamilton Pool _ Fall 2026 _ August 18 to December 12.pdf",
            "content": _pdf_bytes(),
        },
        29599: {
            "filename": "Hamilton Pool Summer 2026.pdf",
            "content": _pdf_bytes(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [entry],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert decisions[0].action == "flag"
    assert decisions[0].reason == "no_grid_header"
    loaded = next(
        item for item in load_registry(registry) if item.slug == "hamilton-pool"
    )
    assert loaded.pdf_url.endswith("/29599")


def test_adopt_band_only_then_flyer_table_is_unchanged(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    text = registry.read_text()
    text = text.replace(
        'pdf_url = "https://sfrecpark.org/DocumentCenter/View/29571"',
        'pdf_url = "https://sfrecpark.org/DocumentCenter/View/29815"',
    )
    registry.write_text(text)
    loaded = load_registry(registry)
    garfield = next(item for item in loaded if item.slug == "garfield-pool")
    sava = next(item for item in loaded if item.slug == "sava-pool")
    pages = {
        garfield.official_page_url: _fixture("garfield-flyer-only.html"),
        sava.official_page_url: _fixture("sava-two-session-grids.html"),
    }
    views = {
        29564: {
            "filename": "Garfield Pool Summer 2026.pdf",
            "content": _grid_pdf(),
        },
        29799: {
            "filename": "Garfield Pool Fall 2026 Schedule.pdf",
            "content": _grid_pdf(),
        },
        29808: {
            "filename": "Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
            "content": _pdf_bytes(),
        },
        29815: {
            "filename": "Sava_Pool_Fall12026_Aug18toDec26_.pdf",
            "content": _grid_pdf(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    first = discover_all(
        [garfield, sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
        adopt=("garfield-pool", 29799),
    )
    by_slug = {item.slug: item for item in first}
    assert by_slug["garfield-pool"].action == "adopt"
    after_adopt = load_registry(registry)
    garfield = next(item for item in after_adopt if item.slug == "garfield-pool")
    sava = next(item for item in after_adopt if item.slug == "sava-pool")
    assert garfield.pdf_url.endswith("/29799")
    assert 29799 in persisted_band_ids(garfield.notes)

    second = discover_all(
        [garfield, sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    by_slug = {item.slug: item for item in second}
    assert by_slug["garfield-pool"].action == "unchanged"
    assert by_slug["garfield-pool"].blocking is False
    reloaded = next(
        item for item in load_registry(registry) if item.slug == "garfield-pool"
    )
    assert reloaded.pdf_url.endswith("/29799")
    assert reloaded.source_status == "published"
    assert 29799 in persisted_band_ids(reloaded.notes)
    notes = reloaded.notes or ""
    assert "flag" not in notes.split("\n")[0]


def test_persist_kept_on_non_404_miss(tmp_path, monkeypatch) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    text = registry.read_text()
    text = text.replace(
        'pdf_url = "https://sfrecpark.org/DocumentCenter/View/29571"',
        'pdf_url = "https://sfrecpark.org/DocumentCenter/View/29815"',
    )
    text = text.replace(
        'slug = "garfield-pool"\npdf_url = "https://sfrecpark.org/DocumentCenter/View/29564"\n'
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214"\n',
        'slug = "garfield-pool"\npdf_url = "https://sfrecpark.org/DocumentCenter/View/29564"\n'
        'official_page_url = "https://sfrecpark.org/facilities/facility/details/Garfield-Pool-214"\n'
        'notes = """\n'
        "discover: 2026-08-19 flag closure_notice id=29808:closure_notice:table "
        "band_session_grid id=29799:session_grid:band\n"
        '"""\n',
    )
    registry.write_text(text)
    loaded = load_registry(registry)
    garfield = next(item for item in loaded if item.slug == "garfield-pool")
    sava = next(item for item in loaded if item.slug == "sava-pool")
    pages = {
        garfield.official_page_url: _fixture("garfield-flyer-only.html"),
        sava.official_page_url: _fixture("sava-two-session-grids.html"),
    }
    views = {
        29799: {
            "status": 500,
            "content": b"upstream error",
            "type": "text/plain",
        },
        29808: {
            "filename": "Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
            "content": _pdf_bytes(),
        },
        29815: {
            "filename": "Sava_Pool_Fall12026_Aug18toDec26_.pdf",
            "content": _grid_pdf(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    discover_all(
        [garfield, sava],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    reloaded = next(
        item for item in load_registry(registry) if item.slug == "garfield-pool"
    )
    assert "id=29799:session_grid:" in (reloaded.notes or "")


def test_adopt_slug_must_be_in_selected_slugs(tmp_path) -> None:
    entries = rec_park_entries(load_registry(FIXTURE_REGISTRY))
    with pytest.raises(DiscoverError, match="not in the selected"):
        discover_all(
            entries,
            dry_run=True,
            delay=0,
            registry_path=tmp_path / "unused.toml",
            report_dir=tmp_path,
            slugs=["hamilton-pool"],
            adopt=("sava-pool", 29815),
        )


def test_cli_adopt_must_be_in_only_slugs() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--only", "hamilton-pool", "--adopt", "sava-pool=29815"],
    )
    assert result.exit_code == 1
    assert "not in the selected" in result.output


def test_discover_all_garfield_flyer_with_weekdays_does_not_adopt(
    tmp_path, monkeypatch
) -> None:
    _freeze_today(monkeypatch)
    registry = _copy_registry(tmp_path)
    entry = next(item for item in load_registry(FIXTURE_REGISTRY) if item.slug == "garfield-pool")
    pages = {entry.official_page_url: _fixture("garfield-flyer-with-weekdays.html")}
    views = {
        29808: {
            "filename": "Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
            "content": _pdf_with_text("Monday Tuesday Wednesday Thursday Friday"),
        },
        29564: {
            "filename": "Garfield Pool Summer 2026.pdf",
            "content": _grid_pdf(),
        },
    }
    _install_http(monkeypatch, pages=pages, views=views)
    decisions = discover_all(
        [entry],
        delay=0,
        registry_path=registry,
        report_dir=tmp_path,
    )
    assert decisions[0].action != "adopt"
    assert decisions[0].kind == "closure_notice"
    assert any(
        item.link.view_id == 29808 and item.kind == "closure_notice"
        for item in decisions[0].candidates
    )
    loaded = next(
        item for item in load_registry(registry) if item.slug == "garfield-pool"
    )
    assert loaded.pdf_url.endswith("/29564")


def test_cli_discover_passes_dry_run_and_adopt(monkeypatch) -> None:
    captured: dict = {}

    def fake_discover_all(entries, *, dry_run=False, slugs=None, adopt=None, **kwargs):
        captured.update(dry_run=dry_run, slugs=slugs, adopt=adopt, n=len(entries))
        return []

    monkeypatch.setattr("schedules.cli.discover_all", fake_discover_all)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--dry-run", "--only", "sava-pool", "--adopt", "sava-pool=29815"],
    )
    assert result.exit_code == 0
    assert captured["dry_run"] is True
    assert captured["slugs"] == ["sava-pool"]
    assert captured["adopt"] == ("sava-pool", 29815)
    assert "dry-run: registry not written" in result.output
