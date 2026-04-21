# Tide Horizon & Phase — Design

**Date:** 2026-04-19
**Status:** Draft for review (revised after magi review 2026-04-19)

## Context

All five open-water spots currently display only the single next-upcoming
tide extremum fetched from NOAA. Two user-visible shortcomings:

1. **Uniformity across spots.** All five open-water records share NOAA
   station 9414290 (documented in `docs/spec.md`). This is correct — NOAA
   does not publish separate prediction stations for Baker, Ocean, or
   China Beach; 9414290 is the authoritative reference for the SF Gate
   region. Subordinate-station offsets exist but their correction is
   small (≤15 min timing, ≤10% amplitude) and does not change tide
   *phase*, which is what actually drives swim decisions. This spec
   accepts the shared-station display as correct and does not introduce
   subordinate offsets.
2. **Horizon is too narrow.** The dominant SF open-water use case is
   planning a dawn swim the night before. "Next low at 11:42 pm" shown
   at 9 pm doesn't answer "when's the tide change tomorrow morning." A
   longer horizon on the detail page closes that gap.

This spec adds **current-phase + time-to-next-turn** to the index row
and a **remaining-today-plus-tomorrow** extrema list to the spot detail
page. It does not change which NOAA station is used, introduce
subordinate-offset logic, or fetch any current (as opposed to tide)
data.

## Goals

- Index row: show tide phase (`EBBING` / `FLOODING`) and the time of
  the next extremum (labeled `NEXT TURN`), replacing the current
  "next low/high" display.
- Detail page: show a list of all tide extrema from "now" through end
  of tomorrow PT, with a "now / ebbing or flooding" header row and
  today/tomorrow grouping.
- Keep the departure-board voice: uppercase, monospace, no charts or
  continuous-curve visualizations.
- Preserve last-good fallback behavior.

## Non-goals

- No subordinate-station offsets. All five spots show identical tide
  data sourced from 9414290.
- No tide charts, curves, or graphical visualizations.
- No 7-day reference table.
- No per-spot tide annotations (e.g. "flood pushes you to the sauna at
  Aquatic Park"). Written commentary belongs in the spot description.
- **No current-slack fetch.** NOAA's `currents_predictions&max_slack`
  product publishes actual slack-current times that differ from tide
  extrema by ~1–2 hours at the Gate. Supporting it would require
  per-spot `current_station_id` config, a parallel worker fetch/cache/
  fallback path, and UI to present two time series. Deferred until a
  concrete pull-request-worth use case exists (most plausible: a
  Crissy Field Gate-crossing user). See the "Vocabulary" note below
  for how we avoid promising slack semantics in v1 UI.

## Vocabulary

NOAA publishes two distinct products:

- `predictions` with `interval=hilo` → tide *water-level* extrema (highs
  and lows). This is what we fetch.
- `currents_predictions` with `max_slack` → times when tidal *current*
  velocity passes through zero. Not fetched.

In a constricted basin like SF Bay, slack current and tide extrema can
differ by 1–2 hours. Using "slack" to label what is actually a
water-level extremum would be semantically wrong. **We use `TURN`
instead** for every user-visible reference, since the direction of the
rise/fall is genuinely turning at each extremum.

## v1 Correctness Limitations (known, acknowledged)

- **Phase is inferred, not provided.** NOAA returns extrema; the phase
  between them is derived (between a H and the next L = ebbing;
  between a L and the next H = flooding). Correct for normal
  semidiurnal tides in SF. Diurnal irregularities or missing extrema at
  the bounds of the fetched window are handled by the fallback rules
  below.
- **Tide turn is not slack current.** See Vocabulary above. The UI
  avoids "slack" wording entirely to stay honest.

## Data

### Worker — `fetchNoaaTides` extension

Replace the current `date: "today"` request with an explicit range that
covers **today 00:00 through end of tomorrow 23:59 in Pacific time**.
The begin-date is anchored to the calendar day, not "now rounded to
hour," so the window is stable across hourly cron ticks within a day.

```ts
const params = {
  product: "predictions",
  datum: "MLLW",
  interval: "hilo",
  begin_date: "YYYYMMDD 00:00",  // today 00:00 PT
  end_date:   "YYYYMMDD 23:59",  // tomorrow 23:59 PT
  time_zone:  "lst_ldt",          // local standard / local daylight
};
```

NOAA's datagetter accepts multi-day ranges for `hilo`. The response
shape is unchanged; `predictions[]` grows from ~2–4 entries to ~4–8.

**Plan-phase TODO:** before merging worker changes, manually issue a
sample `curl` to NOAA with the exact parameter shape above and confirm
the response parses. NOAA's parameter interactions (particularly
timezone) are notoriously finicky.

