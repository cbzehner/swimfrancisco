# Spot Detail Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the pool detail page around the actual user journey ("can I swim here, when, what program?") with a program-primary weekly grid, a live status slab, today's drop-in list, and zone-aware closures — preserving the departure-board aesthetic.

**Architecture:** The pool branch of `templates/spots/page.html` is rewritten. A new `static/js/detail.js` handles client-side hydration (status slab, today block injection, freshness dot, today-column highlight). Pure helpers live in `static/js/helpers/board.mjs` as `computeDetailStatus`, `findNextDropIn`, and `freshnessLabel`; they are exercised under `node:test`. The legacy homepage `computeStatus` is left in place — the only homepage behavior change is that `findActiveClosure` now ignores zone-scoped closures (non-empty `closure.pool`), satisfying the multi-pool-facilities backlog. Existing hash-filter tokens (`/#lap`, `/#family`) already power cross-nav — no change to `filters.js`.

**Tech Stack:** Zola (Tera templates), vanilla ES modules (progressive enhancement), Sass, `node:test`.

**Spec:** [docs/superpowers/specs/2026-04-17-spot-detail-redesign-design.md](../specs/2026-04-17-spot-detail-redesign-design.md)

---

## File Structure

| Path | Change | Responsibility |
|------|--------|----------------|
| `static/js/helpers/board.mjs` | **modify** | Pure helpers. Extend `findActiveClosure` (zone-aware). Add `findNextDropIn`, `freshnessLabel`, `computeDetailStatus`. Legacy `computeStatus` unchanged except via `findActiveClosure`. |
| `static/js/detail.js` | **create** | DOM glue for the detail page: read embedded schedule, hydrate status slab, inject today block, mark today's column, update freshness dot. |
| `templates/spots/page.html` | **modify** | Rewrite the `extra.type == "pool"` branch. Open-water branch untouched. Wire `detail.js` via `scripts` block for pool pages. |
| `sass/main.scss` | **modify** | Add rules for status slab, today block, weekly grid (desktop + mobile), closure banner, freshness dot, zone badge, program-row cross-nav. |
| `tests/js/board-status.test.mjs` | **modify** | Add tests for new helpers and the zone-aware closure change. |
| `docs/plans/multi-pool-facilities.md` | **modify** | Mark the frontend steps as superseded by this plan. |

**Files intentionally unchanged:**

- `static/js/status.js` — the homepage consumer still reads `{ status, next }` from legacy `computeStatus`, which keeps working because the zone-closure rule is the only behavior change.
- `static/js/filters.js` — homepage already supports `/#lap` / `/#family` hash tokens, which serve the detail-page cross-nav links.
- `templates/index.html`, `templates/base.html` — no change.
- `src/schedules/*`, `content/spots/*.md` — data pipeline and content shape unchanged.

---

## Task 1: Zone-aware `findActiveClosure`

**Files:**
- Modify: `static/js/helpers/board.mjs:45-56`
- Test: `tests/js/board-status.test.mjs`

The homepage side of the multi-pool-facilities plan: a closure with a non-empty `pool` zone affects only its zone, so it must not mark the facility closed from the homepage's point of view. The detail page renders zone-scoped closures as banners separately.

- [ ] **Step 1: Add failing test for zone-scoped closure ignored**

