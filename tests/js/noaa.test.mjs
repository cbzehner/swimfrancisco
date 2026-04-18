// Pin the NOAA timestamp normalizer. NOAA returns "YYYY-MM-DD HH:MM" in
// station-local time with `time_zone=lst_ldt`; we reshape it into a zoneless
// ISO string that downstream consumers (static/js/helpers/tide.mjs) parse as
// local time. A drift in this format silently breaks the tide summary on
// every open-water detail page.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test } from "node:test";
import assert from "node:assert/strict";

import { toLocalIso } from "../../worker/src/noaa.ts";

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
