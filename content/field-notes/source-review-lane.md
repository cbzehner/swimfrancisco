+++
title = "Source + Review Lane"
description = "How city PDFs, source pages, models, and human review become trusted pool schedules."
date = 2026-05-16
weight = 10
aliases = ["/field-notes/pool-schedule-pipeline/"]

[extra]
kind = "deep_dive"
lane = "source-review"
lane_number = 1
lane_label = "Source + Review"
topic = "PDFS"
cta = "Read the source + review dive"
commit_sha = "fd28fc7"
history = "fd28fc7, 2a0ad7c, 4a9958a, c9f9565"
+++

This lane starts before the site exists.

SF Rec & Park publishes schedules as PDFs and detail pages. NOAA and
NDBC publish station readings. None of those sources are shaped like
the board. The first job is not rendering. It is deciding what can be
trusted enough to render.

## What Enters

Pool schedules enter as PDF calendars. Those files are good for
people and awkward for machines. Text extraction follows the visual
layout, not the schedule. A program name can be separated from its
time by another cell, another day, or a page break.

Open-water metadata enters differently. The spot pages carry station
IDs, coordinates, cost, hazards, clubs, and notes. NOAA and NDBC are
runtime sources; the pool PDFs are reviewed build-time sources.

That split matters. A bad live temperature can be marked stale and
retried in an hour. A bad pool schedule can send someone to a closed
pool.

## Why The Model Is Not The Authority

The extractor asks Anthropic or Gemini to turn each PDF into JSON.
That saves transcription time, but it does not make the result true.

The schedule has to pass through a review lane:

| Step | Job |
|---|---|
| Fetch | Download the PDF and key it by SHA. |
| Extract | Ask the model for structured sessions. |
| Ground | Check that extracted rows point back to source text. |
| Validate | Refuse catastrophic changes, like sessions dropping to zero. |
| Review | Compare the draft against the PDF by hand. |
| Project | Write approved data into `content/spots/*.md`. |

The production site never calls a model. By the time Zola builds, the
schedule is reviewed content.

## The Trust Boundary

The important boundary is `reviewed.json`. The model can create a
candidate. The review tool can open it next to the source PDF. Only a
reviewed payload gets projected into site content.

That is why the pipeline refuses byte-identical reviews. If the
reviewed file matches the provider output exactly, the tool assumes
no review happened and stops. It is a small annoyance that protects
the public claim: schedules on the board were checked against the
source.

## What This Lane Produces

The lane outputs ordinary Zola content. That is the payoff. Once
review is done, the rest of the site does not need to know about
models, provider artifacts, or PDF weirdness. It reads frontmatter.
