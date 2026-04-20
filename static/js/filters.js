// Swim Francisco departure-board filters (Step 12).
// Wires up the Open Now toggle, Type pills (lap_swim /
// family_swim / open_water), and Near Me button. Each change re-applies
// visibility + sort and retriggers the split-flap animation on visible rows.
//
// Contract with status.js:
//   - status.js dispatches `sf:status-applied` after it populates STATUS/NEXT
//     and performs the baseline sort. filters.js waits for that event so
//     it reads the correct status cell text and preserves the baseline order
//     when Near Me is not active.
//
// Contract with main.scss (.flap / --flap-index):
//   - Set CSS custom property `--flap-index` on each visible row (integer,
//     0..N-1 in sorted order) and add the `.flap` class. Animation is on
//     the <td> cells; listen for animationend bubbling up to the <tr> and
//     remove the class once, so it can be re-applied on the next change.
//
// No frameworks, plain DOM APIs, progressive enhancement: without JS the
// board still renders and all rows remain visible.

import { sortByRank } from "./helpers/board.mjs";

const POOL_SESSION_TYPES = new Set(["lap_swim", "family_swim"]);
const EARTH_RADIUS_MILES = 3958.8;

// Hash routing: short tokens in window.location.hash, joined by "+".
// Filters own the hash. The `/map/` vs `/` switch is a real navigation
// (plain <a href>), not a hash token — see view-switcher in the template.
const TYPE_TOKENS = {
  lap: "lap_swim",
  family: "family_swim",
  beach: "open_water",
};
const TYPE_TO_TOKEN = Object.fromEntries(
  Object.entries(TYPE_TOKENS).map(([token, type]) => [type, token]),
);
const FILTER_TOKENS = new Set([
  "open-now",
  "near-me",
  ...Object.keys(TYPE_TOKENS),
]);

