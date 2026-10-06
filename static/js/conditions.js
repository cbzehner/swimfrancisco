// Swim Francisco open-water live conditions.
// Fetches /api/conditions from the Worker and injects water temp into
// matching rows on the board and the detail page panel.
// The UI fails silently — missing data leaves the existing em-dash
// placeholders — but every failure is reported as `conditions_fetch_failed`
// so a dead endpoint is visible in analytics instead of invisible on screen.

import { formatPacificDate, formatPacificTime, pacificWallClockDate } from "./helpers/pacific.mjs";
import { formatTideSummary } from "./helpers/tide.mjs";
import { t } from "./helpers/i18n.mjs";
import { capture } from "./helpers/analytics.mjs";
import { PLACEHOLDER } from "./helpers/board.mjs";

import { createConditionsClient } from "./helpers/conditions-client.mjs";

const DEFAULT_ENDPOINT = "/api/conditions";
// The bulletin-strip macro (templates/macros/bulletin.html) emits the bay
// and ocean slug lists from open-water frontmatter (water_body), so adding
// a spot updates this module without touching JS.
function stripSlugs(root, attr) {
  const raw = root.querySelector(".bulletin-strip")?.getAttribute(attr) || "";
  return raw.split(/\s+/).filter(Boolean);
}

// Format a Fahrenheit temperature from a conditions record.
// Accepts `water_temp_f` directly, or converts from `water_temp_c`.
// Returns a string like "58°F" or null when unavailable/invalid.
export function formatWaterTemp(record) {
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
    if (formatWaterTemp(record)) return record;
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
  const temp = formatWaterTemp(record);
  root.querySelectorAll(selector).forEach((node) => {
    node.textContent = temp || PLACEHOLDER;
    if (temp && record.temp_stale) {
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

function applyBulletinStrip(root, conditions, instant, { bay, ocean }) {
  const now = pacificWallClockDate(instant);
  setText(root, "[data-today-date]", formatPacificDate(instant));
  setText(root, "[data-pt-time]", formatPacificTime(instant));

  if (!conditions || typeof conditions !== "object") return;
  const bayRecord = firstRecordWithTemp(conditions, bay);
  const oceanRecord = firstRecordWithTemp(conditions, ocean);
  const tideRecord =
    firstRecordWithTide(conditions, bay, now) ||
    firstRecordWithTide(conditions, ocean, now);
  const tideSummary = formatTideSummary(tideRecord, now);
  const updated = formatUpdatedAt(conditions);

  setTemp(root, "[data-bay-temp]", bayRecord);
  setTemp(root, "[data-bay-temp-strip]", bayRecord);
  setTemp(root, "[data-ocean-temp]", oceanRecord);
  setTemp(root, "[data-ocean-temp-strip]", oceanRecord);
  setText(root, "[data-next-tide]", tideSummary || PLACEHOLDER);
  setText(root, "[data-conditions-updated]", updated || PLACEHOLDER);
}

// Inject water temps into the board's TEMP column (5th <td>) and
// the detail-page conditions panel, when present. `conditions` is keyed by slug.
function applyConditions(root, conditions, instant, slugs) {
  if (!conditions || typeof conditions !== "object") return;
  applyBulletinStrip(root, conditions, instant, slugs);

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
  const now = pacificWallClockDate(instant);
  const panels = root.querySelectorAll("section.conditions[data-slug]");
  panels.forEach((panel) => {
    const slug = panel.getAttribute("data-slug");
    if (!slug) return;
    const record = conditions[slug];
    setTemp(panel, '[data-field="water_temp"]', record);
    const tideSummary = formatTideSummary(record, now);
    const tideField = panel.querySelector('[data-field="tide"]');
    if (tideField) tideField.textContent = tideSummary || PLACEHOLDER;
  });
}

export function mountConditions(root = document, {
  now = () => new Date(), fetch: fetcher = globalThis.fetch,
  endpoint = globalThis.window?.SWIMFRANCISCO_API || DEFAULT_ENDPOINT,
  onChange = () => {},
} = {}) {
  const controller = new AbortController();
  const slugs = { bay: stripSlugs(root, "data-bay-slugs"), ocean: stripSlugs(root, "data-ocean-slugs") };
  const client = createConditionsClient({
    now: () => now().getTime(),
    load: async (signal) => {
      try {
        const response = await fetcher(endpoint, { signal, headers: { accept: "application/json" } });
        if (!response.ok) {
          capture("conditions_fetch_failed", { reason: "http_status", status: response.status });
          return null;
        }
        const data = await response.json();
        if (!data || typeof data !== "object" || Array.isArray(data)) {
          capture("conditions_fetch_failed", { reason: "invalid_payload" });
          return null;
        }
        return data;
      } catch {
        if (!signal.aborted) capture("conditions_fetch_failed", { reason: "network" });
        return null;
      }
    },
    onChange: () => paint(),
  });
  function paint() {
    const instant = now();
    const conditions = client.data || {};
    applyConditions(root, conditions, instant, slugs);
    onChange(conditions, instant);
  }
  function refresh() {
    if (controller.signal.aborted || document.hidden) return Promise.resolve(client.data);
    paint();
    return client.refresh();
  }
  const timer = setInterval(refresh, 60_000);
  document.addEventListener("visibilitychange", refresh, { signal: controller.signal });
  refresh();
  return {
    refresh,
    dispose() { controller.abort(); client.dispose(); clearInterval(timer); },
  };
}
