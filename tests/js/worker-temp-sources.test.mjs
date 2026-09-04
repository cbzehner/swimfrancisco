// Pin the multi-source water-temperature chain: the USGS NWIS and ERDDAP
// parsers (fixture-based, like the NDBC test), and the chain walker that
// tries each configured source in order until one yields a reading.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { fetchUsgsTemp } from "../../worker/src/usgs.ts";
import { fetchErddapStationTemp, fetchMurSst } from "../../worker/src/erddap.ts";
import { firstTempFromSources } from "../../worker/src/assemble.ts";

let originalFetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function mockFetch(body, status = 200) {
  globalThis.fetch = async () =>
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
}

function nwisBody(points) {
  return { value: { timeSeries: [{ values: [{ value: points }] }] } };
}

test("fetchUsgsTemp converts the newest instantaneous value to °F", async () => {
  mockFetch(nwisBody([
    { value: "16.8", dateTime: "2026-07-19T20:00:00.000-08:00" },
    { value: "17.0", dateTime: "2026-07-19T21:00:00.000-08:00" },
  ]));

  const reading = await fetchUsgsTemp("374938122251801");
  assert.equal(reading.waterTempC, 17.0);
  assert.equal(reading.waterTempF, 62.6);
  assert.equal(reading.observedAt, "2026-07-19T21:00:00.000-08:00");
  assert.equal(reading.stationId, "374938122251801");
});

test("fetchUsgsTemp skips missing-value sentinels and empty series", async () => {
  mockFetch(nwisBody([
    { value: "16.8", dateTime: "2026-07-19T20:00:00.000-08:00" },
    { value: "-999999", dateTime: "2026-07-19T21:00:00.000-08:00" },
  ]));
  assert.equal((await fetchUsgsTemp("374938122251801")).waterTempC, 16.8);

  mockFetch({ value: { timeSeries: [] } });
  assert.equal(await fetchUsgsTemp("374938122251801"), null);
});

test("fetchUsgsTemp throws on a non-ok response", async () => {
  mockFetch("oops", 503);
  await assert.rejects(() => fetchUsgsTemp("374938122251801"), /USGS 374938122251801 HTTP 503/);
});

test("fetchErddapStationTemp parses the newest tabledap row", async () => {
  mockFetch({
    table: {
      columnNames: ["time", "sea_water_temperature"],
      rows: [["2026-07-19T15:17:00Z", 15.18]],
    },
  });

  const reading = await fetchErddapStationTemp("exploratorium-seabird");
  assert.equal(reading.waterTempC, 15.2);
  assert.equal(reading.waterTempF, 59.3);
  assert.equal(reading.observedAt, "2026-07-19T15:17:00Z");
});

test("fetchErddapStationTemp treats ERDDAP's empty-result 404 as no data", async () => {
  mockFetch('Error { code=404; message="Not Found: Your query produced no matching results. (nRows = 0)"; }', 404);
  assert.equal(await fetchErddapStationTemp("exploratorium-seabird"), null);
});

test("fetchErddapStationTemp throws on a genuine 404", async () => {
  mockFetch('Error { code=404; message="Not Found: dataset does not exist"; }', 404);
  await assert.rejects(() => fetchErddapStationTemp("no-such-dataset"), /HTTP 404/);
});

test("fetchMurSst reads the grid cell and rejects land cells", async () => {
  mockFetch({
    table: {
      columnNames: ["time", "latitude", "longitude", "analysed_sst"],
      rows: [["2026-07-19T09:00:00Z", 37.78, -122.55, 15.013]],
    },
  });
  const reading = await fetchMurSst("37.78,-122.55");
  assert.equal(reading.waterTempC, 15.0);
  assert.equal(reading.stationId, "37.78,-122.55");

  mockFetch({
    table: {
      columnNames: ["time", "latitude", "longitude", "analysed_sst"],
      rows: [["2026-07-19T09:00:00Z", 37.78, -122.51, null]],
    },
  });
  assert.equal(await fetchMurSst("37.78,-122.51"), null);

  await assert.rejects(() => fetchMurSst("not-a-point"), /must be "lat,lon"/);
});

