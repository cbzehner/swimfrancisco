from schedules.registry import load_registry


def test_registry_loads_expected_pools():
    entries = load_registry()
    assert len(entries) == 9
    assert entries[0].slug == "balboa-pool"
    mission = next(entry for entry in entries if entry.slug == "mission-community-pool")
    assert mission.source_status == "published"
    assert mission.pdf_url.endswith("/28959")
