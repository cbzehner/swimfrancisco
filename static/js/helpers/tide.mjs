// Tide summary formatter for open-water detail pages.
//
// Prediction times come from the Worker as zoneless ISO strings in
// station-local time (see worker/src/noaa.ts::toLocalIso). Parsing them
// with `new Date(...)` treats them as local time, which matches the
// station-local `now` passed in by the browser.

import { t } from "./i18n.mjs";

function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatClock(date) {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function labelFor(type) {
  if (type === "H") return t("tide_high", "high");
  if (type === "L") return t("tide_low", "low");
  return t("tide_generic", "tide");
}

// Return a compact string describing the next upcoming tide prediction,
// or null if no usable prediction exists.
export function formatTideSummary(record, now) {
  if (!record || typeof record !== "object") return null;
  const tide = record.tide;
  if (!tide || typeof tide !== "object") return null;
  const predictions = Array.isArray(tide.predictions) ? tide.predictions : [];
  if (predictions.length === 0) return null;

  const nowMs = now.getTime();
  const upcoming = [];
  for (const p of predictions) {
    if (!p || typeof p !== "object") continue;
    if (typeof p.time !== "string") continue;
    const when = new Date(p.time);
    const ms = when.getTime();
    if (!Number.isFinite(ms)) continue;
    if (ms < nowMs) continue;
    upcoming.push({ when, type: p.type, valueFt: p.value_ft });
  }
  if (upcoming.length === 0) return null;
  upcoming.sort((a, b) => a.when.getTime() - b.when.getTime());

  const next = upcoming[0];
  const label = labelFor(next.type);
  const time = formatClock(next.when);
  const feet = typeof next.valueFt === "number" && Number.isFinite(next.valueFt)
    ? ` (${next.valueFt.toFixed(1)} ft)`
    : "";
  return `${t("next_word", "Next")} ${label} ${time}${feet}`;
}
