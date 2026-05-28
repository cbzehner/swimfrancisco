+++
draft = true
title = "Runtime Lane"
description = "How one Worker serves the site, refreshes water data, caches conditions, and survives partial upstream failures."
date = 2026-05-16
weight = 30
aliases = ["/field-notes/live-conditions/"]

[extra]
kind = "deep_dive"
lane = "runtime"
lane_number = 3
lane_label = "Runtime"
topic = "WORKER"
cta = "Read the runtime dive"
commit_sha = "c4f86b1"
history = "f952e4e, 188d427, c4f86b1, e6aa401"
+++

Runtime has two jobs: serve the site and keep open-water conditions
fresh.

One Cloudflare Worker owns both. Static assets come from the build.
`/api/conditions` comes from KV, usually through Cloudflare's edge
cache. The scheduled handler refreshes water data once an hour.

## One Conditions Record

The first KV layout had one key per spot plus a bulk key. The site
used the bulk response, so the per-spot keys were extra moving parts.

The current layout writes one value at `conditions`. The request path
is short:

1. Check `caches.default`.
2. On miss, read `conditions` from KV.
3. Return the JSON response.
4. Write the response back to edge cache.

That is the whole runtime read path for water data.

## Hourly Cron

The scheduled handler fetches station data, assembles condition
records, and writes KV. It also checks whether the scheduled event
landed at Pacific midnight. If it did, the Worker triggers a static
site rebuild so weekday detail pages roll over.

This keeps the site from needing a separate scheduler. The hourly job
already exists; midnight is one branch inside it.

## Partial Failure Is Normal

Stations fail in pieces. Temperature can disappear while tide is
fresh. Tide can fail while temperature is fine. The board should not
mark a whole row stale when only one field reused old data.

That is why stale flags are per field:

| Field | Runtime behavior |
|---|---|
| Temperature | Try primary station, fallback station, then last good value. |
| Tide | Try the configured station, then last good value. |
| Old fallback | Eventually becomes `null` and renders as a dash. |

The rule is practical: keep the last good value when a blank would be
worse, but label exactly what came from storage.
