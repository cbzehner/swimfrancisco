import pytest

from schedules.registry import load_registry


def test_registry_loads_expected_pools():
    entries = load_registry()
    assert entries[0].slug == "balboa-pool"
    mission = next(entry for entry in entries if entry.slug == "mission-community-pool")
    assert mission.source_status == "published"
    assert "/DocumentCenter/View/" in mission.pdf_url
    assert mission.pdf_url.rstrip("/").split("/")[-1].isdigit()
    north_beach = next(entry for entry in entries if entry.slug == "north-beach-pool")
    assert north_beach.source_status == "published"
    assert not north_beach.pdf_url
    assert [(source.pool, source.url.rsplit("/", 1)[1]) for source in north_beach.pool_sources] == [("cool", "29953"), ("warm", "29954")]
    koret = next(entry for entry in entries if entry.slug == "koret-center")
    assert koret.source_kind == "koret_google_sheet"
    assert koret.source_status == "published"
    bay_club = next(entry for entry in entries if entry.slug == "bay-club-gateway")
    assert bay_club.source_status == "access_hours_only"
    fitness_sf = next(entry for entry in entries if entry.slug == "fitness-sf-fillmore")
    assert fitness_sf.source_kind == "fitness_sf_html"
    assert fitness_sf.source_status == "access_hours_only"



def test_registry_pair_replaces_single_pointer(tmp_path, north_beach_pair):
    from schedules.registry import load_registry
    entry, _ = north_beach_pair
    path = tmp_path / "registry.toml"
    prefix = f'[[pool]]\nslug = "{entry.slug}"\nofficial_page_url = "{entry.official_page_url}"\n'
    pair = 'pool_sources = [{pool="cool", url="https://sfrecpark.org/DocumentCenter/View/29953"}, {pool="warm", url="https://sfrecpark.org/DocumentCenter/View/29954"}]\n'
    path.write_text(prefix + pair)
    assert load_registry(path)[0].pool_sources == entry.pool_sources
    for value in (pair.replace('pool="warm"', 'pool="cool"'), pair.replace('29954','29953'), pair + 'pdf_url="https://sfrecpark.org/DocumentCenter/View/29778"\n'):
        path.write_text(prefix + value)
        with pytest.raises(ValueError):
            load_registry(path)


def test_direct_publication_opt_in_is_limited_to_approved_identities(tmp_path):
    entry = next(entry for entry in load_registry() if entry.slug == "pomeroy-pool")
    assert entry.auto_publish
    assert {item.slug for item in load_registry() if item.auto_publish} == _BROWSER_SLUGS | {entry.slug, "ucsf-bakar", "ucsf-millberry", "fitness-sf-fillmore", "city-sports-20th-ave", "equinox-sports-club-sf", "bay-club-gateway"}
    path = tmp_path / "registry.toml"
    for slug, kind, url, opt_in in (
        ("pomeroy-pool", "pomeroy_html", "https://example.org/", "true"),
        ("pomeroy-pool", "pomeroy_html", entry.pdf_url, '"true"'),
        ("jccsf-pool", "jccsf_html", entry.pdf_url, "true"),
    ):
        path.write_text(f'[[pool]]\nslug="{slug}"\nsource_kind="{kind}"\npdf_url="{url}"\nofficial_page_url="{entry.official_page_url}"\nauto_publish={opt_in}\n')
        with pytest.raises(ValueError, match="approved source identities"):
            load_registry(path)


_BROWSER_SLUGS = {"jccsf", "presidio-ymca-letterman", "stonestown-ymca", "embarcadero-ymca", "chinatown-ymca", "sfsu-mashouf"}


def test_registry_uses_browser_primary_only_for_six_approved_sources():
    entries = load_registry()
    assert {entry.slug for entry in entries if entry.capture_method == "cloudflare_browser"} == _BROWSER_SLUGS
    assert all(entry.capture_method == "http" for entry in entries if entry.slug not in _BROWSER_SLUGS)
    assert all(entry.auto_publish for entry in entries if entry.slug in _BROWSER_SLUGS)
    assert {entry.slug for entry in entries if entry.auto_publish} == _BROWSER_SLUGS | {"pomeroy-pool", "ucsf-bakar", "ucsf-millberry", "fitness-sf-fillmore", "city-sports-20th-ave", "equinox-sports-club-sf", "bay-club-gateway"}


def _capture_registry(path, *, slug="jccsf", kind="jccsf_html", url="https://www.jccsf.org/fitness/aquatics/", method=None, auto_publish=False):
    import json

    fields = {"slug": slug, "source_kind": kind, "pdf_url": url, "official_page_url": url, "auto_publish": auto_publish}
    text = "[[pool]]\n" + "".join(f"{key} = {json.dumps(value)}\n" for key, value in fields.items())
    if method is not None:
        text += f"capture_method = {method}\n"
    path.write_text(text)


def test_registry_missing_capture_method_defaults_to_http(tmp_path):
    from schedules.models import PoolEntry

    path = tmp_path / "registry.toml"
    _capture_registry(path)
    assert load_registry(path)[0].capture_method == "http"
    assert PoolEntry("jccsf", "url", "url").capture_method == "http"


@pytest.mark.parametrize("method", ['"browser"', '"HTTP"', '""', 'true', '42', '[]', '{}'])
def test_registry_rejects_unknown_or_non_string_capture_method(tmp_path, method):
    path = tmp_path / "registry.toml"
    _capture_registry(path, method=method)
    with pytest.raises(ValueError, match="capture_method"):
        load_registry(path)


@pytest.mark.parametrize("slug", sorted(_BROWSER_SLUGS))
def test_browser_capture_requires_approved_source_kind_and_exact_url(tmp_path, slug):
    entry = next(entry for entry in load_registry() if entry.slug == slug)
    path = tmp_path / "registry.toml"
    _capture_registry(path, slug=slug, kind=entry.source_kind, url=entry.pdf_url, method='"cloudflare_browser"')
    assert load_registry(path)[0].capture_method == "cloudflare_browser"
    for kind, url in (("sfrecpark_pdf", entry.pdf_url), (entry.source_kind, entry.pdf_url + "?other=1"), (entry.source_kind, "https://example.org/")):
        _capture_registry(path, slug=slug, kind=kind, url=url, method='"cloudflare_browser"')
        with pytest.raises(ValueError, match="six approved HTML sources"):
            load_registry(path)
    _capture_registry(path, slug=slug, kind=entry.source_kind, url=entry.pdf_url, method='"cloudflare_browser"', auto_publish=True)
    assert load_registry(path)[0].auto_publish


@pytest.mark.parametrize("slug", ["pomeroy-pool", "koret-center", "balboa-pool"])
def test_browser_capture_rejects_unapproved_sources(tmp_path, slug):
    entry = next(entry for entry in load_registry() if entry.slug == slug)
    path = tmp_path / "registry.toml"
    _capture_registry(path, slug=slug, kind=entry.source_kind, url=entry.pdf_url, method='"cloudflare_browser"')
    with pytest.raises(ValueError, match="six approved HTML sources"):
        load_registry(path)
