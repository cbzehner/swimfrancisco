// Swim Francisco map view.
// Only loaded on /map/. Initializes Leaflet, renders one marker per spot
// that is visible under the current filters, and re-renders on
// `sf:filters-applied`. No client-side view toggling — the VIEW BOARD link
// is a plain <a href="/"> and the browser handles navigation.

import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { formatTideSummary } from "./helpers/tide.mjs";
import { statusLabel, t } from "./helpers/i18n.mjs";

const LEAFLET_JS_URL = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_JS_INTEGRITY =
  "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
const SF_CENTER = [37.7749, -122.4459];
const SF_ZOOM = 12;

// Lazy-load Leaflet JS. Resolves to the global `L` or rejects on load error.
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = LEAFLET_JS_URL;
    script.integrity = LEAFLET_JS_INTEGRITY;
    script.crossOrigin = "";
    script.async = true;
    script.onload = () =>
      window.L ? resolve(window.L) : reject(new Error("Leaflet missing"));
    script.onerror = () => reject(new Error("Failed to load Leaflet"));
    document.head.appendChild(script);
  });
}

function readNumber(row, attr) {
  const raw = row.getAttribute(attr);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

// Visible rows only — filters.js sets [hidden] on rows that don't match.
function collectVisibleSpots() {
  const rows = document.querySelectorAll("table.board tbody tr:not([hidden])");
  const spots = [];
  rows.forEach((row) => {
    const lat = readNumber(row, "data-lat");
    const lng = readNumber(row, "data-lng");
    if (lat === null || lng === null) return;
    const slug = row.getAttribute("data-slug") || "";
    const type = row.getAttribute("data-type") || "";
    const spotLink = row.querySelector('[data-cell="spot"] a');
    const name = spotLink?.textContent.trim() ?? "";
    const href = spotLink?.getAttribute("href") ?? "";
    const typeLabel =
      row.querySelector('[data-cell="spot"] .spot-subtitle')?.textContent.trim() ||
      row.getAttribute("data-subtype") ||
      type;
    const statusCell = row.querySelector('[data-cell="status"]');
    const status =
      statusCell?.dataset.statusValue ||
      statusCell?.querySelector(".status-pill")?.textContent.trim() ||
      statusCell?.textContent.trim() ||
      "";
    const next = row.querySelector('[data-cell="next"]')?.textContent.trim() ?? "";
    const temp = row.querySelector('[data-cell="water"]')?.textContent.trim() ?? "";
    spots.push({ slug, type, name, href, lat, lng, typeLabel, status, next, temp });
  });
  return spots;
}

function escapeHTML(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function popupRow(label, value) {
  if (!value || value === "—") return "";
  return (
    `<div class="sf-map-popup-row">` +
    `<span class="sf-map-popup-key">${escapeHTML(label)}</span>` +
    `<span class="sf-map-popup-val">${escapeHTML(value)}</span>` +
    `</div>`
  );
}

function beachConditions(spot) {
  const conditions = (typeof window !== "undefined" && window.SWIMFRANCISCO_CONDITIONS) || null;
  const record = conditions ? conditions[spot.slug] : null;
  const tide = record ? formatTideSummary(record, pacificWallClockDate()) : null;
  return { temp: spot.temp, tide };
}

function createPopupHTML(spot) {
  const name = escapeHTML(spot.name);
  const detailsHref = spot.href;
  const appleHref = `https://maps.apple.com/?daddr=${spot.lat},${spot.lng}`;
  const googleHref = `https://www.google.com/maps/dir/?api=1&destination=${spot.lat},${spot.lng}`;
  const rows = [popupRow(t("type", "TYPE"), spot.typeLabel)];

  if (spot.type === "open_water") {
    const { temp, tide } = beachConditions(spot);
    rows.push(popupRow(t("status", "STATUS"), statusLabel(spot.status || "OPEN")));
    rows.push(popupRow(t("water", "WATER"), temp));
    rows.push(popupRow(t("tide", "TIDE"), tide));
  } else {
    rows.push(popupRow(t("status", "STATUS"), statusLabel(spot.status)));
    rows.push(popupRow(t("next", "NEXT"), spot.next));
  }

  return (
    `<div class="sf-map-popup">` +
    `<a class="sf-map-popup-title" href="${detailsHref}">` +
    `<strong>${name}</strong>` +
    `<span class="sf-map-popup-title-arrow" aria-hidden="true">→</span>` +
    `</a>` +
    rows.join("") +
    `<div class="sf-map-popup-actions">` +
    `<div class="sf-map-popup-directions">` +
    `<span class="sf-map-popup-key">${escapeHTML(t("directions", "DIRECTIONS"))}</span>` +
    `<a href="${appleHref}" target="_blank" rel="noopener">APPLE</a>` +
    `<a href="${googleHref}" target="_blank" rel="noopener">GOOGLE</a>` +
    `</div>` +
    `</div>` +
    `</div>`
  );
}

function createMarkerIcon(L, spot) {
  const isOpen = spot.status === "OPEN";
  const cls =
    spot.type === "open_water"
      ? "sf-marker sf-marker-open-water"
      : `sf-marker${isOpen ? " sf-marker-open" : ""}`;
  return L.divIcon({
    className: cls,
    html: '<span class="sf-marker-dot"></span>',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -14],
  });
}

// Zoom level used when zooming into a clicked marker. Far enough in to see
// the immediate neighborhood and walking routes, not so far that context is
// lost (e.g. nearby beaches relative to a pool).
const FOCUS_ZOOM = 15;

function renderMarkers(L, map, layer, spots) {
  layer.clearLayers();
  spots.forEach((spot) => {
    const marker = L.marker([spot.lat, spot.lng], { icon: createMarkerIcon(L, spot) });
    marker.bindPopup(createPopupHTML(spot));
    marker.on("click", () => {
      const targetZoom = Math.max(map.getZoom(), FOCUS_ZOOM);
      map.flyTo([spot.lat, spot.lng], targetZoom, { duration: 0.6 });
    });
    layer.addLayer(marker);
  });
}

async function init() {
  const container = document.getElementById("map-view");
  if (!container) return;

  let L;
  try {
    L = await loadLeaflet();
  } catch (err) {
    console.error("[swimfrancisco] map load failed", err);
    return;
  }

  const map = L.map(container).setView(SF_CENTER, SF_ZOOM);
  // CartoDB Voyager: warm cream basemap that keeps SF's neighborhoods,
  // parks, and the bay legible without overwhelming the brand palette.
  L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    subdomains: "abcd",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);
  const markerLayer = L.layerGroup().addTo(map);
  const refresh = () => renderMarkers(L, map, markerLayer, collectVisibleSpots());
  refresh();

  // Filters update row.hidden; we re-render markers to match.
  document.addEventListener("sf:filters-applied", refresh);
  // Conditions arrive async — re-render so beach popups pick up temp/tide.
  document.addEventListener("sf:conditions-loaded", refresh);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
