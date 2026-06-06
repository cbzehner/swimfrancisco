import { test } from "node:test";
import assert from "node:assert/strict";

import { formatLocalizedISODate } from "../../static/js/helpers/i18n.mjs";

test("formatLocalizedISODate uses active page language date order", () => {
  const previousWindow = globalThis.window;
  try {
    globalThis.window = { SWIMFRANCISCO_LANG: "es", SWIMFRANCISCO_I18N: { month_jun: "JUN" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "7 JUN 2026");

    globalThis.window = { SWIMFRANCISCO_LANG: "en", SWIMFRANCISCO_I18N: { month_jun: "JUN" } };
    assert.equal(formatLocalizedISODate("2026-06-07"), "JUN 7, 2026");

    globalThis.window = { SWIMFRANCISCO_LANG: "zh-Hant" };
    assert.equal(formatLocalizedISODate("2026-06-07"), "2026年6月7日");
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
});
