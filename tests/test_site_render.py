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

import html
import json
import hashlib
import re
import shutil
import subprocess
import tomllib
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


def _json_ld_objects(rendered_html: str) -> list[dict[str, object]]:
    scripts = re.findall(
        r"<script type=application/ld\+json>\s*(.*?)\s*</script>",
        rendered_html,
        flags=re.S,
    )
    return [json.loads(html.unescape(script)) for script in scripts]


def _locales() -> list[dict[str, object]]:
    return tomllib.loads((ROOT / "i18n" / "locales.toml").read_text())["locales"]


def _localized_url_path(locale: dict[str, object], canonical_path: str) -> str:
    code = str(locale["code"])
    return canonical_path if locale.get("is_default") else f"/{code}{canonical_path}"


def _assert_hreflang_cluster(rendered_html: str, canonical_path: str) -> None:
    for locale in _locales():
        code = str(locale["code"])
        path = _localized_url_path(locale, canonical_path)
        assert f"href=https://swimfrancisco.com{path} hreflang={code} rel=alternate" in rendered_html
    assert f"href=https://swimfrancisco.com{canonical_path} hreflang=x-default rel=alternate" in rendered_html


def _canonical_spot_extras() -> dict[str, dict[str, object]]:
    extras: dict[str, dict[str, object]] = {}
    for path in sorted((ROOT / "content" / "spots").glob("*.md")):
        if path.name.startswith("_index"):
            continue
        frontmatter = path.read_text().split("+++", 2)[1]
        extra = tomllib.loads(frontmatter)["extra"]
        if "localized_from" in extra:
            continue
        extras[path.stem] = extra
    return extras


def test_all_spots_have_access_classification() -> None:
    valid_access_modes = {"public", "limited_public", "membership", "private"}
    valid_payment_models = {"free", "session", "day_pass", "membership", "therapy", "unknown"}
    valid_schedule_bases = {
        "swim_schedule",
        "pool_hours",
        "facility_hours",
        "amenity_only",
        "temporarily_closed",
        "unknown",
    }
    for path in sorted((ROOT / "content" / "spots").glob("*.md")):
        if path.name.startswith("_index"):
            continue
        frontmatter = path.read_text().split("+++", 2)[1]
        extra = tomllib.loads(frontmatter)["extra"]
        if "localized_from" in extra:
            continue
        assert extra.get("access_mode") in valid_access_modes, path.name
        assert extra.get("payment_model") in valid_payment_models, path.name
        if extra.get("type") == "pool":
            assert extra.get("schedule_basis") in valid_schedule_bases, path.name


def test_canonical_labels_have_i18n_mappings() -> None:
    extras_by_slug = _canonical_spot_extras()
    translation_keys = set(tomllib.loads((ROOT / "i18n" / "ui" / "en.toml").read_text()))
    dynamic_labels = tomllib.loads((ROOT / "i18n" / "dynamic-labels.toml").read_text())["labels"]
    dynamic_label_source_index = {
        (str(label["kind"]), str(label["source"])): str(label["translation_key"])
        for label in dynamic_labels
    }
    dynamic_label_code_index = {
        (str(label["kind"]), str(label["code"])): str(label["translation_key"])
        for label in dynamic_labels
    }

    visible_spot_labels: set[str] = set()
    access_badges: set[str] = set()
    access_window_labels: set[str] = set()
    closure_reasons: set[str] = set()
    closure_reason_codes: set[str] = set()

    for extra in extras_by_slug.values():
        if subtype := extra.get("subtype"):
            visible_spot_labels.add(str(subtype))
        if setpoint := extra.get("setpoint_label"):
            setpoint = str(setpoint)
            if re.search(r"[A-Za-z]", setpoint) and not re.search(r"\d|°", setpoint):
                visible_spot_labels.add(setpoint)
        if access_label := extra.get("access_label"):
            access_badges.add(str(access_label))
        for key in ("access_hours", "access_exceptions"):
            for window in extra.get(key, []):
                if label := window.get("label"):
                    access_window_labels.add(str(label))
                if reason := window.get("reason"):
                    closure_reasons.add(str(reason))
                if window.get("reason_code"):
                    closure_reason_codes.add(str(window["reason_code"]))
        for closure in extra.get("closures", []):
            if reason := closure.get("reason"):
                closure_reasons.add(str(reason))
            if closure.get("reason_code"):
                closure_reason_codes.add(str(closure["reason_code"]))

    for label in visible_spot_labels | access_badges:
        assert ("spot_label", label) in dynamic_label_source_index
    for label in access_window_labels:
        assert ("access_window", label) in dynamic_label_source_index
    for reason in closure_reasons:
        assert ("closure_reason", reason) in dynamic_label_source_index
    for code in closure_reason_codes:
        assert ("closure_reason", code) in dynamic_label_code_index

    assert set(dynamic_label_source_index.values()) <= translation_keys
    assert set(dynamic_label_code_index.values()) <= translation_keys


