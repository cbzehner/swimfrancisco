# Access Providers — Design

**Date:** 2026-04-19
**Status:** Draft for review (revised after magi review 2026-04-19)

## Context

The current open-water data model (`content/spots/<slug>.md`) represents
associated swim clubs as a flat `clubs: string[]` — e.g. Aquatic Park lists
`["South End Rowing Club", "Dolphin Swimming & Boating Club"]`. The strings
render as flavor text and carry no schedule data.

In practice, the clubs gate the *facilities* at Aquatic Park (sauna, showers,
changing rooms) on specific public-access days. A swimmer planning a visit
needs to know whether today is a Dolphin day or a South End day and when
the building closes — the same "can I go right now / when next?" question
that `sessions[]` answers for pools.

Other swim spots in the region have similar-but-not-identical gating:

| Spot class | Example | What gates access? |
|---|---|---|
| SF Rec pool | Balboa | Facility hours + session type |
| Protected cove + clubs | Aquatic Park | Water: always. Facilities: club public days |
| NPS urban beach | Baker, Ocean, Crissy | Nothing. 24/7, no lifeguards |
| NPS/State beach | Stinson, Muir, HMB state beaches | Park hours (often 9am–sunset), seasonal lifeguards |
| University / private pool | UCSF Bakar, SFSU | Membership or public hours (uses `sessions[]`, not `access[]`) |

The common shape for the open-water classes: a spot has one or more
**access providers**, each with a schedule and a scope. This spec
introduces that abstraction for open-water spots, populates it with
verified Dolphin and South End data, and leaves a partial extension path
for future beach classes (see caveats in the "Extension path" section).

## Goals

- Add `extra.access[]` to the open-water schema, with verified Dolphin and
  South End data on Aquatic Park.
- Render per-access status on the index row and expanded/detail view —
  "Dolphin open until 5pm" today, "South End opens Tue 9am" otherwise.
- Preserve the current always-open status for spots with no `access[]`
  entries (Baker, Ocean, Crissy, China).
- Leave room for future beach classes without schema revision where
  possible; be honest about where schema-level work is still required.

## Non-goals

- No pool schema changes. Pools continue to use `extra.sessions[]`.
  Unifying pools onto `access[]` is not planned; university and private
  pools will use `sessions[]` when added.
- No new spot types. Adding Stinson, Pacifica, HMB, or university pools
  is out of scope.
- No tide work. Tide direction + countdown is the next spec.

## v1 Correctness Limitations (known, acknowledged)

- **Federal and state holidays.** Dolphin's documented "no public access
  on state or federal holidays" and any equivalent SERC rule are **not**
  honored by the status computation in v1. On a federal-holiday Monday,
  the Aquatic Park row will read "DOLPHIN — OPEN UNTIL 5:00 PM" when the
  club is actually closed. The `notes` string warns users, but the status
  line is incorrect. A structured holiday-exclusion mechanism is future
  work. Ship this as a known inaccuracy, not as an undiscovered bug.

## Data Model

### Schema — `extra.access[]`

Each entry represents one entity that gates or augments access to the
spot. Multiple entries are allowed; order is display order.

```toml
[[extra.access]]
name = "Dolphin Swimming & Boating Club"
website = "https://dolphinclub.org"
public_access_url = "https://dolphinclub.org/swimming/#public-access-id"  # optional
scope = "facilities"          # "water" | "facilities" | "parking" | "lifeguarded_zone"
gates = "amenity"             # "spot" | "amenity"
fee = "$12 cash/check, $12.67 credit"  # free-form display string, optional
notes = "Closed on state/federal holidays. 18+. Waiver required."  # optional

[[extra.access.schedules]]
season_start = "05-01"        # optional MM-DD; omit BOTH for year-round
season_end = "10-31"
public_days = ["monday","wednesday","friday"]
open = "08:00"
close = "17:00"

[[extra.access.schedules]]
season_start = "11-01"
season_end = "04-30"
public_days = ["monday","wednesday","friday"]
open = "09:00"
close = "17:00"
```

### Field reference

- **`name`**, **`website`**, **`public_access_url`** — identity and
  external links. `public_access_url` optional.
