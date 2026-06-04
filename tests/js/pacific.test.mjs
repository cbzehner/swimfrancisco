import { test } from "node:test";
import assert from "node:assert/strict";

import {
  formatPacificDate,
  formatPacificTime,
  pacificWallClockDate,
} from "../../static/js/helpers/pacific.mjs";

test("pacificWallClockDate reflects PT wall-clock during PDT (UTC-7)", () => {
  // 2026-04-19T06:00:00Z during PDT -> 2026-04-18 23:00 PT (Saturday).
  const pt = pacificWallClockDate(new Date("2026-04-19T06:00:00Z"));
  assert.equal(pt.getFullYear(), 2026);
  assert.equal(pt.getMonth(), 3); // April (0-indexed)
  assert.equal(pt.getDate(), 18);
  assert.equal(pt.getDay(), 6); // Saturday
  assert.equal(pt.getHours(), 23);
  assert.equal(pt.getMinutes(), 0);
});

test("pacificWallClockDate reflects PT wall-clock during PST (UTC-8)", () => {
  // 2026-01-15T07:30:00Z during PST -> 2026-01-14 23:30 PT (Wednesday).
  const pt = pacificWallClockDate(new Date("2026-01-15T07:30:00Z"));
  assert.equal(pt.getFullYear(), 2026);
  assert.equal(pt.getMonth(), 0); // January
  assert.equal(pt.getDate(), 14);
  assert.equal(pt.getDay(), 3); // Wednesday
  assert.equal(pt.getHours(), 23);
  assert.equal(pt.getMinutes(), 30);
});

test("pacificWallClockDate straddles midnight PT correctly", () => {
  // 08:00 UTC on 2026-01-15 = 00:00 PST on 2026-01-15.
  const midnight = pacificWallClockDate(new Date("2026-01-15T08:00:00Z"));
  assert.equal(midnight.getDate(), 15);
  assert.equal(midnight.getHours(), 0);
  // One minute earlier -> still 2026-01-14 23:59 PT.
  const justBefore = pacificWallClockDate(new Date("2026-01-15T07:59:00Z"));
  assert.equal(justBefore.getDate(), 14);
  assert.equal(justBefore.getHours(), 23);
  assert.equal(justBefore.getMinutes(), 59);
});

test("formatPacificTime renders a real UTC instant as Pacific time", () => {
  assert.equal(formatPacificTime(new Date("2026-04-19T06:59:00Z")), "11:59 PM PT");
});

test("formatPacificDate renders the Pacific calendar day", () => {
  assert.equal(formatPacificDate(new Date("2026-04-19T06:59:00Z")), "Sat, Apr 18");
});