def test_js_translation_keys_are_exported_to_runtime_payload() -> None:
    translation_keys = set(tomllib.loads((ROOT / "i18n" / "ui" / "en.toml").read_text()))
    base = (ROOT / "templates" / "base.html").read_text()
    assert 'load_data(path="data/i18n/" ~ lang ~ ".json")' in base
    assert 'load_data(path="data/i18n/dynamic-labels.json")' in base
    exported_keys = set(json.loads((ROOT / "data" / "i18n" / "en.json").read_text()))
    assert exported_keys <= translation_keys

    js_sources = "\n".join(
        path.read_text()
        for pattern in ("*.js", "*.mjs")
        for path in (ROOT / "static" / "js").rglob(pattern)
    )
    runtime_i18n = (ROOT / "static" / "js" / "helpers" / "i18n.mjs").read_text()
    status_js = (ROOT / "static" / "js" / "status.js").read_text()

    used_translation_keys = set(re.findall(r'(?<![A-Za-z0-9_$])t\("([^"]+)"', js_sources))
    used_translation_keys.update(set(re.findall(r'"([a-z][a-z0-9_]+)"', runtime_i18n)) & translation_keys)
    used_translation_keys.update(
        key
        for key in re.findall(r'"([a-z][a-z0-9_]+)"', status_js)
        if key.startswith("horizon_") or key == "now"
    )
    assert used_translation_keys <= exported_keys


def test_localized_section_files_match_i18n_catalogs() -> None:
    targets = {
        "home": ROOT / "content" / "_index",
        "map": ROOT / "content" / "map" / "_index",
        "spots": ROOT / "content" / "spots" / "_index",
    }
    locale_data = tomllib.loads((ROOT / "i18n" / "locales.toml").read_text())["locales"]
    for locale in locale_data:
        code = locale["code"]
        if locale.get("is_default"):
            continue
        sections = tomllib.loads((ROOT / "i18n" / "sections" / f"{code}.toml").read_text())["sections"]
        assert set(sections) == set(targets)
        for key, path in targets.items():
            frontmatter = Path(f"{path}.{code}.md").read_text().split("+++", 2)[1]
            assert tomllib.loads(frontmatter) == sections[key]


def test_pool_detail_never_renders_object_literal_for_closures(built_site: Path) -> None:
    # Balboa has closures in TOML; template used to render each as `{{ c }}`
    # which Tera prints as `[object]`. The reader must see the actual dates and
    # reasons.
    html = _read(built_site, "balboa-pool")
    assert "[object]" not in html
    assert "[object Object]" not in html
    assert "Juneteenth" in html
    assert "Independence Day" in html


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
    assert "Tue / Thu / Sat 09:00-18:00 Jun-Nov; 08:00-17:00 Dec-May" in html
    assert "Mon / Wed / Fri 08:00-17:00 May-Oct" in html
    assert "$12 cash/check or $12.67 card" in html
    assert "<h2>Common distances</h2>" in html
    assert "1mi loop" in html