- **`scope`** — what the provider controls. v1 uses `facilities` only.
  Reserved values: `water` (entry to the water itself), `parking` (park
  gates), `lifeguarded_zone` (seasonal lifeguard coverage). The scope
  drives display labels, not status logic.
- **`gates`** — how this provider affects the spot's row-level status.
  - `"spot"` — when this provider is closed, the spot is closed.
    Intersected with any other `gates = "spot"` providers; if all are
    closed, the row shows CLOSED. Aquatic Park has **zero** `gates =
    "spot"` providers today.
  - `"amenity"` — when this provider is closed, only the amenity is
    closed. The spot's row-level status is unaffected; the provider
    renders as a sub-status line ("DOLPHIN — OPEN UNTIL 5:00 PM" or
    "DOLPHIN — OPENS WED 9:00 AM").
- **`schedules[]`** — nested array of weekly schedules with optional
  seasonal windows. Invariants:
  1. **Season fields are both-or-neither.** Either both `season_start`
     and `season_end` are present (non-empty MM-DD strings) or both are
     absent. A single present field is a build-time error.
  2. **Seasons may wrap Dec 31.** If `season_start > season_end`
     lexicographically (e.g. `"11-01"` to `"04-30"`), the window wraps
     through Jan 1. Date-in-window check supports wrap.
  3. **Non-overlapping seasons.** Within one `access` entry, no two
     `schedules[]` seasons may overlap on any day of the year. This
     includes wrap-aware comparison. Build-time error on overlap.
  4. **Feb 29.** A schedule active on Feb 29 of a leap year is also
     active on Feb 28 of non-leap years (i.e. treat Feb 29 as Feb 28
     when the current date is Feb 28 in a non-leap year and no schedule
     matches Feb 28 directly). Simpler restatement: membership check is
     by month/day pair, with Feb 29 collapsing to Feb 28 in non-leap
     years.
  5. **Off-season is closed.** If no `schedules[]` entry matches today,
     the provider is treated as closed today; next-open is computed from
     the next upcoming matching schedule.
- **`fee`** and **`notes`** — free-form display strings; no semantics.

### Field removal

- `extra.clubs: string[]` on open-water spots is removed. It is only
  populated on Aquatic Park today and is superseded by `access[].name`.
- Templates referencing `clubs` are updated to render from `access[]`.
- `docs/spec.md` is updated to reflect the new schema.

### Fields NOT in v1 (YAGNI, deferred)

- **`kind`.** Earlier drafts included a `kind` discriminator ("club" |
  "park_hours" | "lifeguard" | "facility"). No v1 rendering or logic
  branches on it. Defer until a concrete consumer needs it. `scope`
  already carries the display-relevant semantic; `gates` already carries
  the status-logic semantic.
- **Structured holidays.** See v1 Correctness Limitations above.

## Content changes — Aquatic Park

```toml
[[extra.access]]
name = "Dolphin Swimming & Boating Club"
website = "https://dolphinclub.org"
public_access_url = "https://dolphinclub.org/swimming/#public-access-id"
scope = "facilities"
gates = "amenity"
fee = "$12 cash/check, $12.67 credit"
notes = "Closed on state/federal holidays. 18+. Waiver required."

[[extra.access.schedules]]
season_start = "05-01"
season_end = "10-31"
public_days = ["monday","wednesday","friday"]
open = "08:00"
close = "17:00"

[[extra.access.schedules]]
season_start = "11-01"
season_end = "04-30"
public_days = ["monday","wednesday","friday"]
open = "09:00"
close = "17:00"

[[extra.access]]
name = "South End Rowing Club"
website = "https://serc.com"
public_access_url = "https://serc.com/faq"
scope = "facilities"
gates = "amenity"
fee = "$12 cash/check + Venmo deposit, or $13 Venmo"
notes = "Guest book + waiver required. Boats and kayaks members only."

[[extra.access.schedules]]
season_start = "06-01"
season_end = "11-30"
public_days = ["tuesday","thursday","saturday"]
open = "09:00"
close = "17:00"

[[extra.access.schedules]]
season_start = "12-01"
season_end = "05-31"
public_days = ["tuesday","thursday","saturday"]
open = "08:00"
close = "17:00"
```

