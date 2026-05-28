+++
draft = true
title = "Why untouched model output is refused"
description = "The review tool rejects byte-identical drafts so model output cannot pass as human review."
date = 2026-05-16
weight = 140

[extra]
kind = "lap_note"
lane = "source-review"
lane_number = 1
lane_label = "Source + Review"
topic = "LAP NOTE"
commit_sha = "2a0ad7c"
history = "2a0ad7c"
+++

The review tool opens the model payload and the source PDF side by
side. The reviewer edits or approves the draft, then the tool writes
`reviewed.json`.

There is one annoying guard: if the reviewed file is byte-identical
to the model output, the tool refuses it.

That blocks a subtle failure mode. Without the guard, "reviewed" can
mean "the file was opened and saved." For a swim schedule, that is
not enough. The site should not publish untouched model output under
a human-review label.

The guard is blunt, but it protects the boundary that matters most in
the schedule pipeline.
