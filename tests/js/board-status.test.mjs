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
  findNextDropIn,
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

const DROP_IN_SCHEDULE = {
  sessions: [
    { day: "tuesday",  type: "lap_swim",    start: "07:00", end: "08:00" },
    { day: "tuesday",  type: "lessons",     start: "15:30", end: "16:00" },
    { day: "tuesday",  type: "family_swim", start: "14:30", end: "15:30" },
    { day: "wednesday",type: "lap_swim",    start: "09:00", end: "10:15" },
  ],
  closures: [],
};

test("findNextDropIn returns the next drop-in later today", () => {
  const now = new Date("2026-04-14T10:00:00"); // Tuesday 10:00 local
  const next = findNextDropIn(DROP_IN_SCHEDULE, now);
  assert.deepEqual(next, { program: "family_swim", day: "tuesday", start: 14 * 60 + 30 });
});

test("findNextDropIn rolls to tomorrow after today's last drop-in", () => {
  const now = new Date("2026-04-14T17:00:00"); // Tuesday 17:00, after all Tue drop-ins
  const next = findNextDropIn(DROP_IN_SCHEDULE, now);
  assert.deepEqual(next, { program: "lap_swim", day: "wednesday", start: 9 * 60 });
});

test("findNextDropIn skips lessons sessions", () => {
  const lessonsOnly = {
    sessions: [
      { day: "tuesday", type: "lessons", start: "15:30", end: "16:00" },
      { day: "thursday", type: "lap_swim", start: "07:00", end: "08:00" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-14T14:00:00"); // Tuesday before lessons
  const next = findNextDropIn(lessonsOnly, now);
  assert.deepEqual(next, { program: "lap_swim", day: "thursday", start: 7 * 60 });
});

test("findNextDropIn skips facility-wide closed days", () => {
  const withClosure = {
    sessions: [
      { day: "tuesday", type: "lap_swim", start: "07:00", end: "08:00" },
      { day: "wednesday", type: "lap_swim", start: "09:00", end: "10:15" },
    ],
    closures: [
      { start: "2026-04-14", end: "2026-04-14", reason: "training" }, // Tuesday
    ],
  };
  const now = new Date("2026-04-14T06:00:00");
  const next = findNextDropIn(withClosure, now);
  assert.deepEqual(next, { program: "lap_swim", day: "wednesday", start: 9 * 60 });
});

test("findNextDropIn returns null when no drop-in sessions exist", () => {
  const lessonsOnly = {
    sessions: [
      { day: "tuesday", type: "lessons", start: "15:30", end: "16:00" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-14T10:00:00");
  assert.equal(findNextDropIn(lessonsOnly, now), null);
});

test("findNextDropIn rolls to the same weekday one week away", () => {
  // Only drop-in on Wednesday; today is Wednesday and the session has
  // ended. Must not return null — must roll to next Wednesday.
  const wednesdayOnly = {
    sessions: [
      { day: "wednesday", type: "lap_swim", start: "09:00", end: "10:15" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-15T11:00:00"); // Wed after session ended
  const next = findNextDropIn(wednesdayOnly, now);
  assert.deepEqual(next, { program: "lap_swim", day: "wednesday", start: 9 * 60 });
});