Append to `tests/js/board-status.test.mjs`:

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/js/board-status.test.mjs`
Expected: the first test FAILs (`status` is currently "CLOSED" because the zone closure still counts).

- [ ] **Step 3: Make `findActiveClosure` zone-aware**

In `static/js/helpers/board.mjs`, replace the body of `findActiveClosure`:

```js
// Return the active facility-wide closure (if any) covering `now`. Closures
// with a non-empty `pool` field are zone-scoped and do NOT close the whole
// facility — they are rendered as detail-page banners but ignored here.
export function findActiveClosure(closures, now) {
  if (!Array.isArray(closures) || closures.length === 0) return null;
  const today = formatISODate(now);
  for (const closure of closures) {
    if (!closure || typeof closure !== "object") continue;
    const start = typeof closure.start === "string" ? closure.start : null;
    const end = typeof closure.end === "string" ? closure.end : null;
    if (!start || !end) continue;
    if (typeof closure.pool === "string" && closure.pool.length > 0) continue;
    if (today >= start && today <= end) return closure;
  }
  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/js/board-status.test.mjs`
Expected: all tests PASS, including the existing "Closed through" test.

- [ ] **Step 5: Commit**

```bash
git add static/js/helpers/board.mjs tests/js/board-status.test.mjs
git commit -m "feat(board): ignore zone-scoped closures in findActiveClosure

Facility-wide closures (empty closure.pool) still close the whole
facility; zone-scoped closures (non-empty pool) are rendered as
detail-page banners and no longer mark the homepage CLOSED."
```

---

## Task 2: `findNextDropIn` helper

**Files:**
- Modify: `static/js/helpers/board.mjs`
- Test: `tests/js/board-status.test.mjs`

Detail-page helper: given a schedule and a reference time, return the next drop-in session (lap / family / senior) that will begin after `now`, or `null` if none within the next 7 days. Skips lessons sessions. Skips days where a facility-wide closure is active.

- [ ] **Step 1: Add failing test**

```js
import {
  computeStatus,
  sortByRank,
  captureBaselineRanks,
  findNextDropIn,   // NEW
} from "../../static/js/helpers/board.mjs";

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/board-status.test.mjs`
Expected: five FAILures with "findNextDropIn is not a function" / ReferenceError.

- [ ] **Step 3: Implement `findNextDropIn`**

Append to `static/js/helpers/board.mjs` (after `closureCopy`):

```js
const DROP_IN_TYPES = new Set(["lap_swim", "family_swim", "senior_swim"]);

// Return the next drop-in session (lap / family / senior) that starts strictly
// after `now`, scanning up to 7 days ahead. Skips lessons and facility-wide
// closed days. Returns `{ program, day, start }` (start in minutes-of-day) or
// null if none found within the window.
export function findNextDropIn(schedule, now) {
  if (!schedule || typeof schedule !== "object") return null;
  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];
  if (sessions.length === 0) return null;

  const normalized = [];
  for (const session of sessions) {
    if (!session || typeof session !== "object") continue;
    if (!DROP_IN_TYPES.has(session.type)) continue;
    const day = typeof session.day === "string" ? session.day.toLowerCase() : null;
    const start = parseHHMM(session.start);
    if (!day || !DAY_KEYS.includes(day) || start === null) continue;
    normalized.push({ program: session.type, day, start });
  }
  if (normalized.length === 0) return null;

  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  for (let offset = 0; offset < 7; offset += 1) {
    const date = new Date(now);
    date.setDate(date.getDate() + offset);
    if (findActiveClosure(closures, date)) continue;
    const dayKey = DAY_KEYS[date.getDay()];
    const candidates = normalized
      .filter((s) => s.day === dayKey)
      .filter((s) => offset > 0 || s.start > nowMinutes)
      .sort((a, b) => a.start - b.start);
    if (candidates.length > 0) return candidates[0];
  }
  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/js/board-status.test.mjs`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/helpers/board.mjs tests/js/board-status.test.mjs
git commit -m "feat(board): add findNextDropIn helper

Pure helper for the detail page status slab and today block. Returns
the next lap/family/senior session after now, skipping lessons and
facility-wide closed days."
```

---

## Task 3: `freshnessLabel` helper

**Files:**
- Modify: `static/js/helpers/board.mjs`
- Test: `tests/js/board-status.test.mjs`

- [ ] **Step 1: Add failing test**

```js
import {
  computeStatus,
  sortByRank,
  captureBaselineRanks,
  findNextDropIn,
  freshnessLabel,  // NEW
} from "../../static/js/helpers/board.mjs";

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/board-status.test.mjs`
Expected: three FAILures with "freshnessLabel is not a function".

- [ ] **Step 3: Implement `freshnessLabel`**

Append to `static/js/helpers/board.mjs`:

```js
const FRESH_WINDOW_DAYS = 30;

// Return "fresh" when `isoDate` (YYYY-MM-DD) is within FRESH_WINDOW_DAYS of
// `now` (inclusive); "stale" otherwise. Missing, empty, or unparseable input
// is treated as stale — we prefer to signal "we don't know" rather than
// overstate freshness.
export function freshnessLabel(isoDate, now) {
  if (typeof isoDate !== "string" || isoDate.length === 0) return "stale";
  const parsed = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "stale";
  const nowMs = now.getTime();
  const ageMs = nowMs - parsed.getTime();
  if (ageMs < 0) return "fresh"; // future-dated counts as fresh
  const ageDays = ageMs / 86_400_000;
  return ageDays <= FRESH_WINDOW_DAYS ? "fresh" : "stale";
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/js/board-status.test.mjs`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/helpers/board.mjs tests/js/board-status.test.mjs
git commit -m "feat(board): add freshnessLabel helper

Returns 'fresh' / 'stale' based on a 30-day window around last
verification. Powers the Trust Layer freshness dot on detail pages."
```

---

## Task 4: `computeDetailStatus` — OPEN / CLOSED_HOURS / CLOSED_TODAY

**Files:**
- Modify: `static/js/helpers/board.mjs`
- Test: `tests/js/board-status.test.mjs`

`computeDetailStatus(schedule, now)` returns the structured state machine consumed by the detail page's status slab. We build it up in four tasks (Tasks 4–7) covering: basic states, lessons, not-verified / empty-week, and concurrent drop-in programs. Returns:

```ts
{
  kind: "OPEN" | "LESSONS" | "CLOSED_TODAY" | "CLOSED_HOURS"
      | "NO_DROPIN_TODAY" | "NO_DROPIN_WEEK" | "NOT_VERIFIED",
  activePrograms: string[],          // e.g. ["lap_swim", "family_swim"]
  activeUntil: number | null,        // minutes-of-day
  activeLessonsUntil: number | null, // minutes-of-day (only when kind=LESSONS)
  nextDropIn: { program, day, start } | null,
  closureReason: string | null,
  is_drop_in: boolean,
}
```

- [ ] **Step 1: Add failing tests for the three basic states**

```js
import {
  computeStatus,
  computeDetailStatus, // NEW
  sortByRank,
  captureBaselineRanks,
  findNextDropIn,
  freshnessLabel,
} from "../../static/js/helpers/board.mjs";

const BASIC_SCHEDULE = {
  sessions: [
    { day: "tuesday", type: "lap_swim",    start: "07:00", end: "08:00" },
    { day: "tuesday", type: "lap_swim",    start: "12:30", end: "14:00" },
    { day: "tuesday", type: "family_swim", start: "14:30", end: "15:30" },
    { day: "wednesday", type: "lap_swim", start: "09:00", end: "10:15" },
  ],
  closures: [],
};

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/board-status.test.mjs`
Expected: four FAILures — `computeDetailStatus is not a function`.

- [ ] **Step 3: Implement the minimal body (basic states only)**

Append to `static/js/helpers/board.mjs`:

```js
const EMPTY_DETAIL = Object.freeze({
  kind: "NOT_VERIFIED",
  activePrograms: [],
  activeUntil: null,
  activeLessonsUntil: null,
  nextDropIn: null,
  closureReason: null,
  is_drop_in: false,
});

// Normalize the session list into { day, type, start, end } with minute-of-day
// ints and lowercased day names. Skips malformed rows.
function normalizeSessions(sessions) {
  const out = [];
  for (const session of sessions) {
    if (!session || typeof session !== "object") continue;
    const day = typeof session.day === "string" ? session.day.toLowerCase() : null;
    const type = typeof session.type === "string" ? session.type : null;
    const start = parseHHMM(session.start);
    const end = parseHHMM(session.end);
    if (!day || !DAY_KEYS.includes(day) || !type || start === null || end === null) continue;
    if (end <= start) continue;
    out.push({ day, type, start, end });
  }
  return out;
}

export function computeDetailStatus(schedule, now) {
  if (!schedule || typeof schedule !== "object") return { ...EMPTY_DETAIL };

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return {
      ...EMPTY_DETAIL,
      kind: "CLOSED_TODAY",
      closureReason: typeof activeClosure.reason === "string" ? activeClosure.reason : null,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const normalized = normalizeSessions(sessions);
  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  const activeDropIn = normalized.filter(
    (s) => s.day === todayKey && DROP_IN_TYPES.has(s.type) && s.start <= nowMinutes && nowMinutes < s.end,
  );

  if (activeDropIn.length > 0) {
    return {
      ...EMPTY_DETAIL,
      kind: "OPEN",
      activePrograms: activeDropIn.map((s) => s.type),
      activeUntil: Math.min(...activeDropIn.map((s) => s.end)),
      is_drop_in: true,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  return {
    ...EMPTY_DETAIL,
    kind: "CLOSED_HOURS",
    nextDropIn: findNextDropIn(schedule, now),
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/js/board-status.test.mjs`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/helpers/board.mjs tests/js/board-status.test.mjs
git commit -m "feat(board): add computeDetailStatus basic states

Structured state machine for the detail page status slab. Covers OPEN
(single drop-in), CLOSED_HOURS, and CLOSED_TODAY. Lessons, concurrent
drop-ins, and not-verified paths are added in follow-ups."
```

---

## Task 5: `computeDetailStatus` — LESSONS and NO_DROPIN_TODAY

Lessons sessions must not mask drop-in availability: if a drop-in session overlaps a lessons session, the status reports OPEN. A lessons session with no concurrent drop-in produces `LESSONS UNTIL HH:MM`. A day with only lessons (no drop-in at all, no active lessons right now) is `NO_DROPIN_TODAY`.

- [ ] **Step 1: Add failing tests**

```js
test("computeDetailStatus LESSONS when only lessons are active", () => {
  const schedule = {
    sessions: [
      { day: "tuesday", type: "lessons",     start: "15:30", end: "17:00" },
      { day: "tuesday", type: "family_swim", start: "17:30", end: "18:30" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-14T16:00:00"); // Tue 16:00 — inside lessons
  const r = computeDetailStatus(schedule, now);
  assert.equal(r.kind, "LESSONS");
  assert.equal(r.activeLessonsUntil, 17 * 60);
  assert.equal(r.is_drop_in, false);
  assert.deepEqual(r.nextDropIn, { program: "family_swim", day: "tuesday", start: 17 * 60 + 30 });
});

test("computeDetailStatus prefers OPEN when drop-in overlaps lessons", () => {
  const schedule = {
    sessions: [
      { day: "tuesday", type: "lessons",  start: "15:30", end: "17:30" },
      { day: "tuesday", type: "lap_swim", start: "16:00", end: "17:00" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-14T16:30:00"); // inside both
  const r = computeDetailStatus(schedule, now);
  assert.equal(r.kind, "OPEN");
  assert.deepEqual(r.activePrograms, ["lap_swim"]);
});

test("computeDetailStatus NO_DROPIN_TODAY on lessons-only day with no active session", () => {
  const schedule = {
    sessions: [
      { day: "tuesday", type: "lessons",  start: "15:30", end: "17:30" },
      { day: "wednesday", type: "lap_swim", start: "09:00", end: "10:15" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-14T10:00:00"); // Tue 10:00 — no active lessons/drop-in
  const r = computeDetailStatus(schedule, now);
  assert.equal(r.kind, "NO_DROPIN_TODAY");
  assert.equal(r.is_drop_in, false);
  assert.deepEqual(r.nextDropIn, { program: "lap_swim", day: "wednesday", start: 9 * 60 });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/board-status.test.mjs`
Expected: three FAILures (kind reports OPEN/CLOSED_HOURS in the current impl).

- [ ] **Step 3: Extend `computeDetailStatus` with lessons handling**

Replace the body of `computeDetailStatus` with this version (keeps the closure branch from Task 4, adds lessons + lessons-only-day after active drop-in check):

```js
export function computeDetailStatus(schedule, now) {
  if (!schedule || typeof schedule !== "object") return { ...EMPTY_DETAIL };

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return {
      ...EMPTY_DETAIL,
      kind: "CLOSED_TODAY",
      closureReason: typeof activeClosure.reason === "string" ? activeClosure.reason : null,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const normalized = normalizeSessions(sessions);
  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const todayAll = normalized.filter((s) => s.day === todayKey);
  const todayDropIn = todayAll.filter((s) => DROP_IN_TYPES.has(s.type));

  const activeDropIn = todayDropIn.filter(
    (s) => s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (activeDropIn.length > 0) {
    return {
      ...EMPTY_DETAIL,
      kind: "OPEN",
      activePrograms: activeDropIn.map((s) => s.type),
      activeUntil: Math.min(...activeDropIn.map((s) => s.end)),
      is_drop_in: true,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const activeLessons = todayAll.find(
    (s) => s.type === "lessons" && s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (activeLessons) {
    return {
      ...EMPTY_DETAIL,
      kind: "LESSONS",
      activeLessonsUntil: activeLessons.end,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  if (todayDropIn.length === 0 && todayAll.length > 0) {
    return {
      ...EMPTY_DETAIL,
      kind: "NO_DROPIN_TODAY",
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  return {
    ...EMPTY_DETAIL,
    kind: "CLOSED_HOURS",
    nextDropIn: findNextDropIn(schedule, now),
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/js/board-status.test.mjs`
Expected: all tests from Tasks 1–5 PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/helpers/board.mjs tests/js/board-status.test.mjs
git commit -m "feat(board): handle lessons in computeDetailStatus

Active lessons with no concurrent drop-in → LESSONS state; drop-in
overlap wins (lessons don't mask drop-in availability). A day with
only lessons sessions → NO_DROPIN_TODAY."
```

---

## Task 6: `computeDetailStatus` — NOT_VERIFIED and NO_DROPIN_WEEK

Distinguishes "we haven't verified this pool's schedule" from "the schedule is verified but has zero drop-in sessions this week" (lessons-only pool, or off-season).

- [ ] **Step 1: Add failing tests**

```js
test("computeDetailStatus NOT_VERIFIED when sessions array is empty", () => {
  const schedule = { sessions: [], closures: [] };
  const now = new Date("2026-04-14T10:00:00");
  const r = computeDetailStatus(schedule, now);
  assert.equal(r.kind, "NOT_VERIFIED");
  assert.equal(r.nextDropIn, null);
});

test("computeDetailStatus NO_DROPIN_WEEK when all sessions are lessons", () => {
  const schedule = {
    sessions: [
      { day: "tuesday", type: "lessons", start: "15:30", end: "17:30" },
      { day: "friday",  type: "lessons", start: "15:30", end: "17:30" },
    ],
    closures: [],
  };
  const now = new Date("2026-04-13T10:00:00"); // Monday 10:00
  const r = computeDetailStatus(schedule, now);
  assert.equal(r.kind, "NO_DROPIN_WEEK");
  assert.equal(r.nextDropIn, null);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/board-status.test.mjs`
Expected: two FAILures (current impl falls through to CLOSED_HOURS).

- [ ] **Step 3: Add verified/empty discrimination to `computeDetailStatus`**

In `computeDetailStatus`, insert this block **immediately after** `const normalized = normalizeSessions(sessions);`:

```js
  if (normalized.length === 0) {
    return { ...EMPTY_DETAIL, kind: "NOT_VERIFIED" };
  }
  const anyDropInThisWeek = normalized.some((s) => DROP_IN_TYPES.has(s.type));
  if (!anyDropInThisWeek) {
    return { ...EMPTY_DETAIL, kind: "NO_DROPIN_WEEK" };
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/js/board-status.test.mjs`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/helpers/board.mjs tests/js/board-status.test.mjs
git commit -m "feat(board): distinguish NOT_VERIFIED from NO_DROPIN_WEEK

Empty sessions → NOT_VERIFIED (we don't know yet). Verified schedule
with zero drop-in sessions → NO_DROPIN_WEEK (lessons-only or
off-season). Lets the detail page show honest copy for both."
```

---

## Task 7: `computeDetailStatus` — concurrent drop-in programs

Balboa Wednesday proves this is a real state: `lap_swim 12:30–15:00` overlaps `family_swim 14:00–15:00`. From 14:00 to 15:00 both programs are active concurrently. The status slab reports `OPEN — LAP + FAMILY UNTIL 15:00` (detail.js formats; here we just populate `activePrograms`). `activeUntil` is the earliest end among overlapping sessions.

- [ ] **Step 1: Add regression test pinning concurrent-drop-in behavior**

(Task 4's implementation already handles concurrent drop-in correctly because `activeDropIn` collects ALL overlapping sessions and takes the minimum end time. This test pins that behavior so a future refactor has to preserve it.)

```js
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
```

- [ ] **Step 2: Run test to verify it passes already** (this path is exercised by Task 4's implementation)

Run: `node --test tests/js/board-status.test.mjs`
Expected: PASS. The Task 4 impl already collects all overlapping drop-ins and takes the min end. This test pins the behavior.

- [ ] **Step 3: Commit**

```bash
git add tests/js/board-status.test.mjs
git commit -m "test(board): pin concurrent drop-in behavior on detail status

Balboa Wednesday: lap (12:30-15:00) + family (14:00-15:00) overlap
14:00-15:00 → both listed in activePrograms, activeUntil=15:00."
```

---

## Task 8: DST regression test

Sessions spec times in local wall-clock (`07:00`). `Date.getHours()` returns local hours per the host timezone. We rely on that. A regression test pins behavior across DST transitions so a future refactor (e.g., switching to UTC internally) would have to address DST explicitly.

- [ ] **Step 1: Add test**

```js
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `node --test tests/js/board-status.test.mjs`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/js/board-status.test.mjs
git commit -m "test(board): pin DST wall-clock behavior on computeDetailStatus"
```

---

## Task 9: Template — pool-branch skeleton rewrite

Replace the entire `{% if extra.type == "pool" %}` branch of `templates/spots/page.html` with the new section structure. Later tasks fill in weekly grid, closure banners, footer, and script wiring. This task introduces the wrapper, data-schedule embed, status slab placeholder, and a stub weekly section. Goal is a page that renders without errors at `zola build`.

**Files:**
- Modify: `templates/spots/page.html:30-83`

- [ ] **Step 1: Replace the pool branch**

In `templates/spots/page.html`, replace the block from `{% if extra.type == "pool" %}` through the closing `{% elif extra.type == "open_water" %}` (keep that line) with:

```html
  {% if extra.type == "pool" %}
    {% set sessions = extra.sessions | default(value=[]) %}
    {% set closures = extra.closures | default(value=[]) %}
    {% set sessions_json = sessions | json_encode %}
    {% set closures_json = closures | json_encode %}
    {% set schedule_json = '{"sessions":' ~ sessions_json ~ ',"closures":' ~ closures_json ~ '}' %}

    <div class="detail-root"
         data-schedule='{{ schedule_json | safe }}'
         data-last-verified="{{ extra.last_verified_at | default(value='') }}">

      {% if extra.subtype or extra.website %}
        <p class="official">
          {% if extra.subtype %}<span class="subtype">{{ extra.subtype | upper }}</span>{% endif %}
          {% if extra.subtype and extra.website %} · {% endif %}
          {% if extra.website %}<a href="{{ extra.website }}" target="_blank" rel="noopener">OFFICIAL PAGE</a>{% endif %}
        </p>
      {% endif %}

      <section class="status-slab" aria-live="polite">
        <div class="status-slab-row">
          <span class="status-slab-label">STATUS</span>
          <span class="status-slab-value" data-field="status">—</span>
        </div>
        <div class="status-slab-row">
          <span class="status-slab-label">NEXT</span>
          <span class="status-slab-value" data-field="next">—</span>
        </div>
      </section>

      {# Weekly grid, closure banners, footer meta filled in by later tasks. #}
      <section class="weekly-grid" data-placeholder="weekly"></section>
      <section class="closure-banners" data-placeholder="closures"></section>
      <footer class="meta" data-placeholder="meta"></footer>
    </div>

  {% elif extra.type == "open_water" %}
```

- [ ] **Step 2: Build and verify no template error**

Run: `zola build`
Expected: build succeeds. Pool pages render the skeleton with STATUS/NEXT showing `—`.

- [ ] **Step 3: Commit**

```bash
git add templates/spots/page.html
git commit -m "refactor(spots): replace pool-page table with redesigned skeleton

Introduces .detail-root wrapper carrying data-schedule JSON plus the
status slab placeholder. Weekly grid, closure banners, and footer
meta are stubs filled by follow-up commits."
```

---

## Task 10: Template — weekly grid

Server-renders a 3-row × 7-col grid grouped by program (LAP / FAMILY / SENIOR) × day (MON–SUN). The SENIOR row is omitted when the pool has zero senior sessions. Each cell stacks its sessions with time range and optional zone parenthetical. An em-dash placeholder fills empty cells.

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Replace the `<section class="weekly-grid" …></section>` stub with the rendering block**

```html
      {% set day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] %}
      {% set day_labels = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] %}
      {% set lap_sessions = sessions | filter(attribute="type", value="lap_swim") %}
      {% set family_sessions = sessions | filter(attribute="type", value="family_swim") %}
      {% set senior_sessions = sessions | filter(attribute="type", value="senior_swim") %}

      {% if sessions | length > 0 %}
        {% if senior_sessions | length > 0 %}
          {% set programs = [
            ["lap_swim",    "LAP SWIM",    lap_sessions,    "lap"],
            ["family_swim", "FAMILY SWIM", family_sessions, "family"],
            ["senior_swim", "SENIOR SWIM", senior_sessions, ""]
          ] %}
        {% else %}
          {% set programs = [
            ["lap_swim",    "LAP SWIM",    lap_sessions,    "lap"],
            ["family_swim", "FAMILY SWIM", family_sessions, "family"]
          ] %}
        {% endif %}

        <section class="weekly-grid">
          <h2 class="weekly-grid-title">WEEKLY · BY PROGRAM</h2>
          <div class="weekly-grid-table" role="table">
            <div class="weekly-grid-head" role="row">
              <span class="weekly-grid-rowlabel" role="columnheader"></span>
              {% for label in day_labels %}
                <span class="weekly-grid-dayhead" role="columnheader" data-day="{{ day_order[loop.index0] }}">{{ label }}</span>
              {% endfor %}
            </div>
            {% for prog in programs %}
              <div class="weekly-grid-row" role="row" data-program="{{ prog[0] }}">
                <span class="weekly-grid-rowlabel" role="rowheader">
                  {{ prog[1] }}
                  {% if prog[3] %}
                    <a class="weekly-grid-crossnav" href="{{ config.base_url }}/#{{ prog[3] }}">→ OTHER {{ prog[3] | upper }} POOLS</a>
                  {% endif %}
                </span>
                {% for day in day_order %}
                  {% set cell = prog[2] | filter(attribute="day", value=day) %}
                  <span class="weekly-grid-cell" role="cell" data-day="{{ day }}">
                    {% if cell | length == 0 %}
                      <span class="weekly-grid-empty">—</span>
                    {% else %}
                      {% for s in cell %}
                        <span class="weekly-grid-session">
                          {{ s.start }}–{{ s.end }}{% if s.pool %} <span class="zone">({{ s.pool }})</span>{% endif %}
                        </span>
                      {% endfor %}
                    {% endif %}
                  </span>
                {% endfor %}
              </div>
            {% endfor %}
          </div>
        </section>
      {% else %}
        <p class="fallback">Schedule not yet verified.</p>
      {% endif %}
```

- [ ] **Step 2: Verify `zola build`**

Run: `zola build`
Expected: build succeeds. Pool pages show the 3-row (or 2-row, if no senior) × 7-col weekly grid with real data.

- [ ] **Step 3: Spot-check Balboa, North Beach, Hamilton in dev server**

Run: `zola serve` → visit `/spots/balboa-pool/`, `/spots/north-beach-pool/`, `/spots/hamilton-pool/`.
Expected: each shows a grid with real session times; unstyled at this point (styling in later SCSS tasks).

- [ ] **Step 4: Commit**

```bash
git add templates/spots/page.html
git commit -m "feat(spots): render weekly schedule as program×day grid

LAP and FAMILY rows always present; SENIOR conditional on presence.
Each cell stacks session time ranges with zone parenthetical. Cross-
nav links reuse the homepage hash filter tokens (#lap, #family)."
```

---

## Task 11: Template — closure banners

Server-renders one banner per closure whose `[start, end]` range overlaps `[today, today+14]`. Uses Tera's `now()` + timestamp arithmetic for the window bounds. Zone label is shown when non-empty.

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Replace the `<section class="closure-banners">` stub**

```html
      {% set today_ts = now(timestamp=true) %}
      {% set today_iso = today_ts | date(format="%Y-%m-%d") %}
      {% set window_end_iso = (today_ts + 1209600) | date(format="%Y-%m-%d") %}
      {% set upcoming_closures = [] %}
      {% for c in closures %}
        {% if c.start <= window_end_iso and c.end >= today_iso %}
          {% set_global upcoming_closures = upcoming_closures | concat(with=c) %}
        {% endif %}
      {% endfor %}

      {% if upcoming_closures | length > 0 %}
        <section class="closure-banners" aria-label="Upcoming closures">
          {% for c in upcoming_closures %}
            <div class="closure-banner">
              <span class="closure-banner-date">
                {% if c.start == c.end %}
                  {{ c.start | date(format="%b %-d") | upper }}
                {% else %}
                  {{ c.start | date(format="%b %-d") | upper }} – {{ c.end | date(format="%b %-d") | upper }}
                {% endif %}
              </span>
              {% if c.pool %}<span class="closure-banner-zone">{{ c.pool | upper }}</span>{% endif %}
              <span class="closure-banner-reason">{{ c.reason }}</span>
            </div>
          {% endfor %}
        </section>
      {% endif %}
```

(Remove the empty `<section class="closure-banners" data-placeholder="closures"></section>` stub.)

- [ ] **Step 2: Verify `zola build`**

Run: `zola build`
Expected: succeeds. For a pool with an upcoming closure (Balboa has May 21 / May 25 / Jun 6 training + holiday entries), a banner renders; closures outside the 14-day window do not.

- [ ] **Step 3: Commit**

```bash
git add templates/spots/page.html
git commit -m "feat(spots): render upcoming closures as range-overlap banners

Shows any closure whose [start, end] range overlaps [today, today+14]
— includes in-flight closures that started before today, not just
those starting in the window."
```

---

## Task 12: Template — footer meta with freshness dot

Server-renders `SCHEDULE EFFECTIVE … → …` when available, plus a freshness indicator `● FRESH · LAST VERIFIED <date>` / `· STALE · LAST VERIFIED <date>`. Initial class is computed server-side from `last_verified_at` at build time; detail.js re-computes at load so cached/stale deploys stay honest.

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Replace the `<footer class="meta">` stub**

```html
      <footer class="meta">
        {% if extra.schedule_effective %}
          <p class="meta-effective">
            SCHEDULE EFFECTIVE {{ extra.schedule_effective | upper }}{% if extra.schedule_effective_end %} → {{ extra.schedule_effective_end | upper }}{% endif %}
          </p>
        {% endif %}
        {% if extra.last_verified_at %}
          <p class="meta-freshness" data-field="freshness">
            <span class="freshness-dot">●</span>
            <span class="freshness-label">FRESH</span>
            · LAST VERIFIED {{ extra.last_verified_at | upper }}
          </p>
        {% endif %}
      </footer>

      {% if page.content %}
        <section class="description">
          {{ page.content | safe }}
        </section>
      {% endif %}
    </div>  {# /.detail-root #}
```

Note: the pool description moves INSIDE `.detail-root` (above the closing `</div>`). Guard the trailing `.notes` section in the content block so it only fires for open-water pages (pool `page.content` is now rendered by the `.detail-root` block above). Change the end of `{% block content %}` from:

```
  {% endif %}

  {% if page.content %}
    <section class="notes">
      {{ page.content | safe }}
    </section>
  {% endif %}
{% endblock %}
```

to:

```
  {% endif %}

  {% if page.content and extra.type == "open_water" %}
    <section class="notes">
      {{ page.content | safe }}
    </section>
  {% endif %}
{% endblock %}
```

- [ ] **Step 2: Verify `zola build`**

Run: `zola build`
Expected: builds; footer shows schedule effective range and a freshness line with a default FRESH class.

- [ ] **Step 3: Commit**

```bash
git add templates/spots/page.html
git commit -m "feat(spots): add footer schedule meta + freshness dot

Server-renders initial 'FRESH' label; detail.js will re-evaluate at
load time against last_verified_at."
```

---

## Task 13: Template — scripts block for detail.js

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Extend the scripts block**

Replace:

```html
{% block scripts %}
  {% if page.extra.type == "open_water" %}
    <script type="module" src="{{ get_url(path='js/conditions.js') }}"></script>
  {% endif %}
{% endblock %}
```

with:

```html
{% block scripts %}
  {% if page.extra.type == "open_water" %}
    <script type="module" src="{{ get_url(path='js/conditions.js') }}"></script>
  {% elif page.extra.type == "pool" %}
    <script type="module" src="{{ get_url(path='js/detail.js') }}"></script>
  {% endif %}
{% endblock %}
```

- [ ] **Step 2: Verify `zola build`** (detail.js doesn't exist yet — the tag will 404 at runtime but build passes because Zola doesn't fetch referenced scripts).

Run: `zola build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add templates/spots/page.html
git commit -m "chore(spots): wire detail.js into pool page scripts block"
```

---

## Task 14: SCSS — status slab + today block

**Files:**
- Modify: `sass/main.scss`

- [ ] **Step 1: Append new styles at end of `sass/main.scss` (before the `@media (max-width: 640px)` block — we'll add the mobile overrides inside it in Task 15)**

```scss
// --- Spot detail page (v2 redesign) -------------------------------------

.detail-root {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  margin: 1rem 0;
}

.detail-root .official {
  margin: 0;
  font-size: 0.85rem;
  color: var(--fg-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.status-slab {
  border: 1px solid var(--fg);
  padding: 0.75rem 1rem;
  display: grid;
  grid-template-columns: 8ch 1fr;
  row-gap: 0.35rem;
  column-gap: 1rem;
  font-size: 0.95rem;
}

.status-slab-row {
  display: contents;
}

.status-slab-label {
  color: var(--fg-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.status-slab-value {
  color: var(--fg);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.today-block {
  border-top: 1px solid var(--row-sep);
  padding-top: 0.75rem;
}

.today-block-heading {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
  color: var(--fg-dim);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.today-block-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: max-content 1fr max-content;
  column-gap: 1rem;
  row-gap: 0.3rem;
  font-size: 0.9rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.today-block-list li {
  display: contents;
}

.today-block-list .time {
  white-space: nowrap;
}

.today-block-list .now-marker {
  color: var(--accent);
}

.today-block-list .row-label {
  color: var(--fg-dim);
  justify-self: end;
}
```

- [ ] **Step 2: Verify `zola build`**

Run: `zola build`
Expected: builds; status slab has a visible border; today block markup isn't injected yet (that's Task 17).

- [ ] **Step 3: Commit**

```bash
git add sass/main.scss
git commit -m "style(spots): status slab + today block styles"
```

---

## Task 15: SCSS — weekly grid (desktop + mobile)

**Files:**
- Modify: `sass/main.scss`

- [ ] **Step 1: Append weekly-grid desktop rules after the today-block styles**

```scss
// Weekly grid — desktop (default) -----------------------------------------

.weekly-grid-title {
  margin: 0 0 0.5rem;
  font-size: 1rem;
  color: var(--fg);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.weekly-grid-table {
  display: grid;
  grid-template-columns: 10ch repeat(7, minmax(7ch, 1fr));
  border-top: 1px solid var(--fg);
  font-size: 0.85rem;
}

.weekly-grid-head,
.weekly-grid-row {
  display: contents;
}

.weekly-grid-rowlabel,
.weekly-grid-dayhead,
.weekly-grid-cell {
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--row-sep);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.weekly-grid-dayhead {
  color: var(--fg-dim);
  font-size: 0.8rem;
  text-align: left;
}

.weekly-grid-rowlabel {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  color: var(--fg);
  font-weight: 700;
}

.weekly-grid-crossnav {
  color: var(--fg-dim);
  font-size: 0.75rem;
  font-weight: 400;

  &:hover,
  &:focus {
    color: var(--fg);
  }
}

.weekly-grid-cell {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.weekly-grid-session {
  white-space: nowrap;
}

.weekly-grid-empty {
  color: var(--fg-dim);
}

.weekly-grid-cell[data-today="true"],
.weekly-grid-dayhead[data-today="true"] {
  background: rgba(245, 197, 24, 0.08);
}

.zone {
  color: var(--fg-dim);
  font-size: 0.85em;
  text-transform: lowercase;
  letter-spacing: 0;
}
```

- [ ] **Step 2: Add mobile collapse inside the existing `@media (max-width: 640px)` block**

Inside the existing `@media (max-width: 640px) { … }` in `sass/main.scss`, append:

```scss
  // Weekly grid collapses to one-column stacks grouped by program.
  // Row-label becomes a heading; day header row is hidden; each cell
  // becomes a row prefixed by its weekday abbreviation.
  .weekly-grid-table {
    grid-template-columns: 1fr;
    border-top: none;
  }

  .weekly-grid-head {
    display: none;
  }

  .weekly-grid-rowlabel {
    border-bottom: 1px solid var(--fg);
    padding-top: 1rem;
    flex-direction: row;
  }

  .weekly-grid-cell {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 0.5rem;
    padding-left: 0.5rem;
  }

  .weekly-grid-cell::before {
    content: attr(data-day-short);
    color: var(--fg-dim);
    min-width: 4ch;
    text-transform: uppercase;
  }

  .weekly-grid-cell[data-empty="true"] {
    display: none;
  }
```

- [ ] **Step 3: Add `data-day-short` attributes in the template**

In `templates/spots/page.html`, update the weekly-grid cell line to include a short-day label:

```html
                  <span class="weekly-grid-cell" role="cell" data-day="{{ day }}" data-day-short="{{ day_labels[loop.index0] }}"{% if cell | length == 0 %} data-empty="true"{% endif %}>
```

- [ ] **Step 4: Verify `zola build` + visual check at 375px viewport**

Run: `zola build && zola serve` → open `/spots/balboa-pool/` and resize to 375px.
Expected: desktop shows 7-column grid; mobile stacks each program into a single column with day prefixes.

- [ ] **Step 5: Commit**

```bash
git add sass/main.scss templates/spots/page.html
git commit -m "style(spots): weekly grid layout for desktop + mobile

Seven-column grid above 640px; stacks into single-column program
sections with weekday prefixes below. Empty cells hide on mobile."
```

---

## Task 16: SCSS — closure banner + freshness dot

**Files:**
- Modify: `sass/main.scss`

- [ ] **Step 1: Append to `sass/main.scss`**

```scss
// Closure banners ---------------------------------------------------------

.closure-banners {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.closure-banner {
  border-left: 3px solid var(--fg);
  background: rgba(245, 197, 24, 0.08);
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem 0.75rem;
  font-size: 0.9rem;
}

.closure-banner-date,
.closure-banner-zone {
  color: var(--fg);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 700;
}

.closure-banner-reason {
  color: var(--fg-dim);
  flex: 1 1 auto;
}

// Freshness dot + meta ----------------------------------------------------

.meta-effective,
.meta-freshness {
  margin: 0.25rem 0;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--fg-dim);
}

.meta-freshness .freshness-dot {
  color: var(--fg);
  margin-right: 0.25rem;
}

.meta-freshness[data-freshness="stale"] .freshness-dot {
  color: var(--fg-dim);
}

// Description block (moved from .notes) ----------------------------------

.description {
  color: var(--fg-dim);
  font-size: 0.9rem;
  line-height: 1.5;
  margin-top: 1.5rem;
  // Prose stays natural case — do NOT uppercase.
  text-transform: none;
}
```

- [ ] **Step 2: Remove obsolete rules**

In `sass/main.scss`, delete the obsolete `.schedule-table { … }` block (now unused — the pool branch no longer renders a table) and the `.closures ul` selector piece inside the `.hazards ul, .clubs ul, .distances ul, .closures ul` group. Update the multi-selector to drop `.closures ul`:

Change:
```scss
.hazards ul,
.clubs ul,
.distances ul,
.closures ul {
```

to:

```scss
.hazards ul,
.clubs ul,
.distances ul {
```

Delete the `.schedule-table { … }` block entirely.

- [ ] **Step 3: Verify `zola build`**

Run: `zola build`
Expected: builds; closure banners appear with left border; freshness line styled.

- [ ] **Step 4: Commit**

```bash
git add sass/main.scss
git commit -m "style(spots): closure banners + freshness dot + description

Drops obsolete .schedule-table and .closures ul rules (no longer
rendered). Description keeps natural case — uppercase is chrome only."
```

---

## Task 17: detail.js — status slab hydration

**Files:**
- Create: `static/js/detail.js`
- Test: manual (DOM glue; pure logic lives in board.mjs helpers already tested)

- [ ] **Step 1: Create `static/js/detail.js`**

Write this file to `static/js/detail.js`:

```js
// SwimFrancisco pool detail page.
// Reads the schedule embedded in .detail-root[data-schedule], hydrates the
// status slab, injects the today block, marks today's column in the weekly
// grid, and updates the freshness dot. Pure computation lives in
// ./helpers/board.mjs (exercised by node:test).

import {
  DAY_KEYS,
  computeDetailStatus,
  freshnessLabel,
  formatHHMM,
} from "./helpers/board.mjs";

const PROGRAM_LABEL = {
  lap_swim: "LAP",
  family_swim: "FAMILY",
  senior_swim: "SENIOR",
};

const DAY_LABEL_SHORT = {
  sunday: "SUN",
  monday: "MON",
  tuesday: "TUE",
  wednesday: "WED",
  thursday: "THU",
  friday: "FRI",
  saturday: "SAT",
};

function readSchedule(root) {
  const raw = root.getAttribute("data-schedule");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

function formatStatusLine(result) {
  switch (result.kind) {
    case "OPEN": {
      const programs = result.activePrograms.map((p) => PROGRAM_LABEL[p] || p.toUpperCase()).join(" + ");
      return `OPEN — ${programs} UNTIL ${formatHHMM(result.activeUntil)}`;
    }
    case "LESSONS":
      return `LESSONS UNTIL ${formatHHMM(result.activeLessonsUntil)}`;
    case "CLOSED_TODAY":
      return result.closureReason
        ? `CLOSED TODAY — ${result.closureReason.toUpperCase()}`
        : "CLOSED TODAY";
    case "CLOSED_HOURS":
    case "NO_DROPIN_TODAY": {
      if (!result.nextDropIn) return "CLOSED";
      const program = PROGRAM_LABEL[result.nextDropIn.program] || result.nextDropIn.program.toUpperCase();
      const day = DAY_LABEL_SHORT[result.nextDropIn.day] || result.nextDropIn.day.toUpperCase();
      const time = formatHHMM(result.nextDropIn.start);
      const prefix = result.kind === "NO_DROPIN_TODAY" ? "NO DROP-IN TODAY" : "CLOSED";
      return `${prefix} — NEXT ${program} ${day} ${time}`;
    }
    case "NOT_VERIFIED":
      return "SCHEDULE NOT YET VERIFIED";
    case "NO_DROPIN_WEEK":
      return "NO DROP-IN THIS WEEK";
    default:
      return "—";
  }
}

function formatNextLine(result) {
  // The STATUS line already carries NEXT info for these kinds.
  const inlineKinds = new Set([
    "CLOSED_TODAY", "CLOSED_HOURS", "NO_DROPIN_TODAY", "NOT_VERIFIED", "NO_DROPIN_WEEK",
  ]);
  if (inlineKinds.has(result.kind)) return "—";
  if (!result.nextDropIn) return "—";
  const program = PROGRAM_LABEL[result.nextDropIn.program] || result.nextDropIn.program.toUpperCase();
  const day = DAY_LABEL_SHORT[result.nextDropIn.day] || result.nextDropIn.day.toUpperCase();
  return `${program} · ${day} ${formatHHMM(result.nextDropIn.start)}`;
}

function applyStatusSlab(root, schedule, now) {
  const result = computeDetailStatus(schedule, now);
  const statusEl = root.querySelector('[data-field="status"]');
  const nextEl = root.querySelector('[data-field="next"]');
  if (statusEl) statusEl.textContent = formatStatusLine(result);
  if (nextEl) nextEl.textContent = formatNextLine(result);
  return result;
}

function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readSchedule(root);
  if (!schedule) return;
  const now = new Date();
  applyStatusSlab(root, schedule, now);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
```

- [ ] **Step 2: Verify `zola build` + manual load**

Run: `zola build && zola serve` → open `/spots/balboa-pool/`.
Expected: status slab shows something like `STATUS: OPEN — LAP UNTIL 14:00` / `NEXT: FAMILY · TUE 14:30` (exact text depends on current time).

- [ ] **Step 3: Commit**

```bash
git add static/js/detail.js
git commit -m "feat(spots): hydrate detail-page status slab

New detail.js reads data-schedule from .detail-root and replaces the
STATUS / NEXT placeholders with formatted text derived from
computeDetailStatus."
```

---

## Task 18: detail.js — today block injection + decorations

Builds the today block from the schedule data (pure client-side). Injected below the status slab. Each row shows `HH:MM–HH:MM  PROGRAM  [● NOW|NEXT]`.

**Files:**
- Modify: `static/js/detail.js`

- [ ] **Step 1: Extend `detail.js`**

After the `applyStatusSlab` function and before `init`, add:

```js
const DROP_IN_TYPES = new Set(["lap_swim", "family_swim", "senior_swim"]);

function parseHHMMSafe(value) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(value || "").trim());
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

function todaysDropInSessions(schedule, now) {
  if (!schedule || !Array.isArray(schedule.sessions)) return [];
  const todayKey = DAY_KEYS[now.getDay()];
  return schedule.sessions
    .filter((s) => s && DROP_IN_TYPES.has(s.type) && typeof s.day === "string" && s.day.toLowerCase() === todayKey)
    .map((s) => ({
      program: s.type,
      start: parseHHMMSafe(s.start),
      end: parseHHMMSafe(s.end),
    }))
    .filter((s) => s.start !== null && s.end !== null && s.end > s.start)
    .sort((a, b) => a.start - b.start);
}

function renderTodayBlock(root, schedule, now, statusResult) {
  // Suppressed on closed-today, not-verified, no-drop-in-week, and
  // lessons-only day — the status slab already tells that story.
  const suppressedKinds = new Set([
    "CLOSED_TODAY", "NOT_VERIFIED", "NO_DROPIN_WEEK", "NO_DROPIN_TODAY",
  ]);
  if (suppressedKinds.has(statusResult.kind)) return;

  const sessions = todaysDropInSessions(schedule, now);
  if (sessions.length === 0) return;

  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const weekdayName = now.toLocaleDateString(undefined, { weekday: "long" }).toUpperCase();

  const block = document.createElement("section");
  block.className = "today-block";
  const heading = document.createElement("p");
  heading.className = "today-block-heading";
  heading.textContent = `TODAY · ${weekdayName}`;
  block.appendChild(heading);

  const list = document.createElement("ul");
  list.className = "today-block-list";

  // First future-not-active session (for the NEXT label).
  const firstNextIndex = sessions.findIndex((s) => s.start > nowMinutes);

  sessions.forEach((s, i) => {
    const li = document.createElement("li");
    const isNow = s.start <= nowMinutes && nowMinutes < s.end;
    const timeSpan = document.createElement("span");
    timeSpan.className = "time";
    timeSpan.textContent = `${isNow ? "● " : ""}${formatHHMM(s.start)}–${formatHHMM(s.end)}`;
    const programSpan = document.createElement("span");
    programSpan.className = "program";
    programSpan.textContent = PROGRAM_LABEL[s.program] || s.program.toUpperCase();
    const labelSpan = document.createElement("span");
    labelSpan.className = "row-label";
    if (isNow) labelSpan.textContent = "NOW";
    else if (i === firstNextIndex) labelSpan.textContent = "NEXT";
    else labelSpan.textContent = "";
    li.appendChild(timeSpan);
    li.appendChild(programSpan);
    li.appendChild(labelSpan);
    list.appendChild(li);
  });

  block.appendChild(list);
  const slab = root.querySelector(".status-slab");
  if (slab && slab.parentNode) {
    slab.insertAdjacentElement("afterend", block);
  }
}
```

Then replace the `init` function:

```js
function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readSchedule(root);
  if (!schedule) return;
  const now = new Date();
  const result = applyStatusSlab(root, schedule, now);
  renderTodayBlock(root, schedule, now, result);
}
```

- [ ] **Step 2: Verify `zola build` + manual load**

Run: `zola build && zola serve` → open `/spots/balboa-pool/` during a day that has drop-in sessions.
Expected: a `TODAY · TUESDAY` block with session rows; the currently-live row is prefixed `●` with a `NOW` label; the next-future row has `NEXT`.

- [ ] **Step 3: Commit**

```bash
git add static/js/detail.js
git commit -m "feat(spots): inject today block with ● NOW / NEXT markers

Pure client-side; reads sessions from data-schedule and renders
today's drop-in list below the status slab. Suppressed when status
slab already carries the story (CLOSED_TODAY, NOT_VERIFIED, etc)."
```

---

## Task 19: detail.js — freshness dot + today-column highlight

**Files:**
- Modify: `static/js/detail.js`

- [ ] **Step 1: Extend `detail.js` with the two helpers**

Add before `init`:

```js
function applyFreshness(root, now) {
  const el = root.querySelector('[data-field="freshness"]');
  if (!el) return;
  const iso = root.getAttribute("data-last-verified");
  const label = freshnessLabel(iso, now);
  el.setAttribute("data-freshness", label);
  const labelEl = el.querySelector(".freshness-label");
  if (labelEl) labelEl.textContent = label.toUpperCase();
}

function markTodayColumn(root, now) {
  const todayKey = DAY_KEYS[now.getDay()];
  const dayheads = root.querySelectorAll(`.weekly-grid-dayhead[data-day="${todayKey}"]`);
  dayheads.forEach((el) => el.setAttribute("data-today", "true"));
  const cells = root.querySelectorAll(`.weekly-grid-cell[data-day="${todayKey}"]`);
  cells.forEach((el) => el.setAttribute("data-today", "true"));
}
```

Update `init`:

```js
function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readSchedule(root);
  if (!schedule) return;
  const now = new Date();
  const result = applyStatusSlab(root, schedule, now);
  renderTodayBlock(root, schedule, now, result);
  markTodayColumn(root, now);
  applyFreshness(root, now);
}
```

- [ ] **Step 2: Verify at `zola serve`**

Open a pool detail page. Expected: today's column has a subtle background tint (desktop) / row appears at the top of each program's stack (mobile handled via CSS ordering already). Freshness line reads FRESH (yellow dot) when `last_verified_at` is within 30 days, STALE (dim dot) otherwise.

- [ ] **Step 3: Commit**

```bash
git add static/js/detail.js
git commit -m "feat(spots): mark today's column + update freshness dot

Completes detail.js client-side enhancements. Freshness label is
recomputed at page load against last_verified_at, so a build that
drifts across the 30-day boundary reflects reality in the browser."
```

---

## Task 20: Regression sweep — zola build + all tests + visual checks

**Files:** none (verification task).

- [ ] **Step 1: Run the full test suite**

Run: `node --test tests/js/`
Expected: all tests pass (the board-status suite plus existing conditions/noaa suites).

- [ ] **Step 2: Run `zola build`**

Run: `zola build`
Expected: clean build, no template errors, no broken links warnings.

- [ ] **Step 3: Manual visual sweep** (start `zola serve` and walk through)

Visit each and confirm the expected shape. Record any breakages as follow-up tasks.

- `/spots/balboa-pool/` — zoned, moderate density; weekly grid 3 rows (LAP, FAMILY, SENIOR); Wednesday row shows both `lap_swim 12:30–15:00` and `family_swim 14:00–15:00` stacked in Wed cell of both rows.
- `/spots/north-beach-pool/` — high density; the Wednesday column should be the stress test.
- `/spots/hamilton-pool/` — populated, single-zone.
- `/spots/martin-luther-king-jr-pool/` — single-zone, low density.
- `/spots/mission-community-pool/` or `/spots/sava-pool/` — empty `sessions` → status slab shows `SCHEDULE NOT YET VERIFIED`; no weekly grid; fallback paragraph.
- `/spots/aquatic-park/` — open water; untouched.
- `/` — homepage unchanged.
- Resize to 375px on Balboa; confirm mobile stack.
- Visit `/#lap` — LAP filter preselected (verifies the cross-nav target).

- [ ] **Step 4: Commit any test/spec corrections surfaced by the sweep** (no-op if none).

---

## Task 21: Archive multi-pool-facilities plan

The frontend steps of `docs/plans/multi-pool-facilities.md` are now implemented via this redesign. Annotate the old plan as superseded and leave the document in place for history.

**Files:**
- Modify: `docs/plans/multi-pool-facilities.md`

- [ ] **Step 1: Prepend a superseded banner to the old plan**

Open `docs/plans/multi-pool-facilities.md` and insert at the very top, above the existing header:

```markdown
> **Superseded — 2026-04-18.** Frontend work (zone rendering on detail pages,
> zone-scoped closure logic on the homepage, detail-page layout) landed via
> [`docs/superpowers/plans/2026-04-18-spot-detail-redesign.md`](../superpowers/plans/2026-04-18-spot-detail-redesign.md)
> and the design spec
> [`docs/superpowers/specs/2026-04-17-spot-detail-redesign-design.md`](../superpowers/specs/2026-04-17-spot-detail-redesign-design.md).
> Backend extractor work in this plan (populating `session.pool` from PDFs
> for multi-zone facilities) remains open as a separate data task.

---
```

- [ ] **Step 2: Commit**

```bash
git add docs/plans/multi-pool-facilities.md
git commit -m "docs(plans): mark multi-pool-facilities frontend as superseded"
```

---

## Self-Review Notes

**Spec coverage check:**
- Program-primary weekly grid → Task 10 + Task 15
- Status slab with full state machine → Tasks 4–8 + 17
- Today block (today-only, no toggle) → Task 18
- Zone rendering inline → Task 10 (Tera emits `<span class="zone">`) + Task 15 (CSS)
- Zone-scoped closures ignored on homepage → Task 1
- Closure banner range-overlap window → Task 11
- Freshness dot → Task 12 (server) + Task 19 (client)
- Cross-nav to homepage program filter → Task 10 (`/#lap`, `/#family`) — relies on existing hash handling, no `filters.js` change needed
- Mobile collapse → Task 15
- DST correctness → Task 8
- Aesthetic: uppercase chrome, mixed-case prose → Task 16 (`.description` explicitly `text-transform: none`)
- Open-water unchanged → untouched branch in Task 9
- Archiving old plan → Task 21

**Design-note deviation:** Spec line "`filters.js` accepts a `?filter=<type>` URL parameter on load" is obsolete — the homepage already supports `/#lap` / `/#family` hash tokens (see `filters.js:29-41`). Cross-nav uses those directly; no JS change. If a future task needs query-param support, add it then.

**Scope:** 21 tasks is a lot, but each is a tight, commit-sized change. The plan is appropriately decomposed; no further splitting warranted.
