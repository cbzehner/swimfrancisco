// Pure helpers for the board. Node's built-in node:test runner —
// no Vitest, no Jest, no jsdom. DOM-mutating logic is kept in status.js /
// filters.js; the branching that matters lives in board.mjs and is tested
// against plain arrays.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  computeStatus,
  computeAccessStatus,
  computeAccessWindowAvailability,
  computeDetailStatus,
  computeStatusRunKey,
  computeWindowAvailability,
  sortByRank,
  captureBaselineRanks,
  computeNextOpenOffset,
  findActiveClosure,
  findNextDropIn,
  getHorizonOptions,
  PLACEHOLDER,
  resolveActiveSchedule,
  resolveHorizon,
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

test("computeAccessStatus reports facility access without verified swim sessions", () => {
  const now = new Date("2026-04-14T06:00:00"); // Tuesday
  const schedule = {
    sessions: [],
    access_hours: [
      { day: "tuesday", start: "05:30", end: "20:30", label: "Facility hours" },
    ],
    closures: [],
  };
  const result = computeAccessStatus(schedule, now);
  assert.equal(result.status, "ACCESS");
  assert.equal(result.next, "Until 20:30");
  assert.equal(result.nextKind, "until");
});

test("computeAccessStatus lets date-specific access exceptions override weekly hours", () => {
  const schedule = {
    sessions: [],
    access_hours: [
      { day: "monday", start: "06:00", end: "20:30", label: "Pool hours" },
    ],
    access_exceptions: [
      { date: "2026-05-25", start: "07:30", end: "13:30", label: "Holiday pool hours", reason: "Memorial Day" },
    ],
    closures: [],
  };

  const beforeHolidayWindow = computeAccessStatus(schedule, new Date("2026-05-25T07:00:00"));
  assert.equal(beforeHolidayWindow.status, "CHECK");
  assert.equal(beforeHolidayWindow.next, "Access 07:30");
  assert.equal(beforeHolidayWindow.nextKind, "access_today");

  const afterHolidayWindow = computeAccessStatus(schedule, new Date("2026-05-25T14:00:00"));
  assert.equal(afterHolidayWindow.status, "CHECK");
  assert.equal(afterHolidayWindow.next, "Access MON 06:00");
  assert.equal(afterHolidayWindow.nextKind, "access_day");
});

test("computeAccessWindowAvailability uses access hours for plan-ahead windows", () => {
  const horizon = {
    kind: "window",
    day: "tuesday",
    date: "2026-04-14",
    start: 6 * 60,
    end: 11 * 60,
  };
  const schedule = {
    sessions: [],
    access_hours: [
      { day: "tuesday", start: "05:30", end: "20:30", label: "Facility hours" },
    ],
    closures: [],
  };
  assert.deepEqual(computeAccessWindowAvailability(schedule, horizon), {
    status: "ACCESS",
    next: "05:30-20:30",
    sortRank: 2,
  });
});

