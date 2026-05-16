"""Render-time tests for pool detail pages.

These tests run `zola build` against the real site content and inspect the
rendered HTML. They exist because templates are the last place where the
schedule schema meets the reader — a stale enum or a missing field renders
as `[object]` or `FAMILY_SWIM` and there is no Python-level test that
catches it.

Session-scoped: one `zola build` per test session; individual tests read
the already-built HTML.
"""

from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def built_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("zola") is None:
        pytest.skip("zola binary not available")
    out = tmp_path_factory.mktemp("zola-build")
    result = subprocess.run(
        ["zola", "build", "--output-dir", str(out), "--force"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"zola build failed:\n{result.stderr}"
    return out


def _read(built_site: Path, slug: str) -> str:
    return (built_site / "spots" / slug / "index.html").read_text()


def test_pool_detail_never_renders_object_literal_for_closures(built_site: Path) -> None:
    # Balboa has five closures in TOML; template used to render each as `{{ c }}`
    # which Tera prints as `[object]`. The reader must see the actual dates and
    # reasons.
    html = _read(built_site, "balboa-pool")
    assert "[object]" not in html
    assert "[object Object]" not in html
    assert "In Service Training" in html
    assert "Memorial Day" in html


def test_schedule_table_uses_current_schema_fields(built_site: Path) -> None:
    # `lanes` is not in the current schema; the column must go. Session type
    # must render as a human label, not the raw enum id. The weekly-grid render
    # uses uppercase program labels (e.g. "LAP SWIM"), so check visible text
    # case-insensitively. Raw enum ids live legitimately in the `data-schedule`
    # JSON attribute; the guard here targets the uppercase form that would
    # appear if the enum id leaked into visible text (CSS uppercases labels).
    html = _read(built_site, "balboa-pool")
    assert "<th>LANES</th>" not in html
    assert "FAMILY_SWIM" not in html
    assert "LAP_SWIM" not in html
    assert "SENIOR_SWIM" not in html
    # Human-readable labels present.
    assert "FAMILY SWIM" in html
    assert "LAP SWIM" in html


def test_weekly_grid_omits_days_without_drop_in_sessions(built_site: Path) -> None:
    html = _read(built_site, "balboa-pool")
    assert "data-day=tuesday" in html
    assert "data-day=saturday" in html
    assert "class=weekly-grid-dayhead data-day=monday" not in html
    assert "class=weekly-grid-dayhead data-day=sunday" not in html
    assert "style=--weekday-count:5" in html
    assert "NO DROP-IN HOURS MONDAY AND SUNDAY" in html


def test_open_water_item_list_sections_render(built_site: Path) -> None:
    # Hazards, clubs, and common distances share an `item_list` macro. Verify
    # each section renders with its heading, class, and list items.
    html = _read(built_site, "aquatic-park")
    assert "<h2>Hazards</h2>" in html
    assert "boat traffic outside cove" in html
    assert "<h2>Clubs</h2>" in html
    assert "South End Rowing Club" in html
    assert "<h2>Common distances</h2>" in html
    assert "1mi loop" in html


def test_open_water_empty_item_lists_are_suppressed(built_site: Path) -> None:
    # The macro must not render a section when its list is empty. Ocean Beach
    # has no clubs configured — the heading must be absent.
    html = _read(built_site, "ocean-beach")
    assert "<h2>Clubs</h2>" not in html


def test_closures_render_without_object_literal_across_all_pools(built_site: Path) -> None:
    # Defense in depth: no pool detail page should ever contain `[object]`.
    for slug_dir in (built_site / "spots").iterdir():
        if not slug_dir.is_dir():
            continue
        index = slug_dir / "index.html"
        if not index.exists():
            continue
        assert "[object]" not in index.read_text(), f"{slug_dir.name} rendered [object]"


def test_pool_meta_dates_render_in_human_format(built_site: Path) -> None:
    html = _read(built_site, "balboa-pool")
    assert "SCHEDULE EFFECTIVE FROM MAR 17, 2026 TO JUN 6, 2026" in html
    assert "SOURCE SF REC & PARKS" in html
    assert "REVIEWED" not in html
    assert "PDF REVIEWED" not in html
    assert "LAST VERIFIED" not in html
    assert html.index("recently reopened after a $9M renovation") < html.index(
        "SCHEDULE EFFECTIVE FROM MAR 17, 2026 TO JUN 6, 2026"
    )


def test_homepage_omits_trust_column(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "<th>TRUST" not in html
    assert "trust-cell" not in html
    assert "REVIEWED AGAINST SF REC & PARK PDF" not in html
    assert "NO REVIEWED DROP-IN SCHEDULE YET" not in html
    assert "NOAA/NDBC CONDITIONS UPDATED HOURLY" not in html


def test_homepage_renders_bulletin_redesign_shell(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "class=bulletin-hero" in html
    assert "<span class=red>SWIM</span> <span>SAN</span> <span class=teal>FRANCISCO.</span>" in html
    assert "class=bulletin-strip" in html
    assert "No. 00 · Live bulletin · right now" in html
    assert "BULLETIN 00" in html
    assert "BULLETIN 14" not in html
    assert "data-open-count" in html
    assert "data-conditions-updated" in html
    assert "data-sun-range" not in html


def test_bulletin_number_matches_reviewed_schedule_snapshots() -> None:
    bulletin = json.loads((ROOT / "data" / "bulletin.json").read_text())
    reviewed_paths = sorted((ROOT / "data").glob("*/*/reviewed.json"))
    digest = hashlib.sha256()
    for path in reviewed_paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    assert bulletin["reviewed_count"] == len(reviewed_paths)
    assert bulletin["schedule_fingerprint"] == digest.hexdigest()
    assert bulletin["label"] == f"{bulletin['number']:02d}"


def test_bulletin_generator_increments_when_reviewed_payload_changes(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")

    reviewed = tmp_path / "data" / "balboa-pool" / "2026-05-01-a" / "reviewed.json"
    reviewed.parent.mkdir(parents=True)
    reviewed.write_text('{"sessions":[{"day":"monday"}]}\n')

    script = ROOT / "scripts" / "generate-bulletin.mjs"

    def run_generator() -> dict[str, object]:
        result = subprocess.run(
            ["node", str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return json.loads((tmp_path / "data" / "bulletin.json").read_text())

    assert run_generator()["label"] == "00"
    assert run_generator()["label"] == "00"

    reviewed.write_text('{"sessions":[{"day":"tuesday"}]}\n')
    assert run_generator()["label"] == "01"

    another_reviewed = tmp_path / "data" / "coffman-pool" / "2026-05-02-b" / "reviewed.json"
    another_reviewed.parent.mkdir(parents=True)
    another_reviewed.write_text('{"sessions":[{"day":"wednesday"}]}\n')
    assert run_generator()["label"] == "02"


def test_homepage_preserves_redesign_dom_contract(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "OPEN NEXT" in html
    assert "OPEN FIRST" not in html
    controls_start = html.index("class=board-controls")
    menu_start = html.index("class=horizon-menu", controls_start)
    assert "data-horizon-menu" not in html[controls_start:menu_start]
    filters = html.index('class="filters control-cluster"')
    filter_group = html[filters : filters + 120]
    assert "aria-label=Filters" in filter_group
    assert "role=group" in filter_group
    spot = html.index("data-cell=spot")
    status = html.index("data-cell=status")
    next_cell = html.index("data-cell=next")
    water = html.index("data-cell=water")
    locale = html.index("data-cell=locale")
    assert spot < status < next_cell < water < locale


def test_map_page_keeps_board_hidden_and_map_visible(built_site: Path) -> None:
    html = (built_site / "map" / "index.html").read_text()
    assert "<body class=map-page>" in html
    assert "class=board hidden" in html
    assert "id=map-view hidden" not in html
    assert "js/map.js" in html


def test_field_notes_render_as_section_with_deep_dives(built_site: Path) -> None:
    html = (built_site / "field-notes" / "index.html").read_text()
    assert "FIELD NOTES." in html
    assert "class=fn-system-map" in html
    assert "data-system-title=\"Reviewed schedules\"" in html
    assert "js/field-notes.js" in html
    assert "class=fn-card" not in html
    assert "https://swimfrancisco.com/field-notes/pool-schedule-pipeline" in html
    assert "https://swimfrancisco.com/field-notes/live-conditions" in html
    assert "https://swimfrancisco.com/field-notes/map-view" in html
    assert "/how-it-works/" not in html
    assert not (built_site / "how-it-works" / "index.html").exists()


def test_field_note_page_renders_history_trail(built_site: Path) -> None:
    html = (built_site / "field-notes" / "pool-schedule-pipeline" / "index.html").read_text()
    assert "FIELD NOTE · PDFS" in html
    assert "fd28fc7, 2a0ad7c, 4a9958a, c9f9565" in html
    assert "byte-identical to the model output" in html


def test_homepage_renders_cost_badges_without_hardcoded_price(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert 'class="cost-badge is-free">Free</span>' in html
    assert 'class="cost-badge is-paid">Paid</span>' in html
    assert 'class="cost-badge is-paid">$7</span>' not in html


def test_spot_detail_uses_print_header_and_preserves_long_titles(built_site: Path) -> None:
    html = _read(built_site, "martin-luther-king-jr-pool")
    assert "class=spot-detail-head" in html
    assert "MARTIN LUTHER KING JR. <span class=accent>POOL.</span>" in html
    assert "class=bulletin-strip" in html
    assert "OFFICIAL PAGE" in html
    assert "DIRECTIONS" in html
    assert 'class="cost-badge is-paid">Paid</span>' in html


def test_footer_renders_sources_and_credit(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "Pool hours from SF Rec & Park · Open-water from NOAA + NDBC" in html
    assert "Made in San Francisco by" in html
    assert "href=/field-notes/>Field notes</a>" in html
    assert "/how-it-works/" not in html
    # Sources line above byline (sources first, byline last as the page signature).
    assert html.index("Pool hours from SF Rec & Park") < html.index("Made in San Francisco by")
