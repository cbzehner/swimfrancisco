// Pin the stale-coalescing contract in assemble.ts — the highest-risk logic
// in the worker. The freshness ceiling must be measured from the run that
// actually observed a value (carried_since), not from the previous assembly's
// updated_at: updated_at resets every hourly run, so gating on it alone would
// let a week-old reading look one hour old forever.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  assembleAndPersist,
  coalesceTemp,
  coalesceTide,
  tempReadingIsFresh,
  tempFromReading,
  withinFreshnessCeiling,
} from "../../worker/src/assemble.ts";
import { readingFromC, readingFromF } from "../../worker/src/temp.ts";

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

test("a complete refresh shares source requests, carries outages, expires data, and recovers", async () => {
  let instant = new Date("2026-04-17T12:00:00Z");
  let stored = null;
  const calls = [];
  const writes = [];
  const kv = {
    async get(key, type) {
      assert.equal(key, "conditions");
      assert.equal(type, "json");
      calls.push("read");
      return stored;
    },
    async put(key, value) {
      assert.equal(key, "conditions");
      calls.push("write");
      stored = JSON.parse(value);
      writes.push(stored);
    },
  };
  const spots = ["bay-one", "bay-two"].map((slug) => ({
    slug, tideStationId: "shared-tide",
    tempSources: [{ type: "usgs", id: "dark" }, { type: "noaa", id: "old" }, { type: "erddap", id: "live" }],
  }));
  let available = true;
  const tempFetchers = {
    usgs: async (id) => { calls.push(id); return null; },
    noaa: async (id) => {
      calls.push(id);
      return readingFromF(id, 70, "2026-04-15T12:00:00Z");
    },
    erddap: async (id) => {
      calls.push(id);
      return available ? readingFromF(id, 60, instant.toISOString()) : null;
    },
  };
  const fetchTides = async (id) => {
    calls.push(id);
    return available ? { stationId: id, predictions: [{ time: "2026-04-17T08:00:00", type: "H", valueFt: 4.5 }] } : null;
  };
  const refresh = () => assembleAndPersist(kv, { spots, now: () => instant, tempFetchers, fetchTides });
  const first = await refresh();
  assert.equal(calls[0], "read");
  assert.equal(calls.at(-1), "write");
  for (const id of ["dark", "old", "live", "shared-tide"]) assert.equal(calls.filter((call) => call === id).length, 1);
  assert.deepEqual(first["bay-one"], {
    slug: "bay-one", water_temp_f: 60, water_temp_c: 15.6,
    temp_observed_at: "2026-04-17T12:00:00.000Z", temp_station_id: "live", temp_station_type: "erddap",
    tide: { station_id: "shared-tide", predictions: [{ time: "2026-04-17T08:00:00", type: "H", value_ft: 4.5 }] },
    updated_at: "2026-04-17T12:00:00.000Z", temp_stale: false, tide_stale: false,
    temp_carried_since: null, tide_carried_since: null,
  });
  assert.deepEqual(first["bay-two"], { ...first["bay-one"], slug: "bay-two" });

  available = false;
  for (const hour of [13, 14]) {
    instant = new Date(`2026-04-17T${hour}:00:00Z`);
    const next = await refresh();
    assert.equal(next["bay-one"].water_temp_f, 60);
    assert.equal(next["bay-one"].temp_stale, true);
    assert.equal(next["bay-one"].tide_stale, true);
    assert.equal(next["bay-one"].temp_carried_since, "2026-04-17T12:00:00.000Z");
    assert.equal(next["bay-one"].tide_carried_since, "2026-04-17T12:00:00.000Z");
  }
  assert.equal(calls.filter((call) => call === "shared-tide").length, 3, "each refresh gets its own cache");
  instant = new Date("2026-04-18T12:00:00Z");
  const expired = await refresh();
  assert.equal(expired["bay-one"].water_temp_f, null);
  assert.equal(expired["bay-one"].tide, null);
  assert.equal(expired["bay-one"].temp_stale, false);
  available = true;
  const recovered = await refresh();
  assert.equal(recovered["bay-one"].water_temp_f, 60);
  assert.equal(recovered["bay-one"].temp_carried_since, null);
  assert.equal(recovered["bay-one"].tide_stale, false);
  assert.equal(writes.length, 5);
});

test("storage failures propagate and an unreadable previous record prevents collection and writes", async () => {
  const failIfCalled = async () => assert.fail("must not run after a failed read");
  await assert.rejects(assembleAndPersist({
    get: async () => { throw new Error("read failed"); }, put: failIfCalled,
  }, { fetchTides: failIfCalled, tempFetchers: { usgs: failIfCalled } }), /read failed/);
  let writes = 0;
  await assert.rejects(assembleAndPersist({
    get: async () => null,
    put: async () => { writes += 1; throw new Error("write failed"); },
  }, { spots: [], now: () => new Date(NOW) }), /write failed/);
  assert.equal(writes, 1);
});