test("computeAccessWindowAvailability uses access exceptions for plan-ahead windows", () => {
  const horizon = {
    kind: "window",
    day: "monday",
    date: "2026-05-25",
    start: 6 * 60,
    end: 11 * 60,
  };
  const schedule = {
    sessions: [],
    access_hours: [
      { day: "monday", start: "06:00", end: "20:30", label: "Pool hours" },
    ],
    access_exceptions: [
      { date: "2026-05-25", start: "07:30", end: "13:30", label: "Holiday pool hours", reason: "Memorial Day" },
    ],
    closures: [],
  };
  assert.deepEqual(computeAccessWindowAvailability(schedule, horizon), {
    status: "ACCESS",
    next: "07:30-13:30",
    sortRank: 2,
  });
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

test("computeStatus honors closures", () => {
  const now = new Date("2026-04-17T10:00:00");
  const schedule = {
    sessions: [
      { day: "friday", type: "lap_swim", start: "09:00", end: "11:00" },
    ],
    closures: [
      { start: "2026-04-17", end: "2026-04-17", reason: "training", reason_code: "staff_training" },
    ],
  };
  const { status, next, nextKind, nextArgs } = computeStatus(schedule, now);
  assert.equal(status, "CLOSED");
  assert.equal(next, "training");
  assert.equal(nextKind, "closure_reason");
  assert.deepEqual(nextArgs, { reason: "training", reasonCode: "staff_training" });
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

test("computeNextOpenOffset returns zero for a currently open session", () => {
  const now = new Date("2026-04-14T13:00:00"); // Tuesday
  assert.equal(computeNextOpenOffset(BASIC_SCHEDULE, now), 0);
});

test("computeNextOpenOffset returns minutes until the next session", () => {
  const now = new Date("2026-04-14T08:30:00"); // Tuesday
  assert.equal(computeNextOpenOffset(BASIC_SCHEDULE, now), 4 * 60);
});

test("computeNextOpenOffset honors allowed program types", () => {
  const now = new Date("2026-04-14T13:00:00"); // Tuesday during lap
  assert.equal(computeNextOpenOffset(BASIC_SCHEDULE, now, ["family_swim"]), 90);
});

test("computeNextOpenOffset puts schedules without upcoming sessions at the tail", () => {
  const now = new Date("2026-04-14T13:00:00");
  assert.equal(
    computeNextOpenOffset({ sessions: [], closures: [] }, now),
    Number.POSITIVE_INFINITY,
  );
});

test("computeNextOpenOffset respects effective-window closures", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
    effective_start: "2026-05-12",
    effective_end: "2026-06-06",
  };

  const before = new Date("2026-05-05T08:00:00");
  assert.equal(computeNextOpenOffset(schedule, before), 7 * 1440 - 30);

  const after = new Date("2026-06-09T08:00:00");
  assert.equal(computeNextOpenOffset(schedule, after), Number.POSITIVE_INFINITY);
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
    closures: [{ start: "2026-04-14", end: "2026-04-14", reason: "In-service training", reason_code: "in_service_training" }],
  };
  const now = new Date("2026-04-14T10:00:00");
  const r = computeDetailStatus(withClosure, now);
  assert.equal(r.kind, "CLOSED_TODAY");
  assert.equal(r.closureReason, "In-service training");
  assert.equal(r.closureReasonCode, "in_service_training");
  assert.equal(r.is_drop_in, false);
  assert.equal(r.nextDropIn.day, "wednesday");
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

test("computeDetailStatus surfaces an active closure even when sessions are empty", () => {
  // Sava (closed for repairs, no sessions on file) should render its
  // closure reason — not the generic "SCHEDULE NOT YET VERIFIED" that
  // hides the actual signal. NOT_VERIFIED is reserved for pools with
  // no sessions AND no active closure.
  const closedForRepairs = {
    sessions: [],
    closures: [{ start: "2026-04-14", end: "2026-04-14", reason: "training", reason_code: "staff_training" }],
  };
  const now = new Date("2026-04-14T10:00:00");
  const r = computeDetailStatus(closedForRepairs, now);
  assert.equal(r.kind, "CLOSED_TODAY");
  assert.equal(r.closureReason, "training");
  assert.equal(r.closureReasonCode, "staff_training");
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

test("getHorizonOptions omits same-day windows that have already ended", () => {
  const now = new Date("2026-04-14T11:00:00"); // Tuesday 11:00 local
  const ids = getHorizonOptions(now).map((option) => option.id);
  assert.deepEqual(ids, [
    "now",
    "this-afternoon",
    "this-evening",
    "tomorrow-morning",
    "tomorrow-afternoon",
    "tomorrow-evening",
  ]);
});

test("resolveHorizon falls back to Now when a URL horizon is no longer available", () => {
  const now = new Date("2026-04-14T21:30:00"); // all same-day windows ended
  assert.equal(resolveHorizon("this-evening", now).id, "now");
});

test("computeWindowAvailability marks a useful overlapping session available", () => {
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeWindowAvailability(BASIC_SCHEDULE, horizon, ["lap_swim"]);
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.bestSession.type, "lap_swim");
  assert.equal(result.bestSession.start, 12 * 60 + 30);
});

test("computeWindowAvailability marks short overlaps limited", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "16:30", end: "17:10" }],
    closures: [],
  };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeWindowAvailability(schedule, horizon, ["lap_swim"]);
  assert.equal(result.status, "LIMITED");
  assert.equal(result.status, "LIMITED");
});

test("computeWindowAvailability returns no session when filters exclude the overlap", () => {
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeWindowAvailability(BASIC_SCHEDULE, horizon, ["senior_swim"]);
  assert.equal(result.status, "NO SESSION");
  assert.equal(result.status, "NO SESSION");
});

