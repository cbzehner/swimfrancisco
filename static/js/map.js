// Swim Francisco map view.
// Only loaded on /map/. Initializes Leaflet, renders one marker per spot
// that is visible under the current filters, and re-renders on
// `sf:filters-applied`. No client-side view toggling — the VIEW BOARD link
// is a plain <a href="/"> and the browser handles navigation.

import { OPEN_STATUSES, readNumberAttribute } from "./helpers/board.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { formatTideSummary } from "./helpers/tide.mjs";
import { statusLabel, t } from "./helpers/i18n.mjs";
import { capture } from "./helpers/analytics.mjs";

const SF_CENTER = [37.7749, -122.4459];
const SF_ZOOM = 12;

// Visible rows only — filters.js sets [hidden] on rows that don't match.
function collectVisibleSpots() {
  const rows = document.querySelectorAll("table.board tbody tr:not([hidden])");
  const spots = [];
  rows.forEach((row) => {
    const lat = readNumberAttribute(row, "data-lat");
    const lng = readNumberAttribute(row, "data-lng");
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
    const status = statusCell?.dataset.statusValue || "";
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
    `<a href="${appleHref}" target="_blank" rel="noopener" data-outbound="directions">APPLE</a>` +
    `<a href="${googleHref}" target="_blank" rel="noopener" data-outbound="directions">GOOGLE</a>` +
    `</div>` +
    `</div>` +
    `</div>`
  );
}

function createMarkerIcon(L, spot) {
  const isOpen = OPEN_STATUSES.has(spot.status);
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

function renderMarkers(L, map, layer, markers, spots) {
  const visibleSlugs = new Set(spots.map((spot) => spot.slug));
  for (const [slug, entry] of markers) {
    if (visibleSlugs.has(slug)) continue;
    layer.removeLayer(entry.marker);
    markers.delete(slug);
  }
  spots.forEach((spot) => {
    const icon = createMarkerIcon(L, spot);
    const popupHTML = createPopupHTML(spot);
    const existing = markers.get(spot.slug);
    if (existing) {
      if (existing.iconClass !== icon.options.className) existing.marker.setIcon(icon);
      if (existing.popupHTML !== popupHTML) existing.marker.setPopupContent(popupHTML);
      existing.iconClass = icon.options.className;
      existing.popupHTML = popupHTML;
      return;
    }
    const marker = L.marker([spot.lat, spot.lng], { icon });
    marker.bindPopup(popupHTML);
    marker.on("click", () => {
      const targetZoom = Math.max(map.getZoom(), FOCUS_ZOOM);
      // Honor prefers-reduced-motion (WCAG 2.3.3) — a 600ms animated pan
      // can trigger vestibular issues; setView is instant.
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        map.setView([spot.lat, spot.lng], targetZoom);
      } else {
        map.flyTo([spot.lat, spot.lng], targetZoom, { duration: 0.6 });
      }
    });
    // WCAG 2.4.3 — return focus to the marker on popup close so Tab order
    // resumes from where the user opened it. Leaflet defaults to <body>.
    marker.on("popupclose", () => {
      marker.getElement()?.focus();
    });
    layer.addLayer(marker);
    markers.set(spot.slug, { marker, iconClass: icon.options.className, popupHTML });
  });
}

async function loadBasemap(L, map) {
  const response = await fetch("/api/map-config", { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error("Map configuration unavailable");
  const config = await response.json();
  const key = config?.carto_basemap_key;
  if (typeof key !== "string" || !key.trim()) throw new Error("Map configuration invalid");

  // CartoDB Voyager: warm cream basemap that keeps SF's neighborhoods,
  // parks, and the bay legible without overwhelming the brand palette.
  L.tileLayer(`https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(key.trim())}`, {
    maxZoom: 19,
    subdomains: "abcd",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);
}

async function init() {
  const container = document.getElementById("map-view");
  if (!container) return;

  const L = window.L;
  if (!L) {
    console.error("[swimfrancisco] map load failed");
    return;
  }

  const map = L.map(container).setView(SF_CENTER, SF_ZOOM);
  const markerLayer = L.layerGroup().addTo(map);
  const markers = new Map();
  const refresh = () => renderMarkers(L, map, markerLayer, markers, collectVisibleSpots());
  refresh();

  // The map is lazy-loaded only when someone opens /map/, so a successful
  // init is itself the adoption signal. `spots_visible` records how many
  // markers were shown under the inbound filter state.
  capture("map_opened", { spots_visible: collectVisibleSpots().length });

  // Popups are injected HTML, so delegate from the container. Directions
  // links are outbound conversions; the popup title opens a spot detail.
  container.addEventListener("click", (event) => {
    const directions = event.target.closest('.sf-map-popup-directions a');
    if (directions) {
      capture("outbound_click", {
        destination: "directions",
        href: directions.getAttribute("href") || "",
        source: "map_popup",
      });
      return;
    }
    const title = event.target.closest(".sf-map-popup-title");
    if (title) {
      const href = title.getAttribute("href") || "";
      capture("spot_opened", {
        slug: (href.match(/\/spots\/([^/]+)\//) || [])[1] || "",
        source: "map_popup",
      });
    }
  });

  // Filters update row.hidden; we re-render markers to match.
  document.addEventListener("sf:filters-applied", refresh);
  // Conditions arrive async — re-render so beach popups pick up temp/tide.
  document.addEventListener("sf:conditions-loaded", refresh);
  try {
    await loadBasemap(L, map);
  } catch {
    console.error("[swimfrancisco] basemap unavailable");
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
