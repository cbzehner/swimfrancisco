// Pin the stale-coalescing contract in assemble.ts — the highest-risk logic
// in the worker. The freshness ceiling must be measured from the run that
// actually observed a value (carried_since), not from the previous assembly's
// updated_at: updated_at resets every hourly run, so gating on it alone would
// let a week-old reading look one hour old forever.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test } from "node:test";
import assert from "node:assert/strict";

import { coalesceTemp, coalesceTide, withinFreshnessCeiling } from "../../worker/src/assemble.ts";

const NOW = Date.UTC(2026, 3, 17, 12, 0); // 2026-04-17T12:00Z

function hoursAgo(hours) {
  return new Date(NOW - hours * 60 * 60 * 1000).toISOString();
}

function record(overrides = {}) {
  return {
    slug: "aquatic-park",
    water_temp_f: 58.1,
    water_temp_c: 14.5,
    temp_observed_at: hoursAgo(1.5),
    temp_station_id: "9414290",
    temp_station_type: "noaa",
    tide: { station_id: "9414290", predictions: [] },
    updated_at: hoursAgo(1),
    temp_stale: false,
    tide_stale: false,
    temp_carried_since: null,
    tide_carried_since: null,
    ...overrides,
  };
}

const FRESH_TEMP = {
  water_temp_f: 60.0,
  water_temp_c: 15.6,
  temp_observed_at: hoursAgo(0),
  temp_station_id: "9414290",
  temp_station_type: "noaa",
};

test("withinFreshnessCeiling accepts recent ISO and rejects old or garbage input", () => {
  assert.equal(withinFreshnessCeiling(hoursAgo(23), NOW), true);
  assert.equal(withinFreshnessCeiling(hoursAgo(25), NOW), false);
  assert.equal(withinFreshnessCeiling("not-a-date", NOW), false);
});

test("coalesceTemp prefers a fresh reading and clears carried-since", () => {
  const out = coalesceTemp(FRESH_TEMP, record({ temp_carried_since: hoursAgo(5) }), NOW);
  assert.equal(out.fields, FRESH_TEMP);
  assert.equal(out.stale, false);
  assert.equal(out.carriedSince, null);
});

test("coalesceTemp carries last-good values, anchored to the observing run", () => {
  const previous = record({ updated_at: hoursAgo(1) });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.fields.water_temp_f, 58.1);
  assert.equal(out.stale, true);
  assert.equal(out.carriedSince, previous.updated_at);
});

test("coalesceTemp preserves the original carried-since across repeated carries", () => {
  // The regression this file exists for: run N carries from run 1; run N's
  // updated_at is always one hour old, but carried_since must stay anchored
  // to the run that actually observed the value.
  const previous = record({ updated_at: hoursAgo(1), temp_carried_since: hoursAgo(23), temp_stale: true });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.stale, true);
  assert.equal(out.carriedSince, previous.temp_carried_since);
});

test("coalesceTemp nulls fields once the carried value passes the 24h ceiling", () => {
  const previous = record({ updated_at: hoursAgo(1), temp_carried_since: hoursAgo(25), temp_stale: true });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.fields, null);
  assert.equal(out.stale, false);
  assert.equal(out.carriedSince, null);
});

test("coalesceTemp treats legacy records without carried-since as observed at updated_at", () => {
  const legacy = record({ updated_at: hoursAgo(2) });
  delete legacy.temp_carried_since;
  delete legacy.tide_carried_since;
  const out = coalesceTemp(null, legacy, NOW);
  assert.equal(out.stale, true);
  assert.equal(out.carriedSince, legacy.updated_at);
});

test("coalesceTemp refuses partial previous temp fields", () => {
  const previous = record({ water_temp_c: null });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.fields, null);
  assert.equal(out.stale, false);
});

test("coalesceTide mirrors the temp contract", () => {
  const previous = record({ updated_at: hoursAgo(1), tide_carried_since: hoursAgo(23), tide_stale: true });
  const carried = coalesceTide(null, previous, NOW);
  assert.equal(carried.value, previous.tide);
  assert.equal(carried.stale, true);
  assert.equal(carried.carriedSince, previous.tide_carried_since);

  const expired = coalesceTide(null, record({ tide_carried_since: hoursAgo(25) }), NOW);
  assert.equal(expired.value, null);
  assert.equal(expired.stale, false);
});

test("coalesce helpers handle a missing previous record", () => {
  assert.deepEqual(coalesceTemp(null, null, NOW), { fields: null, stale: false, carriedSince: null });
  assert.deepEqual(coalesceTide(null, null, NOW), { value: null, stale: false, carriedSince: null });
});
