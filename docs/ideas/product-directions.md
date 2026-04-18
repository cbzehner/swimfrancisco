# SwimFrancisco Product Directions

Product ideas extracted from the 2026-04-17 review. These are
intentionally kept out of the fix plan (`docs/plans/review-followup.md`)
so they do not get mixed with bug work.

## 1. Swim Windows

Recommended long-term direction.

Reframe the board around time-bounded opportunities instead of static spot
rows. A row becomes a "window" with start, end, confidence, and a short why
instead of just a spot-level status.

Why it matters:

- makes the departure-board metaphor literal rather than decorative
- answers the real user question better than raw spot status
- gives tide, temperature, and schedule data a common unit
- creates a clear path to subscriptions, alerts, and "today's best swim"

## 2. Time Of Departure / Time Scrubber

Best medium-size enhancement.

Let users shift the board forward in time with a scrubber or preset buttons
like "after work" and "tomorrow morning". Turns the homepage from a
"right now" novelty into a planning tool without needing major backend change.

Why it matters:

- solves planning, not just lookup
- makes the split-flap board feel alive
- can be built mostly from schedule and tide data already in hand

## 3. Trust Layer

Best near-term product multiplier after bug fixes.

Expose freshness, verification source, and confidence directly in the UI. Show
which data is verified, stale, inferred, or missing instead of collapsing all
unknowns into em dashes.

Why it matters:

- turns incomplete data into honest utility instead of ambiguity
- complements the schedule extraction work
- raises confidence without changing the core architecture

## Prioritization (post fix-plan)

1. Trust Layer
2. Time Of Departure / Time Scrubber
3. Swim Windows

Rationale:

- trust makes the current product more honest immediately
- time shifting increases daily usefulness without major model change
- swim windows is the strongest concept, but it should land after the data
  and presentation foundations are more trustworthy
