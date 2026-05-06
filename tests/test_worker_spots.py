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


def _content_open_water() -> dict[str, dict[str, str | None]]:
    spots: dict[str, dict[str, str | None]] = {}
    for path in (ROOT / "content" / "spots").glob("*.md"):
        document = _frontmatter(path)
        extra = document.get("extra", {})
        if extra.get("type") != "open_water":
            continue
        slug = str(document["slug"])
        spots[slug] = {
            "tempStationId": str(extra["temp_station_id"]),
            "tempStationType": str(extra["temp_station_type"]),
            "tempFallbackStationId": (
                str(extra["temp_fallback_station_id"])
                if "temp_fallback_station_id" in extra
                else None
            ),
            "tideStationId": str(extra["noaa_tide_station"]),
        }
    return spots


def _field(body: str, name: str) -> str | None:
    match = re.search(rf'{name}:\s*"([^"]+)"', body)
    return match.group(1) if match else None


def _worker_spots() -> dict[str, dict[str, str | None]]:
    source = (ROOT / "worker" / "src" / "spots.ts").read_text()
    spots: dict[str, dict[str, str | None]] = {}
    for match in re.finditer(r"\{\s*slug:\s*\"([^\"]+)\"(?P<body>.*?)\n\s*\}", source, flags=re.S):
        slug = match.group(1)
        body = match.group("body")
        spots[slug] = {
            "tempStationId": _field(body, "tempStationId"),
            "tempStationType": _field(body, "tempStationType"),
            "tempFallbackStationId": _field(body, "tempFallbackStationId"),
            "tideStationId": _field(body, "tideStationId"),
        }
    return spots


def test_worker_open_water_station_config_matches_content() -> None:
    assert _worker_spots() == _content_open_water()
