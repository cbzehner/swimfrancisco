import { test } from "node:test";
import assert from "node:assert/strict";

import { formatLocalizedISODate } from "../../static/js/helpers/i18n.mjs";

test("formatLocalizedISODate uses active page language date order", () => {
  const previousWindow = globalThis.window;
  try {
    globalThis.window = { SWIMFRANCISCO_LANG: "es", SWIMFRANCISCO_I18N: { month_jun: "JUN" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "7/6/2026");

    globalThis.window = { SWIMFRANCISCO_LANG: "en", SWIMFRANCISCO_I18N: { month_jun: "JUN" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "JUN 7, 2026");

    globalThis.window = { SWIMFRANCISCO_LANG: "zh-Hant" };
    assert.equal(formatLocalizedISODate("2026-06-07"), "2026年6月7日");

    globalThis.window = { SWIMFRANCISCO_LANG: "fil", SWIMFRANCISCO_I18N: { month_jun: "HUN" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "HUN 7, 2026");

    globalThis.window = { SWIMFRANCISCO_LANG: "vi", SWIMFRANCISCO_I18N: { month_jun: "THG 6" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "7/6/2026");

    globalThis.window = { SWIMFRANCISCO_LANG: "fi", SWIMFRANCISCO_I18N: { month_jun: "KESÄ" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "7.6.2026");
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
});
