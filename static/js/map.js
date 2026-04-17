// SwimFrancisco map view toggle (Step 13).
// Leaflet is lazy-loaded from a CDN on first MAP click so non-map pageviews
// don't pay for it. On subsequent clicks we just flip `hidden` on the map
// container and the board table.

const LEAFLET_JS_URL = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_JS_INTEGRITY =
  "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
const SF_CENTER = [37.7749, -122.4459];
const SF_ZOOM = 12;

let leafletPromise = null;
let mapInstance = null;

// Lazy-load Leaflet JS. Resolves to the global `L` or rejects on load error.
function ensureLeaflet() {
  if (typeof window !== "undefined" && window.L) {
    return Promise.resolve(window.L);
  }
  if (leafletPromise) return leafletPromise;
  leafletPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = LEAFLET_JS_URL;
    script.integrity = LEAFLET_JS_INTEGRITY;
    script.crossOrigin = "";
    script.async = true;
    script.onload = () => {
      if (window.L) resolve(window.L);
      else reject(new Error("Leaflet loaded but window.L missing"));
    };
    script.onerror = () => {
      leafletPromise = null;
      reject(new Error("Failed to load Leaflet"));
    };
    document.head.appendChild(script);
  });
  return leafletPromise;
}

// Parse a numeric data-* attribute; null if absent/non-finite.
function readNumber(row, attr) {
  const raw = row.getAttribute(attr);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

// Collect spot data from the board. Skips rows with invalid coords.
function collectSpots(root) {
  const rows = root.querySelectorAll("table.board tbody tr");
  const spots = [];
  rows.forEach((row) => {
    const lat = readNumber(row, "data-lat");
    const lng = readNumber(row, "data-lng");
    if (lat === null || lng === null) return;
    const slug = row.getAttribute("data-slug") || "";
    const type = row.getAttribute("data-type") || "";
    const cells = row.querySelectorAll("td");
    const nameEl = cells.length > 0 ? cells[0].querySelector("a") : null;
    const name = nameEl ? nameEl.textContent.trim() : "";
    const typeLabel = cells.length > 1 ? cells[1].textContent.trim() : "";
    const status = cells.length > 2 ? cells[2].textContent.trim() : "";
    spots.push({ slug, name, lat, lng, type, typeLabel, status });
  });
  return spots;
}

// Escape HTML special characters for safe interpolation into popup strings.
function escapeHTML(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Build popup HTML for a spot (name, type, status, link to detail page).
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

// Create the Leaflet map instance inside `container` with markers for each spot.
function initMap(L, container, spots) {
  const map = L.map(container).setView(SF_CENTER, SF_ZOOM);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  spots.forEach((spot) => {
    const marker = L.marker([spot.lat, spot.lng]).addTo(map);
    marker.bindPopup(createPopupHTML(spot));
  });
  return map;
}

// Toggle handler wired to the MAP button.
function toggleMap(button, mapContainer, boardTable) {
  const showingMap = !mapContainer.hidden;
  if (showingMap) {
    mapContainer.hidden = true;
    if (boardTable) boardTable.hidden = false;
    button.setAttribute("aria-pressed", "false");
    return;
  }
  // Switching to map view.
  mapContainer.hidden = false;
  if (boardTable) boardTable.hidden = true;
  button.setAttribute("aria-pressed", "true");

  if (mapInstance) {
    // Leaflet needs an invalidateSize after the container becomes visible.
    mapInstance.invalidateSize();
    return;
  }

  ensureLeaflet()
    .then((L) => {
      const spots = collectSpots(document);
      mapInstance = initMap(L, mapContainer, spots);
      // Post-show size recalculation (container was hidden during init).
      mapInstance.invalidateSize();
    })
    .catch((err) => {
      console.error("[swimfrancisco] map load failed", err);
      mapContainer.hidden = true;
      if (boardTable) boardTable.hidden = false;
      button.setAttribute("aria-pressed", "false");
    });
}

function init() {
  const button = document.querySelector('button[data-action="toggle-map"]');
  const mapContainer = document.getElementById("map-view");
  const boardTable = document.querySelector("table.board");
  if (!button || !mapContainer) return;
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => {
    toggleMap(button, mapContainer, boardTable);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
