# Spot Detail Page Redesign — Design

**Date:** 2026-04-17
**Status:** Draft for review
**Supersedes:** Frontend steps of [docs/plans/multi-pool-facilities.md](../../plans/multi-pool-facilities.md)

## Context

The current spot detail template (`templates/spots/page.html`) renders a pool's
entire weekly schedule as a 30+ row table with columns `DAY | START | END |
PROGRAM | POOL | NOTES`. It is a faithful dump of the data model but a poor
fit for the user's journey:

- Primary journey (70%): **planning a future visit** — "when does Balboa do
  lap swim this week?" — and the user anchors on **program first, time second**.
- Secondary journey (30%): **confirming right-now** — "can I swim here now,
  and if not when next?"
- The current page forces users to scan day-by-day to answer either question.

The multi-pool-facilities plan added an optional `pool` zone field to the data
model. That plan's remaining work — rendering zones on the detail page and
scoping closures to zones — would currently be implemented as "add a POOL
column, patch status.js" against the existing table. That would harden a
layout we already want to replace. This spec folds those frontend pieces into
a redesigned detail page instead.

## Goals

- Reorganize the weekly schedule to be program-primary (grouped by LAP /
  FAMILY / SENIOR), so the planning journey is a two-second scan.
- Add a "now / today" layer at the top of the page to serve the
  confirmation journey without bouncing users back to the homepage.
- Render zones natively (inline parenthetical) and scope zone-only closures
  correctly, closing out the multi-pool-facilities plan.
- Preserve the departure-board aesthetic (monospace, yellow-on-dark, uppercase)
  — extending it with subtle structure (program group headers, status slab,
  banners) but not breaking with it.
- Land the smallest viable version of one product direction inline:
  - Trust Layer → a facility-level freshness indicator next to
    `LAST VERIFIED`.
- Add cross-nav from LAP and FAMILY program groups back to the homepage
  board filtered by that program. (SENIOR cross-nav is deferred — the
  homepage has no SENIOR filter; adding one is out of scope here.)
- Work at 1200px desktop and 375px mobile.

## Non-goals

- No changes to the schedule extraction pipeline, prompt, schema, or merge
  logic. `content/spots/*.md` frontmatter shape is frozen.
- No full Trust Layer. The footer freshness dot is the only Trust Layer
  element in this spec; per-session freshness / verified / inferred labels
  are a separate project.
- No Time Scrubber of any kind. Neither a `TODAY / TOMORROW` toggle nor
  date offsets nor presets. The detail page renders today's state only.
  Time shifting is a separate project.
- No changes to the homepage board layout or `templates/index.html`. The
  only homepage-adjacent changes are: (1) zone-scoped closure logic in
  `helpers/board.mjs`, (2) `filters.js` accepts a `?filter=<type>` URL
  parameter on load so the cross-nav links from detail pages work. No
  new filter buttons on the homepage (in particular, no SENIOR filter).
- No open-water detail page changes. The `extra.type == "open_water"` branch
  in `page.html` is untouched.
- No sub-day / overnight closure handling. The `closure` schema is
  `YYYY-MM-DD`-only (whole-day granularity). If SF Rec & Parks publishes
  an "afternoon only" closure, it is modeled as a full-day closure or
  omitted — not rendered as a partial banner.

## User journey framing

The detail page is a **planning surface with a real-time header**.

- When the user arrives, the top ~30% of the viewport answers "what about
  right now?" (status slab + today block).
- The rest of the page answers "how do I fit a visit into my week?" (weekly
  program-grouped grid).
- The tail of the page answers "anything I should know?" (upcoming closures,
  description, meta).

The page renders today only. Planning further ahead — "what about next
Saturday?" — is a Time Scrubber concern, out of scope here. For today's
schedule the weekly grid suffices: it shows every day's sessions at a
glance.

