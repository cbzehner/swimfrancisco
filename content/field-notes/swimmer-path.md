+++
title = "Swimmer Path"
description = "How the product turns schedules and conditions into a decision someone can make before leaving home."
date = 2026-05-16
weight = 50
aliases = ["/field-notes/map-view/", "/field-notes/bulletin-redesign/"]

[extra]
kind = "deep_dive"
lane = "swimmer"
lane_number = 5
lane_label = "Swimmer"
topic = "PRODUCT"
cta = "Read the swimmer-path dive"
commit_sha = "ab6f6c9"
history = "ab6f6c9, 26d5165, efc0ec5"
+++

The swimmer path is the user journey through all the machinery.

The technical system exists to answer a small set of questions fast:
what is open, what opens next, how cold is the water, and where is
the spot?

## First Answer First

The homepage leads with the answer. The bulletin hero says the
current horizon and open count. The board sorts by what opens next.
The filter controls stay close to the rows they affect.

That is more than visual polish. It keeps the user from translating
raw schedules into a decision by hand.

## Trust Without A Trust Column

Earlier versions surfaced review metadata directly in the board. It
was accurate, but it made the primary view feel like an audit table.

The current design moves trust into the system itself: reviewed
schedules, source links, detail pages, Field Notes, and footer
attribution. The board stays focused on the swim decision.

## The Bulletin Voice

The redesign stopped treating the board like a neutral dashboard.
Heavy type, hard rules, stamps, and time-of-day language make it feel
like a public city bulletin.

That voice still has to be precise. "Before breakfast" is fun only
when the selected horizon is actually morning. Otherwise it is just a
bug with personality.

## Why There Is No App

There is no account, no saved profile, and no tracking. The board is
a public status page. A swimmer should be able to open it, decide,
and leave.

That constraint shapes the technical choices: static pages, tiny
client modules, one Worker, and no runtime database.
