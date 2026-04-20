// Swim Francisco map view.
// Only loaded on /map/. Initializes Leaflet, renders one marker per spot
// that is visible under the current filters, and re-renders on
// `sf:filters-applied`. No client-side view toggling — the VIEW BOARD link
// is a plain <a href="/"> and the browser handles navigation.

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
    const cells = row.querySelectorAll("td");
    const name = cells[0]?.querySelector("a")?.textContent.trim() ?? "";
    const typeLabel = cells[1]?.textContent.trim() ?? "";
    const status = cells[2]?.textContent.trim() ?? "";
    spots.push({ slug, name, lat, lng, typeLabel, status });
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

function createPopupHTML(spot) {
  const name = escapeHTML(spot.name);
  const typeLabel = escapeHTML(spot.typeLabel);
  const status = escapeHTML(spot.status);
  const href = `/spots/${encodeURIComponent(spot.slug)}/`;
  return (
    `<div class="sf-map-popup">` +
    `<strong>${name}</strong>` +
    `<div class="sf-map-popup-meta">${typeLabel}${typeLabel && status ? " — " : ""}${status}</div>` +
    `<a href="${href}">Details</a>` +
    `</div>`
  );
}

function renderMarkers(L, layer, spots) {
  layer.clearLayers();
  spots.forEach((spot) => {
    const marker = L.marker([spot.lat, spot.lng]);
    marker.bindPopup(createPopupHTML(spot));
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
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const markerLayer = L.layerGroup().addTo(map);
  renderMarkers(L, markerLayer, collectVisibleSpots());

  // Filters update row.hidden; we re-render markers to match.
  document.addEventListener("sf:filters-applied", () => {
    renderMarkers(L, markerLayer, collectVisibleSpots());
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
