from schedules.registry import load_registry


def test_registry_loads_expected_pools():
    entries = load_registry()
    assert entries[0].slug == "balboa-pool"
    mission = next(entry for entry in entries if entry.slug == "mission-community-pool")
    assert mission.source_status == "published"
    assert "/DocumentCenter/View/" in mission.pdf_url
    assert mission.pdf_url.rstrip("/").split("/")[-1].isdigit()
    north_beach = next(entry for entry in entries if entry.slug == "north-beach-pool")
    assert north_beach.source_status == "missing_current_schedule"
    assert north_beach.pdf_url.endswith("/29778")
    assert "Warm Pool (29779)" in (north_beach.notes or "")
    koret = next(entry for entry in entries if entry.slug == "koret-center")
    assert koret.source_kind == "koret_google_sheet"
    assert koret.source_status == "published"
    bay_club = next(entry for entry in entries if entry.slug == "bay-club-gateway")
    assert bay_club.source_status == "access_hours_only"
    fitness_sf = next(entry for entry in entries if entry.slug == "fitness-sf-fillmore")
    assert fitness_sf.source_kind == "fitness_sf_html"
    assert fitness_sf.source_status == "access_hours_only"
