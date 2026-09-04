---
status: implemented
progress:
  - "First pass from ~/Downloads/handoff/*"
  - "Second pass aligned to ~/Downloads/direction-print.jsx and ~/Downloads/direction-print-mobile.jsx"
last_review: null
iterations: 0
no_progress_count: 0
started_at: null
work_unit_granularity: step
---

# Aquatic Park Print Redesign

## Context

Claude Design first handed off a partial Aquatic Park Print package in
`~/Downloads/handoff/`. The package contains:

- `README.md`
- `templates/base.html`
- `static/main.css`

The README also references `templates/index.html` and
`templates/spots/page.html.patch`, but those files are not present in the
handoff directory. Treat the README snippets as the source for those template
changes.

The missing source later appeared in the recently downloaded `~/Downloads/*.jsx`
files, especially `direction-print.jsx`, `direction-print-mobile.jsx`,
`prototype.jsx`, `data.jsx`, and `print-extras.jsx`. Those files became the
source of truth for the second implementation pass.

Note: the implementation plan below records the first-pass handoff strategy.
The final implementation follows the JSX source where it differs: the board is
now the print-source five-column layout (`SPOT`, `STATUS`, `NEXT`, `WATER`,
`LOCALE`), detail pages have the shared print header/strip, and mobile uses the
sticky compact header plus fixed three-tab nav pattern from
`direction-print-mobile.jsx`.

The current site is a Zola static site with small DOM-enhancement modules in
`static/js/`. The redesign should preserve that shape: no framework, no new
build step, and no new data model.

## Goal

Replace the split-flap board look with the Aquatic Park Print bulletin look:
cream paper, heavy ink rules, red/teal/ochre accents, a board hero, a compact
conditions strip, cost badges, reskinned spot details, and matching map
markers/popups.

## Design Review Improvements

These changes improve the handoff before implementation while keeping the
migration small.

### Keep The Board In The First Viewport

The proposed hero is visually strong, but Swim Francisco's core job is still
"where can I swim right now?" The board must remain visible or clearly peeking
on common mobile and desktop viewports.

Implement the hero as a compact bulletin masthead:

- Use a smaller clamp than the handoff's `clamp(48px, 9vw, 96px)`.
- Keep the deck to one short line where possible.
- Keep the controls and first board rows above the fold on desktop.
- On mobile, allow the hero to compress before the board controls, not push the
  board into a second-screen landing-page feel.

### Make Hero Copy Match The Active Horizon

The handoff says "`places open right now`", but the existing board supports
`?when=` horizons such as later today and tomorrow morning. Avoid a hero that
says "right now" while the board is showing a future window.

Use one of these approaches:

- Easiest: hero count always means the current real-time open count, and the
  copy explicitly says `open now`.
- Better: add a small `data-open-count-label` hook and update copy to match
  the selected horizon, e.g. `available later today`.

Do not duplicate the horizon state machine. Read from the existing
`status.js`/board state and degrade to dashes if unavailable.

### Replace Or Ground The Sun Strip Item

The current `/api/conditions` response does not include sunrise or sunset.
Adding a solar calculator or another upstream source just for the strip is not
worth the complexity in this pass.

Prefer replacing `Sun` with `Updated` for v1:

- Use the newest/representative `updated_at` value already returned by the
  Worker.
- Label stale fields through existing `temp_stale` / `tide_stale` data if
  there is room.

If `Sun` stays in the design, implement it as a separately tested helper and
do not block the visual migration on it.

### Avoid Hardcoding The Paid Price

The handoff renders paid pools as `$7`, but the content model only promises
`cost = "paid"` or `cost = "free"`. Hardcoding a price creates a data accuracy
problem if SF Rec & Park fees change.

Use `Paid` for v1, or add an explicit `fee_label` content field in a separate
data migration. Keep free spots as `Free`.

### Add A Stronger Open-Water Safety Cue

The print palette makes open-water spots attractive, but beach rows should not
read as equivalent to supervised pool lanes. Keep open-water rows accessible,
but visually distinguish them:

