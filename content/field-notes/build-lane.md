+++
draft = true
title = "Build Lane"
description = "How reviewed content becomes static pages, Worker spot data, and the visible bulletin number."
date = 2026-05-16
weight = 20
aliases = ["/field-notes/static-site-live-time/"]

[extra]
kind = "deep_dive"
lane = "build"
lane_number = 2
lane_label = "Build"
topic = "ZOLA"
cta = "Read the build dive"
commit_sha = "174a259"
history = "174a259, bbfb982, ee12b98, 3326715"
+++

The build lane turns reviewed content into files the Worker can
serve.

Zola renders the board, spot pages, map page, and Field Notes. The
same spot content also feeds a generated Worker module, so the cron
knows which open-water stations belong to which slug.

## Static First

Pool schedules ship in the HTML. Each pool row carries enough
schedule data for the browser to answer "open now?" without calling a
database.

That keeps the build lane simple:

| Input | Output |
|---|---|
| `content/spots/*.md` | Board rows and spot detail pages. |
| Reviewed schedules | Embedded schedule data attributes. |
| Open-water spot metadata | Generated Worker spot config. |
| Reviewed payload fingerprint | `data/bulletin.json`. |

The static page is not dumb. It contains the data needed for the
browser to compute status at the current minute.

## The Bulletin Number

The masthead says `BULLETIN 00` because schedule data has a
fingerprint. The generator hashes reviewed schedule payloads and
increments the issue number when that fingerprint changes.

CSS changes do not move the number. Copy changes do not move the
number. A reviewed schedule payload does.

That makes the bulletin number a publication marker instead of
decoration.

## The Build Hook Lesson

The generated Worker spot file used to be produced inside a Wrangler
build hook. It worked locally and broke in Cloudflare Workers Builds
because the relative path resolved from a different directory.

The simpler design won: commit the generated file, regenerate it
before local typecheck, and let a parity test fail if content and
Worker spot data drift.

The build lane should be boring. It is allowed to generate files, but
it should not hide deployment assumptions inside clever hooks.
