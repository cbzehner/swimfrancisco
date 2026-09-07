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
