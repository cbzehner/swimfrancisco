+++
title = "What moves the bulletin number"
description = "The masthead counter changes when reviewed schedule payloads change, not when the site gets a coat of paint."
date = 2026-05-16
weight = 110

[extra]
kind = "lap_note"
lane = "build"
lane_number = 2
lane_label = "Build"
topic = "LAP NOTE"
commit_sha = "3326715"
history = "ab6f6c9, 3326715"
+++

`BULLETIN 00` is tied to schedule publication, not deploy count.

The generator reads every reviewed schedule payload, hashes the paths
and contents, and stores that fingerprint in `data/bulletin.json`.
If the fingerprint is unchanged, the number stays put. If reviewed
schedule JSON changes, the number increments.

That means a redesign can ship without pretending the schedules were
updated. It also means a small reviewed schedule correction becomes
visible in the masthead.

The number is narrow on purpose. It answers one question: did the
reviewed schedule payload change?
