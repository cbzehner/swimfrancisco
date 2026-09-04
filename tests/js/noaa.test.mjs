// Pin the NOAA timestamp normalizer. NOAA returns "YYYY-MM-DD HH:MM" in
// station-local time with `time_zone=lst_ldt`; we reshape it into a zoneless
// ISO string that downstream consumers (static/js/helpers/tide.mjs) parse as
// local time. A drift in this format silently breaks the tide summary on
// every open-water detail page.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { fetchNoaaTemp, fetchNoaaTides, toLocalIso } from "../../worker/src/noaa.ts";
import { tempFromReading } from "../../worker/src/assemble.ts";

let originalFetch;
let requestedUrl;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  requestedUrl = null;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function mockFetch(body, status = 200) {
  globalThis.fetch = async (url) => {
    requestedUrl = String(url);
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  };
}

test("toLocalIso replaces the space with T and pads seconds", () => {
  assert.equal(toLocalIso("2026-04-16 14:30"), "2026-04-16T14:30:00");
});

test("toLocalIso preserves an already-formatted string with seconds", () => {
  // When NOAA returns an input longer than 16 chars (seconds present), we
  // must not double-append `:00`.
  assert.equal(toLocalIso("2026-04-16 14:30:45"), "2026-04-16T14:30:45");
});

test("toLocalIso trims incidental whitespace", () => {
  assert.equal(toLocalIso("  2026-04-16 14:30  "), "2026-04-16T14:30:00");
});

test("toLocalIso output is zoneless (no trailing Z or offset)", () => {
  // Invariant relied on by tide.mjs: the string is parsed as local time by
  // `new Date(...)`. If a zone suffix ever sneaks in, times would shift.
  const out = toLocalIso("2026-04-16 14:30");
  assert.doesNotMatch(out, /Z$/);
  assert.doesNotMatch(out, /[+-]\d{2}:?\d{2}$/);
});

test("fetchNoaaTemp keeps native Fahrenheit through assemble", async () => {
  // 58.4°F → 14.666…°C. Rounding C and converting back would yield 58.5°F.
  mockFetch({ data: [{ t: "2026-04-16 14:30", v: "58.4" }] });

  const reading = await fetchNoaaTemp("9414863");
  assert.ok(reading);
  assert.equal(reading.stationId, "9414863");
  assert.equal(reading.waterTempF, 58.4);
  assert.equal(reading.waterTempC, 14.7);
  assert.equal(reading.observedAt, "2026-04-16T14:30:00Z");
  assert.equal(new URL(requestedUrl).searchParams.get("time_zone"), "gmt");

  const fields = tempFromReading({ reading, sourceType: "noaa" });
  assert.equal(fields.water_temp_f, 58.4);
  assert.equal(fields.water_temp_c, 14.7);
});

test("fetchNoaaTides keeps station-local timestamps", async () => {
  mockFetch({ predictions: [{ t: "2026-04-16 14:30", v: "2.1", type: "H" }] });

  const tides = await fetchNoaaTides("9414290");

  assert.equal(new URL(requestedUrl).searchParams.get("time_zone"), "lst_ldt");
  assert.equal(tides.predictions[0].time, "2026-04-16T14:30:00");
});