### KV schema — `TideSummary`

No new fields. `TideSummary` stays as raw extrema:

```ts
export interface TideSummary {
  station_id: string;
  predictions: Array<{ time: string; type: "H" | "L"; value_ft: number }>;
}
```

Consumers must not assume the array is bounded at 4 entries.

No `phase` or `next_turn` on the stored summary. The magi-review
rationale: the client must derive these at minute granularity anyway
(see "Phase derivation" below), so storing derived fields earns nothing
and creates a second source of truth that drifts between cron ticks.
Single source of truth is `predictions[]`; derivation happens in
exactly one place.

### Phase derivation — `computeTideDisplay(conditions, now)`

Lives in `static/js/helpers/tide.mjs`, which already exists and
currently exports `formatTideSummary(record, now)` returning a compact
string. This spec **replaces** `formatTideSummary` with
`computeTideDisplay` returning a structured result (contract below).
`static/js/conditions.js` and any other call sites migrate to the new
API in the same change.

Tide values are **entirely client-rendered** — neither Tera templates
nor the 00:05 PT rebuild populate tide fields server-side. The build
renders a shell with placeholder `TIDE —` cells, and `conditions.js`
fetches `/api/conditions` and calls `computeTideDisplay` on load and
on every minute tick to fill them in. No server-side port of the
helper is required.

**Contract:**

```ts
type Extremum = { time: string; type: "H" | "L"; value_ft: number };

type TideDisplay =
  | { kind: "ok";
      phase: "ebbing" | "flooding";
      nextTurn: Extremum;              // the first extremum strictly after now
      today: Extremum[];               // PT today, time > now
      tomorrow: Extremum[];            // PT tomorrow, all entries
      stale: boolean;                  // record-level stale flag, pass-through
    }
  | { kind: "horizon_exhausted"; stale: boolean }   // all extrema are in the past
  | { kind: "no_data"; stale: boolean };            // conditions.tide === null
```

Rules:
- `kind = "no_data"` iff `conditions.tide === null`.
- Otherwise find the first extremum with `time > now` (strict greater
  than — so an extremum exactly at `now` is treated as "already past").
  - None found → `kind = "horizon_exhausted"`.
  - Found as `next` →
    - `kind = "ok"`
    - `phase = "ebbing"` if `next.type === "L"` else `"flooding"`
    - `nextTurn = next`
    - `today = predictions.filter(p => p.time > now && sameDayPT(p.time, now))`
    - `tomorrow = predictions.filter(p => sameDayPT(p.time, addDaysPT(now, 1)))`

`now` is the browser's local time, interpreted as station-local per the
existing `tide.mjs` comment — prediction times come from the worker as
zoneless ISO strings in station-local time, so `new Date(p.time)`
parsed in the browser lines up with a locally-constructed `now`. No
explicit PT conversion is needed in the helper; the semantics are
inherited from the worker's `toLocalIso` output.

## Rendering

### Index row

Replace the current next-high/next-low display with a single line:

- `kind = "ok"` →
  - `EBBING · NEXT TURN 2:34 PM` or
  - `FLOODING · NEXT TURN 8:17 PM`
- `kind = "horizon_exhausted"` → `TIDE — CHECK BACK AFTER 00:05 PT`
  (stale-enough fallback already ran out; the 00:05 rebuild will
  refresh predictions)
- `kind = "no_data"` → `TIDE —`

One line. Same row height as today. Identical across all five
open-water spots (honest per Context section 1).

### Detail page

A new TIDE section on `templates/spots/page.html`, replacing the
existing tide render:

