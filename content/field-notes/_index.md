+++
draft = true
title = "Field Notes"
description = "A technical map of how Swim Francisco turns scattered public swim data into one live board."
sort_by = "weight"
template = "field-notes/index.html"
page_template = "field-notes/page.html"
insert_anchor_links = "left"

[extra]
issue = "01"
+++

Swim Francisco is a small static site wrapped around a messy data
problem. Pool schedules start as city PDFs. Open-water conditions
come from NOAA and NDBC. The board has to answer a human question:
can I swim, where, and what should I know before I leave?

The Swim Lane is the overview. It shows the system as a path from
raw public sources to a swimmer making a decision: source data,
review, build, runtime, board, swimmer.

The lane pages are the deep dives. They explain the core machinery:
where data enters, where it gets trusted, how it ships, how the
Worker refreshes conditions, and how the browser turns schedules into
status.

Lap Notes are shorter. They cover the small incidents that are too
specific for the overview but too sharp to bury: a broken Cloudflare
build hook, a tide station correction, a review guard that refuses
untouched model output, and the bulletin number that moves only when
reviewed schedules change.
