# SwimFrancisco Spec

## Overview
swimfrancisco.com — a live-updating database of all the places to swim in San Francisco. Utility-first: answers "where can I swim right now?"

## Architecture

- **Static site:** Zola on Cloudflare Pages
- **Live data:** Cloudflare Worker (TypeScript), hourly cron, KV storage
- **Scraping pipeline (v2):** Python (devenv + uv, pdfplumber + Haiku) via GitHub Actions — deferred, hand-curate for v1
- **Domain:** swimfrancisco.com on Cloudflare
- **Dev environment:** devenv + uv

## Data

### Pools (9 — SF Rec & Parks)

| Pool | Address | Type |
|------|---------|------|
| Mission Community Pool | 101 Linda St | Outdoor |
| Balboa Pool | 51 Havelock St | Indoor |
| Coffman Pool | 1701 Visitacion Ave | Indoor |
| Garfield Pool | 1271 Treat Ave | Indoor |
| Hamilton Pool | 1900 Geary Blvd | Indoor |
| Martin Luther King Jr. Pool | 5701 3rd St | Indoor |
| North Beach Pool | 661 Lombard St | Indoor |
| Rossi Pool | 600 Arguello Blvd | Indoor |
| Sava Pool | 2695 19th Ave | Indoor (closed for repairs, reopening summer 2026) |

### Open Water Spots

| Spot | Zone | Temp Station | Tide Station |
|------|------|-------------|-------------|
| Aquatic Park | Bay | 9414290 (fallback: 9414750) | 9414290 |
| Crissy Field / East Beach | Bay | 9414290 (fallback: 9414750) | 9414290 |
| Baker Beach | Ocean | NDBC 46237 | 9414290 |
| Ocean Beach | Ocean | NDBC 46237 | 9414290 |
| China Beach | Ocean | NDBC 46237 | 9414290 |

Bay water: ~60-64°F. Ocean water: ~56-58°F. Delta of 4-7°F.

### Data Model — Pool

```toml
+++
title = "Hamilton Pool"
slug = "hamilton-pool"

[extra]
type = "pool"
subtype = "indoor"
address = "1900 Geary Blvd, San Francisco, CA 94115"
lat = 37.7847
lng = -122.4340
website = "https://sfrecpark.org/..."
cost = "paid"
schedule_effective = "2026-01-06"  # when this schedule took effect
last_verified_at = "2026-04-16"   # last human verification

[[extra.sessions]]
day = "monday"
type = "lap_swim"
start = "06:00"
end = "08:30"

[[extra.sessions]]
day = "monday"
type = "open_swim"
start = "12:00"
end = "14:00"

# Date-scoped overrides for holidays, maintenance, etc.
[[extra.closures]]
start = "2026-07-04"
end = "2026-07-04"
reason = "Independence Day"

[[extra.closures]]
start = "2026-08-01"
end = "2026-08-15"
reason = "Annual maintenance"
+++

Description of the pool.
```

### Data Model — Open Water

```toml
+++
title = "Aquatic Park"
slug = "aquatic-park"

[extra]
type = "open_water"
address = "499 Jefferson St, San Francisco, CA 94109"
lat = 37.8063
lng = -122.4223
website = ""
cost = "free"
noaa_tide_station = "9414290"
temp_station_id = "9414290"
temp_station_type = "noaa"
description_short = "Protected cove, calm water, popular with swim clubs"
hazards = ["boat traffic outside cove", "cold water year-round"]
clubs = ["South End Rowing Club", "Dolphin Swimming & Boating Club"]
common_distances = ["0.25mi to breakwater", "1mi loop"]
+++

Description of the spot.
```

## UI

### Design: "Swim Log / Departure Board" (Concept 4)

Airport departure board aesthetic. Split-flap animation.

**Color:** Yellow-on-black or white-on-dark-blue.

**Homepage = departure board:**

