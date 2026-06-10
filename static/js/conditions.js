// Swim Francisco open-water live conditions.
// Fetches /api/conditions from the Worker and injects water temp into
// matching rows on the board and the detail page panel.
// Fails silently — missing data leaves the existing em-dash placeholders.

import { formatPacificDate, formatPacificTime, pacificWallClockDate } from "./helpers/pacific.mjs";
import { formatTideSummary } from "./helpers/tide.mjs";
import { t } from "./helpers/i18n.mjs";

const DEFAULT_ENDPOINT = "/api/conditions";
const BAY_SLUGS = ["aquatic-park", "crissy-field"];
const OCEAN_SLUGS = ["ocean-beach", "baker-beach", "china-beach"];
const AVAILABLE_STATUSES = new Set(["OPEN", "AVAILABLE", "LIMITED", "OCEAN"]);

// Format a Fahrenheit temperature from a conditions record.
// Accepts `water_temp_f` directly, or converts from `water_temp_c`.
// Returns a string like "58°F" or null when unavailable/invalid.
function extractTemp(record) {
  if (!record || typeof record !== "object") return null;
  let fahrenheit = null;
  if (typeof record.water_temp_f === "number" && Number.isFinite(record.water_temp_f)) {
    fahrenheit = record.water_temp_f;
  } else if (typeof record.water_temp_c === "number" && Number.isFinite(record.water_temp_c)) {
    fahrenheit = (record.water_temp_c * 9) / 5 + 32;
  }
  if (fahrenheit === null) return null;
  return `${Math.round(fahrenheit)}\u00B0F`;
}

function firstRecordWithTemp(conditions, slugs) {
  for (const slug of slugs) {
    const record = conditions[slug];
    if (extractTemp(record)) return record;
  }
  return null;
}

function firstRecordWithTide(conditions, slugs, now) {
  for (const slug of slugs) {
    const record = conditions[slug];
    if (formatTideSummary(record, now)) return record;
  }
  return null;
}

function setText(root, selector, value) {
  if (!value) return;
  root.querySelectorAll(selector).forEach((node) => {
    node.textContent = value;
  });
}

// Write a temp reading into matching nodes, flagging carried-forward
// (stale) readings so CSS can dim them instead of presenting them as live.
function setTemp(root, selector, record) {
  const temp = extractTemp(record);
  if (!temp) return;
  root.querySelectorAll(selector).forEach((node) => {
    node.textContent = temp;
    if (record.temp_stale) {
      node.setAttribute("data-temp-stale", "true");
    } else {
      node.removeAttribute("data-temp-stale");
    }
  });
}

function formatUpdatedAt(conditions) {
  const timestamps = Object.values(conditions)
    .map((record) => Date.parse(record?.updated_at || ""))
    .filter((value) => Number.isFinite(value));
  if (timestamps.length === 0) return null;
  return formatPacificTime(new Date(Math.max(...timestamps)));
}

function openCountLabel(count) {
  const nowLabel = t("now", "Now");
  const horizonLabel = document.querySelector("[data-horizon-button]")?.textContent.trim() || nowLabel;
  const unit = count === 1 ? t("place_singular", "place") : t("place_plural", "places");
  const normalized = horizonLabel.toLowerCase();
  if (normalized !== nowLabel.toLowerCase()) return `${unit} ${t("available", "available")} ${normalized}`;
  return `${unit} ${t("open_now_lower", "open now")}`;
}

function applyBoardSummary(root) {
  const rows = Array.from(root.querySelectorAll("table.board tbody tr:not([hidden])"));
  if (rows.length === 0) return;
  const count = rows.filter((row) => {
    const status =
      row.querySelector('[data-cell="status"]')?.dataset.statusValue ||
      row.querySelector('[data-cell="status"] .status-pill')?.textContent.trim().toUpperCase() ||
      row.querySelector('[data-cell="status"]')?.textContent.trim().toUpperCase() ||
      "";
    return AVAILABLE_STATUSES.has(status);
  }).length;
  setText(root, "[data-open-count]", String(count));
  setText(root, "[data-open-count-label]", openCountLabel(count));
}