test("computeWindowAvailability treats all-day closures as closed", () => {
  const schedule = {
    sessions: BASIC_SCHEDULE.sessions,
    closures: [{ start: "2026-04-14", end: "2026-04-14", reason: "maintenance" }],
  };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeWindowAvailability(schedule, horizon);
  assert.equal(result.status, "CLOSED");
  assert.equal(result.status, "CLOSED");
});

test("computeWindowAvailability skips sessions blocked by partial closures", () => {
  const schedule = {
    sessions: [
      { day: "tuesday", type: "lap_swim", start: "12:30", end: "14:00" },
      { day: "tuesday", type: "lap_swim", start: "15:00", end: "16:00" },
    ],
    closures: [{
      start: "2026-04-14",
      end: "2026-04-14",
      start_time: "12:00",
      end_time: "14:30",
      reason: "training",
    }],
  };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeWindowAvailability(schedule, horizon);
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.bestSession.start, 15 * 60);
});

test("computeWindowAvailability trims sessions around partial closures", () => {
  const schedule = {
    sessions: [
      { day: "saturday", type: "lap_swim", start: "12:00", end: "14:00" },
    ],
    closures: [{
      start: "2026-06-06",
      end: "2026-06-06",
      start_time: "09:00",
      end_time: "13:00",
      reason: "Inservice Training",
    }],
  };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-06-06T11:00:00"));
  const result = computeWindowAvailability(schedule, horizon, ["lap_swim"]);
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.bestSession.start, 13 * 60);
  assert.equal(result.bestSession.end, 14 * 60);
});

test("computeAccessWindowAvailability trims access around partial closures", () => {
  const schedule = {
    access_hours: [
      { day: "saturday", start: "10:00", end: "16:00", label: "Facility hours" },
    ],
    access_exceptions: [],
    closures: [{
      start: "2026-06-06",
      end: "2026-06-06",
      start_time: "12:00",
      end_time: "13:00",
      reason: "Staff training",
    }],
  };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-06-06T11:00:00"));
  const result = computeAccessWindowAvailability(schedule, horizon);
  assert.equal(result.status, "ACCESS");
  assert.equal(result.next, "13:00-16:00");
});

test("computeWindowAvailability reports unverified when a schedule has no sessions", () => {
  // Distinct from the "no schedule at all" (NO SESSION/no bestSession key
  // change) and "no overlapping session" paths: an explicit empty sessions
  // array surfaces its own copy/nextKind so the board can tell "never
  // verified" apart from "nothing scheduled in this window".
  const schedule = { sessions: [], closures: [] };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeWindowAvailability(schedule, horizon);
  assert.deepEqual(result, {
    status: "NO SESSION",
    next: "Schedule not verified",
    nextKind: "not_verified",
    nextArgs: {},
    sortRank: 3,
    bestSession: null,
  });
});

test("computeWindowAvailability returns a placeholder for non-window horizons regardless of schedule", () => {
  // Pinned separately from computeAccessWindowAvailability's equivalent
  // branch below: the pool variant ranks this Infinity (below even CLOSED)
  // and always includes a null bestSession, while the access variant ranks
  // it 3 and omits bestSession entirely.
  const horizon = { id: "now", kind: "point" };
  const result = computeWindowAvailability(BASIC_SCHEDULE, horizon);
  assert.deepEqual(result, {
    status: PLACEHOLDER,
    next: PLACEHOLDER,
    sortRank: Number.POSITIVE_INFINITY,
    bestSession: null,
  });
});

test("computeAccessWindowAvailability reports CHECK/OFFICIAL SITE when a schedule has no access hours or exceptions", () => {
  const schedule = { sessions: [], access_hours: [], access_exceptions: [], closures: [] };
  const horizon = resolveHorizon("this-afternoon", new Date("2026-04-14T11:00:00"));
  const result = computeAccessWindowAvailability(schedule, horizon);
  assert.deepEqual(result, {
    status: "CHECK",
    next: "OFFICIAL SITE",
    nextKind: "official_site",
    nextArgs: {},
    sortRank: 3,
  });
});

test("computeAccessWindowAvailability returns a placeholder for non-window horizons without a bestSession key", () => {
  const horizon = { id: "now", kind: "point" };
  const schedule = {
    access_hours: [{ day: "tuesday", start: "05:30", end: "20:30", label: "Facility hours" }],
    closures: [],
  };
  const result = computeAccessWindowAvailability(schedule, horizon);
  assert.deepEqual(result, { status: PLACEHOLDER, next: PLACEHOLDER, sortRank: 3 });
});