def test_localized_spot_pages_store_translated_markdown(built_site: Path) -> None:
    aquatic = (built_site / "es" / "spots" / "aquatic-park" / "index.html").read_text()
    assert "<title>Aquatic Park condiciones de aguas abiertas y acceso — Swim Francisco</title>" in aquatic
    assert "Natación en aguas abiertas en Aquatic Park, San Francisco: Cala protegida" in aquatic
    assert "<p class=description>Cala protegida en la ribera norte" in aquatic
    assert "La cala y la playa de Aquatic Park son públicas y gratuitas" in aquatic
    assert "Cala pública" in aquatic
    assert "tráfico de embarcaciones fuera de la cala" in aquatic
    assert "0,25 mi hasta el rompeolas" in aquatic
    assert "Aquatic Park es una cala protegida" in aquatic
    assert "principal lugar de entrenamiento de aguas abiertas" in aquatic
    assert "The Aquatic Park cove and beach are public and free" not in aquatic
    assert "boat traffic outside cove" not in aquatic

    aquatic_objects = _json_ld_objects(aquatic)
    aquatic_place = next(obj for obj in aquatic_objects if obj["@type"] == "Beach")
    assert aquatic_place["url"] == "https://swimfrancisco.com/es/spots/aquatic-park/"
    assert aquatic_place["inLanguage"] == "es"
    assert str(aquatic_place["description"]).startswith("Natación en aguas abiertas")

    baker = (built_site / "es" / "spots" / "baker-beach" / "index.html").read_text()
    assert "corrientes de resaca" in baker
    assert "large shore break" not in baker

    garfield = (built_site / "es" / "spots" / "garfield-pool" / "index.html").read_text()
    assert "<title>Garfield Pool horario de natación y acceso — Swim Francisco</title>" in garfield
    assert "El horario empieza 7/6/2026" in garfield
    assert "SIN HORARIO SIN CITA VIERNES Y SÁBADO" in garfield

    mission = (built_site / "es" / "spots" / "mission-community-pool" / "index.html").read_text()
    assert "Capacitación del personal" in mission

    potrero = (built_site / "es" / "spots" / "24-hour-fitness-potrero" / "index.html").read_text()
    assert "piscina cubierta de carriles" in potrero
    assert "Usa la página del club para membresía" in potrero
    assert "Gym pool access" not in potrero

    chinatown = (built_site / "es" / "spots" / "chinatown-ymca" / "index.html").read_text()
    assert "HORARIO DE FERIADO DE LA INSTALACIÓN" in chinatown
    assert "AGUA SALADA" in chinatown
    assert "AGUA AGUA SALADA" not in chinatown
    assert "HOLIDAY FACILITY HOURS" not in chinatown

    city_sports = (built_site / "es" / "spots" / "city-sports-20th-ave" / "index.html").read_text()
    assert "MEMBRESÍA CUBIERTA" in city_sports
    assert "MEMBERSHIP INDOOR" not in city_sports

    jcc = (built_site / "es" / "spots" / "jccsf" / "index.html").read_text()
    assert "PRIVADA CUBIERTA" in jcc
    assert "PRIVATE INDOOR" not in jcc

    spanish_board = (built_site / "es" / "index.html").read_text()
    assert "Cala protegida en la ribera norte" in spanish_board
    assert "MEMBRESÍA CUBIERTA" in spanish_board
    assert "Protected cove, calm water" not in spanish_board
    assert "MEMBERSHIP INDOOR" not in spanish_board

    filipino_bakar = html.unescape((built_site / "fil" / "spots" / "ucsf-bakar" / "index.html").read_text())
    assert "PRIBADONG PANLOOB/PANLABAS" in filipino_bakar
    assert "Kasama sa membership" in filipino_bakar
    assert "PRIVATE INDOOR/OUTDOOR" not in filipino_bakar

    vietnamese_potrero = (built_site / "vi" / "spots" / "24-hour-fitness-potrero" / "index.html").read_text()
    assert "Hội viên phòng gym" in vietnamese_potrero
    assert "Hỏi câu lạc bộ" in vietnamese_potrero
    assert "Gym member" not in vietnamese_potrero