Program is the primary dimension because users arrive with a program
preference (lap / family / senior) and want to intersect it with their
available times. Time-anchored multi-pool queries ("where can I swim
Saturday?") are a different surface; the homepage and future Time Scrubber
handle those.

## Page structure

Top to bottom:

1. **Back link** — `← DEPARTURE BOARD`, existing style.
2. **Header** — `<h1>` spot title, address linked to Google Maps, subtype
   (`indoor` / `outdoor`), official-page link. Existing content, same order.
3. **Status slab** — bordered block with two rows: `STATUS` and `NEXT`.
   Server-rendered placeholder (`—`); JS hydrates at load.
4. **Today block** — today's drop-in sessions (lap / family / senior) in a
   compact list with a day heading (`TODAY · <WEEKDAY>`). JS marks the
   current session `● NOW` and the next one `NEXT`. Server-rendered without
   decorations; JS adds them. No toggle, no tomorrow, no date offset — the
   page renders today only.
5. **Weekly grid** — the `WEEKLY · BY PROGRAM` section. Three program rows
   (LAP, FAMILY, SENIOR) × seven day columns (MON–SUN). Sessions stack
   vertically within each cell. Today's column is subtly highlighted. Each
   program row header has a dim right-aligned cross-nav link —
   `→ OTHER LAP POOLS`, `→ OTHER FAMILY POOLS`, etc. — that deep-links to
   the homepage board with that program's filter preselected
   (`/?filter=lap_swim`).
6. **Upcoming closure banner(s)** — one yellow left-border banner per
   closure whose `[start, end]` range overlaps `[today, today+14]`. This
   includes closures already underway (started before today but ending in
   the window) as well as upcoming closures starting within the window.
   Omitted if none.
7. **Description** — existing `{{ page.content }}` prose body, placed below
   the schedule.
8. **Footer meta** — `SCHEDULE EFFECTIVE <start> → <end>` and
   `● FRESH · LAST VERIFIED <date>` (or `· STALE · LAST VERIFIED <date>`
   when the verification is older than 30 days). The freshness dot is the
   smallest viable Trust Layer hint — yellow when fresh, dim when stale —
   and sets up the larger Trust Layer work without pre-engineering for it.

On mobile (< 760px) the weekly grid collapses to program-grouped day stacks:
one `<h3>` per program; each day is a single row with its sessions stacked
inline. Information hierarchy preserved; column count goes from 7 to 1.

## Status slab

Rendered server-side with placeholder values; JS replaces them at load. Two
key-value rows:

- `STATUS` — one of:
  - `OPEN — <program> UNTIL HH:MM` — a single drop-in program is currently
    running. Example: `OPEN — LAP UNTIL 14:00`.
  - `OPEN — <program> + <program> UNTIL HH:MM` — two or more drop-in
    programs run concurrently (different zones, same facility). Programs
    listed in schedule order; `UNTIL` is the earliest end time among the
    overlapping sessions. Example (Balboa Wed): `OPEN — LAP + FAMILY
    UNTIL 15:00`. This is a real state; see `content/spots/balboa-pool.md`
    Wednesday where `lap_swim 12:30–15:00` overlaps `family_swim
    14:00–15:00`.
  - `LESSONS UNTIL HH:MM` — a lessons session is active and no drop-in
    session is concurrently active. (If a drop-in session *is* also active,
    prefer the `OPEN — <program> UNTIL …` form; lessons do not mask
    drop-in availability.)
  - `CLOSED TODAY — <reason>` — today falls inside a facility-wide closure.
  - `CLOSED — NEXT <program> <day> HH:MM` — outside hours on a regular day
    with drop-in sessions elsewhere this week.
  - `NO DROP-IN TODAY — NEXT <program> <day> HH:MM` — today is scheduled
    as lessons-only (no drop-in sessions of any type today). Distinguished
    from `CLOSED` because the facility is not closed, and distinguished
    from `OPEN` because no drop-in program is available.
  - `SCHEDULE NOT YET VERIFIED` — the pool has `last_verified_at` unset or
    the `sessions` array is empty in the verified content. Distinct from
    `NO DROP-IN THIS WEEK`.
  - `NO DROP-IN THIS WEEK` — the pool is verified, but the weekly schedule
    contains zero drop-in sessions (lessons-only pools or off-season).
- `NEXT` — the next drop-in session, as `<PROGRAM> · <DAY> HH:MM`. Suppressed
  when `STATUS` already communicates that info (`CLOSED TODAY`,
  `CLOSED — NEXT …`, `NO DROP-IN TODAY — NEXT …`, `SCHEDULE NOT YET
  VERIFIED`, `NO DROP-IN THIS WEEK`).

State resolution order (first match wins):

1. `SCHEDULE NOT YET VERIFIED` → unverified / empty content.
2. `CLOSED TODAY` → today intersects a facility-wide (no-zone) closure.
3. `OPEN — …` → at least one drop-in session is currently active. Prefer
   over `LESSONS UNTIL …` when any drop-in session overlaps now.
4. `LESSONS UNTIL …` → a lessons session is active and no drop-in session
   is concurrently active.
5. `NO DROP-IN TODAY` → today has lessons sessions but no drop-in sessions
   and no currently-active session.
6. `CLOSED — NEXT …` → today has drop-in sessions but none is active and
   a future drop-in exists this week.
7. `NO DROP-IN THIS WEEK` → verified schedule contains zero drop-in
   sessions of any kind.

All boundary comparisons (active-now, next-session) are evaluated in the
pool's local timezone (America/Los_Angeles) so DST transitions do not
shift perceived session times.

## Today block

Renders only `lap_swim`, `family_swim`, `senior_swim` sessions for the
current day. Heading: `TODAY · <WEEKDAY>`. Suppressed entirely if today
is a closed day (the status slab handles that) or if today has zero
drop-in sessions (the status slab handles that too, via `NO DROP-IN
TODAY`).

```
TODAY · TUESDAY
07:00–08:00   LAP
10:30–12:00   SENIOR
● 12:30–14:00 LAP           NOW
14:30–15:30   FAMILY        NEXT
```

JS adds the `● NOW` prefix and the `NOW` / `NEXT` right-column labels.
Without JS, today's sessions render statically as a plain list with no
decorations. There is no toggle; the detail page renders today only.

## Weekly grid (desktop ≥ 760px)

A CSS grid with one header row and three body rows:

| header  | MON | TUE | WED | THU | FRI | SAT | SUN |
|---------|-----|-----|-----|-----|-----|-----|-----|
| LAP     | ... | ... | ... | ... | ... | ... | ... |
| FAMILY  | ... | ... | ... | ... | ... | ... | ... |
| SENIOR  | ... | ... | ... | ... | ... | ... | ... |

Each body cell contains zero or more time-range entries stacked vertically.
A day with no session for that program renders a dim em-dash. Today's column
has a slightly lighter background fill.

`lessons` sessions are filtered out of the grid. Pools with zero `senior_swim`
sessions omit the SENIOR row (small pools will never need three rows). A pool
with zero drop-in sessions of any kind omits the grid entirely and shows
`Schedule not yet verified.` (same fallback as today).

## Weekly grid (mobile < 760px)

The grid collapses to stacked program sections:

```
LAP SWIM
TUE   07:00–08:00
      12:30–14:00
WED   09:00–10:15
      12:30–15:00 (deep)
THU   07:00–08:00
      11:30–14:00
      14:30–16:00
...

FAMILY SWIM
TUE   14:30–15:30
...
```

One `<h3>` per program, each day as a single row with sessions stacked inline
within the cell. Today's day row has the subtle highlight.

The breakpoint is expressed as a CSS media query on the grid container; the
underlying HTML is the same markup for both viewports. This keeps the
template simple and lets the browser handle the reflow.

## Zones & closures

Zone rendering rule, applied uniformly wherever sessions or closures print:

- When `session.pool` is non-empty, append ` (<zone>)` inline after the time
  range, lowercase, dim-yellow, same font-size as siblings. Example:
  `12:30–15:00 (deep)`.
- When `closure.pool` is non-empty, the closure banner shows e.g.
  `APR 16 · LEISURE POOL · AQUATIC DIVISION TRAINING` — the zone label sits
  between the date and the reason, uppercase.
- When either field is empty (the majority of pools and most closures),
  render nothing extra. Single-zone pools look visually unchanged from today.

Homepage status behavior change (smallest change outside the detail page):

- `helpers/board.mjs` `computeStatus` currently treats any closure as closing
  the facility. It must now treat a closure as facility-closed **only when
  `closure.pool` is empty**. Closures with a non-empty `pool` do not mark the
  facility closed; they only affect the detail page's banner.
- This is the homepage side of the multi-pool-facilities plan, now expressed
  as a single logic change in the existing helper.

## Lessons handling

- Extraction, schema, and merge: unchanged — `lessons` sessions are still
  captured in `content/spots/*.md`.
- Weekly grid: filtered out.
- Today block: filtered out.
- Status slab: the **only** surface where lessons surface. When lessons is the
  active session type, `STATUS` reads `LESSONS UNTIL HH:MM`, and `NEXT`
  points at the next non-lessons session.

The `computeStatus` result gets a new classification field (`is_drop_in:
boolean`) so the template and the slab renderer can treat lessons
consistently without duplicating the type check.

## Aesthetic

- Palette and typography unchanged from the current template: monospace,
  primary yellow `#f3c640` on dark `#131728`. Uppercase applies to **chrome
  only** — status lines, program headers, day labels, cross-nav, footer
  meta. Prose renders in its natural case: closure reasons (e.g.
  "Aquatic division training"), descriptions (`{{ page.content }}` body),
  and error fallbacks are not uppercased.
- New structural elements:
  - Status slab: 1px solid primary border, 10–14px padding, two-column grid.
  - Program group headers: yellow, uppercase, 2px letter-spacing, 1px solid
    rule below.
  - Zone badges: lowercase, dim `#8a7d3c`, parenthetical. Same font-size as
    siblings. No background, no border.
  - Today highlight: `#1f2540` background fill on the current day's column
    (desktop) or row (mobile). Subtle; not a pill.
  - Closure banner: 3px solid primary left border, dim dark-blue background
    fill, primary text.
- No icons, no emoji, no card shadows, no rounded corners beyond 0.

## Implementation surface

**Files changed:**

- `templates/spots/page.html` — pool branch rewritten; open-water branch
  unchanged; common header unchanged.
- `static/js/detail.js` — new module. Handles status slab hydration,
  today-block `● NOW` / `NEXT` decorations, and freshness indicator.
  Imports `computeStatus`, `findNextDropIn`, and `freshnessLabel`.
- `static/js/helpers/board.mjs` — add `findNextDropIn(sessions, closures,
  now)`; add `freshnessLabel(last_verified_at, now)` returning
  `"fresh" | "stale"`; extend `computeStatus` return with `is_drop_in`
  classification and drop-in lesson handling; change closure logic to
  respect `closure.pool`.
- `static/main.css` (or wherever the current CSS lives) — add rules for the
  slab, today block, weekly grid, cross-nav link, freshness dot, closure
  banner, mobile breakpoint.
- `static/js/filters.js` — on page load, read `?filter=<type>` from
  `location.search` and activate the matching filter button. Enables the
  detail page's `→ OTHER LAP POOLS` cross-nav links. Behavior when the
  parameter is absent is unchanged.
- `templates/base.html` — no change (already supports the `scripts` block;
  `detail.js` is included conditionally when `page.extra.type == "pool"`).

**Files unchanged:**

- All extractor code in `src/schedules/`.
- `content/spots/*.md` frontmatter shape.
- `templates/index.html` and its homepage scripts.
- Open-water detail page behavior.

## Testing

- **Unit (`node:test`)** — `static/js/helpers/board.mjs`:
  - `findNextDropIn`: drop-in later today, drop-in rolls to tomorrow, no
    drop-in this week (open water spot-like edge case), skips lessons,
    skips facility-wide closed days, skips today when today is a
    lessons-only day (but returns tomorrow's first drop-in).
  - `computeStatus`:
    - Active lessons with no overlapping drop-in → `LESSONS UNTIL HH:MM`
      with `is_drop_in: false`.
    - Active lessons with a concurrent drop-in session → `OPEN — <program>
      UNTIL HH:MM` (drop-in wins over lessons).
    - Two concurrent drop-in sessions → `OPEN — <a> + <b> UNTIL HH:MM` with
      the earliest end time (Balboa Wed 14:30 case).
    - Lessons-only day, no currently-active session → `NO DROP-IN TODAY —
      NEXT <program> <day> HH:MM`.
    - Zone-scoped closure (non-empty `closure.pool`) does NOT mark facility
      closed; `computeStatus` returns the normal open/closed-by-hours
      result.
    - Facility-wide closure (empty `closure.pool`) returns `CLOSED TODAY`.
    - Verified pool with zero drop-in sessions returns `NO DROP-IN THIS
      WEEK`; unverified pool returns `SCHEDULE NOT YET VERIFIED`.
    - DST transition: a session spec of `10:00–11:00` on the day clocks
      jump forward (second Sunday in March) or fall back (first Sunday in
      November) is evaluated against local wall-clock time, not UTC
      offset. At `now = 10:30 local`, the session is active on both days.
  - `freshnessLabel`: returns `"fresh"` for dates within 30 days of `now`,
    `"stale"` for older, boundary behavior at exactly 30 days.
- **Integration** — `zola build` passes for all nine pools plus all open-water
  spots. No unresolved template errors.
- **Visual** — manual walk-through at 1200px and 375px viewports for:
  - Balboa (zoned, modest density)
  - North Beach (zoned, high density — Wednesday is the stress test)
  - Hamilton (single-zone, populated)
  - MLK (single-zone, low density)
  - Mission Community or Sava (empty `sessions` — fallback text)
  - Aquatic Park (open water — ensure untouched)
- **Regression** — homepage board (`/`) status and closures continue to work
  for all pools. Specifically:
  - A pool with only zone-scoped closures stays OPEN on the homepage.
  - A pool with a facility-wide closure still shows CLOSED TODAY on the
    homepage.
  - Visiting `/?filter=lap_swim` preselects the LAP filter; visiting `/`
    with no query params behaves identically to today.

## Open questions

None blocking. Noted follow-ons (out of scope for this spec):

- When a pool actually gets `pool` zones populated for its sessions, the
  extractor side of the multi-pool-facilities plan needs a human review pass
  to validate North Beach and Balboa PDFs. That is a data task, separate
  from this template work.
- Full Trust Layer (per-session freshness, verified/inferred/missing labels
  on each session) is a separate project. This spec lands only a
  facility-level freshness dot; the richer session-level Trust Layer work
  fits inside the existing grid without structural change.
- iCal subscribe feeds per spot and per program (`?program=lap_swim`) are a
  natural future footer action. They require a feed-generation endpoint
  (likely via the existing worker), which is out of scope here. Placeholder
  for the link belongs in the footer area next to schedule / freshness meta.
- A Time Scrubber (arbitrary date offset, "after work" presets, shared URL
  state, even a `TODAY / TOMORROW` toggle) is a separate spec. This page
  renders today only.

## Acceptance

- All nine pool detail pages render without regressions.
- North Beach and Balboa detail pages render zones inline when
  `session.pool` is set (currently not populated — the mechanism is in place
  and proven on test data, but live zones come with a separate extractor
  pass).
- The homepage board is visually identical and functionally equivalent,
  except that zone-scoped closures no longer close the whole facility.
- Mobile browser at 375px shows the collapsed stacked layout; desktop at
  1200px shows the 7-column grid.
- `zola build` and `node:test` pass in CI.
- Multi-pool-facilities.md plan is archived (frontend steps completed here;
  backend steps already done and crossed off).