test("tempReadingIsFresh rejects timestamps without an explicit zone", () => {
  assert.equal(tempReadingIsFresh("noaa", "2026-04-16T13:00:00", NOW), false);
  assert.equal(tempReadingIsFresh("noaa", "2026-04-16T13:00:00Z", NOW), true);
});

test("tempReadingIsFresh uses source-specific age limits", () => {
  assert.equal(tempReadingIsFresh("ndbc", hoursAgo(23), NOW), true);
  assert.equal(tempReadingIsFresh("ndbc", hoursAgo(25), NOW), false);
  assert.equal(tempReadingIsFresh("sst", hoursAgo(71), NOW), true);
  assert.equal(tempReadingIsFresh("sst", hoursAgo(73), NOW), false);
  assert.equal(tempReadingIsFresh("ndbc", hoursAgo(-1), NOW), false);
});

test("coalesceTemp prefers a fresh reading and clears carried-since", () => {
  const out = coalesceTemp(FRESH_TEMP, record({ temp_carried_since: hoursAgo(5) }), NOW);
  assert.equal(out.state, "fresh");
  assert.equal(out.value, FRESH_TEMP);
});

test("coalesceTemp carries last-good values, anchored to the observing run", () => {
  const previous = record({ updated_at: hoursAgo(1) });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.state, "carried");
  assert.equal(out.value.water_temp_f, 58.1);
  assert.equal(out.carriedSince, previous.updated_at);
});

test("coalesceTemp preserves the original carried-since across repeated carries", () => {
  // The regression this file exists for: run N carries from run 1; run N's
  // updated_at is always one hour old, but carried_since must stay anchored
  // to the run that actually observed the value.
  const previous = record({ updated_at: hoursAgo(1), temp_carried_since: hoursAgo(23), temp_stale: true });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.state, "carried");
  assert.equal(out.carriedSince, previous.temp_carried_since);
});

test("coalesceTemp nulls fields once the carried value passes the 24h ceiling", () => {
  const previous = record({ updated_at: hoursAgo(1), temp_carried_since: hoursAgo(25), temp_stale: true });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.state, "unavailable");
});

test("coalesceTemp does not carry an expired source observation", () => {
  const previous = record({
    temp_observed_at: hoursAgo(25),
    temp_carried_since: hoursAgo(1),
    temp_stale: true,
  });
  assert.deepEqual(coalesceTemp(null, previous, NOW), { state: "unavailable" });
});

test("coalesceTemp treats legacy records without carried-since as observed at updated_at", () => {
  const legacy = record({ updated_at: hoursAgo(2) });
  delete legacy.temp_carried_since;
  delete legacy.tide_carried_since;
  const out = coalesceTemp(null, legacy, NOW);
  assert.equal(out.state, "carried");
  assert.equal(out.carriedSince, legacy.updated_at);
});

test("coalesceTemp refuses partial previous temp fields", () => {
  const previous = record({ water_temp_c: null });
  const out = coalesceTemp(null, previous, NOW);
  assert.equal(out.state, "unavailable");
});

test("coalesceTide mirrors the temp contract", () => {
  const previous = record({ updated_at: hoursAgo(1), tide_carried_since: hoursAgo(23), tide_stale: true });
  const carried = coalesceTide(null, previous, NOW);
  assert.equal(carried.state, "carried");
  assert.equal(carried.value, previous.tide);
  assert.equal(carried.carriedSince, previous.tide_carried_since);

  const expired = coalesceTide(null, record({ tide_carried_since: hoursAgo(25) }), NOW);
  assert.equal(expired.state, "unavailable");
});

test("coalesce helpers handle a missing previous record", () => {
  assert.deepEqual(coalesceTemp(null, null, NOW), { state: "unavailable" });
  assert.deepEqual(coalesceTide(null, null, NOW), { state: "unavailable" });
});

test("tempFromReading copies native units without converting again", () => {
  const noaa = tempFromReading({
    reading: readingFromF("9414863", 58.4, "2026-04-16T14:30:00Z"),
    sourceType: "noaa",
  });
  assert.equal(noaa.water_temp_f, 58.4);
  assert.equal(noaa.water_temp_c, 14.7);

  const usgs = tempFromReading({
    reading: readingFromC("374938122251801", 17.0, "2026-07-19T21:00:00.000-08:00"),
    sourceType: "usgs",
  });
  assert.equal(usgs.water_temp_f, 62.6);
  assert.equal(usgs.water_temp_c, 17.0);
});
