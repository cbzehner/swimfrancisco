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

### SF Rec & Parks pools (9)

The live board also lists membership and limited-access pools; those live
in `content/spots/` and stay behind the membership toggle. The table below
is the original city set.

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
| Sava Pool | 2695 19th Ave | Indoor |

### Open Water Spots

| Spot | Zone | Temp sources (in fallback order) | Tide Station |
|------|------|----------------------------------|-------------|
| Aquatic Park | Bay | USGS Alcatraz → NOAA 9414863 → ERDDAP Exploratorium → satellite SST | 9414290 |
| Crissy Field / East Beach | Bay | USGS Alcatraz → NOAA 9414863 → ERDDAP Exploratorium → satellite SST | 9414290 |
| Baker Beach | Ocean | NDBC 46237 → satellite SST | 9414275 |
| Ocean Beach | Ocean | NDBC 46237 → satellite SST | 9414275 |
| China Beach | Ocean | NDBC 46237 → satellite SST | 9414275 |

Bay water: ~60-64°F. Ocean water: ~56-58°F. Delta of 4-7°F.

### Data Model — Pool

Each spot is one TOML-frontmatter page in `content/spots/<slug>.md`
(translations live alongside as `<slug>.<lang>.md`). Schedules are an
array of dated windows; the board picks the window covering today.

```toml
+++
title = "Hamilton Pool"
slug = "hamilton-pool"

[extra]
type = "pool"
subtype = "indoor"                 # or "private indoor", "outdoor", ...
address = "1900 Geary Blvd, San Francisco, CA 94115"
locale_label = "Western Addition"  # neighborhood shown on the board
lat = 37.7847
lng = -122.434
website = "https://sfrecpark.org/facilities/facility/details/Hamilton-Pool-215"
setpoint_label = "80–82°F"
access_mode = "public"             # public | membership | ...
payment_model = "session"          # session | membership | free | ...
# Membership pools add day_pass_price, access_summary, access_notes, [[extra.pricing]]

[[extra.schedules]]
effective_start = "2026-03-17"
effective_end = "2026-06-06"       # optional; open-ended when omitted
schedule_basis = "swim_schedule"
last_verified_at = "2026-04-19"    # last attestation (human review or CI publish-pending)

[[extra.schedules.sessions]]
day = "tuesday"
type = "lap_swim"                  # lap_swim | family_swim | senior_swim
start = "09:00"
end = "11:00"
pool = "main"                      # optional sub-pool for multi-pool facilities

# Date-scoped closures (holidays, maintenance). Single-day closures may
# carry start_time/end_time for a partial-day closure.
[[extra.schedules.closures]]
start = "2026-07-04"
end = "2026-07-04"
reason = "Independence Day"

# Optional building hours / one-off exceptions for facilities that
# publish them separately from swim sessions.
[[extra.schedules.access_hours]]
day = "monday"
start = "06:00"
end = "21:00"
label = "Building open"
+++

Description of the pool.
```

The canonical schema is `schedule-tools/src/schedules/schemas/reviewed-snapshot.json`;
`schedule-tools` projects reviewed data into these pages.

### Data Model — Open Water

```toml
+++
title = "Aquatic Park"
slug = "aquatic-park"

[extra]
type = "open_water"
water_body = "bay"                 # bay | ocean
address = "499 Jefferson St, San Francisco, CA 94109"
locale_label = "Aquatic Park"
lat = 37.8063
lng = -122.4223
website = "https://sfrecpark.org/Facilities/Facility/Details/Aquatic-Park-200"
noaa_tide_station = "9414290"
access_mode = "public"
payment_model = "free"
description_short = "Protected cove, calm water, popular with swim clubs"
hazards = ["boat traffic outside cove", "cold water year-round"]
common_distances = ["0.25mi to breakwater", "1mi loop"]

# Ordered fallback chain; the Worker uses the first source that returns
# a fresh reading. `scripts/generate-worker-spots.mjs` compiles these
# into worker/src/spots.ts.
[[extra.temp_sources]]
type = "usgs"
id = "374938122251801"

[[extra.temp_sources]]
type = "noaa"
id = "9414863"

[[extra.temp_sources]]
type = "erddap"
id = "exploratorium-seabird"

[[extra.temp_sources]]
type = "sst"
id = "37.81,-122.43"

[[extra.clubs]]
name = "South End Rowing Club"
url = "https://serc.com/faq"
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
- Filters: **Open/Next** sort, **Type** pills (All / Lap / Family / Senior / Beach), **Memberships** toggle for membership-only pools
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
  - Walks each open-water spot's `temp_sources` chain (USGS, NOAA, NDBC, ERDDAP, satellite SST) until one returns a fresh reading
  - Fetches per-spot NOAA tide predictions
  - Writes the slug-keyed bulk record to KV under the single `conditions` key
  - On the 00:00 PT tick, fires the Workers Builds deploy hook so date-sensitive HTML is rebuilt
- **Endpoints:**
  - `GET /api/conditions` — slug-keyed conditions for every spot (board + detail pages)
  - `/ingest/*` — same-origin reverse proxy for PostHog analytics
  - Everything else is served from the Zola build as static assets
- **Per-spot record shape** (`SpotConditions` in `worker/src/assemble.ts`):
  - Flat temp fields: `water_temp_f`, `water_temp_c`, `temp_observed_at`, `temp_station_id`, `temp_station_type` — either all set or all null
  - `tide` summary or null
  - `temp_stale: boolean` and `tide_stale: boolean` — true when the field was reused from the last-good KV value because the upstream fetch returned nothing (24h freshness ceiling); `temp_carried_since` / `tide_carried_since` record when carrying began
  - `updated_at` ISO 8601 UTC of the assembly run
- Keep it simple, but prioritize error handling over brevity

### API Sources (free, no keys required)

- USGS Instantaneous Values (Alcatraz 374938122251801)
- NOAA Tides & Currents (water temperature and tide predictions)
- NDBC real-time buoy text (46237)
- ERDDAP (Exploratorium Seabird)
- Satellite SST as the last-resort fallback

See `worker/src/*.ts` for exact URLs and parsers.

## Schedule Extraction

The pool schedule extractor is a local and CI-runnable Python CLI under
`schedule-tools/`. It fetches SF Rec & Park PDFs, runs Gemini and/or Anthropic
against the PDF with a JSON schema, stores source/provider/review artifacts
under `data/<slug>/<date>-<sha12>/`, and projects `reviewed.json` into
`content/spots/*.md`. Unique, unambiguous Rec & Park grids are attested by CI
(`schedules publish-pending`); anything flagged waits for human review.
See `docs/schedules.md`.

## Deploy

- **On push to `main`:** Cloudflare Workers Builds runs the Zola build and deploys the Worker/static assets together
- **Daily:** the hourly Worker cron also triggers a Workers Builds deploy hook on the tick at 00:00 PT so date-sensitive HTML stays current
- **Schedules:** weekly GitHub Action (`schedules-extract.yml`, Mondays) refreshes one rolling auto PR; it auto-merges when every change was CI-attested, otherwise it is labeled `needs-schedule-review`. `workflow_dispatch` still runs on demand.

## Future (not v1)

- Crowd-sourced condition updates
- Amenities, pool specs, swim routes on detail pages
- Indoor/Outdoor and Cost filters
- Surf/wind data for ocean-side spots (NDBC buoy wind data, Surfline)
- CDPH beach water quality grades
- Prototype all 5 design concepts (see docs/design-concepts.md)