```
TIDE  (SF — 9414290)
  NOW    EBBING · NEXT TURN 2:34 PM

  TODAY
  LOW     2:34 PM   0.3 FT  ← next
  HIGH    8:51 PM   5.1 FT

  TOMORROW
  LOW     3:12 AM   0.9 FT
  HIGH    9:47 AM   5.9 FT
  LOW     3:58 PM   0.2 FT
  HIGH   10:19 PM   5.0 FT
```

Rendering rules:
- **Header line:** `NOW    <phase> · NEXT TURN <hh:mm>`.
- **Grouping:** split into TODAY / TOMORROW by PT calendar day.
- **`today[]` is already filtered** to `time > now`, so every entry
  rendered is strictly after `now`. The `← next` marker sits on the
  first row of the first non-empty bucket.
- **Empty TODAY bucket:** render a single line `TODAY — no more tide
  changes`, then the TOMORROW block.
- **`kind = "horizon_exhausted"`:** hide the whole TIDE section and
  render only the status line from the index-row rule above.
- **`kind = "no_data"`:** hide the whole TIDE section.

Typography inherits the existing TIDE row's — no new tokens.

## Implementation surfaces

- `worker/src/noaa.ts` — `fetchNoaaTides` takes a PT date range instead
  of `date: "today"`. Window computed from today 00:00 through tomorrow
  23:59 PT, formatted as `YYYYMMDD HH:mm` for NOAA's `lst_ldt` zone.
- `worker/src/assemble.ts` — `tideToSummary` unchanged (no new
  fields). Existing last-good fallback behavior preserved.
- `static/js/helpers/tide.mjs` (new) — implements
  `computeTideDisplay(conditions, now)` matching the contract above.
  Exports the discriminated-union type for the renderer.
- `templates/index.html` — tide cell stays as a placeholder
  (`TIDE —`) populated client-side; only CSS / DOM structure may need
  tweaks to accommodate the phase-line wording.
- `templates/spots/page.html` — render a TIDE section scaffold
  (heading, TODAY / TOMORROW containers) that `conditions.js`
  populates from `computeTideDisplay`.
- `static/js/helpers/tide.mjs` — replace `formatTideSummary` with
  `computeTideDisplay` per the contract above.
- `static/js/conditions.js` — consume the new return shape; render
  index-row phase line and detail-page TODAY / TOMORROW lists on load
  and on every minute tick. Handle the three `kind` variants.
- Tests:
  - Worker test: extended `fetchNoaaTides` issues a PT-day range
    request and parses ≥ 4 predictions. Manual curl verification
    noted as a pre-merge TODO.
  - JS helper test: `computeTideDisplay` covers
    - (a) mid-afternoon: today non-empty, tomorrow full, phase correct.
    - (b) 11:58 pm: today empty (or one remaining), tomorrow full.
    - (c) all extrema in past: `kind = "horizon_exhausted"`.
    - (d) `conditions.tide === null`: `kind = "no_data"`.
    - (e) extremum exactly at `now`: filtered out (strict `>` semantics).
    - (f) stale flag propagates through all three kinds.

## Open questions

- Should the index row show the numeric height of the next turn (e.g.
  `EBBING · NEXT TURN 2:34 PM · 0.3 FT`) or just the time? Leaning
  time-only for row compactness; height is on the detail page already.
  Revisit in the plan phase.

## Acceptance

- Worker emits a `TideSummary` with `predictions[]` covering today
  through tomorrow PT (4–8 entries typically). No new fields.
- All five open-water rows render identical phase lines (expected —
  shared station).
- Detail page's TIDE section splits into TODAY / TOMORROW, with the
  `← next` marker on the correct extremum.
- An extremum whose time is exactly `now` is treated as already past
  (strict `>`), so the header and list agree.
- `kind = "horizon_exhausted"` and `kind = "no_data"` render distinct
  copy per the rules above.
- Last-good fallback continues to work when NOAA is unreachable; the
  `stale` flag propagates through all three kinds.
- `zola build` passes; `uv run pytest`, `node --test tests/js/*.test.mjs`,
  and `npm run typecheck` (in `worker/`) all pass.
