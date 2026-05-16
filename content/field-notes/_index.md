+++
title = "Field Notes"
description = "Notes from building Swim Francisco: the PDF mistakes, water-data edge cases, design turns, and small decisions behind the board."
sort_by = "weight"
template = "field-notes/index.html"
page_template = "field-notes/page.html"
insert_anchor_links = "left"

[extra]
issue = "01"
+++

Swim Francisco started with a dull question before leaving the house:
can I swim right now?

The answer lived in too many places: city PDFs, pool detail pages,
NOAA stations, NDBC buoys, tide tables, and a few facts that only
showed up after the board gave a wrong answer. Field Notes is where I
write those parts down.

The site stays small on purpose. Zola renders the board and spot
pages. One Cloudflare Worker serves the site, refreshes open-water
conditions, and writes one KV record. Pool schedules go through an
LLM, but only behind a review gate; production never calls a model.

The first set of notes follows the bugs and decisions that changed
the shape of the project: PDF extraction, stale water data, Pacific
midnight, the print-bulletin redesign, and the map becoming its own
mode. Next up: outer-coast tide stations, partial-day closures, shared
PDF cells, and the bulletin number tied to reviewed schedule changes.
