import { test } from "node:test";
import assert from "node:assert/strict";

import { formatPacificDate, formatPacificTime } from "../../static/js/helpers/pacific.mjs";

test("formatPacificTime renders a real UTC instant as Pacific time", () => {
  assert.equal(formatPacificTime(new Date("2026-04-19T06:59:00Z")), "11:59 PM PT");
});

test("formatPacificDate renders the Pacific calendar day", () => {
  assert.equal(formatPacificDate(new Date("2026-04-19T06:59:00Z")), "Sat, Apr 18");
});