| SPOT | TYPE | STATUS | NEXT | TEMP |
|------|------|--------|------|------|
| Hamilton Pool | LAP SWIM | OPEN | Closes 3pm | 80°F |
| Sava Pool | OPEN SWIM | CLOSED | Tomorrow 10am | — |
| Aquatic Park | OPEN WATER | — | — | 56°F |

- Default sort: open-first, then alphabetical
- Filters: **Open Now** (toggle), **Type** (pills: Lap / Open / Family / Open Water), **Near Me** (button, triggers geolocation → re-sort by distance)
- Map view toggle (Leaflet + OpenStreetMap), not the default

**Mobile (primary):**
- 3 columns: SPOT, STATUS, TEMP
- Tap row to expand: shows NEXT, TYPE, link to detail page
- Split-flap animation preserved

**Animation:**
- CSS transforms + vanilla JS
- Staggered row flip on load (50ms delay per row, ~500ms total)
- Rows flip on filter change

**Detail pages (`/spots/:slug/`):**
- Pools: full weekly schedule table, address, static map image, link to official page
- Open water: live conditions panel (water temp, tide), hazards, safety notes, address, static map image
  - (v2) air temperature alongside water temp
- Progressive enhancement — works without JS

### Progressive Enhancement
- Zola renders full static HTML departure board with schedule data embedded (inline JSON or `data-` attributes)
- Small inline `<script>` does two things:
  1. Computes STATUS/NEXT client-side by checking current time against the embedded schedule + closures
  2. Fetches `/api/conditions` and injects water temp/conditions into rows by `data-slug`
- Without JS: full schedule table is visible, but no computed STATUS/NEXT columns and no live water temp
- Open water spots never show OPEN/CLOSED — they show conditions (temp, tide, last updated) and let the swimmer decide

## Cloudflare Worker

- TypeScript, lives in `worker/` directory
- **Cron Trigger:** runs hourly
  - Fetches NOAA Tides & Currents API (station 9414290, fallback 9414750) for bay temp + tides
  - Fetches NDBC buoy 46237 data for ocean temp
  - Writes per-spot JSON to KV + bulk `all` key
- **Endpoints:**
  - `GET /api/conditions` — all open water conditions (homepage bulk fetch)
  - `GET /api/conditions/:slug` — single spot (detail pages)
- Keep it simple, but prioritize error handling over brevity

### API Sources (free, no keys required)

- NOAA Tides & Currents: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=STATION_ID&product=water_temperature&units=english&time_zone=lst_ldt&format=json`
- NDBC real-time: `https://www.ndbc.noaa.gov/data/realtime2/46237.txt`

## Scraping Pipeline (v2 — deferred)

For v1, hand-curate all pool data. 9 pools with quarterly schedule changes don't justify automation yet.

When ready to automate (v2):

1. Weekly GitHub Action fetches SF Rec & Parks pool schedule PDF
2. Parse with `pdfplumber` for table extraction
3. Validate/clean with Haiku (LLM fallback for messy formatting)
4. Write Zola content files (one `.md` per spot)
5. Store raw PDF in repo for debugging
6. **Open a PR for human review** — do not auto-push to `main`

Tools: Python, pdfplumber, Anthropic API (Haiku), potentially Exa/Firecrawl for web scraping.

## Deploy

- **On push to `main`:** Cloudflare Pages rebuilds from Zola output
- **v1:** manual content updates pushed to `main`
- **v2:** weekly GitHub Actions scrape → opens PR for review
- **Worker:** deployed separately via `wrangler`

## Future (not v1)

- Automated scraping pipeline (see "Scraping Pipeline" section above)
- Private clubs/gyms with membership opt-in (Bay Club, Olympic Club, Equinox, etc.)
- Crowd-sourced condition updates
- Amenities, pool specs, swim routes on detail pages
- Indoor/Outdoor and Cost filters
- Surf/wind data for ocean-side spots (NDBC buoy wind data, Surfline)
- CDPH beach water quality grades
- Prototype all 5 design concepts (see docs/design-concepts.md)
