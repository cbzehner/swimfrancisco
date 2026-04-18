// Tide-summary formatter. Worker returns predictions as zoneless ISO strings
// in station-local time (see worker/src/noaa.ts::toLocalIso). We compare them
// against a local-time `now` and render the next upcoming high/low.

import { test } from "node:test";
import assert from "node:assert/strict";

import { formatTideSummary } from "../../static/js/helpers/tide.mjs";

test("formatTideSummary returns the next upcoming prediction", () => {
  const now = new Date("2026-04-17T10:00:00");
  const record = {
    tide: {
      station_id: "9414290",
      predictions: [
        { time: "2026-04-17T06:12:00", type: "H", value_ft: 5.1 },
        { time: "2026-04-17T12:30:00", type: "L", value_ft: 0.4 },
        { time: "2026-04-17T18:48:00", type: "H", value_ft: 4.7 },
      ],
    },
  };
  const summary = formatTideSummary(record, now);
  assert.ok(summary, "summary must be produced when upcoming predictions exist");
  assert.match(summary, /low/i, "next upcoming prediction is the 12:30 low");
  assert.match(summary, /12:30/);
  assert.match(summary, /0\.4/);
});

test("formatTideSummary skips past predictions", () => {
  const now = new Date("2026-04-17T20:00:00");
  const record = {
    tide: {
      station_id: "9414290",
      predictions: [
        { time: "2026-04-17T06:12:00", type: "H", value_ft: 5.1 },
        { time: "2026-04-17T12:30:00", type: "L", value_ft: 0.4 },
        { time: "2026-04-18T01:15:00", type: "H", value_ft: 4.9 },
      ],
    },
  };
  const summary = formatTideSummary(record, now);
  assert.ok(summary);
  assert.match(summary, /high/i);
  assert.match(summary, /01:15/);
});

test("formatTideSummary returns null when no predictions", () => {
  assert.equal(formatTideSummary(null, new Date()), null);
  assert.equal(formatTideSummary({}, new Date()), null);
  assert.equal(formatTideSummary({ tide: null }, new Date()), null);
  assert.equal(
    formatTideSummary({ tide: { predictions: [] } }, new Date()),
    null,
  );
});

test("formatTideSummary returns null when all predictions are in the past", () => {
  const now = new Date("2026-04-18T12:00:00");
  const record = {
    tide: {
      predictions: [
        { time: "2026-04-17T06:12:00", type: "H", value_ft: 5.1 },
      ],
    },
  };
  assert.equal(formatTideSummary(record, now), null);
});
