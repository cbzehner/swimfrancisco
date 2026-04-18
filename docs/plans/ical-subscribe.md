---
status: pending
progress: []
last_review: null
iterations: 0
no_progress_count: 0
started_at: null
work_unit_granularity: step
---

# iCal Per-Spot Subscribe

## Context

Raised in past-session magi notes and echoed by the detail-page review: a
natural footer action on each spot page is "add this spot's schedule to my
calendar". Today the weekly schedule is only visible on the page as a
static table. Users re-type sessions into their own calendar by hand.

A single endpoint can serve per-spot feeds generated from the same content
files the site already renders. This slots in after the schedule
extraction and multi-pool work land, because the feed's quality is bounded
by schedule data quality.

## Goal

A subscribe link on every pool detail page that drops a live-updating
feed of that pool's sessions into Apple Calendar, Google Calendar, and
Outlook. Open-water spots get a different treatment (tide events) —
deferred; see "Non-goals".

## Proposed change

### Endpoint

Add to the existing Cloudflare Worker (`worker/`).

- `GET /api/calendar/:slug.ics` — returns `text/calendar; charset=utf-8`
  for the pool with that slug. 404 if slug is unknown or the spot is not
  a pool.
- Cache-Control: `public, max-age=3600` (feed recomputation is cheap, but
  calendar clients already poll on their own schedule).
- ETag over the source content file's `last_verified_at` and `sessions[]`
  hash so unchanged feeds 304.

### Feed content

One `VEVENT` per session instance over a rolling window: today through
+90 days.

- `UID`: `<slug>-<yyyymmdd>-<start>-<type>@swimfrancisco.com` — stable
  across fetches so clients update in place instead of duplicating.
- `SUMMARY`: `LAP SWIM — Hamilton Pool` (session type title-cased, em-dash,
  spot name). Matches the departure-board vocabulary.
- `DTSTART` / `DTEND`: local time in `America/Los_Angeles` with a
  `VTIMEZONE` component. No floating times.
- `LOCATION`: the address from the content file.
- `URL`: `https://swimfrancisco.com/spots/<slug>/`.
- `DESCRIPTION`: short, e.g. `Source: SF Rec & Parks. Verified
  2026-04-16.` Use `last_verified_at`.
- `CATEGORIES`: session type (`LAP_SWIM`, `OPEN_SWIM`, …). Lets power
  users filter inside their calendar.

### Recurrence and zones

Expand each weekly session into concrete instances rather than emitting
`RRULE` + `EXDATE`. Reasoning:

- Closures already have explicit date ranges in `extra.closures[]` —
  expanding lets us simply skip those dates.
- Quarterly schedule changes invalidate `RRULE` assumptions anyway.
- The 90-day window caps feed size at roughly a few hundred events per
  pool, which is well inside calendar-client limits.

For multi-zone facilities (see `docs/plans/multi-pool-facilities.md`),
include the zone in `SUMMARY` when present: `LAP SWIM (Deep) — Balboa`.

### Closures

Any session instance that falls inside an `extra.closures[]` range is
omitted from the feed for the affected zone. The closure itself is not
emitted as an event — this is a schedule feed, not a maintenance feed.

### Frontend

On pool detail pages (`/spots/<slug>/` where `extra.type = "pool"`), add a
footer line:

```
SUBSCRIBE · webcal://swimfrancisco.com/api/calendar/<slug>.ics
```

Style: match the existing back link and official-page link so the three
read as a consistent tier of text links (picked up in the same review
note). Click opens the `webcal://` URL; copy-button for the raw URL for
users whose clients do not handle `webcal://`.

### Non-goals

- Open-water feeds. Those would be tide-event feeds (high/low tide
  warnings, cold-snap thresholds) and are a different product. Defer.
- Per-session-type filtering via query string (`?type=lap_swim`). The
  feed is small enough; users filter in their client.
- "All of SF" aggregate feed. Out of scope for v1 of this plan.
- Authenticated or personalized feeds.

## Failure modes

- **Unknown slug**: 404 with a tiny ics-flavored body so misconfigured
  clients surface a readable error instead of a silent empty feed.
- **Missing `last_verified_at`**: omit the verified-on line from
  `DESCRIPTION` rather than printing "null".
- **No sessions in window** (e.g., Sava during closure through summer
  2026): return a valid empty VCALENDAR with a single event explaining
  the closure window in `DESCRIPTION`. Keeps subscribing users informed
  when the pool reopens.

## Open questions

- `webcal://` vs `https://` link: most modern clients accept either, but
  iOS prefers `webcal://`. Offer both?
- Do we need a `X-WR-CALNAME` and `X-WR-TIMEZONE` for better client
  display? Probably yes — test against Apple Calendar, Google, Outlook,
  Fantastical.
- Rate limiting: is Cloudflare's default enough, or do we need a small
  KV counter? Feed cost is low, so default is fine unless we see abuse.

## Compatibility with other work

- **Multi-pool zones**: feed must include zone in `SUMMARY` once that
  lands. Build after, not before.
- **Trust Layer**: the `DESCRIPTION` verification line is the minimal
  hook; later can include confidence tier.
- **Schedule extraction pipeline (v2)**: nothing to add — the feed reads
  the same content files the site renders.
