from schedules.registry import load_registry


def test_registry_loads_expected_pools():
    entries = load_registry()
    assert len(entries) == 25
    assert entries[0].slug == "balboa-pool"
    mission = next(entry for entry in entries if entry.slug == "mission-community-pool")
    assert mission.source_status == "published"
    assert mission.pdf_url.endswith("/28959")
    koret = next(entry for entry in entries if entry.slug == "koret-center")
    assert koret.source_kind == "koret_google_sheet"
    assert koret.source_status == "published"
    bay_club = next(entry for entry in entries if entry.slug == "bay-club-gateway")
    assert bay_club.source_status == "access_hours_only"
    fitness_sf = next(entry for entry in entries if entry.slug == "fitness-sf-fillmore")
    assert fitness_sf.source_kind == "fitness_sf_html"
    assert fitness_sf.source_status == "access_hours_only"
