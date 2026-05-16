+++
title = "The map as a mode"
description = "The map became clearer once the board and footer stopped competing with it."
date = 2026-05-15
weight = 50

[extra]
topic = "MAP"
commit_sha = "efc0ec5"
history = "c2c75e9, efc0ec5"
+++

The map started as another view of the same data. It clicked when it
stopped carrying the whole page with it.

The board answers "what is open next?" The map answers "where is
this in the city?" Those are adjacent questions, but they should not
fight for the same viewport.

## What Stayed

The map keeps the pieces that help geography:

| Piece | Reason |
|---|---|
| Brand header | Keeps the mode grounded in the same site. |
| Type filters | Lets someone compare pools, beaches, lap swims, and family swims. |
| Markers and popups | Keeps spot details one click away. |

## What Left

The board table left the map page. So did the footer and source
sentence. They help on the board. On a phone, they turned the map
into a scrollable sliver.

`efc0ec5` made `/map/` use `body.map-page`, hid the normal footer,
and let `#map-view` fill the remaining viewport under the header and
filters. The change was simple CSS, but it carried a product
decision: map mode is for looking at the map.
