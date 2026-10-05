import { test } from "node:test";
import assert from "node:assert/strict";
import { evaluateBoard } from "../../static/js/helpers/board.mjs";
import { initialBoardState, parseBoardHash, serializeBoardHash, transitionBoard } from "../../static/js/helpers/board-state.mjs";
import { catalog, programSpots } from "../fixtures/board-spots.mjs";

const instant = new Date("2026-09-24T18:30:00Z");
const query = (overrides = {}) => ({ ...initialBoardState(), ...overrides });
const visible = (snapshot) => snapshot.entries.filter((entry) => !entry.hidden);
const decisions = (snapshot) => visible(snapshot).map(({ slug, result }) => [slug, result.status, result.next]);
const evaluate = (spots, overrides, time = instant) => evaluateBoard(catalog(spots), query(overrides), time);
const orderingSpots = [
  { slug: "tomorrow", name: "Alpha", schedules: [{ sessions: [{ day: "friday", type: "lap_swim", start: "09:00", end: "10:00" }] }] },
  { slug: "unknown", name: "Beta" },
  { slug: "open", name: "Middle", schedules: [{ sessions: [{ day: "thursday", type: "lap_swim", start: "11:00", end: "13:00" }] }] },
  { slug: "soon", name: "Zulu", schedules: [{ sessions: [{ day: "thursday", type: "lap_swim", start: "12:00", end: "13:00" }] }] },
  { slug: "beach", type: "open_water" },
];

test("board default ordering keeps open pools first, then alphabetical closed pools, then beaches", () => {
  assert.deepEqual(visible(evaluate(orderingSpots)).map(({ slug }) => slug), ["open", "tomorrow", "soon", "unknown", "beach"]);
});

test("board Open/Next ordering puts known swimming times before unknown pools and beaches", () => {
  assert.deepEqual(decisions(evaluate(orderingSpots, { sort: { kind: "open" } })), [
    ["open", "OPEN", "Closes 13:00"], ["soon", "CLOSED", "Opens 12:00"],
    ["tomorrow", "CLOSED", "Opens FRI 09:00"], ["unknown", "—", "—"], ["beach", "OCEAN", "—"],
  ]);
});

const accessSpots = [
  { slug: "access-only", schedules: [{ access_hours: [{ day: "thursday", start: "09:00", end: "18:00" }] }] },
  { slug: "unknown" }, { slug: "beach", type: "open_water" },
];

test("board facility access remains distinct from verified swimming and the summary excludes ACCESS", () => {
  const snapshot = evaluate(accessSpots);
  assert.deepEqual(decisions(snapshot), [["access-only", "ACCESS", "Until 18:00"], ["unknown", "—", "—"], ["beach", "OCEAN", "—"]]);
  assert.deepEqual(snapshot.summary, { visibleCount: 3, openCount: 1 });
});

test("board program filters exclude access hours and unknown schedules; an empty result clears the count", () => {
  for (const type of ["lap_swim", "family_swim", "senior_swim"]) {
    const snapshot = evaluate(accessSpots, { type });
    assert.deepEqual(decisions(snapshot), []);
    assert.deepEqual(snapshot.summary, { visibleCount: 0, openCount: 0 });
  }
  assert.deepEqual(decisions(evaluate(accessSpots, { type: "open_water" })), [["beach", "OCEAN", "—"]]);
});

test("board selected program and membership opt-in determine both recommendations and counts", () => {
  const before = structuredClone(programSpots);
  assert.deepEqual(decisions(evaluate(programSpots, { type: "family_swim" })), [["mixed-programs", "CLOSED", "Opens 15:00"]]);
  const snapshot = evaluate(programSpots, { type: "family_swim", includeMemberships: true });
  assert.deepEqual(decisions(snapshot), [["members-family", "OPEN", "Closes 13:00"], ["mixed-programs", "CLOSED", "Opens 15:00"]]);
  assert.deepEqual(snapshot.summary, { visibleCount: 2, openCount: 1 });
  assert.deepEqual(programSpots, before, "evaluation must not mutate catalog schedules");
});

test("board planning uses the selected program and returning to now recomputes its status", () => {
  const future = evaluate(programSpots, { horizon: "this-afternoon", type: "family_swim" });
  assert.deepEqual(visible(future).map(({ slug, result }) => [slug, result.status, result.bestWindow.start, result.bestWindow.end]),
    [["mixed-programs", "AVAILABLE", 900, 960]]);
  assert.deepEqual(future.summary, { visibleCount: 1, openCount: 1 });
  assert.deepEqual(decisions(evaluate(programSpots, { type: "family_swim" })), [["mixed-programs", "CLOSED", "Opens 15:00"]]);
});

test("board distance keeps pools ahead of beaches, uses baseline order for ties, and puts missing coordinates last", () => {
  const snapshot = evaluate([
    { slug: "missing", name: "Alpha" }, { slug: "far", lat: 38, lng: -122 },
    { slug: "tie-z", lat: 37, lng: -122 }, { slug: "tie-a", lat: 37, lng: -122 },
    { slug: "beach", type: "open_water", lat: 37, lng: -122 },
  ], { sort: { kind: "distance", coords: { latitude: 37, longitude: -122 } } });
  assert.deepEqual(visible(snapshot).map(({ slug }) => slug), ["tie-a", "tie-z", "far", "missing", "beach"]);
});