test("computeDetailStatus treats pre-season as a synthetic closure", () => {
  // Pre-season collapses into the same CLOSED_TODAY shape used for repair
  // shutdowns and holidays; the closure reason carries the transition copy.
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
    effective_start: "2026-05-12",
    effective_end: "2026-06-06",
  };
  const before = new Date("2026-05-05T15:00:00");
  const result = computeDetailStatus(schedule, before);
  assert.equal(result.kind, "CLOSED_TODAY");
  assert.equal(result.closureKind, "PRE_SEASON");
  assert.match(result.closureReason, /Schedule starts/);
});

test("computeDetailStatus treats post-season as a synthetic closure", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
    effective_start: "2026-05-12",
    effective_end: "2026-06-06",
  };
  const after = new Date("2026-06-09T08:00:00");
  const result = computeDetailStatus(schedule, after);
  assert.equal(result.kind, "CLOSED_TODAY");
  assert.equal(result.closureKind, "POST_SEASON");
  assert.match(result.closureReason, /Schedule ended/);
  // Post-season has no known reopen, so we don't compute a nextDropIn.
  assert.equal(result.nextDropIn, null);
});

test("computeStatus dashboard line for pre-season points at schedule start", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
    effective_start: "2026-05-12",
    effective_end: "2026-06-06",
  };
  const before = new Date("2026-05-05T15:00:00");
  const { status, next, nextKind, nextArgs } = computeStatus(schedule, before);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Schedule starts May 12, 2026");
  assert.equal(nextKind, "schedule_starts");
  assert.deepEqual(nextArgs, { iso: "2026-05-12" });
});

test("computeStatus dashboard line for same-day closure surfaces the reason", () => {
  const schedule = {
    sessions: [{ day: "saturday", type: "lap_swim", start: "09:00", end: "10:30" }],
    closures: [{ start: "2026-06-06", end: "2026-06-06", reason: "Inservice Training", reason_code: "in_service_training" }],
  };
  const during = new Date("2026-06-06T13:25:00");
  const { status, next, nextKind, nextArgs } = computeStatus(schedule, during);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Inservice Training");
  assert.equal(nextKind, "closure_reason");
  assert.deepEqual(nextArgs, { reason: "Inservice Training", reasonCode: "in_service_training" });
});

test("computeStatus dashboard line for post-season uses 'Schedule ended'", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
    effective_start: "2026-05-12",
    effective_end: "2026-06-06",
  };
  const after = new Date("2026-06-09T08:00:00");
  const { status, next, nextKind, nextArgs } = computeStatus(schedule, after);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Schedule ended Jun 6, 2026");
  assert.equal(nextKind, "schedule_ended");
  assert.deepEqual(nextArgs, { iso: "2026-06-06" });
});

test("findActiveClosure respects start_time/end_time on partial-day closures", () => {
  const closures = [{
    start: "2026-05-21",
    end: "2026-05-21",
    start_time: "11:00",
    end_time: "14:00",
    reason: "Aquatics training",
  }];
  // 10:00 AM — before the closure window — pool is open.
  const before = new Date("2026-05-21T10:00:00");
  assert.equal(findActiveClosure(closures, before), null);
  // 12:00 PM — inside the window — closed.
  const during = new Date("2026-05-21T12:00:00");
  const active = findActiveClosure(closures, during);
  assert.ok(active);
  assert.equal(active.reason, "Aquatics training");
  // 14:00 — boundary — open (end is exclusive).
  const after = new Date("2026-05-21T14:00:00");
  assert.equal(findActiveClosure(closures, after), null);
});

test("computeStatus dashboard line for partial-day closure shows the time window", () => {
  const schedule = {
    sessions: [{ day: "thursday", type: "lap_swim", start: "11:30", end: "13:30" }],
    closures: [{
      start: "2026-05-21",
      end: "2026-05-21",
      start_time: "11:00",
      end_time: "14:00",
      reason: "Aquatics training",
    }],
  };
  const during = new Date("2026-05-21T12:00:00");
  const { status, next, nextKind, nextArgs } = computeStatus(schedule, during);
  assert.equal(status, "CLOSED");
  // No "through DATE" copy when a partial window is present — just the
  // time range, since the pool reopens later that same day.
  assert.equal(next, "Closed 11:00–14:00");
  assert.equal(nextKind, "closed_window");
  assert.deepEqual(nextArgs, { start: "11:00", end: "14:00" });
});