- Use the teal open-water marker on the map.
- Keep board status for beaches as access-oriented (`OPEN` / `ACCESS`) rather
  than implying lifeguarded safety.
- On open-water detail pages, keep hazards and conditions high on the page and
  visually prominent in the print style.

### Preserve Performance And Progressive Enhancement

The handoff adds three external font families. This is acceptable for the first
pass, but verify the page remains readable before fonts load.

Implementation guardrails:

- Keep system-font fallbacks in CSS.
- Do not hide text while fonts load.
- Preserve no-JS behavior: board rows, detail pages, and navigation still work
  with dashes for live values.

### Tighten Accessibility During Visual Review

The handoff uses heavy ink and saturated accent colors. Verify the actual
render, not just the CSS:

- Keyboard focus remains visible on buttons, links, menu items, and map popup
  controls.
- Red/teal/ochre are not the only status indicators.
- Mobile tap targets are at least 44px high for controls.
- Text inside sharp buttons does not clip with loaded fonts.
- The cream paper background maintains sufficient contrast for muted metadata.

## Implementation Plan

### 1. Base Head

Apply the handoff's `templates/base.html` changes:

- Change theme color from `#1a1a2e` to `#f1e6cf`.
- Add Google Fonts preconnects and the Archivo / Archivo Black /
  JetBrains Mono stylesheet before `main.css`.

Keep the existing footer and block structure unchanged.

### 2. CSS Migration

Use `~/Downloads/handoff/static/main.css` as the starting point, but do not
copy it blindly. Patch it for the current live markup and house style:

- Preserve `.status-slab-row { display: contents; }`; the current template
  wraps label/value pairs in row divs, and the handoff CSS otherwise makes the
  slab grid layout collapse.
- Preserve the current responsive board behavior that hides TYPE, STATUS, and
  TEMP on phones, leaving SPOT and NEXT visible. The handoff only hides TYPE
  and STATUS.
- Fix weekly-grid right borders without assuming seven visible day columns;
  this app intentionally omits days with no drop-in hours.
- Keep `.weekly-grid-rowlabel .weekly-grid-crossnav` behavior from the current
  CSS so desktop uses the crossnav strip and mobile re-enables inline links.
- Add styling for `.conditions` on open-water detail pages; the handoff styles
  hazards/clubs/distances but not the current conditions panel.
- Remove negative letter-spacing in the handoff CSS and use zero or positive
  spacing instead.

No selectors used by `status.js`, `filters.js`, `detail.js`, or `map.js`
should be renamed.

### 3. Homepage Template

In `templates/index.html`, add the bulletin hero and strip immediately after
the site header and before `<noscript>`.

Add the README's `data-*` hooks:

- `data-open-count`
- `data-bay-temp`
- `data-ocean-temp`
- `data-today-date`
- `data-pt-time`
- `data-bay-temp-strip`
- `data-ocean-temp-strip`
- `data-next-tide`
- `data-sun-range`

Add a cost badge inside the existing SPOT cell for each row. Use the existing
`page.extra.cost` frontmatter, which is already present for all 14 spots.

Keep the table columns unchanged: SPOT, TYPE, STATUS, NEXT, TEMP.

### 4. Conditions Hydration

Extend `static/js/conditions.js` in one pass after `/api/conditions` returns:

- Continue hydrating open-water row temps and open-water detail conditions.
- Populate the new hero/strip fields when present.
- Derive bay temperature from a bay-side record such as `aquatic-park` or
  `crissy-field`.
- Derive ocean temperature from an ocean-side record such as `ocean-beach` or
  `baker-beach`.
- Use the existing `formatTideSummary(record, nowInPacific())` helper for the
  next tide display.
- Derive Today and Time client-side in Pacific time; no Worker schema change is
  needed.
- Prefer an `Updated` strip value from existing `updated_at` data instead of a
  `Sun` value unless the design explicitly keeps the sun item.
