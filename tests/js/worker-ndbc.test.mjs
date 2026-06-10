// Pin the NDBC realtime2 fixed-width parser against a captured fixture.
// This is exactly the format-drift-prone code the noaa test comment warns
// about: NDBC ships whitespace-separated columns with a #-prefixed header,
// "MM" for missing values, and the newest observation first.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { fetchNdbc } from "../../worker/src/ndbc.ts";

const HEADER = [
  "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE",
  "#yr  mo dy hr mn degT m/s  m/s  m      sec   sec degT  hPa   degC  degC  degC  nmi hPa   ft",
].join("\n");

let originalFetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function mockFetch(body, status = 200) {
  globalThis.fetch = async () =>
    new Response(body, { status, headers: { "content-type": "text/plain" } });
}

test("fetchNdbc parses the newest observation from a realtime2 fixture", async () => {
  mockFetch(
    `${HEADER}
2026 04 16 18 20 270  5.0  7.0  1.5  12.0   8.0 280 1015.2  13.5  12.3  10.1 99.0 +0.5    MM
2026 04 16 17 50 260  4.0  6.0  1.4  12.0   8.0 280 1015.0  13.4  12.1  10.0 99.0 +0.4    MM
`,
  );

  const reading = await fetchNdbc("46237");
  assert.ok(reading);
  assert.equal(reading.stationId, "46237");
  assert.equal(reading.waterTempC, 12.3);
  assert.equal(reading.waterTempF, 54.1);
  assert.equal(reading.observedAt, "2026-04-16T18:20:00.000Z");
});

test("fetchNdbc skips rows with a missing WTMP and uses the next observation", async () => {
  mockFetch(
    `${HEADER}
2026 04 16 18 20 270  5.0  7.0  1.5  12.0   8.0 280 1015.2  13.5    MM  10.1 99.0 +0.5    MM
2026 04 16 17 50 260  4.0  6.0  1.4  12.0   8.0 280 1015.0  13.4  11.8  10.0 99.0 +0.4    MM
`,
  );

  const reading = await fetchNdbc("46237");
  assert.ok(reading);
  assert.equal(reading.waterTempC, 11.8);
  assert.equal(reading.observedAt, "2026-04-16T17:50:00.000Z");
});

test("fetchNdbc locates WTMP by header position when columns shift", async () => {
  // Same data, but WTMP moved one column earlier — the parser must follow
  // the header, not assume index 14.
  mockFetch(
    `#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  WTMP  ATMP  DEWP  VIS PTDY  TIDE
2026 04 16 18 20 270  5.0  7.0  1.5  12.0   8.0 280 1015.2  12.9  13.5  10.1 99.0 +0.5    MM
`,
  );

  const reading = await fetchNdbc("46237");
  assert.ok(reading);
  assert.equal(reading.waterTempC, 12.9);
});

test("fetchNdbc returns null when no row has a usable WTMP", async () => {
  mockFetch(
    `${HEADER}
2026 04 16 18 20 270  5.0  7.0  1.5  12.0   8.0 280 1015.2  13.5    MM  10.1 99.0 +0.5    MM
`,
  );

  assert.equal(await fetchNdbc("46237"), null);
});

test("fetchNdbc throws on a non-ok response", async () => {
  mockFetch("service unavailable", 503);

  await assert.rejects(() => fetchNdbc("46237"), /NDBC 46237 HTTP 503/);
});
