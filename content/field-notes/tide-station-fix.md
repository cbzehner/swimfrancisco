+++
title = "The tide station was too far inside the bay"
description = "Outer-coast beaches needed an ocean-coast tide station, not the same station as Aquatic Park."
date = 2026-05-16
weight = 120

[extra]
kind = "lap_note"
lane = "runtime"
lane_number = 3
lane_label = "Runtime"
topic = "LAP NOTE"
commit_sha = "e6aa401"
history = "e6aa401"
+++

Aquatic Park and Ocean Beach are both in San Francisco, but they are
not the same water.

An early version treated the bay tide station as good enough for all
open-water spots. That made the board look consistent while quietly
being wrong for the outer coast. Ocean Beach, Baker Beach, and China
Beach needed an ocean-coast station.

The fix was small: configure the right tide station for those spots.
The lesson was larger. A polished board can make bad geography feel
official. Station IDs are product decisions, not just config.
