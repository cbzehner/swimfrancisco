from __future__ import annotations

import re
from pathlib import Path

import tomlkit

ROOT = Path(__file__).resolve().parents[1]


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    match = re.match(r"^\+\+\+\n(.*?)\n\+\+\+\n", text, flags=re.S)
    assert match is not None, f"{path} is missing TOML frontmatter"
    return tomlkit.parse(match.group(1))


def _content_open_water() -> dict[str, dict]:
    spots: dict[str, dict] = {}
    for path in (ROOT / "content" / "spots").glob("*.md"):
        document = _frontmatter(path)
        extra = document.get("extra", {})
        if extra.get("type") != "open_water":
            continue
        slug = str(document["slug"])
        sources = [
            {"type": str(source["type"]), "id": str(source["id"])}
            for source in extra["temp_sources"]
        ]
        assert sources, f"{path} has an empty temp_sources chain"
        spots[slug] = {
            "tempSources": sources,
            "tideStationId": str(extra["noaa_tide_station"]),
        }
    return spots


def _worker_spots() -> dict[str, dict]:
    source = (ROOT / "worker" / "src" / "spots.ts").read_text()
    spots: dict[str, dict] = {}
    for match in re.finditer(r"\{\s*slug:\s*\"([^\"]+)\"(?P<body>.*?)\n\s*\},\n", source, flags=re.S):
        slug = match.group(1)
        body = match.group("body")
        sources = [
            {"type": pair.group(1), "id": pair.group(2)}
            for pair in re.finditer(r'\{ type: "([^"]+)", id: "([^"]+)" \}', body)
        ]
        tide = re.search(r'tideStationId:\s*"([^"]+)"', body)
        assert tide is not None, f"{slug} block in spots.ts is missing tideStationId"
        spots[slug] = {
            "tempSources": sources,
            "tideStationId": tide.group(1),
        }
    return spots


def test_worker_open_water_station_config_matches_content() -> None:
    content = _content_open_water()
    assert content, "no open-water spots found in content"
    assert _worker_spots() == content
