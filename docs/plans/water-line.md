---
status: pending
progress: []
last_review: null
iterations: 0
no_progress_count: 0
started_at: null
work_unit_granularity: step
---

# Water Line (Open-Water Detail Pages)

## Context

Concept 1 from `docs/design-concepts.md` — a tide-driven horizontal water
line and a temperature-driven background color shift. It belongs only on
open-water detail pages (`/spots/<slug>/` where `extra.type = "open_water"`).
Indoor pools have no meaningful live conditions to drive it. Homepage stays
as the departure board regardless of filter; the Water Line is a detail-page
treatment only.

Applies to the five open-water spots in `docs/spec.md`: Aquatic Park, Crissy
Field, Baker Beach, Ocean Beach, China Beach.

## Goal

Make an open-water detail page feel like the water before the reader parses
any text. The background color tells you roughly how cold it is; the water
line tells you where the tide is in its cycle.

## Proposed change

### Data inputs

Both already come from `GET /api/conditions/:slug` (see `worker/` cron).

- `water_temp_f: number` — current reading
- `tide_height_ft: number` — current reading
- `tide_range: { min: number, max: number }` — today's low and high
- `fetched_at: ISO8601` — used for the freshness dot (compatible with the
  pending Trust Layer work)
- `station_id`, `source` — used in the footer attribution line

If any field is missing, degrade as described under "Failure modes".

### Background color

CSS custom property `--water-tint` applied to the page background. Linear
interpolation between two anchors:

- 50°F → `#0a2540` (deep navy)
- 62°F → `#1fb6a0` (bright teal)

Clamp below 50°F to the navy anchor; above 62°F interpolate one more stop
to `#6fd7c8` at 68°F then clamp. Use `oklch` for the interpolation so the
midpoints do not go muddy.

Apply as a full-viewport gradient: `--water-tint` at the bottom fading to
`color-mix(in oklch, var(--water-tint) 55%, #000)` at the top. The
departure-board palette (yellow-on-black) is preserved for the content
layer; only the background plate changes.

### Water line

A horizontal band across the viewport behind the content.

- **Height** maps today's tide to vertical position. `min` → 12% from
  bottom. `max` → 52% from bottom. Current reading interpolates between.
  Clamp to that band so the line never touches the edges.
- **Motion**: a gentle sine oscillation with amplitude 4px and period 7s.
  Pure CSS `@keyframes`, no JS.
- **Rendering**: an SVG path with a single sine wave, stroked at 1.5px in
  `color-mix(in oklch, var(--water-tint) 20%, white)` and filled below with
  `color-mix(in oklch, var(--water-tint) 15%, transparent)`.
- Respect `prefers-reduced-motion: reduce` — skip the oscillation, render
  a static line at the interpolated height.

### Layout

Content sits above the water line in the existing detail-page stack:

1. Back link (matches departure board)
2. Spot name and address
3. Conditions panel (water temp, tide, last updated)
4. Hazards
5. Safety notes
6. Static map
7. Footer: station attribution, official page link, freshness dot

The water line SVG is `position: fixed` at z-index 0; content is z-index 1
on a translucent panel (`background: color-mix(in oklch, black 70%,
transparent)`) so the tint still reads through.

### Progressive enhancement

- Zola renders the page with a static mid-band water line and a neutral
  `--water-tint` derived from the last-verified snapshot embedded in the
  page.
- The inline `<script>` that already fetches `/api/conditions` updates two
  custom properties on `<html>`: `--water-tint` and `--tide-pct`. No DOM
  swaps, no animation kickoff.
- Without JS: static line, static tint, all real content still visible.

## Failure modes

- **Missing temp**: fall back to `#13384a` (neutral deep). Do not attempt a
  guess.
- **Missing tide**: render the line at 32% (midband) with no animation.
- **Stale reading** (> 6h since `fetched_at`): desaturate `--water-tint` by
  40% via `color-mix` with grey, and mark the freshness dot as stale.
- **Ocean beach swell warning** (future): out of scope here; hazards list
  already covers surf copy.

## Non-goals

- No homepage changes. The departure board stays as-is even when filtered
  to open water.
- No pool application, indoor or outdoor. Mission Community Pool is
  outdoor but still driven by schedule, not conditions.
- No animation beyond the gentle sine. No particles, no ripples.
- No second color axis for air temperature; v2 at earliest.

## Open questions

- Should Aquatic Park's calmer-water character affect the oscillation
  amplitude (smaller) compared to Ocean Beach? Decide after first render.
- Does the tint fight the hazards list on Ocean Beach (which has the most
  warnings)? Check contrast at the cold end.

## Compatibility with other work

- **Trust Layer**: the freshness dot described above is the minimal
  version called out in the review notes; the full Trust Layer plan can
  supersede without rework.
- **Swim Windows**: detail-page content is untouched by the Water Line —
  only the background plate changes — so a future reframe of the homepage
  as windows has no conflict here.
