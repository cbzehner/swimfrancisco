+++
title = "A static site that knows what time it is"
description = "The board stays static, but pool status still follows the clock."
date = 2026-05-15
weight = 30

[extra]
topic = "TIME"
commit_sha = "174a259"
history = "174a259, bbfb982, ee12b98"
+++

Swim Francisco is static HTML until time matters.

Pool schedules are embedded into the board as data attributes. The
browser reads that schedule and computes the current status against
the visitor's clock: open now, closed, next open time. That keeps the
homepage accurate to the minute without rebuilding every minute.

Spot pages are different. They render the current weekday in the
weekly grid, and that markup comes from Zola. At midnight Pacific,
the static HTML becomes a day old.

## The Midnight Tick

The Worker already had an hourly scheduled event for open-water
conditions. `174a259` made that same cron responsible for the daily
rebuild. If the scheduled event lands during Pacific hour `00`, the
Worker POSTs to the Workers Builds deploy hook.

That keeps the deployment model small:

| Job | Owner |
|---|---|
| Pool row status | Browser, from embedded schedule JSON. |
| Open-water data | Worker cron, hourly. |
| Static weekday markup | Worker cron, once per Pacific day. |

## The Build Hook That Broke

`bbfb982` is the cautionary note. A generated `worker/src/spots.ts`
file used to be produced from a Wrangler build hook. It worked
locally and failed in Cloudflare Workers Builds because the relative
path resolved from a different working directory.

The fix was plain: commit the generated file, regenerate it before
local typecheck, and let a parity test fail if it drifts from
`content/spots/*.md`.

That is the rule this project keeps rediscovering: if the system can
be boring, let it be boring.
