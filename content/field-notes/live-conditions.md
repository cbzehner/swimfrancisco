+++
title = "Live conditions without a database"
description = "The Worker fetches NOAA and NDBC data hourly, then serves one cached conditions record."
date = 2026-05-15
weight = 20

[extra]
topic = "WATER"
commit_sha = "188d427"
history = "188d427, f952e4e, c4f86b1, e6aa401"
+++

Open-water rows need live-ish data: bay temperature, ocean
temperature, and tide. Those readings come from NOAA and NDBC, not
from a database I control.

The Worker cron runs once an hour. It fetches station data, assembles
slug-keyed condition records, writes a single KV value at
`conditions`, and lets `/api/conditions` serve that payload to the
browser.

## One Key

The first KV layout had one key per spot plus a bulk key. It sounded
flexible and turned into bookkeeping. Detail pages used the bulk
response anyway, so the cron was doing extra reads and writes for
routes nothing called.

`f952e4e` collapsed the layout to one KV key. That left one request
path: cache hit, or Worker reads `conditions`, returns JSON, and
writes the response to `caches.default`.

## Stale Is Not One Thing

The harder lesson was staleness. A tide station can fail while
temperature is healthy. A temperature station can fail while tide is
fresh. The UI should not mark the whole row stale when only one field
fell back to the previous value.

`188d427` split the stale flag by field:

| Field | Failure behavior |
|---|---|
| Temperature | Try fallback station, then reuse last good value with `temp_stale`. |
| Tide | Reuse last good tide with `tide_stale`, then eventually show a dash. |

That small data-shape change made the board more honest. It also set
the rule for the rest of the project: keep the last good value when a
blank would be worse, but label exactly what happened.

`e6aa401` is the other note worth writing up later. The outer-coast
beaches should not use the same tide prediction station as Aquatic
Park. A board can look polished and still be geographically wrong.
