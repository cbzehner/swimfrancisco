// Locks in the branch selection for the scheduled handler. Two UTC crons
// cover the year (`5 7 UTC` = 00:05 PDT; `5 8 UTC` = 00:05 PST), and the
// hourly `0 * * * *` must always fall through to NOAA refresh — including
// at 00:00 PT. These inputs cover PDT midnight, PST midnight, the hourly
// edge case at 00:00 PT, and an arbitrary non-midnight tick.

import { test } from "node:test";
import assert from "node:assert/strict";

import { classifyTick } from "../../worker/src/schedule.ts";

test("PDT midnight (5 7 UTC on 2026-06-15) → rebuild", () => {
  assert.equal(classifyTick(Date.UTC(2026, 5, 15, 7, 5)), "rebuild");
});

test("PST midnight (5 8 UTC on 2026-01-15) → rebuild", () => {
  assert.equal(classifyTick(Date.UTC(2026, 0, 15, 8, 5)), "rebuild");
});

test("hourly tick at 00:00 PT (PDT, 2026-06-15 07:00 UTC) → refresh", () => {
  assert.equal(classifyTick(Date.UTC(2026, 5, 15, 7, 0)), "refresh");
});

test("hourly tick at 12:00 PT (PST, 2026-01-15 20:00 UTC) → refresh", () => {
  assert.equal(classifyTick(Date.UTC(2026, 0, 15, 20, 0)), "refresh");
});

test("off-PT-midnight daily tick (PST on 2026-06-15 08:05 UTC = 01:05 PDT) → refresh", () => {
  // During PDT, the PST cron `5 8 UTC` lands at 01:05 PT, not midnight.
  assert.equal(classifyTick(Date.UTC(2026, 5, 15, 8, 5)), "refresh");
});
