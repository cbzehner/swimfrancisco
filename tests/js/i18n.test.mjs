import { test } from "node:test";
import assert from "node:assert/strict";

import { closureReasonLabel, formatLocalizedISODate } from "../../static/js/helpers/i18n.mjs";

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

test("closureReasonLabel resolves cataloged dynamic labels before falling back", () => {
  const previousWindow = globalThis.window;
  try {
    globalThis.window = {
      SWIMFRANCISCO_I18N: { reason_juneteenth: "Juneteenth translated" },
      SWIMFRANCISCO_DYNAMIC_LABELS: {
        closure_reason: {
          by_code: {
            juneteenth: { translation_key: "reason_juneteenth", sources: ["Juneteenth"] },
          },
          by_source: {
            Juneteenth: { code: "juneteenth", translation_key: "reason_juneteenth" },
          },
        },
      },
    };
    assert.equal(closureReasonLabel("", "Juneteenth"), "Juneteenth translated");
    assert.equal(closureReasonLabel("juneteenth", "Juneteenth"), "Juneteenth translated");
    assert.equal(closureReasonLabel("juneteenth", ""), "Juneteenth translated");
    assert.equal(closureReasonLabel("", "Unmapped reason"), "Unmapped reason");
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
});
