+++
title = "Board Lane"
description = "How the browser combines static schedules, live conditions, filters, horizons, and map state."
date = 2026-05-16
weight = 40

[extra]
kind = "deep_dive"
lane = "board"
lane_number = 4
lane_label = "Board"
topic = "BROWSER"
cta = "Read the board dive"
commit_sha = "69764f8"
history = "69764f8, 16f5b5c, 6baf1c6, efc0ec5"
+++

The board lane runs in the browser.

By the time a visitor loads the page, pool schedules are already in
the HTML and open-water metadata is already in the markup. The
browser computes what changes with time: current status, next open
time, horizon labels, filter state, and hydrated water readings.

## Status From Static Data

Pool rows include schedule data. The browser reads that data and
compares it with the current time in San Francisco. That is how a
static page can say "open now" without a live schedule database.

Open-water rows are different. They get water temperature and tide
from `/api/conditions`, then the board updates the visible cells.

## Filters Change The Question

The board does more than hide rows. For pools, a filter can change
the status question.

If someone selects `LAP`, the board should answer "is lap swim open?"
not "is anything at this pool open?" The same applies to family and
senior swim. That rule pushed status computation into shared helper
functions that can be scoped by program type.

## Horizons

The horizon selector lets the board answer for now, morning,
afternoon, evening, and night. That affects sorting, copy, and the
hero stamp.

This is where the redesign becomes technical. If the selected horizon
is tomorrow afternoon, the page copy has to say that. Cute language
only works when it maps to the selected time.

## Map Mode

The map is a board mode, not a second homepage. It keeps the filters
and spot popups, then drops the table and footer so geography can use
the screen. On mobile, that decision matters more than any marker
styling.