def test_localized_domain_terms_are_not_left_literal() -> None:
    def collect_strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            out: list[str] = []
            for item in value.values():
                out.extend(collect_strings(item))
            return out
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                out.extend(collect_strings(item))
            return out
        return []

    glossary = tomllib.loads((ROOT / "docs" / "localization-glossary.toml").read_text())["locales"]
    translation_text_by_lang = {
        locale["code"]: "\n".join(
            str(value) for value in tomllib.loads((ROOT / "i18n" / "ui" / f"{locale['code']}.toml").read_text()).values()
        )
        for locale in _locales()
    }
    content_text_by_lang: dict[str, str] = {}
    localized_suffixes = tuple(f".{locale['code']}.md" for locale in _locales() if not locale.get("is_default"))
    for lang in glossary:
        localized_strings: list[str] = []
        if lang == "en":
            paths = [
                path
                for path in sorted((ROOT / "content").rglob("*.md"))
                if not path.name.endswith(localized_suffixes)
            ]
        else:
            paths = sorted((ROOT / "content").rglob(f"*.{lang}.md"))
        for path in paths:
            text = path.read_text()
            if text.startswith("+++"):
                frontmatter, _, body = text[3:].partition("+++")
                localized_strings.extend(collect_strings(tomllib.loads(frontmatter)))
                localized_strings.append(body)
            else:
                localized_strings.append(text)
        content_text_by_lang[lang] = "\n".join(localized_strings)

    for lang, rules in glossary.items():
        haystack = f"{translation_text_by_lang[lang]}\n{content_text_by_lang[lang]}"
        for pattern in rules.get("banned", []):
            assert re.search(pattern, haystack, flags=re.I) is None, f"{lang} still contains {pattern}"
        for pattern in rules.get("required", []):
            assert re.search(pattern, haystack, flags=re.I), f"{lang} is missing {pattern}"


def test_access_panel_renders_pricing_options(built_site: Path) -> None:
    html = _read(built_site, "aquatic-park")
    assert "<h2>Access</h2>" in html
    assert "Public cove" in html
    assert "clubhouses are separate" in html
    assert "Public day-use Tue / Thu / Sat, 09:00-18:00 Jun-Nov and 08:00-17:00 Dec-May" in html
    assert "Public day-use Mon / Wed / Fri" in html

    jcc = _read(built_site, "jccsf")
    assert 'class="cost-badge is-member">Members</span>' in jcc
    assert "Fitness Center member" in jcc
    assert "Non-member / guest" in jcc


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
    effective_copy = "SCHEDULE EFFECTIVE FROM JUN 9, 2026 TO AUG 15, 2026"
    assert effective_copy in html
    assert "SOURCE OFFICIAL SITE" in html
    assert "REVIEWED" not in html
    assert "PDF REVIEWED" not in html
    assert "LAST VERIFIED" not in html
    assert html.index("recently reopened after a $9M renovation") < html.index(effective_copy)


