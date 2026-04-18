// Pure helpers for the departure board. Node's built-in node:test runner —
// no Vitest, no Jest, no jsdom. DOM-mutating logic is kept in status.js /
// filters.js; the branching that matters lives in board.mjs and is tested
// against plain arrays.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  computeStatus,
  sortByRank,
  captureBaselineRanks,
} from "../../static/js/helpers/board.mjs";

test("computeStatus uses 'Closed through' for inclusive end dates", () => {
  // Closure spans 2026-04-15..2026-04-20 inclusive. Today is 2026-04-17.
  // The pool is closed today and reopens on 2026-04-21, so the end date
  // in the copy describes the last closed day, not the first open day.
  const now = new Date("2026-04-17T10:00:00");
  const schedule = {
    sessions: [],
    closures: [
      { start: "2026-04-15", end: "2026-04-20", reason: "maintenance" },
    ],
  };
  const { status, next } = computeStatus(schedule, now);
  assert.equal(status, "CLOSED");
  assert.equal(
    next,
    "Closed through 2026-04-20",
    "inclusive end date must read 'through', not 'until'",
  );
});

test("captureBaselineRanks + sortByRank restores baseline order after reshuffle", () => {
  // Baseline: status.js sorts by OPEN-first + alpha, then captures ranks.
  const baseline = [
    { id: "A" },
    { id: "B" },
    { id: "C" },
    { id: "D" },
  ];
  captureBaselineRanks(baseline, (row, rank) => {
    row.baselineRank = rank;
  });

  // Near Me reshuffles into distance order.
  const reshuffled = [baseline[2], baseline[0], baseline[3], baseline[1]];

  // Near Me off → restore baseline.
  const restored = sortByRank(reshuffled, (row) => row.baselineRank);
  assert.deepEqual(
    restored.map((r) => r.id),
    ["A", "B", "C", "D"],
    "baseline order must be recoverable from captured ranks",
  );
});

test("sortByRank is stable and keeps unknown ranks at the tail", () => {
  const items = [
    { id: "A", rank: 2 },
    { id: "B", rank: 0 },
    { id: "C" }, // no rank
    { id: "D", rank: 1 },
  ];
  const sorted = sortByRank(items, (x) => x.rank);
  assert.deepEqual(sorted.map((x) => x.id), ["B", "D", "A", "C"]);
});

test("computeStatus ignores zone-scoped closures (non-empty closure.pool)", () => {
  const now = new Date("2026-04-17T10:00:00");
  const schedule = {
    sessions: [
      { day: "friday", type: "lap_swim", start: "09:00", end: "11:00" },
    ],
    closures: [
      { start: "2026-04-17", end: "2026-04-17", reason: "training", pool: "deep" },
    ],
  };
  const { status } = computeStatus(schedule, now);
  // 2026-04-17 is a Friday; no session is active at 10:00 (session is 09:00-11:00, so actually active).
  // We expect OPEN because the zone closure does not close the facility, AND a session is live.
  assert.equal(status, "OPEN");
});

test("computeStatus honors facility-wide closures (empty closure.pool)", () => {
  const now = new Date("2026-04-17T10:00:00");
  const schedule = {
    sessions: [
      { day: "friday", type: "lap_swim", start: "09:00", end: "11:00" },
    ],
    closures: [
      { start: "2026-04-17", end: "2026-04-17", reason: "training" },
    ],
  };
  const { status, next } = computeStatus(schedule, now);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Closed through 2026-04-17");
});