- Populate open count after statuses have been applied. Listen for
  `sf:status-applied` / `sf:horizon-changed` and count visible open/available
  rows from the current board cells.

If data is missing, leave the existing em dash placeholders.

### 5. Spot Detail Template

Replace the current bare back-link plus `<header>` block in
`templates/spots/page.html` with a `.spot-detail-head` section based on the
handoff snippet.

Adjust the snippet before applying:

- Keep the existing `place_href`, `apple_dir`, and `google_dir` URL logic.
- Include `OFFICIAL PAGE` when `extra.website` exists; the handoff snippet
  omits it.
- Include setpoint text for pools when `extra.setpoint_label` exists.
- Do not split titles into only the first two words. That would lose names
  like `Martin Luther King Jr. Pool` and `Crissy Field / East Beach`.
  Instead, render the full title and optionally accent only the final word or
  first significant word with a safer template pattern.
- Add the cost badge for free/paid spots. Use `Paid` unless a specific
  `fee_label` content field exists; do not hardcode `$7` from the design
  mockup.

Leave the existing status slab, today block, weekly grid, closures,
open-water lists, and meta footer markup intact.

### 6. Map Marker Classification

Patch `static/js/map.js` marker class generation:

- `open_water` gets `sf-marker sf-marker-open-water`.
- Open pools keep `sf-marker sf-marker-open`.
- If a near-future "soon" state is introduced later, use
  `sf-marker-soon`; do not invent it in this pass without a current data
  source.

This is purely visual. Keep Leaflet loading and popup data unchanged.

### 7. Tests

Update or add render tests in `tests/test_site_render.py`:

- Homepage includes `.bulletin-hero`, `.bulletin-strip`, and cost badges.
- Cost badges are rendered for both free and paid spot examples.
- Detail pages render `.spot-detail-head`.
- Long multi-word titles still render fully on detail pages.
- Existing schedule and closure tests continue to pass.

Add JS tests only for pure helpers if `conditions.js` grows a small exported
formatter. Otherwise keep the conditions-strip behavior covered by browser
smoke review rather than testing private DOM glue.

### 8. Verification

Run:

- `zola build --output-dir /tmp/swimfrancisco-redesign --force`
- `just test-js`
- `just typecheck-worker`
- `just test-python` if the local Python environment is ready

Then run the live review shape from the runbook:

- `devenv up`
- `just refresh-conditions`
- Inspect `http://localhost:8787/`
- Inspect `http://localhost:8787/map/`
- Inspect at least one pool detail page and one open-water detail page

Visual checklist:

- Homepage hero and strip render without overlap on desktop and mobile.
- First board rows remain visible, or visibly begin, in the initial viewport on
  common desktop and mobile sizes.
- Header controls, horizon menu, filters, table, and cost badges match the
  print palette.
- Hero copy does not contradict the active `?when=` horizon.
- Board row click/navigation and hash/query state still work.
- Conditions strip hydrates when `/api/conditions` is available and degrades
  to dashes otherwise.
- Every strip value is backed by existing data or intentionally omitted.
- Map markers distinguish open water from pools.
- Pool weekly grid stacks correctly on mobile.
- Open-water detail conditions panel remains legible.

## Known Handoff Gaps

- The handoff folder is missing two files named in its README.
- The README says "no JS changes" and later requests JS changes. Implement the
  explicit JS changes for `conditions.js` and `map.js`.
- The new CSS expects `.status-slab` children to participate directly in the
  grid, but the current template uses `.status-slab-row` wrappers.
- The weekly-grid CSS assumes a fixed seven-day grid, while the current
  template intentionally renders only days with drop-in sessions.
- The title-splitting detail-page snippet would truncate important spot names.

## Rollback

The rollback should remain one static-site revert:

- `templates/base.html`
- `templates/index.html`
- `templates/spots/page.html`
- `static/main.css`
- `static/js/conditions.js`
- `static/js/map.js`
- related tests

No content or Worker schema migration is part of this plan.