def test_homepage_omits_trust_column(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "<th>TRUST" not in html
    assert "trust-cell" not in html
    assert "REVIEWED AGAINST SF REC & PARK PDF" not in html
    assert "NO REVIEWED DROP-IN SCHEDULE YET" not in html
    assert "NOAA/NDBC CONDITIONS UPDATED HOURLY" not in html


def test_homepage_renders_bulletin_redesign_shell(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    bulletin = json.loads((ROOT / "data" / "bulletin.json").read_text())
    assert "class=bulletin-hero" in html
    assert "<span class=red>SWIM</span> <span>SAN</span> <span class=teal>FRANCISCO.</span>" in html
    assert "class=bulletin-strip" in html
    assert f"No. {bulletin['label']} · Live bulletin · right now" in html
    assert f"BULLETIN {bulletin['label']}" in html
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
    assert isinstance(bulletin["released_schedule_fingerprint"], str)
    assert bulletin["label"] == f"{bulletin['number']:02d}"


def test_bulletin_generator_bumps_number_when_reviewed_schedules_change(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")

    reviewed = tmp_path / "data" / "balboa-pool" / "2026-05-01-a" / "reviewed.json"
    reviewed.parent.mkdir(parents=True)
    reviewed.write_text('{"sessions":[{"day":"monday"}]}\n')

    script = ROOT / "scripts" / "generate-bulletin.mjs"

    def run_generator(*args: str) -> dict[str, object]:
        result = subprocess.run(
            ["node", str(script), *args],
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
    assert run_generator()["label"] == "01"

    another_reviewed = tmp_path / "data" / "coffman-pool" / "2026-05-02-b" / "reviewed.json"
    another_reviewed.parent.mkdir(parents=True)
    another_reviewed.write_text('{"sessions":[{"day":"wednesday"}]}\n')
    assert run_generator()["label"] == "02"
    assert run_generator()["label"] == "02"


def test_homepage_preserves_redesign_dom_contract(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "OPEN NEXT" in html
    assert "MEMBERSHIPS" in html
    assert 'data-access-mode=membership' in html
    assert 'data-payment-model=membership' in html
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


def test_field_notes_are_omitted_from_build(built_site: Path) -> None:
    assert not (built_site / "field-notes" / "index.html").exists()
    assert not (built_site / "field-notes" / "source-review-lane" / "index.html").exists()
    assert not (built_site / "field-notes" / "pool-schedule-pipeline" / "index.html").exists()
    assert not (built_site / "js" / "field-notes.js").exists()
    assert not (built_site / "js" / "scrollspy.js").exists()

    html = (built_site / "index.html").read_text()
    assert "/field-notes/" not in html
    assert "FIELD NOTES" not in html
    css = (built_site / "main.css").read_text()
    assert "field-notes" not in css
    assert ".fn-" not in css


def test_homepage_renders_cost_badges_without_hardcoded_price(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert 'class="cost-badge is-free">Free</span>' in html
    assert 'class="cost-badge is-paid">Paid</span>' in html
    assert 'class="cost-badge is-paid">$7</span>' not in html


def test_board_uses_water_column_as_the_only_temperature_surface(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    assert "INDOOR · 80–82°F" not in html
    assert "OUTDOOR · 80–82°F" not in html
    assert "THERAPEUTIC INDOOR · 92°F" not in html
    assert "data-cell=water>80–82°F" in html
    assert "data-cell=water>92°F" in html

    css = (built_site / "main.css").read_text()
    assert 'tr[data-type="open_water"] [data-cell="water"]' not in css
    assert 'tr.is-open [data-cell="water"]' not in css


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
    assert "Pool hours from SF Rec & Park · Open-water from NOAA + NDBC" not in html
    assert "site-footer-sources" not in html
    assert "Made in San Francisco by" in html
    assert "/field-notes/" not in html
    assert "/how-it-works/" not in html


def test_homepage_renders_search_metadata_and_website_json_ld(built_site: Path) -> None:
    html_text = (built_site / "index.html").read_text()
    assert "<link href=https://swimfrancisco.com/ rel=canonical>" in html_text
    assert "<meta content=en_US property=og:locale>" in html_text
    _assert_hreflang_cluster(html_text, "/")
    assert "Find where to swim right now in San Francisco: lap swim, family swim" in html_text
    assert 'property=og:title' in html_text

    objects = _json_ld_objects(html_text)
    website = next(obj for obj in objects if obj["@type"] == "WebSite")
    assert website["name"] == "Swim Francisco"
    assert website["url"] == "https://swimfrancisco.com"
    assert "lap swim" in website["description"]


def test_map_page_has_distinct_canonical_and_description(built_site: Path) -> None:
    html_text = (built_site / "map" / "index.html").read_text()
    assert "<title>San Francisco swim map — Swim Francisco</title>" in html_text
    assert "<link href=https://swimfrancisco.com/map/ rel=canonical>" in html_text
    _assert_hreflang_cluster(html_text, "/map/")
    assert "Map of San Francisco pools, beaches, and open-water swim spots" in html_text
    assert not _json_ld_objects(html_text)


def test_localized_pages_render_hreflang_and_open_graph_locale(built_site: Path) -> None:
    spanish = (built_site / "es" / "spots" / "aquatic-park" / "index.html").read_text()
    assert "<html lang=es>" in spanish
    assert "<meta content=es_US property=og:locale>" in spanish
    assert "<meta content=zh_HK property=og:locale:alternate>" in spanish
    assert "<meta content=es_US property=og:locale:alternate>" not in spanish
    _assert_hreflang_cluster(spanish, "/spots/aquatic-park/")

    chinese = (built_site / "zh-Hant" / "index.html").read_text()
    assert "<html lang=zh-Hant>" in chinese
    assert "<meta content=zh_HK property=og:locale>" in chinese
    assert "<meta content=zh_HK property=og:locale:alternate>" not in chinese
    _assert_hreflang_cluster(chinese, "/")

    finnish = (built_site / "fi" / "spots" / "aquatic-park" / "index.html").read_text()
    assert "<html lang=fi>" in finnish
    assert "<meta content=fi_FI property=og:locale>" in finnish
    assert "<meta content=fi_FI property=og:locale:alternate>" not in finnish
    assert "Aquatic Park avovesiuinti San Franciscossa" in finnish
    assert "Suojaisa poukama" in finnish
    _assert_hreflang_cluster(finnish, "/spots/aquatic-park/")


def test_spot_pages_render_valid_place_and_breadcrumb_json_ld(built_site: Path) -> None:
    aquatic = _read(built_site, "aquatic-park")
    assert "<title>Aquatic Park open-water conditions and access — Swim Francisco</title>" in aquatic
    assert "<link href=https://swimfrancisco.com/spots/aquatic-park/ rel=canonical>" in aquatic
    assert "Aquatic Park open-water swimming in San Francisco" in aquatic

    aquatic_objects = _json_ld_objects(aquatic)
    place = next(obj for obj in aquatic_objects if obj["@type"] == "Beach")
    assert place["name"] == "Aquatic Park"
    assert place["url"] == "https://swimfrancisco.com/spots/aquatic-park/"
    assert place["inLanguage"] == "en"
    assert place["isAccessibleForFree"] is True
    assert place["geo"] == {
        "@type": "GeoCoordinates",
        "latitude": 37.8063,
        "longitude": -122.4223,
    }

    breadcrumb = next(obj for obj in aquatic_objects if obj["@type"] == "BreadcrumbList")
    assert breadcrumb["inLanguage"] == "en"
    assert [item["name"] for item in breadcrumb["itemListElement"]] == [
        "Swim Francisco",
        "Aquatic Park",
    ]

    garfield = _read(built_site, "garfield-pool")
    assert "Garfield Pool swim schedule and access — Swim Francisco" in garfield
    pool_objects = _json_ld_objects(garfield)
    pool = next(obj for obj in pool_objects if obj["@type"] == "SportsActivityLocation")
    assert pool["name"] == "Garfield Pool"
    assert pool["isAccessibleForFree"] is False


def test_robots_and_sitemap_are_search_console_ready(built_site: Path) -> None:
    robots = (built_site / "robots.txt").read_text()
    for user_agent in [
        "OAI-SearchBot",
        "ChatGPT-User",
        "GPTBot",
        "PerplexityBot",
        "Perplexity-User",
        "Claude-SearchBot",
        "Claude-User",
        "ClaudeBot",
        "Google-Extended",
        "Bingbot",
        "*",
    ]:
        assert f"User-agent: {user_agent}\nAllow: /" in robots
    assert "Sitemap: https://swimfrancisco.com/sitemap.xml" in robots

    sitemap = (built_site / "sitemap.xml").read_text()
    assert 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in sitemap
    assert "<loc>https://swimfrancisco.com/</loc>" in sitemap
    assert "<loc>https://swimfrancisco.com/map/</loc>" in sitemap
    assert "<loc>https://swimfrancisco.com/spots/aquatic-park/</loc>" in sitemap
    for canonical_path in ("/", "/spots/aquatic-park/"):
        for locale in _locales():
            code = str(locale["code"])
            path = _localized_url_path(locale, canonical_path)
            assert (
                f'<xhtml:link rel="alternate" hreflang="{code}" href="https://swimfrancisco.com{path}" />'
                in sitemap
            )
        assert (
            f'<xhtml:link rel="alternate" hreflang="x-default" href="https://swimfrancisco.com{canonical_path}" />'
            in sitemap
        )
    assert "https://swimfrancisco.com/field-notes/" not in sitemap


def test_llms_txt_points_agents_at_canonical_swim_pages(built_site: Path) -> None:
    llms = (built_site / "llms.txt").read_text()
    assert "# Swim Francisco" in llms
    assert "https://swimfrancisco.com/" in llms
    assert "https://swimfrancisco.com/map/" in llms
    assert "https://swimfrancisco.com/sitemap.xml" in llms
    assert "https://swimfrancisco.com/spots/aquatic-park/" in llms
    assert "https://swimfrancisco.com/spots/garfield-pool/" in llms