const READING = {
  stationId: "374938122251801",
  waterTempC: 17.0,
  waterTempF: 62.6,
  observedAt: "2026-07-19T21:00:00.000-08:00",
};

const NOW = Date.parse("2026-07-19T22:00:00.000-08:00");

function fetchers(overrides) {
  return {
    usgs: async () => null,
    noaa: async () => null,
    ndbc: async () => null,
    erddap: async () => null,
    sst: async () => null,
    ...overrides,
  };
}

test("firstTempFromSources returns the first usable reading with its source type", async () => {
  const chain = [
    { type: "usgs", id: "374938122251801" },
    { type: "noaa", id: "9414863" },
  ];
  const result = await firstTempFromSources(
    "aquatic-park",
    chain,
    fetchers({
      usgs: async () => READING,
      noaa: async () => {
        throw new Error("must not be called");
      },
    }),
    undefined,
    NOW,
  );
  assert.equal(result.reading, READING);
  assert.equal(result.sourceType, "usgs");
});

test("firstTempFromSources falls through nulls and thrown errors in order", async () => {
  const calls = [];
  const chain = [
    { type: "usgs", id: "a" },
    { type: "noaa", id: "b" },
    { type: "erddap", id: "c" },
    { type: "sst", id: "d" },
  ];
  const result = await firstTempFromSources(
    "aquatic-park",
    chain,
    fetchers({
      usgs: async () => {
        calls.push("usgs");
        throw new Error("decommissioned");
      },
      noaa: async () => {
        calls.push("noaa");
        return null;
      },
      sst: async () => {
        calls.push("sst");
        return READING;
      },
      erddap: async () => {
        calls.push("erddap");
        return null;
      },
    }),
    undefined,
    NOW,
  );
  assert.deepEqual(calls, ["usgs", "noaa", "erddap", "sst"]);
  assert.equal(result.sourceType, "sst");
});

test("firstTempFromSources returns null when every source fails", async () => {
  const chain = [
    { type: "usgs", id: "a" },
    { type: "sst", id: "d" },
  ];
  assert.equal(await firstTempFromSources("aquatic-park", chain, fetchers({}), undefined, NOW), null);
});

test("firstTempFromSources shares one in-flight request per source across spots", async () => {
  let usgsCalls = 0;
  const cache = new Map();
  const shared = [{ type: "usgs", id: "374938122251801" }];
  const sharedFetchers = fetchers({
    usgs: async () => {
      usgsCalls += 1;
      return READING;
    },
  });
  const [first, second] = await Promise.all([
    firstTempFromSources("aquatic-park", shared, sharedFetchers, cache, NOW),
    firstTempFromSources("crissy-field", shared, sharedFetchers, cache, NOW),
  ]);
  assert.equal(usgsCalls, 1);
  assert.equal(first.reading, READING);
  assert.equal(second.reading, READING);
});

test("firstTempFromSources skips an old NDBC reading and accepts a daily SST fallback", async () => {
  const chain = [
    { type: "ndbc", id: "46237" },
    { type: "sst", id: "37.78,-122.55" },
  ];
  const oldNdbc = { ...READING, stationId: "46237", observedAt: new Date(NOW - 25 * 60 * 60 * 1000).toISOString() };
  const dailySst = { ...READING, stationId: "37.78,-122.55", observedAt: new Date(NOW - 48 * 60 * 60 * 1000).toISOString() };

  const result = await firstTempFromSources(
    "baker-beach",
    chain,
    fetchers({
      ndbc: async () => oldNdbc,
      sst: async () => dailySst,
    }),
    undefined,
    NOW,
  );

  assert.equal(result.sourceType, "sst");
  assert.equal(result.reading, dailySst);
});