function readHashTokens() {
  const raw = window.location.hash.replace(/^#/, "");
  return new Set(raw.split("+").filter(Boolean));
}

function writeHashTokens(tokens) {
  const sorted = Array.from(tokens).sort();
  const hash = sorted.length ? `#${sorted.join("+")}` : "";
  const url = window.location.pathname + window.location.search + hash;
  history.replaceState(null, "", url);
}

// Remove this module's tokens from hash, then add the ones currently active.
function syncStateToHash(state) {
  const tokens = readHashTokens();
  for (const token of FILTER_TOKENS) tokens.delete(token);
  if (state.openNow) tokens.add("open-now");
  if (state.nearMe) tokens.add("near-me");
  for (const type of state.types) {
    const token = TYPE_TO_TOKEN[type];
    if (token) tokens.add(token);
  }
  writeHashTokens(tokens);
  updateViewSwitcherHref();
}

// Keep the VIEW MAP / VIEW BOARD link's href in sync with the current
// filter hash so navigating preserves filter state. Middle-click / cmd-click
// work naturally because we update the actual attribute.
function updateViewSwitcherHref() {
  const link = document.querySelector(".view-switcher-link");
  if (!link) return;
  const target = link.dataset.targetPath;
  if (!target) return;
  link.setAttribute("href", target + window.location.hash);
}

// Parse a row's data-schedule JSON (same shape as status.js expects).
function readSchedule(row) {
  const raw = row.getAttribute("data-schedule");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

// Parse a numeric data-* attribute; returns null if absent or non-finite.
function readNumber(row, attr) {
  const raw = row.getAttribute(attr);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

// Pure: does this row match a single type-pill selection?
// For `open_water` → match rows whose data-type is "open_water".
// For pool session types (lap_swim/family_swim) → true iff any
// session inside data-schedule has a matching `type` field.
function rowMatchesType(row, type) {
  if (type === "open_water") {
    return row.getAttribute("data-type") === "open_water";
  }
  if (!POOL_SESSION_TYPES.has(type)) return false;
  if (row.getAttribute("data-type") !== "pool") return false;
  const schedule = readSchedule(row);
  if (!schedule || !Array.isArray(schedule.sessions)) return false;
  return schedule.sessions.some(
    (session) => session && typeof session === "object" && session.type === type,
  );
}

// Pure: can this spot be used right now?
// - Open-water spots (Aquatic Park, Ocean Beach, …) pass because the water
//   is always there; no schedule constraint.
// - Pool rows pass only if status.js computed STATUS === "OPEN". A status
//   of "CLOSED" or "—" (no schedule data yet, or closed all week) fails.
function rowIsOpenNow(row) {
  if (row.getAttribute("data-type") === "open_water") return true;
  const cells = row.querySelectorAll("td");
  if (cells.length < 3) return false;
  return cells[2].textContent.trim() === "OPEN";
}

// Pure: apply all active filter predicates. If no type pills are pressed,
// every type passes. Type pills OR together (union).
function rowPassesFilters(row, state) {
  if (state.openNow && !rowIsOpenNow(row)) return false;
  if (state.types.size > 0) {
    let anyMatch = false;
    for (const type of state.types) {
      if (rowMatchesType(row, type)) {
        anyMatch = true;
        break;
      }
    }
    if (!anyMatch) return false;
  }
  return true;
}

// Great-circle distance in miles between two lat/lng points.
function haversineMiles(lat1, lng1, lat2, lng2) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_MILES * c;
}

// When Near Me is active, sort visible rows by ascending distance from
// userCoords. Rows missing lat/lng fall to the end. Stable via index.
function sortByDistance(rows, userCoords) {
  const decorated = rows.map((row, index) => {
    const lat = readNumber(row, "data-lat");
    const lng = readNumber(row, "data-lng");
    const distance =
      lat !== null && lng !== null
        ? haversineMiles(userCoords.latitude, userCoords.longitude, lat, lng)
        : Number.POSITIVE_INFINITY;
    return { row, index, distance };
  });
  decorated.sort((a, b) => {
    if (a.distance !== b.distance) return a.distance - b.distance;
    return a.index - b.index;
  });
  return decorated.map((item) => item.row);
}

// Trigger the split-flap animation on the given rows. Assigns --flap-index
// in order (0..N-1), adds the .flap class, and removes it on the next
// animationend bubbling up from a cell. The `once` option means the listener
// tears itself down, so the class can be re-applied on the next filter change.
function triggerFlap(rows) {
  rows.forEach((row, index) => {
    // Reset so retrigger works even if an earlier animation is mid-flight.
    row.classList.remove("flap");
    row.style.setProperty("--flap-index", String(index));
    // Force reflow so removing + re-adding .flap restarts the animation.
    void row.offsetWidth;
    row.classList.add("flap");
    row.addEventListener(
      "animationend",
      () => {
        row.classList.remove("flap");
      },
      { once: true },
    );
  });
}

// Apply current filter state to the board: toggle row.hidden, sort visible
// rows (by distance if Near Me is on, otherwise leave in the baseline order
// that status.js produced), move them to the top of tbody, and flap them.
function applyFilters(tbody, state) {
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const visible = [];
  rows.forEach((row) => {
    const passes = rowPassesFilters(row, state);
    row.hidden = !passes;
    if (passes) visible.push(row);
  });

  const ordered =
    state.nearMe && state.userCoords
      ? sortByDistance(visible, state.userCoords)
      : sortByRank(visible, (row) => Number(row.dataset.baselineRank));

  // Move visible rows to the top in their new order; hidden rows retain
  // their DOM position at the tail (visually irrelevant since hidden).
  ordered.forEach((row) => tbody.appendChild(row));

  triggerFlap(ordered);

  // Broadcast so other modules (map.js) can react to the new visible set.
  document.dispatchEvent(new CustomEvent("sf:filters-applied"));
}

// Wire click handlers. Returns the state object (handlers close over it).
function attachHandlers(tbody, filtersRoot) {
  const state = {
    openNow: false,
    types: new Set(),
    nearMe: false,
    userCoords: null,
  };

  const openNowButton = filtersRoot.querySelector('button[data-filter="open-now"]');
  if (openNowButton) {
    openNowButton.setAttribute("aria-pressed", "false");
    openNowButton.addEventListener("click", () => {
      state.openNow = !state.openNow;
      openNowButton.setAttribute("aria-pressed", String(state.openNow));
      applyFilters(tbody, state);
      syncStateToHash(state);
    });
  }

  const typeButtons = filtersRoot.querySelectorAll('button[data-filter="type"]');
  typeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", "false");
    const type = button.getAttribute("data-type");
    if (!type) return;
    button.addEventListener("click", () => {
      if (state.types.has(type)) {
        state.types.delete(type);
        button.setAttribute("aria-pressed", "false");
      } else {
        state.types.add(type);
        button.setAttribute("aria-pressed", "true");
      }
      applyFilters(tbody, state);
      syncStateToHash(state);
    });
  });

  const nearMeButton = filtersRoot.querySelector('button[data-action="near-me"]');
  if (nearMeButton) {
    nearMeButton.setAttribute("aria-pressed", "false");
    nearMeButton.addEventListener("click", () => {
      // Toggle off if already on.
      if (state.nearMe) {
        state.nearMe = false;
        state.userCoords = null;
        nearMeButton.setAttribute("aria-pressed", "false");
        applyFilters(tbody, state);
        syncStateToHash(state);
        return;
      }
      if (!("geolocation" in navigator)) {
        nearMeButton.setAttribute("aria-pressed", "false");
        return;
      }
      nearMeButton.setAttribute("aria-pressed", "true");
      navigator.geolocation.getCurrentPosition(
        (position) => {
          state.nearMe = true;
          state.userCoords = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          };
          applyFilters(tbody, state);
          syncStateToHash(state);
        },
        () => {
          state.nearMe = false;
          state.userCoords = null;
          nearMeButton.setAttribute("aria-pressed", "false");
        },
      );
    });
  }

  return { state, openNowButton, typeButtons, nearMeButton };
}

