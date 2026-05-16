+++
title = "The bulletin redesign"
description = "The interface started working when it stopped acting like a generic status dashboard."
date = 2026-05-15
weight = 40

[extra]
topic = "DESIGN"
commit_sha = "ab6f6c9"
history = "ab6f6c9, 69764f8, 26d5165"
+++

The redesign started to work when the site became a bulletin.

The old version was understandable, but it stood like a small
dashboard. The current version borrows from city posters, pool
signage, stamps, and the print language around Aquatic Park: heavy
type, hard rules, paper, red, teal, and blunt controls.

## The First Screen

The board still does the same job, but the first screen now has an
opinion:

| Element | Job |
|---|---|
| `SWIM SAN FRANCISCO.` | Make the site unmistakably about this city. |
| Horizon copy | Say whether this is now, morning, afternoon, evening, or night. |
| Stamp | Repeat the operational answer without feeling like a form field. |
| Bulletin number | Show that schedule payloads have a visible publication rhythm. |

A few regressions made the rule clear. Repeating the dropdown value
as the hero title felt dead. Always saying "before breakfast" was
cute but wrong. The copy can be playful, but it has to map to the
selected time of day.

## The Number

The masthead says `BULLETIN 00` because the schedule payload has a
fingerprint. It increments when reviewed schedule JSON changes, not
when CSS changes, map copy changes, or a favicon gets swapped.

That makes the number part of the publication system instead of
decoration. A future note should show the generator and the test that
proves the counter moves when `reviewed.json` changes.
