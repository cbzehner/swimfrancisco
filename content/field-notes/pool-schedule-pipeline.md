+++
title = "The pool schedule pipeline"
description = "PDF schedules go through models, but reviewed JSON is the only thing allowed onto the board."
date = 2026-05-15
weight = 10

[extra]
topic = "PDFS"
commit_sha = "fd28fc7"
history = "fd28fc7, 2a0ad7c, 4a9958a, c9f9565"
+++

The city publishes pool schedules as PDFs. That sounds manageable
until a calendar grid has to become data.

The first pass used regex over extracted PDF text. It failed the way
PDF calendars usually fail: extraction follows the visual layout, not
the schedule. A program label can land on one line, its time range
several cells later, with an unrelated day in between. Tight regex
missed sessions. Loose regex invented them.

The current pipeline treats the model as a transcriber, not an
authority. Anthropic or Gemini turns the PDF into structured JSON.
The repo checks the result before it can touch `content/spots/*.md`.

## The Review Gate

Four checks do most of the work:

| Guardrail | Purpose |
|---|---|
| SHA cache | Reuse a reviewed schedule when the source PDF has not changed. |
| Grounding | Make every extracted row point back at evidence in the PDF text. |
| Validation | Refuse catastrophic drops, like a pool going from sessions to zero. |
| Human review | Require edited, approved `reviewed.json` before projection to content. |

`fd28fc7` is the commit that made grounding fit the source. A literal
substring check sounded safer, but these PDFs split evidence across
lines and cells. The working check asks whether the important tokens
appear in order inside a small window of the source text.

`2a0ad7c` tightened the human part. If the reviewed file is
byte-identical to the model output, the tool refuses it. That sounds
annoying, but it protects the core promise: the production site shows
reviewed schedules, not untouched model guesses.

## What Changed

The pipeline stops before full automation. Weekly extraction can open
a PR, but a person still decides what is safe to publish. The model
saves transcription time. It does not get write access to the board.

That boundary is why the static site can be boring. By the time Zola
builds, the schedule is just frontmatter that was approved against a
specific PDF SHA.