function applyBulletinStrip(root, conditions) {
  const instant = new Date();
  const now = pacificWallClockDate(instant);
  setText(root, "[data-today-date]", formatPacificDate(instant));
  setText(root, "[data-pt-time]", formatPacificTime(instant));

  if (!conditions || typeof conditions !== "object") return;
  const bayRecord = firstRecordWithTemp(conditions, BAY_SLUGS);
  const oceanRecord = firstRecordWithTemp(conditions, OCEAN_SLUGS);
  const tideRecord =
    firstRecordWithTide(conditions, BAY_SLUGS, now) ||
    firstRecordWithTide(conditions, OCEAN_SLUGS, now);
  const tideSummary = formatTideSummary(tideRecord, now);
  const updated = formatUpdatedAt(conditions);

  setTemp(root, "[data-bay-temp]", bayRecord);
  setTemp(root, "[data-bay-temp-strip]", bayRecord);
  setTemp(root, "[data-ocean-temp]", oceanRecord);
  setTemp(root, "[data-ocean-temp-strip]", oceanRecord);
  setText(root, "[data-next-tide]", tideSummary);
  setText(root, "[data-conditions-updated]", updated);
}

// Fetch and parse the conditions bulk endpoint. Returns null on any failure.
async function fetchConditions(url) {
  try {
    const response = await fetch(url, { headers: { accept: "application/json" } });
    if (!response.ok) return null;
    const data = await response.json();
    if (!data || typeof data !== "object") return null;
    return data;
  } catch (_err) {
    return null;
  }
}

// Inject water temps into the board's TEMP column (5th <td>) and
// the detail-page conditions panel, when present. `conditions` is keyed by slug.
function applyConditions(root, conditions) {
  if (!conditions || typeof conditions !== "object") return;
  applyBulletinStrip(root, conditions);

  const rows = root.querySelectorAll(
    'table.board tbody tr[data-type="open_water"]',
  );
  rows.forEach((row) => {
    const slug = row.getAttribute("data-slug");
    if (!slug) return;
    setTemp(row, '[data-cell="water"]', conditions[slug]);
  });

  // Tide predictions arrive as zoneless station-local (Pacific) ISO strings.
  // Pinning `now` to PT wall-clock keeps the "past" filter correct for
  // visitors whose browser is outside Pacific time.
  const now = pacificWallClockDate();
  const panels = root.querySelectorAll("section.conditions[data-slug]");
  panels.forEach((panel) => {
    const slug = panel.getAttribute("data-slug");
    if (!slug) return;
    const record = conditions[slug];
    setTemp(panel, '[data-field="water_temp"]', record);
    const tideSummary = formatTideSummary(record, now);
    if (tideSummary) {
      const tideField = panel.querySelector('[data-field="tide"]');
      if (tideField) tideField.textContent = tideSummary;
    }
  });
}

async function init() {
  applyBoardSummary(document);
  applyBulletinStrip(document, null);
  const endpoint = (typeof window !== "undefined" && window.SWIMFRANCISCO_API) || DEFAULT_ENDPOINT;
  const conditions = await fetchConditions(endpoint);
  if (conditions) applyConditions(document, conditions);
  // Expose for other modules (e.g. map popups) and signal availability.
  window.SWIMFRANCISCO_CONDITIONS = conditions;
  document.dispatchEvent(new CustomEvent("sf:conditions-loaded"));
}

document.addEventListener("sf:status-applied", () => applyBoardSummary(document));
document.addEventListener("sf:horizon-changed", () => applyBoardSummary(document));
document.addEventListener("sf:filters-applied", () => applyBoardSummary(document));

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    init().catch(() => {
      /* swallow — placeholders remain */
    });
  });
} else {
  init().catch(() => {
    /* swallow — placeholders remain */
  });
}