test("board program eligibility follows the selected schedule window", () => {
  const spots = [{ slug: "switching", schedules: [
    { effective_start: "2026-09-01", effective_end: "2026-09-24", sessions: [{ day: "thursday", type: "lap_swim", start: "11:00", end: "13:00" }] },
    { effective_start: "2026-09-25", effective_end: "2026-10-01", sessions: [{ day: "friday", type: "family_swim", start: "08:00", end: "10:00" }] },
  ] }];
  assert.deepEqual(decisions(evaluate(spots, { type: "family_swim" })), []);
  assert.equal(visible(evaluate(spots, { type: "family_swim", horizon: "tomorrow-morning" }))[0].result.status, "AVAILABLE");
  assert.deepEqual(decisions(evaluate(spots, { type: "lap_swim", horizon: "tomorrow-morning" })), []);
});

test("board evaluation is independent of the visitor timezone and uses inclusive starts, exclusive ends", () => {
  for (const [time, status, next] of [
    ["2026-09-24T21:59:00Z", "CLOSED", "Opens 15:00"],
    ["2026-09-24T22:00:00Z", "OPEN", "Closes 16:00"],
    ["2026-09-24T23:00:00Z", "CLOSED", "Opens THU 15:00"],
  ]) assert.deepEqual(decisions(evaluate(programSpots, { type: "family_swim" }, new Date(time))), [["mixed-programs", status, next]]);
});

const step = (state, action) => transitionBoard(state, { instant, ...action });
test("URL restore canonicalizes legacy sorts, preserves foreign tokens, and never prompts for distance", () => {
  for (const token of ["next-open", "open-now", "open"]) {
    const restored = step(initialBoardState(), { type: "restore", hash: `#zebra+${token}+family+memberships`, search: "?keep=yes&when=this-afternoon" });
    assert.equal(serializeBoardHash(restored.state), "#family+memberships+open+zebra");
    assert.equal(restored.state.horizon, "this-afternoon");
    assert.equal(restored.effects.some(({ kind }) => kind === "geolocate"), false);
  }
  const restored = step(initialBoardState(), { type: "restore", hash: "#distance+lap", search: "?when=invalid" });
  assert.equal(serializeBoardHash(restored.state), "#lap");
  assert.equal(restored.state.horizon, "now");
  assert.equal(restored.effects.some(({ kind }) => kind === "geolocate"), false);
  assert.equal(parseBoardHash("#beach+senior+family+lap").type, "lap_swim");
});

test("denied geolocation preserves the prior sort and stale successes cannot replace newer choices", () => {
  const open = step(initialBoardState(), { type: "toggle-open" }).state;
  const pending = step(open, { type: "request-distance", available: true });
  assert.equal(pending.state.sort.kind, "open");
  assert.deepEqual(pending.effects.map(({ kind }) => kind), ["controls", "geolocate"]);
  assert.deepEqual(step(pending.state, { type: "request-distance", available: true }).effects, []);
  const denied = step(pending.state, { type: "geo-denied", requestId: 1 }).state;
  assert.equal(denied.sort.kind, "open");
  const newer = step(denied, { type: "request-distance", available: true }).state;
  assert.equal(newer.geo.requestId, 2);
  assert.equal(step(newer, { type: "geo-success", requestId: 1, coords: {} }).state, newer);
  const navigated = step(newer, { type: "hashchange", hash: "#family" }).state;
  assert.equal(navigated.geo.status, "idle");
  assert.equal(step(navigated, { type: "geo-success", requestId: 2, coords: {} }).state, navigated);
});

test("program, membership, and horizon changes retain a pending distance request", () => {
  let state = step(initialBoardState(), { type: "request-distance", available: true }).state;
  state = step(state, { type: "set-program", program: "family_swim" }).state;
  state = step(state, { type: "toggle-memberships" }).state;
  state = step(state, { type: "set-horizon", horizon: "tomorrow-morning" }).state;
  assert.equal(state.geo.requestId, 1);
  state = step(state, { type: "geo-success", requestId: 1, coords: { latitude: 37, longitude: -122 } }).state;
  assert.equal(state.sort.kind, "distance");
  assert.equal(serializeBoardHash(state), "#distance+family+memberships");
  assert.equal(state.horizon, "tomorrow-morning");
});

test("distance coordinates survive in-session hash changes but are never restored on reload", () => {
  const active = { ...initialBoardState(), sort: { kind: "distance", coords: { latitude: 37, longitude: -122 } } };
  assert.equal(step(active, { type: "hashchange", hash: "#distance+family" }).state.sort, active.sort);
  assert.equal(step(active, { type: "hashchange", hash: "#family" }).state.sort.kind, "default");
  assert.equal(step(active, { type: "restore", hash: "#distance+family", search: "" }).state.sort.kind, "default");
  assert.equal(step(active, { type: "request-distance", available: true }).state.sort.kind, "default");
});

test("minute ticks expire horizons without analytics or flap effects", () => {
  const state = query({ horizon: "this-morning", type: "family_swim" });
  const tick = step(state, { type: "tick" });
  assert.equal(tick.state.horizon, "now");
  assert.equal(tick.state.type, "family_swim");
  assert.deepEqual(tick.effects, [{ kind: "render", flap: false }, { kind: "write-url" }]);
});