Both clubs verified directly from official sources on 2026-04-19
(`dolphinclub.org/swimming`, `serc.com/faq`). `last_verified_at` on the
spot is updated accordingly.

## Rendering

### `computeAccessStatus(spot, now)` — contract

Shared by server-side templates (Tera via helper) and the client-side
minute-level JS updater. Pinned shape so both consumers agree.

**Input:**
- `spot` — the parsed spot object, with `spot.access[]`.
- `now` — a Date interpreted in Pacific time (reusing the existing PT
  convention; see MEMORY note on server-rendered day-tick-over).

**Output:**

```ts
type ProviderState = "open_now" | "opens_later_today" | "closed_today";

type AccessProviderStatus = {
  name: string;            // provider.name, for display
  scope: string;           // provider.scope
  gates: "spot" | "amenity";
  state: ProviderState;
  // When state == "open_now": the close time today.
  // When state == "opens_later_today": today's open time.
  // When state == "closed_today": the next upcoming open instant.
  //
  // Always a wall-clock instant in PT, expressed as { weekday, hhmm }
  // so the renderer doesn't carry Date objects through templates.
  nextTransition: { weekday: Weekday; hhmm: string };
  // The schedule entry selected for today. null when off-season.
  currentSchedule: ScheduleEntry | null;
};

type AccessStatus = {
  providers: AccessProviderStatus[];   // order matches spot.access[]
  spotOpen: boolean;                   // see row rollup below
  spotNextTransition: { weekday, hhmm } | null; // null when spotOpen === true
};
```

### Row rollup (used by `spotOpen`)

1. If no provider has `gates = "spot"` → `spotOpen = true`,
   `spotNextTransition = null`. Aquatic Park falls in this branch: the
   water is always accessible; amenity providers affect sub-status only.
2. If any `gates = "spot"` provider is in `state = "open_now"` →
   `spotOpen = true`.
3. Otherwise → `spotOpen = false`, and `spotNextTransition` is the
   earliest `nextTransition` across all `gates = "spot"` providers.

### Per-provider state

For each provider:

1. Select the `schedules[]` entry whose season window contains today
   (with wrap-aware and Feb-29 rules above). If none, `currentSchedule =
   null`, `state = "closed_today"`, and `nextTransition` is the next
   upcoming open instant across *any* future-matching schedule.
2. Given `currentSchedule`:
   - `state = "open_now"` if today's weekday ∈ `public_days` and
     `open ≤ now.hhmm < close` → `nextTransition = { today, close }`.
   - `state = "opens_later_today"` if today's weekday ∈ `public_days`
     and `now.hhmm < open` → `nextTransition = { today, open }`.
   - Otherwise `state = "closed_today"` and `nextTransition` is the next
     upcoming open instant across all matching schedules, respecting
     season windows.

### Index row (open-water)

Current DOM (`templates/index.html`) has one STATUS cell and one NEXT
cell per row. Mobile expansion (`static/js/expand.js`) assumes a single
status/next pair. Sub-lines per provider need explicit placement:

- **Placement:** a new `<div class="access-sublines">` inserted *inside*
  the expanded-row body, below the hazards/distances lines. Not in the
  main STATUS / NEXT cells (those continue to reflect `spotOpen` only).
- **Content:** one `<div class="access-subline">` per provider. Format:
  - `open_now`: `DOLPHIN — OPEN UNTIL 5:00 PM`
  - `opens_later_today`: `DOLPHIN — OPENS TODAY AT 9:00 AM`
  - `closed_today`: `DOLPHIN — OPENS MON 9:00 AM`
- **Typography:** uppercase, monospace, amber-on-navy (inherits row
  styles). No new color tokens.
- **Intra-day updates:** the existing minute-level JS updater reads
  `AccessStatus.providers[]` and rewrites each subline's text content.
  Day-tick transitions are owned by the 00:05 PT server rebuild, as
  today.

### Detail page

On `templates/spots/page.html`, replace the flat `clubs` render with an
ACCESS section — one block per provider. Simplified from the earlier
draft: no weekly grid, no off-season dim rows.