test("findNextSession skips sessions inside a partial-day closure", () => {
  const schedule = {
    sessions: [
      { day: "thursday", type: "lap_swim", start: "11:30", end: "13:30" },
      { day: "thursday", type: "lap_swim", start: "16:00", end: "18:00" },
    ],
    closures: [{
      start: "2026-05-21",
      end: "2026-05-21",
      start_time: "11:00",
      end_time: "14:00",
      reason: "Aquatics training",
    }],
  };
  // Tuesday morning, looking ahead. The 11:30 Thursday lap swim falls in
  // the partial closure and must be skipped; the 16:00 Thursday session
  // is the real next slot.
  const now = new Date("2026-05-19T10:00:00");
  const next = findNextDropIn(schedule, now);
  assert.ok(next);
  assert.equal(next.day, "thursday");
  assert.equal(next.start, 16 * 60);
});

test("computeStatus surfaces 'Schedule not yet verified' on bare schedules", () => {
  // No sessions, no closures, no effective window — the canonical
  // "we have no idea what this pool is doing" state.
  const empty = { sessions: [], closures: [] };
  const t = new Date("2026-05-05T15:00:00");
  const { status, next } = computeStatus(empty, t);
  assert.equal(status, "CLOSED");
  assert.equal(next, "Schedule not yet verified");
});

test("computeDetailStatus runs normal logic inside the effective window", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
    effective_start: "2026-05-12",
    effective_end: "2026-06-06",
  };
  const inside = new Date("2026-05-19T08:00:00");
  const result = computeDetailStatus(schedule, inside);
  assert.equal(result.kind, "OPEN");
});

test("computeDetailStatus ignores effective_start when missing", () => {
  const schedule = {
    sessions: [{ day: "tuesday", type: "lap_swim", start: "07:30", end: "09:30" }],
    closures: [],
  };
  const t = new Date("2026-05-19T08:00:00");
  const result = computeDetailStatus(schedule, t);
  assert.equal(result.kind, "OPEN");
});

const NORTH_BEACH_TRANSITION_SCHEDULE = {
  schedules: [
    {
      sessions: [
        { day: "saturday", type: "lap_swim", start: "12:00", end: "14:00", pool: "cool" },
        { day: "saturday", type: "family_swim", start: "13:45", end: "15:00", pool: "warm" },
      ],
      closures: [{
        start: "2026-06-06",
        end: "2026-06-06",
        start_time: "09:00",
        end_time: "13:00",
        reason: "In- Service Training: Pool Closed 9:00-1:00pm",
      }],
      effective_start: "2026-03-17",
      effective_end: "2026-06-06",
    },
    {
      sessions: [
        { day: "tuesday", type: "lap_swim", start: "07:00", end: "08:00", pool: "c/w/t" },
      ],
      closures: [],
      effective_start: "2026-06-09",
      effective_end: "2026-08-15",
    },
  ],
};

test("queued schedule keeps North Beach current schedule active on June 6", () => {
  const duringClosure = new Date("2026-06-06T10:00:00");
  const closed = computeStatus(NORTH_BEACH_TRANSITION_SCHEDULE, duringClosure);
  assert.equal(closed.status, "CLOSED");
  assert.equal(closed.next, "Closed 09:00–13:00");
  assert.equal(closed.nextKind, "closed_window");

  const afterClosure = new Date("2026-06-06T13:01:00");
  const open = computeStatus(NORTH_BEACH_TRANSITION_SCHEDULE, afterClosure);
  assert.equal(open.status, "OPEN");
  assert.equal(open.next, "Closes 14:00");
});

test("queued schedule surfaces start date during gap before summer schedule", () => {
  const gap = new Date("2026-06-07T10:00:00");
  const status = computeStatus(NORTH_BEACH_TRANSITION_SCHEDULE, gap);
  assert.equal(status.status, "CLOSED");
  assert.equal(status.next, "Schedule starts Jun 9, 2026");
  assert.equal(status.nextKind, "schedule_starts");
  assert.deepEqual(status.nextArgs, { iso: "2026-06-09" });
});

test("queued schedule becomes active on its effective date", () => {
  const startDay = new Date("2026-06-09T07:30:00");
  const active = resolveActiveSchedule(NORTH_BEACH_TRANSITION_SCHEDULE, startDay);
  assert.equal(active.effective_start, "2026-06-09");
  const status = computeStatus(NORTH_BEACH_TRANSITION_SCHEDULE, startDay);
  assert.equal(status.status, "OPEN");
  assert.equal(status.next, "Closes 08:00");
});

