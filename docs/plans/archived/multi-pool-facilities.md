> **Archived — 2026-04-21.** Frontend work (zone rendering on detail pages,
> zone-scoped closure logic on the homepage, detail-page layout) shipped via
> [`docs/plans/archived/2026-04-18-spot-detail-redesign.md`](2026-04-18-spot-detail-redesign.md)
> and the design spec
> [`docs/specs/archived/2026-04-17-spot-detail-redesign-design.md`](../../specs/archived/2026-04-17-spot-detail-redesign-design.md).
> Backend extractor work described here (populating `session.pool` from PDFs
> for multi-zone facilities) has been partially delivered by reviewer-driven
> zone labeling in `data/reviews/**/reviewed.json`; no further planned work
> is carried forward under this plan.

---

---
status: archived
archived_at: 2026-04-21
progress: []
last_review: null
iterations: 0
no_progress_count: 0
started_at: null
work_unit_granularity: step
---

# Pool Zones (Multi-Tank and Partitioned Pools)

## Context

`content/spots/<slug>.md` treats each facility as a single pool with one flat
`extra.sessions[]` and `extra.closures[]`. That is wrong whenever a facility
runs concurrent programs on different pieces of water — either physically
separate tanks or partitioned sections of a single tank.

Two observed cases in SFRP PDFs:

- **North Beach Pool** has a main lap tank and a separate leisure/dive tank
  that run concurrent programs. The reviewed North Beach Tuesday has
  `senior_swim 12:50–15:15` and `lap_swim 12:30–15:00` at the same moment —
  those cannot coexist in one tank.

- **Balboa Aquatics Center** has one pool but carves it into deep and
  shallow ends that host different programs at the same hour. Tuesday
  2:30–3:30pm shows a cell labeled `REC/FAMILY SWIM / LAP SWIM
  (shallow / deep) (Lap until 4pm)` — two session types, two sections, and
  one of them stretches past the common end.

The extractor observes both patterns as overlapping same-type or
simultaneous-different-type rows that look like duplicates or column drift.
The current grounding check cannot explain why — the evidence strings are
legitimate PDF content.

## Failure modes in the current model

- Overlapping rows look like extraction bugs when they are actually
  concurrent sessions in different zones of the water.
- Closures that apply to one zone ("leisure pool drained for resurfacing")
  mark the whole facility closed on the homepage.
- Frontend `/spots/<slug>/` detail pages cannot describe which zone a
  session happens in.

## Proposed change

Add an optional `pool: string` field to each `extra.sessions[]` and
`extra.closures[]` entry. The value is the zone label as printed on the
PDF, lowercased and stripped of the trailing word "pool":

- `deep`, `shallow`, `deep / shallow`, `shallow / deep`
- `lap/therapy`, `leisure`, `dive`
- Omitted when the PDF shows no zone label (meaning: the whole pool).

The extractor prompt instructs: if a cell has a parenthetical section label,
copy it into `pool`; if a cell contains two session types separated by `/`
or `&`, emit one session per type and assign zones in the same order the
PDF lists them.

Downstream integration:

- `src/schedules/merge.py` preserves `pool` (and `notes`) through merge —
  done.
- `static/js/status.js` ignores `pool` initially. All sessions render
  together.
- `templates/spots/page.html` later groups the weekly schedule table by
  `pool` when the field is populated.
- `static/js/status.js` later uses `pool` on closures so only the affected
  zone is marked closed.

## Scope

- Schema additions only; no rewrite of the homepage or detail-page data
  flow in this pass.
- Confined to North Beach and Balboa today. Other SFRP facilities may gain
  the field later if PDFs reveal zone labeling.

## Critical files

- `src/schedules/schema.py` — `pool` on session and closure items (done)
- `src/schedules/prompts/extract.txt` — describe when to populate `pool`
  (done)
- `src/schedules/merge.py` — preserve `pool` and `notes` during merge
  (done)
- `templates/spots/page.html` — optional grouping by `pool`
- `static/js/status.js` — ignore initially; later use for closures

## Verification

- Unit: extractor populates `pool` on Balboa and North Beach and leaves it
  absent on single-zone pools like Hamilton and Rossi.
- End-to-end: North Beach and Balboa detail pages render the zones'
  schedules distinctly.
- Regression: homepage status continues to compute correctly when `pool`
  is missing.

## Open questions

- Canonical names for the two North Beach tanks. The PDF uses informal
  labels ("Main", "Leisure", "Dive"); pick one naming convention.
- Whether private bookings (SFUSD) that close one zone should be modeled
  as per-pool closures or as a new closure reason with `pool` set.
