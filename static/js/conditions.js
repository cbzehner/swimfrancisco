// Swim Francisco open-water live conditions.
// Fetches /api/conditions from the Worker and injects water temp into
// matching rows on the board and the detail page panel.
// Fails silently — missing data leaves the existing em-dash placeholders.

import { nowInPacific } from "./helpers/board.mjs";
import { formatTideSummary } from "./helpers/tide.mjs";

const DEFAULT_ENDPOINT = "/api/conditions";

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

  const rows = root.querySelectorAll(
    'table.board tbody tr[data-type="open_water"]',
  );
  rows.forEach((row) => {
    const slug = row.getAttribute("data-slug");
    if (!slug) return;
    const temp = extractTemp(conditions[slug]);
    if (!temp) return;
    const cells = row.querySelectorAll("td");
    if (cells.length < 5) return;
    cells[4].textContent = temp;
  });

  // Tide predictions arrive as zoneless station-local (Pacific) ISO strings.
  // Pinning `now` to PT wall-clock keeps the "past" filter correct for
  // visitors whose browser is outside Pacific time.
  const now = nowInPacific();
  const panels = root.querySelectorAll("section.conditions[data-slug]");
  panels.forEach((panel) => {
    const slug = panel.getAttribute("data-slug");
    if (!slug) return;
    const record = conditions[slug];
    const temp = extractTemp(record);
    if (temp) {
      const tempField = panel.querySelector('[data-field="water_temp"]');
      if (tempField) tempField.textContent = temp;
    }
    const tideSummary = formatTideSummary(record, now);
    if (tideSummary) {
      const tideField = panel.querySelector('[data-field="tide"]');
      if (tideField) tideField.textContent = tideSummary;
    }
  });
}

async function init() {
  const endpoint = (typeof window !== "undefined" && window.SWIMFRANCISCO_API) || DEFAULT_ENDPOINT;
  const conditions = await fetchConditions(endpoint);
  if (!conditions) return;
  applyConditions(document, conditions);
}

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