// computeStatusRunKey backs the memoization in status.js's applyStatuses:
// filters.js reruns renderBoard on every filter/sort click (it needs to,
// to pick up the active program-type filter), but a full status recompute
// (parsing every row's data-schedule, running computeStatus /
// computeWindowAvailability) should only actually happen when the key
// changes — i.e. when horizon, the current minute, or the allowed program
// types genuinely changed. These tests pin that contract.
test("computeStatusRunKey is stable across calls within the same minute and allowed types", () => {
  const horizon = { id: "now", kind: "point" };
  const a = computeStatusRunKey(horizon, new Date("2026-04-14T10:00:05"), ["lap_swim"]);
  const b = computeStatusRunKey(horizon, new Date("2026-04-14T10:00:55"), ["lap_swim"]);
  assert.equal(a, b, "same minute + same allowed types must not force a recompute");
});

test("computeStatusRunKey changes when the minute advances", () => {
  const horizon = { id: "now", kind: "point" };
  const a = computeStatusRunKey(horizon, new Date("2026-04-14T10:00:59"), null);
  const b = computeStatusRunKey(horizon, new Date("2026-04-14T10:01:00"), null);
  assert.notEqual(a, b, "the minute tick must force a recompute");
});

test("computeStatusRunKey changes when the allowed program types change", () => {
  const horizon = { id: "now", kind: "point" };
  const now = new Date("2026-04-14T10:00:00");
  const unfiltered = computeStatusRunKey(horizon, now, null);
  const lapOnly = computeStatusRunKey(horizon, now, ["lap_swim"]);
  const familyOnly = computeStatusRunKey(horizon, now, ["family_swim"]);
  assert.notEqual(unfiltered, lapOnly, "selecting a type filter must force a recompute");
  assert.notEqual(lapOnly, familyOnly, "switching type filters must force a recompute");
});

test("computeStatusRunKey is order-independent for allowed program types", () => {
  const horizon = { id: "now", kind: "point" };
  const now = new Date("2026-04-14T10:00:00");
  const a = computeStatusRunKey(horizon, now, ["lap_swim", "family_swim"]);
  const b = computeStatusRunKey(horizon, now, ["family_swim", "lap_swim"]);
  assert.equal(a, b, "the same set of allowed types must not force a recompute regardless of order");
});

test("computeStatusRunKey treats null and empty allowed types the same", () => {
  const horizon = { id: "now", kind: "point" };
  const now = new Date("2026-04-14T10:00:00");
  assert.equal(
    computeStatusRunKey(horizon, now, null),
    computeStatusRunKey(horizon, now, []),
  );
});

test("computeStatusRunKey for window horizons ignores the clock and keys off the horizon date", () => {
  const horizon = { id: "this-afternoon", kind: "window", date: "2026-04-14" };
  const a = computeStatusRunKey(horizon, new Date("2026-04-14T09:00:00"), null);
  const b = computeStatusRunKey(horizon, new Date("2026-04-14T16:00:00"), null);
  assert.equal(a, b, "a plan-ahead window's key must not depend on the current minute");
});

test("computeStatusRunKey changes when the horizon id changes", () => {
  const now = new Date("2026-04-14T10:00:00");
  const a = computeStatusRunKey({ id: "now", kind: "point" }, now, null);
  const b = computeStatusRunKey({ id: "this-afternoon", kind: "window", date: "2026-04-14" }, now, null);
  assert.notEqual(a, b);
});

test("queued reopening schedule handles Sava repair closure through June 8", () => {
  const schedule = {
    schedules: [
      {
        sessions: [],
        closures: [{
          start: "2026-04-16",
          end: "2026-06-08",
          reason: "Closed for repairs; reopening June 9, 2026",
        }],
        effective_start: "2026-01-06",
        effective_end: "2026-06-08",
      },
      {
        sessions: [{ day: "tuesday", type: "lap_swim", start: "06:30", end: "10:30" }],
        closures: [],
        effective_start: "2026-06-09",
        effective_end: "2026-06-27",
      },
    ],
  };
  const before = computeStatus(schedule, new Date("2026-06-08T12:00:00"));
  assert.equal(before.status, "CLOSED");
  assert.equal(before.next, "Closed through Jun 8, 2026");

  const reopened = computeStatus(schedule, new Date("2026-06-09T07:00:00"));
  assert.equal(reopened.status, "OPEN");
  assert.equal(reopened.next, "Closes 10:30");
});
