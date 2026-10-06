// Swim Francisco map view.
// Explicitly mounted on /map/. Markers consume the same board snapshot as
// the table and summary; updates preserve retained markers and open popups.

import { OPEN_STATUSES } from "./helpers/board.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { formatTideSummary } from "./helpers/tide.mjs";
import { statusLabel, t } from "./helpers/i18n.mjs";
import { formatWaterTemp } from "./conditions.js";
import { capture } from "./helpers/analytics.mjs";

const SF_CENTER = [37.7749, -122.4459];
const SF_ZOOM = 12;

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

function createPopupHTML(spot, conditions, instant) {
  const name = escapeHTML(spot.name);
  const detailsHref = spot.href;
  const appleHref = `https://maps.apple.com/?daddr=${spot.lat},${spot.lng}`;
  const googleHref = `https://www.google.com/maps/dir/?api=1&destination=${spot.lat},${spot.lng}`;
  const rows = [popupRow(t("type", "TYPE"), spot.typeLabel)];

  if (spot.type === "open_water") {
    const record = conditions[spot.slug];
    const tide = formatTideSummary(record, pacificWallClockDate(instant));
    rows.push(popupRow(t("status", "STATUS"), statusLabel(spot.status || "OPEN")));
    rows.push(popupRow(t("water", "WATER"), formatWaterTemp(record)));
    rows.push(popupRow(t("tide", "TIDE"), tide));
  } else {
    rows.push(popupRow(t("status", "STATUS"), statusLabel(spot.status)));
    rows.push(popupRow(t("next", "NEXT"), spot.nextText));
  }

  return (
    `<div class="sf-map-popup mono-caps">` +
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

function renderMarkers(L, map, markers, spots, conditions, instant) {
  const visibleSlugs = new Set(spots.map((spot) => spot.slug));
  for (const [slug, entry] of markers) {
    if (visibleSlugs.has(slug)) continue;
    map.removeLayer(entry.marker);
    markers.delete(slug);
  }
  spots.forEach((spot) => {
    const icon = createMarkerIcon(L, spot);
    const popupHTML = createPopupHTML(spot, conditions, instant);
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
    marker.addTo(map);
    markers.set(spot.slug, { marker, iconClass: icon.options.className, popupHTML });
  });
}

async function loadBasemap(L, map, signal, fetcher) {
  const request = new AbortController();
  const abort = () => request.abort();
  if (signal.aborted) abort();
  else signal.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(abort, 10_000);
  try {
    const response = await fetcher("/api/map-config", { signal: request.signal });
    if (!response.ok) throw new Error("Map configuration unavailable");
    const config = await response.json();
    if (request.signal.aborted) return;
    const key = config?.carto_basemap_key;
    if (typeof key !== "string" || !key.trim()) throw new Error("Map configuration invalid");

    // CartoDB Voyager keeps SF's neighborhoods and bay legible.
    L.tileLayer(`https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(key.trim())}`, {
      maxZoom: 19,
      subdomains: "abcd",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", abort);
  }
}

export function mountMap(root = document, {
  L = globalThis.window?.L, snapshot, conditions = {}, instant = new Date(),
  fetch: fetcher = globalThis.fetch,
} = {}) {
  const container = root.querySelector("#map-view");
  if (!container) return null;
  if (!L) {
    console.error("[swimfrancisco] map load failed");
    return null;
  }
  const controller = new AbortController();
  const map = L.map(container).setView(SF_CENTER, SF_ZOOM);
  const markers = new Map();
  function update(nextSnapshot, nextConditions = {}, nextInstant = new Date()) {
    if (controller.signal.aborted) return;
    const spots = (nextSnapshot?.entries || []).filter((entry) => !entry.hidden && Number.isFinite(entry.lat) && Number.isFinite(entry.lng));
    renderMarkers(L, map, markers, spots, nextConditions, nextInstant);
  }
  update(snapshot, conditions, instant);
  capture("map_opened", { spots_visible: markers.size });

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
  }, { signal: controller.signal });

  const ready = loadBasemap(L, map, controller.signal, fetcher).catch(() => {
    if (!controller.signal.aborted) {
      capture("map_config_fetch_failed");
      console.error("[swimfrancisco] basemap unavailable");
    }
  });
  return {
    update, ready,
    dispose() {
      if (controller.signal.aborted) return;
      controller.abort();
      markers.clear();
      map.remove();
    },
  };
}
