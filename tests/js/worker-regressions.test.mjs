import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchNoaaTides } from "../../worker/src/noaa.ts";
import { assembleAndPersist } from "../../worker/src/assemble.ts";
import worker from "../../worker/src/index.ts";

const instant = new Date("2026-04-18T02:00:00Z");

test("empty and invalid NOAA predictions are unavailable and use the injected Pacific date", async () => {
  const original = globalThis.fetch;
  try {
    for (const predictions of [
      [],
      [{ t: "2026-04-17 12:00", v: "bad", type: "H" }],
      [{ t: "2026-04-17 12:00", v: "", type: "H" }],
      [{ t: "", v: "1.5", type: "H" }],
    ]) {
      globalThis.fetch = async (url) => {
        assert.equal(new URL(url).searchParams.get("begin_date"), "20260417");
        return Response.json({ predictions });
      };
      assert.equal(await fetchNoaaTides("station", instant), null);
    }
    globalThis.fetch = async () => Response.json({ predictions: [{ t: "2026-04-17 12:00", v: "0", type: "L" }] });
    const zeroTide = await fetchNoaaTides("station", instant);
    assert.deepEqual(zeroTide?.predictions, [{ time: "2026-04-17T12:00:00", type: "L", valueFt: 0 }]);
  } finally { globalThis.fetch = original; }
});

test("cold all-null refresh does not persist but a subsequent reading does", async () => {
  let stored = null;
  const kv = { get: async () => stored, put: async (_key, value) => { stored = JSON.parse(value); } };
  let available = false;
  const options = { now: () => instant, spots: [{ slug: "bay", tideStationId: "t", tempSources: [] }],
    tempFetchers: {}, fetchTides: async () => available ? { stationId: "t", predictions: [{ time: "2026-04-17T12:00:00", type: "H", valueFt: 2 }] } : null };
  await assembleAndPersist(kv, options);
  assert.equal(stored, null);
  available = true;
  await assembleAndPersist(kv, options);
  assert.equal(stored.bay.tide.station_id, "t");
});

test("scheduled refresh invalidates the conditions cache after persistence", async () => {
  const originalFetch = globalThis.fetch;
  const originalCaches = globalThis.caches;
  const calls = [];
  try {
    globalThis.fetch = async () => Response.json({ predictions: [] });
    globalThis.caches = { default: { delete: async (request) => { calls.push(request.url); return true; } } };
    const kv = { get: async () => ({ existing: {} }), put: async () => calls.push("put") };
    let work;
    await worker.scheduled({}, { CONDITIONS: kv }, { waitUntil(promise) { work = promise; } });
    await work;
    assert.deepEqual(calls, ["put", "https://swimfrancisco.com/api/conditions"]);
  } finally { globalThis.fetch = originalFetch; globalThis.caches = originalCaches; }
});

test("best-effort cache invalidation failure does not fail a completed scheduled refresh", async () => {
  const originalFetch = globalThis.fetch;
  const originalCaches = globalThis.caches;
  try {
    globalThis.fetch = async () => Response.json({ predictions: [] });
    globalThis.caches = { default: { delete: async () => { throw new Error("cache unavailable"); } } };
    const kv = { get: async () => ({ existing: {} }), put: async () => {} };
    let work;
    await worker.scheduled({}, { CONDITIONS: kv }, { waitUntil(promise) { work = promise; } });
    await work;
  } finally { globalThis.fetch = originalFetch; globalThis.caches = originalCaches; }
});
