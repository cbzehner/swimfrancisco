# Swim Francisco Spec

## Overview
swimfrancisco.com — a live-updating database of all the places to swim in San Francisco. Utility-first: answers "where can I swim right now?"

## Architecture

- **Static site:** Zola served by a single Cloudflare Worker in the Workers Builds model
- **Live data:** Cloudflare Worker (TypeScript), hourly cron, KV storage
- **Schedule extraction:** Python (devenv + uv) with Gemini/Anthropic PDF extraction, human-reviewed `reviewed.json`, and projection into `content/spots/*.md`
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
| Baker Beach | Ocean | NDBC 46237 | 9414275 |
| Ocean Beach | Ocean | NDBC 46237 | 9414275 |
| China Beach | Ocean | NDBC 46237 | 9414275 |

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
type = "family_swim"
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
temp_fallback_station_id = "9414750"
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

| SPOT | TYPE | STATUS | NEXT | TEMP | TRUST |
|------|------|--------|------|------|-------|
| Hamilton Pool | INDOOR | OPEN | Closes 15:00 | 80°F | PDF |
| Sava Pool | INDOOR | CLOSED | Closed through Sep 21, 2026 | — | REVIEW |
| Aquatic Park | BEACH | OPEN | — | 56°F | NOAA/NDBC |

- Default sort: open-first, then alphabetical
- Filters: **Open** sort, **Type** (pills: Lap / Beach / Family / Senior)
- Sort: **Distance** (button, triggers geolocation → re-sort by distance; board view only)
- Map view toggle (Leaflet + OpenStreetMap), not the default

**Mobile (primary):**
- Compact columns prioritize SPOT, STATUS, and NEXT; TYPE, TEMP, and TRUST collapse at phone widths
- Tap row to expand: shows hidden row context and link to detail page
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
- Open-water rows show `OPEN` as access status and leave safety decisions to condition details (temp, tide, hazards)

## Cloudflare Worker

- TypeScript, lives in `worker/` directory
- **Cron Trigger:** runs hourly
  - Fetches NOAA Tides & Currents API for bay temp (9414290, fallback 9414750) and per-spot tide predictions
  - Fetches NDBC buoy 46237 data for ocean temp
  - Writes the slug-keyed bulk record to KV under the single `conditions` key
- **Endpoints:**
  - `GET /api/conditions` — slug-keyed conditions for every spot (board + detail pages)
- **Per-spot record shape** (`SpotConditions` in `worker/src/assemble.ts`):
  - Flat temp fields: `water_temp_f`, `water_temp_c`, `temp_observed_at`, `temp_station_id`, `temp_station_type` — either all set or all null
  - `tide` summary or null
  - `temp_stale: boolean` and `tide_stale: boolean` — true when the field was reused from the last-good KV value because the upstream fetch returned nothing (24h freshness ceiling)
  - `updated_at` ISO 8601 UTC of the assembly run
- Keep it simple, but prioritize error handling over brevity

### API Sources (free, no keys required)

- NOAA Tides & Currents: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=STATION_ID&product=water_temperature&units=english&time_zone=lst_ldt&format=json`
- NDBC real-time: `https://www.ndbc.noaa.gov/data/realtime2/46237.txt`

## Schedule Extraction

The pool schedule extractor is a local and CI-runnable Python CLI under
`schedule-tools/`. It fetches SF Rec & Park PDFs, runs Gemini and/or Anthropic
against the PDF with a JSON schema, stores source/provider/review artifacts
under `data/<slug>/<date>-<sha12>/`, and requires human approval of
`reviewed.json` before projecting into `content/spots/*.md`.

## Deploy

- **On push to `main`:** Cloudflare Workers Builds runs the Zola build and deploys the Worker/static assets together
- **Daily:** Worker cron triggers a Workers Builds deploy hook at 00:05 PT so date-sensitive HTML stays current
- **Schedules:** weekly GitHub Action writes provider artifacts to an auto PR; humans review before `content/spots/*.md` changes merge

## Future (not v1)

- Higher-confidence auto-merge for trivially safe schedule refreshes
- Private clubs/gyms with membership opt-in (Bay Club, Olympic Club, Equinox, etc.)
- Crowd-sourced condition updates
- Amenities, pool specs, swim routes on detail pages
- Indoor/Outdoor and Cost filters
- Surf/wind data for ocean-side spots (NDBC buoy wind data, Surfline)
- CDPH beach water quality grades
- Prototype all 5 design concepts (see docs/design-concepts.md)
