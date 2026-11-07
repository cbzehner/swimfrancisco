import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { splitFrontMatter } from "../../scripts/lib/spot-frontmatter.mjs";
import {
  PLACEHOLDER, computeStatus, computeDetailStatus, computeWindowAvailability,
  findActiveClosure, findNextDropIn, resolveActiveSchedule,
} from "../../static/js/helpers/board.mjs";

const path = new URL("../../content/spots/sava-pool.md", import.meta.url);
const { front } = splitFrontMatter(readFileSync(path, "utf8"), path.pathname);
const legacy = (schedules = []) => ({ schedules: schedules.filter((window) => window.effective_start < "2026-11-03") });

function assertWithdrawnHours(schedules) {
  const history = legacy(schedules);
  for (const window of history.schedules) {
    assert.ok(window.effective_end && window.effective_end <= "2026-11-02", "Withdrawn Sava recommendations must end by November 2");
    assert.equal(new Date(window.effective_end).toISOString().slice(0, 10), window.effective_end);
  }
  // just pins TZ=America/Los_Angeles. Keep explicit closures, including those
  // beyond the shortened recommendation window, distinct from unknown hours.
  for (const instant of [
    "2026-11-03T08:00:00Z", "2026-11-07T22:00:00Z", "2026-11-11T18:00:00Z",
    "2026-11-13T23:15:00Z", "2026-11-20T21:00:00Z", "2026-11-26T18:00:00Z",
    "2026-12-05T18:00:00Z", "2026-12-19T18:00:00Z", "2026-12-20T18:00:00Z",
    "2026-12-22T17:30:00Z", "2027-01-08T21:00:00Z",
  ]) {
    const now = new Date(instant);
    const selected = resolveActiveSchedule(history, now);
    const closure = findActiveClosure(selected?.closures, now);
    const board = computeStatus(history, now);
    assert.equal(board.status, closure ? "CLOSED" : history.schedules.length ? "CHECK" : PLACEHOLDER, instant);
    if (history.schedules.length && !closure) assert.equal(board.nextKind, "schedule_ended", instant);
    const detail = computeDetailStatus(history, now);
    assert.equal(detail.kind, closure ? "CLOSED_TODAY" : "NOT_VERIFIED", instant);
    assert.equal(detail.nextDropIn, null, instant);
    assert.equal(findNextDropIn(history, now), null, instant);
    const horizon = { kind: "window", date: now.toLocaleDateString("en-CA"),
      day: ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][now.getDay()],
      start: now.getHours() * 60 + now.getMinutes(), end: Math.min(1440, now.getHours() * 60 + now.getMinutes() + 30) };
    const planned = computeWindowAvailability(history, horizon);
    if (closure?.start_time) {
      // A full-day expired boundary may take planning precedence over a timed
      // notice; neither conservative result may offer a swimming window.
      assert.ok(["CHECK", "CLOSED"].includes(planned.status), instant);
    } else {
      assert.equal(planned.status, closure ? "CLOSED" : history.schedules.length ? "CHECK" : "NO SESSION", instant);
    }
    assert.equal(planned.bestWindow, null, instant);
  }
}

test("Sava's conflicting legacy hours cannot recommend a swim", () => {
  assertWithdrawnHours(front.extra.schedules);
});

test("Sava's withdrawal permits a successor and pruning, but rejects restoration", () => {
  // Synthetic successor, not official hours or a real review/approval.
  const successor = { effective_start: "2026-11-03", effective_end: "2026-12-31", schedule_basis: "swim_schedule",
    sessions: [{ day: "saturday", type: "lap_swim", start: "08:00", end: "09:00" }], closures: [] };
  const bounded = { effective_start: "2026-08-29", effective_end: "2026-11-02", schedule_basis: "swim_schedule",
    sessions: [{ day: "friday", type: "lap_swim", start: "12:00", end: "16:00" }], closures: [] };
  assertWithdrawnHours([]);
  assertWithdrawnHours([successor]);
  assertWithdrawnHours([bounded, successor]);
  for (const effective_end of [undefined, "2026-12-12"]) {
    assert.throws(() => assertWithdrawnHours([{ ...bounded, effective_end }]), /must end by November 2/);
  }
  const now = new Date("2026-11-07T16:30:00Z");
  for (const schedules of [[successor], [bounded, successor]]) {
    assert.equal(computeStatus({ schedules }, now).status, "OPEN");
    assert.equal(computeDetailStatus({ schedules }, now).kind, "OPEN");
  }
});

test("Sava's recommendation cutoff uses Pacific midnight without a future swim", () => {
  const history = legacy(front.extra.schedules);
  if (!history.schedules.length) return; // A reviewed successor can prune history.
  const before = new Date("2026-11-03T07:59:00Z");
  assert.notEqual(computeStatus(history, before).nextKind, "schedule_ended");
  assert.equal(findNextDropIn(history, before), null);
  const after = new Date("2026-11-03T08:00:00Z");
  assert.equal(computeStatus(history, after).status, "CHECK");
  assert.equal(computeStatus(history, after).nextKind, "schedule_ended");
  assert.equal(findNextDropIn(history, after), null);
});
