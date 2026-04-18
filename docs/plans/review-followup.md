---
status: pending
progress: []
last_review: null
iterations: 0
no_progress_count: 0
started_at: null
work_unit_granularity: step
---

# SwimFrancisco Review Follow-up Plan

Reference: review performed on 2026-04-17 across source, `zola build`,
`worker/npm run typecheck`, `devenv up`, local `/__scheduled`, and live UI
inspection in headless Chrome.

## Context

The project has a strong core shape:

- static Zola site + small Cloudflare Worker is the right size
- local and production topology match well via `wrangler` assets
- the departure-board aesthetic is distinctive enough to carry the brand

The main drag is not architectural complexity. It is a combination of:

- incomplete pool schedule data
- a few user-visible UI defects
- missing follow-through where live data exists in the API but is not surfaced

This plan does two things:

1. preserve the strongest product ideas from the review so they do not get lost
2. sequence fixes for the concrete issues already identified

## Saved Ideas

### 1. Swim Windows

Recommended long-term direction.

Reframe the board around time-bounded opportunities instead of static spot
rows. A row becomes a "window" with start, end, confidence, and a short why
instead of just a spot-level status.

Why it matters:

- it makes the departure-board metaphor literal rather than decorative
- it answers the real user question better than raw spot status
- it gives tide, temperature, and schedule data a common unit
- it creates a clear path to subscriptions, alerts, and "today's best swim"

### 2. Time Of Departure / Time Scrubber

Best medium-size enhancement.

Let users shift the board forward in time with a scrubber or preset buttons
like "after work" and "tomorrow morning". This turns the homepage from a
"right now" novelty into a planning tool without needing major backend change.

Why it matters:

- it solves planning, not just lookup
- it makes the split-flap board feel alive
- it can be built mostly from schedule and tide data already in hand

### 3. Trust Layer

Best near-term product multiplier after bug fixes.

Expose freshness, verification source, and confidence directly in the UI. Show
which data is verified, stale, inferred, or missing instead of collapsing all
unknowns into em dashes.

Why it matters:

- it turns incomplete data into honest utility instead of ambiguity
- it complements the upcoming schedule extraction work
- it raises confidence without changing the core architecture

## Review Findings To Fix

### 1. Near Me sort does not restore baseline order

Severity: medium

Files:

- `static/js/filters.js`
- `static/js/status.js`

Problem:

`Near Me` mutates DOM order, but turning it off falls back to the mutated order
instead of the original open-first / alphabetical baseline.

Target behavior:

- `status.js` establishes a canonical baseline ordering once
- `filters.js` preserves or can reconstruct that baseline at any time
- toggling `Near Me` off restores the baseline ordering exactly

### 2. Pool closures render as `[object]` on detail pages

Severity: medium

Files:

- `templates/spots/page.html`

Problem:

Pool detail pages iterate closure objects directly instead of rendering their
fields.

Target behavior:

- each closure shows a readable date range and reason
- closures remain useful even when a pool has no verified sessions

### 3. Open-water tide data is present in the API but missing in the UI

Severity: medium

Files:

- `templates/spots/page.html`
- `static/js/conditions.js`

Problem:

The Worker returns tide predictions, the template reserves a tide field, but
the frontend only injects water temperature.

Target behavior:

- open-water detail pages show a readable tide summary
- the summary is robust when predictions are missing or stale
- temperature and tide formatting live in one place instead of being improvised

### 4. Closure phrasing is semantically wrong for inclusive end dates

Severity: low

Files:

- `static/js/status.js`

Problem:

The status logic treats closure `end` as inclusive, but the user-facing copy
says `Closed until <end>`, which implies reopening on that date.

Target behavior:

- active closures use copy consistent with inclusive ranges
- preferred wording: `Closed through YYYY-MM-DD` or `Reopens YYYY-MM-DD`

## Success Criteria

- pool detail pages render closure dates and reasons correctly
- open-water detail pages render both water temp and tide from live data
- `Near Me` on/off is reversible and deterministic
- closure copy matches the actual schedule semantics
- at least one lightweight regression layer exists for the status/filter or
  formatting logic so these bugs are harder to reintroduce

## Execution Plan

### Step 1: Fix detail-page data rendering

- render `closures[]` objects explicitly in `templates/spots/page.html`
- preserve the current visual style while making date ranges readable
- verify on `sava-pool` and `mission-community-pool`

Definition of done:

- no pool detail page shows `[object]`
- `zola build` succeeds

### Step 2: Wire tide data through the open-water detail UI

- extend `static/js/conditions.js` to format and inject tide data
- decide on one compact summary format for the detail page
- keep graceful fallback behavior when the API is unavailable

Definition of done:

- `aquatic-park` and `ocean-beach` show non-placeholder tide data locally
- homepage temperature injection still works

### Step 3: Make board ordering reversible

- give each row a stable baseline rank after `status.js` sorts the board
- make `filters.js` sort from that rank when `Near Me` is inactive
- ensure the map view follows the same visible ordering assumptions

Definition of done:

- toggling `Near Me` on and off restores the exact baseline row order
- hash restoration and filter combinations still behave correctly

### Step 4: Fix closure copy semantics

- update `computeStatus()` copy for active closures
- if using `Reopens`, compute the next day explicitly; otherwise use
  `Closed through` and avoid date math ambiguity

Definition of done:

- active closures no longer imply reopening on the closure end date

### Step 5: Add lightweight regression coverage

Preferred path:

- extract or expose pure helpers for status, ordering, and conditions
- cover them with a minimal Node-based test layer in-repo

Fallback path:

- if a JS test harness is too heavy right now, add a small verification script
  plus documented manual checks that run in CI-friendly fashion later

Definition of done:

- at least one automated check covers the bugs fixed in Steps 2-4

## Verification

- `zola build`
- `worker/npm run typecheck`
- `devenv up`
- trigger `http://localhost:8787/__scheduled`
- inspect:
  - `/`
  - `/map/`
  - `/spots/aquatic-park/`
  - `/spots/sava-pool/`
- specifically verify:
  - `Near Me` restores baseline ordering
  - tide is rendered on open-water detail pages
  - closures render correctly on pool detail pages

## Post-Fix Prioritization

Once the defects above are fixed, the next best sequence is:

1. Trust Layer
2. Time Of Departure / Time Scrubber
3. Swim Windows

Rationale:

- trust makes the current product more honest immediately
- time shifting increases daily usefulness without major model change
- swim windows is the strongest concept, but it should land after the data and
  presentation foundations are more trustworthy
