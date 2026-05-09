// Locks in the rebuild gate. The hourly cron `0 * * * *` fires every UTC
// hour; the handler also triggers a rebuild on the tick that lands at
// 00:00 PT. Inputs cover PDT midnight, PST midnight, an off-midnight PT
// tick during PDT, and a midday non-rebuild tick.

import { test } from "node:test";
import assert from "node:assert/strict";

import { isPtMidnight } from "../../worker/src/schedule.ts";

test("PDT midnight (07:00 UTC on 2026-06-15) → rebuild", () => {
  assert.equal(isPtMidnight(Date.UTC(2026, 5, 15, 7, 0)), true);
});

test("PST midnight (08:00 UTC on 2026-01-15) → rebuild", () => {
  assert.equal(isPtMidnight(Date.UTC(2026, 0, 15, 8, 0)), true);
});

test("hourly tick at 12:00 PT (PST, 2026-01-15 20:00 UTC) → no rebuild", () => {
  assert.equal(isPtMidnight(Date.UTC(2026, 0, 15, 20, 0)), false);
});

test("01:00 PT during PDT (2026-06-15 08:00 UTC) → no rebuild", () => {
  // The PST-midnight UTC hour (08:00) is 01:00 PT during PDT — must not rebuild.
  assert.equal(isPtMidnight(Date.UTC(2026, 5, 15, 8, 0)), false);
});

test("23:00 PT during PST (2026-01-15 07:00 UTC) → no rebuild", () => {
  // The PDT-midnight UTC hour (07:00) is 23:00 PT during PST — must not rebuild.
  assert.equal(isPtMidnight(Date.UTC(2026, 0, 15, 7, 0)), false);
});