// Apply hash tokens by dispatching clicks on buttons whose desired pressed-
// state differs from current. Reuses existing handlers (which also sync hash,
// idempotently).
function restoreFromHash(controls) {
  const tokens = readHashTokens();
  const { state, openNowButton, typeButtons, nearMeButton } = controls;

  if (openNowButton) {
    const want = tokens.has("open-now");
    if (want !== state.openNow) openNowButton.click();
  }
  typeButtons.forEach((button) => {
    const type = button.getAttribute("data-type");
    const token = TYPE_TO_TOKEN[type];
    if (!token) return;
    const want = tokens.has(token);
    const have = state.types.has(type);
    if (want !== have) button.click();
  });
  if (nearMeButton) {
    const want = tokens.has("near-me");
    if (want !== state.nearMe) nearMeButton.click();
  }
}

function init() {
  const tbody = document.querySelector("table.board tbody");
  const filtersRoot = document.querySelector(".filters");
  if (!tbody || !filtersRoot) return;
  const controls = attachHandlers(tbody, filtersRoot);
  // Apply any filter tokens present in the URL hash on load.
  restoreFromHash(controls);
  updateViewSwitcherHref();
  // Keep state in sync if the hash changes (back/forward, manual edit).
  window.addEventListener("hashchange", () => {
    restoreFromHash(controls);
    updateViewSwitcherHref();
  });
}

// Wait until status.js has populated STATUS cells + baseline-sorted rows.
// If that event already fired (script order guarantees it fires on
// DOMContentLoaded before this one runs in most cases, but defensively
// also listen for DOMContentLoaded as a fallback).
let started = false;
function startOnce() {
  if (started) return;
  started = true;
  init();
}

document.addEventListener("sf:status-applied", startOnce, { once: true });
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    // If status.js is absent or did not dispatch, still attach handlers
    // after the next frame so the page is interactive.
    requestAnimationFrame(startOnce);
  });
} else {
  requestAnimationFrame(startOnce);
}