```
ACCESS
─────────────────────────────────────
DOLPHIN SWIMMING & BOATING CLUB
OPEN UNTIL 5:00 PM · facilities
MON WED FRI · 8:00–17:00
FEE  $12 cash/check, $12.67 credit
NOTE Closed on state/federal holidays. 18+. Waiver required.
dolphinclub.org/swimming
```

Each block shows: name, today's status line, **current-season schedule
only** (single weekday + time line), fee, notes, link. The current
season is indicated by absence of a qualifier when one schedule is
active today; when off-season, show the next-upcoming schedule with a
prefix like `NEXT SEASON (NOV 1–APR 30): MON WED FRI · 9:00–17:00`.

## Implementation surfaces

- `docs/spec.md` — update open-water schema section, add access-provider
  reference.
- `content/spots/aquatic-park.md` — replace `clubs = [...]` with the
  `[[extra.access]]` entries.
- `helpers/board.mjs` (or wherever the server-rendered today column is
  computed) — add `computeAccessStatus(spot, now)` matching the contract
  above. Reuses the existing Pacific-time convention and 00:05 PT
  rebuild.
- `templates/spots/page.html` — replace the clubs block with the ACCESS
  section.
- `templates/index.html` — add `.access-sublines` block to expanded-row
  body.
- `static/js/*` — intra-day updater calls `computeAccessStatus` once per
  minute and rewrites subline text. Day-tick owned by server rebuild.
- **Schema validation (build time).** A Python check (co-located with
  existing content validation) enforces the `schedules[]` invariants:
  both-or-neither season fields, non-overlapping wrap-aware seasons.
  `zola build` fails when a spot frontmatter violates these.
- Tests:
  - Python site-render test: Aquatic Park emits an ACCESS block with
    both clubs; Baker Beach does not.
  - Python schema-validation test: a spot with (a) only `season_start`,
    (b) overlapping seasons — both fail the build with clear errors.
  - JS helper test: `computeAccessStatus` covers (a) open now, (b) opens
    later today, (c) closed today with next-open in same season, (d)
    closed today with next-open in next season, (e) season wrap across
    Dec 31, (f) Feb 28 in a non-leap year matching a Feb-29-active
    schedule.

## Extension path (informational — partial, not "free")

The schema accommodates some but not all future beach classes without
revision. Be honest about which:

- **Seasonal lifeguard coverage** — fits cleanly. New `access` entry
  with `scope = "lifeguarded_zone"`, `gates = "amenity"`, and a
  seasonal weekday schedule. No schema change.
- **NPS/State beach park hours** — fits *partially*. Coarse posted
  hours (e.g. "8am–5pm Mon–Sun") map to `scope = "parking"`, `gates =
  "spot"`, with a standard `open`/`close`. But "sunset" closing hours
  are a function of latitude and date; expressing them requires either
  (a) a `"sunset"` sentinel plus an astronomical calculation in the
  renderer, or (b) pre-computed seasonal approximations. Neither is in
  this spec. Adding Stinson or similar is a schema *concept* reuse but
  a renderer extension.
- **University / private pools** — do **not** migrate to `access[]`.
  They remain `type = "pool"` with `sessions[]`. Non-member public
  hours become `sessions[]` entries tagged appropriately. Unifying
  pools onto `access[]` is explicitly not planned.

## Open questions

- Off-season display on the detail page: show "NEXT SEASON: …" inline,
  or hide until closer to the transition? Revisit in the plan phase.
- SERC does not publish a dedicated public-access URL; link goes to the
  FAQ (`serc.com/faq`). Acceptable.

## Acceptance

- Aquatic Park's index row shows correct per-club sub-status for each
  of: (a) a Monday 10am in summer (Dolphin OPEN UNTIL 5:00 PM; South
  End OPENS TUE 9:00 AM), (b) a Saturday 11am in winter (South End
  OPEN UNTIL 5:00 PM; Dolphin OPENS MON 9:00 AM).
- A federal-holiday Monday shows "DOLPHIN — OPEN UNTIL 5:00 PM"
  (documented v1 inaccuracy — see correctness limitations).
- Other open-water spots render exactly as before.
- Schema validator rejects invalid `schedules[]` configurations at
  build time.
- `zola build` passes; `uv run pytest` and `node --test tests/js/*.test.mjs`
  pass.
