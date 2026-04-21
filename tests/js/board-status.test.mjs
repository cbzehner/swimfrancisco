// Pure helpers for the board. Node's built-in node:test runner —
// no Vitest, no Jest, no jsdom. DOM-mutating logic is kept in status.js /
// filters.js; the branching that matters lives in board.mjs and is tested
// against plain arrays.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  computeStatus,
  computeDetailStatus, // NEW
  sortByRank,
  captureBaselineRanks,
  findNextDropIn,
  freshnessLabel,
  nowInPacific,
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
    "Closed through Apr 20, 2026",
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

  // Distance sort reshuffles into distance order.
  const reshuffled = [baseline[2], baseline[0], baseline[3], baseline[1]];

  // Distance sort off → restore baseline.
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
  assert.equal(next, "Closed through Apr 17, 2026");
});

const DROP_IN_SCHEDULE = {
  sessions: [
    { day: "tuesday",  type: "lap_swim",    start: "07:00", end: "08:00" },
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

test("findNextDropIn honors allowed program types", () => {
  const now = new Date("2026-04-14T10:00:00"); // Tuesday 10:00 local
  const next = findNextDropIn(DROP_IN_SCHEDULE, now, ["lap_swim"]);
  assert.deepEqual(next, { program: "lap_swim", day: "wednesday", start: 9 * 60 });
});

test("findNextDropIn rolls to tomorrow after today's last drop-in", () => {
  const now = new Date("2026-04-14T17:00:00"); // Tuesday 17:00, after all Tue drop-ins
  const next = findNextDropIn(DROP_IN_SCHEDULE, now);
  assert.deepEqual(next, { program: "lap_swim", day: "wednesday", start: 9 * 60 });
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

test("freshnessLabel: within 30 days is fresh", () => {
  const now = new Date("2026-04-17T10:00:00");
  assert.equal(freshnessLabel("2026-04-17", now), "fresh");
  assert.equal(freshnessLabel("2026-03-18", now), "fresh"); // exactly 30 days
});

test("freshnessLabel: older than 30 days is stale", () => {
  const now = new Date("2026-04-17T10:00:00");
  assert.equal(freshnessLabel("2026-03-17", now), "stale"); // 31 days
  assert.equal(freshnessLabel("2025-10-01", now), "stale");
});

test("freshnessLabel: missing or invalid input is stale", () => {
  const now = new Date("2026-04-17T10:00:00");
  assert.equal(freshnessLabel(null, now), "stale");
  assert.equal(freshnessLabel("", now), "stale");
  assert.equal(freshnessLabel("not-a-date", now), "stale");
});

const BASIC_SCHEDULE = {
  sessions: [
    { day: "tuesday", type: "lap_swim",    start: "07:00", end: "08:00" },
    { day: "tuesday", type: "lap_swim",    start: "12:30", end: "14:00" },
    { day: "tuesday", type: "family_swim", start: "14:30", end: "15:30" },
    { day: "wednesday", type: "lap_swim", start: "09:00", end: "10:15" },
  ],
  closures: [],
};

const FILTERED_STATUS_SCHEDULE = {
  sessions: [
    { day: "tuesday", type: "lap_swim", start: "07:00", end: "08:00" },
    { day: "tuesday", type: "family_swim", start: "14:30", end: "15:30" },
    { day: "wednesday", type: "lap_swim", start: "09:00", end: "10:15" },
    { day: "wednesday", type: "family_swim", start: "13:00", end: "14:00" },
  ],
  closures: [],
};

test("computeStatus honors a family-only filter", () => {
  const now = new Date("2026-04-14T15:40:00"); // Tue after family ended
  const { status, next } = computeStatus(FILTERED_STATUS_SCHEDULE, now, ["family_swim"]);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Opens WED 13:00");
});

test("computeStatus honors a lap-only filter", () => {
  const now = new Date("2026-04-14T14:40:00"); // Tue during family, no lap active
  const { status, next } = computeStatus(FILTERED_STATUS_SCHEDULE, now, ["lap_swim"]);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Opens WED 09:00");
});

test("computeStatus treats multiple active program filters as a union", () => {
  const now = new Date("2026-04-14T14:40:00"); // Tue during family
  const { status, next } = computeStatus(FILTERED_STATUS_SCHEDULE, now, ["lap_swim", "family_swim"]);
  assert.equal(status, "OPEN");
  assert.equal(next, "Closes 15:30");
});

test("computeStatus rolls filtered programs to the same weekday one week away", () => {
  const wednesdayFamilyOnly = {
    sessions: [
      { day: "wednesday", type: "family_swim", start: "14:00", end: "15:00" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-15T16:00:00"); // Wed after the family block ended
  const { status, next } = computeStatus(wednesdayFamilyOnly, now, ["family_swim"]);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Opens WED 14:00");
});

test("computeDetailStatus OPEN during a single drop-in session", () => {
  const now = new Date("2026-04-14T13:00:00"); // Tue 13:00 — inside lap 12:30-14:00
  const r = computeDetailStatus(BASIC_SCHEDULE, now);
  assert.equal(r.kind, "OPEN");
  assert.deepEqual(r.activePrograms, ["lap_swim"]);
  assert.equal(r.activeUntil, 14 * 60);
  assert.equal(r.is_drop_in, true);
  assert.equal(r.closureReason, null);
});

test("computeDetailStatus CLOSED_HOURS between sessions with next drop-in today", () => {
  const now = new Date("2026-04-14T08:30:00"); // Tue 08:30 — after 07-08 lap, before 12:30 lap
  const r = computeDetailStatus(BASIC_SCHEDULE, now);
  assert.equal(r.kind, "CLOSED_HOURS");
  assert.deepEqual(r.activePrograms, []);
  assert.equal(r.activeUntil, null);
  assert.equal(r.is_drop_in, false);
  assert.deepEqual(r.nextDropIn, { program: "lap_swim", day: "tuesday", start: 12 * 60 + 30 });
});

test("computeDetailStatus CLOSED_TODAY for facility-wide closure", () => {
  const withClosure = {
    sessions: BASIC_SCHEDULE.sessions,
    closures: [{ start: "2026-04-14", end: "2026-04-14", reason: "In-service training" }],
  };
  const now = new Date("2026-04-14T10:00:00");
  const r = computeDetailStatus(withClosure, now);
  assert.equal(r.kind, "CLOSED_TODAY");
  assert.equal(r.closureReason, "In-service training");
  assert.equal(r.is_drop_in, false);
  assert.equal(r.nextDropIn.day, "wednesday");
});

test("computeDetailStatus ignores zone-scoped closures", () => {
  const zoneOnly = {
    sessions: BASIC_SCHEDULE.sessions,
    closures: [{ start: "2026-04-14", end: "2026-04-14", reason: "deep end down", pool: "deep" }],
  };
  const now = new Date("2026-04-14T13:00:00");
  const r = computeDetailStatus(zoneOnly, now);
  assert.equal(r.kind, "OPEN");
  assert.equal(r.closureReason, null);
});

test("computeDetailStatus boundary: now === start is OPEN", () => {
  // Tue 07:00 exactly — first minute of the 07:00-08:00 lap session.
  const now = new Date("2026-04-14T07:00:00");
  const r = computeDetailStatus(BASIC_SCHEDULE, now);
  assert.equal(r.kind, "OPEN");
  assert.deepEqual(r.activePrograms, ["lap_swim"]);
});

test("computeDetailStatus boundary: now === end is CLOSED_HOURS", () => {
  // Tue 08:00 exactly — the 07:00-08:00 session has ended (half-open
  // interval). Next session is 12:30 same day.
  const now = new Date("2026-04-14T08:00:00");
  const r = computeDetailStatus(BASIC_SCHEDULE, now);
  assert.equal(r.kind, "CLOSED_HOURS");
  assert.deepEqual(r.nextDropIn, { program: "lap_swim", day: "tuesday", start: 12 * 60 + 30 });
});

test("computeDetailStatus NOT_VERIFIED wins over active closure", () => {
  // A pool with empty sessions + an active facility-wide closure is
  // "we don't know yet", not "closed today" — Mission Community and
  // Sava are the real cases.
  const unverifiedWithClosure = {
    sessions: [],
    closures: [{ start: "2026-04-14", end: "2026-04-14", reason: "training" }],
  };
  const now = new Date("2026-04-14T10:00:00");
  const r = computeDetailStatus(unverifiedWithClosure, now);
  assert.equal(r.kind, "NOT_VERIFIED");
});

test("computeDetailStatus NOT_VERIFIED when sessions array is empty", () => {
  const schedule = { sessions: [], closures: [] };
  const now = new Date("2026-04-14T10:00:00");
  const r = computeDetailStatus(schedule, now);
  assert.equal(r.kind, "NOT_VERIFIED");
  assert.equal(r.nextDropIn, null);
});

test("computeDetailStatus concurrent drop-in (Balboa Wednesday case)", () => {
  const balboaWed = {
    sessions: [
      { day: "wednesday", type: "lap_swim",    start: "12:30", end: "15:00" },
      { day: "wednesday", type: "family_swim", start: "14:00", end: "15:00" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-15T14:30:00"); // Wed 14:30 — both active
  const r = computeDetailStatus(balboaWed, now);
  assert.equal(r.kind, "OPEN");
  assert.deepEqual(r.activePrograms.sort(), ["family_swim", "lap_swim"]);
  assert.equal(r.activeUntil, 15 * 60);
  assert.equal(r.is_drop_in, true);
});

test("computeDetailStatus respects local wall-clock across DST transitions", () => {
  const schedule = {
    sessions: [
      { day: "sunday", type: "lap_swim", start: "10:00", end: "11:00" },
    ],
    closures: [],
  };
  // 2026-03-08 is the US "spring forward" Sunday. At 10:30 LOCAL time the
  // session should be active regardless of the UTC offset shift.
  const springForward = new Date("2026-03-08T10:30:00");
  const r1 = computeDetailStatus(schedule, springForward);
  assert.equal(r1.kind, "OPEN", "spring-forward Sunday 10:30 should be OPEN");

  // 2026-11-01 is "fall back" Sunday; 10:30 local again.
  const fallBack = new Date("2026-11-01T10:30:00");
  const r2 = computeDetailStatus(schedule, fallBack);
  assert.equal(r2.kind, "OPEN", "fall-back Sunday 10:30 should be OPEN");
});

test("nowInPacific reflects PT wall-clock during PDT (UTC-7)", () => {
  // 2026-04-19T06:00:00Z during PDT → 2026-04-18 23:00 PT (Saturday).
  const pt = nowInPacific(new Date("2026-04-19T06:00:00Z"));
  assert.equal(pt.getFullYear(), 2026);
  assert.equal(pt.getMonth(), 3); // April (0-indexed)
  assert.equal(pt.getDate(), 18);
  assert.equal(pt.getDay(), 6); // Saturday
  assert.equal(pt.getHours(), 23);
  assert.equal(pt.getMinutes(), 0);
});

test("nowInPacific reflects PT wall-clock during PST (UTC-8)", () => {
  // 2026-01-15T07:30:00Z during PST → 2026-01-14 23:30 PT (Wednesday).
  const pt = nowInPacific(new Date("2026-01-15T07:30:00Z"));
  assert.equal(pt.getFullYear(), 2026);
  assert.equal(pt.getMonth(), 0); // January
  assert.equal(pt.getDate(), 14);
  assert.equal(pt.getDay(), 3); // Wednesday
  assert.equal(pt.getHours(), 23);
  assert.equal(pt.getMinutes(), 30);
});

test("nowInPacific straddles midnight PT correctly", () => {
  // 08:00 UTC on 2026-01-15 = 00:00 PST on 2026-01-15.
  const midnight = nowInPacific(new Date("2026-01-15T08:00:00Z"));
  assert.equal(midnight.getDate(), 15);
  assert.equal(midnight.getHours(), 0);
  // One minute earlier → still 2026-01-14 23:59 PT.
  const justBefore = nowInPacific(new Date("2026-01-15T07:59:00Z"));
  assert.equal(justBefore.getDate(), 14);
  assert.equal(justBefore.getHours(), 23);
  assert.equal(justBefore.getMinutes(), 59);
});
