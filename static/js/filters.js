// Swim Francisco board filters (Step 12).
// Wires up the Next Open sort, Type pills (lap_swim /
// family_swim / open_water), and Distance sort. Each change re-applies
// visibility + sort and retriggers the split-flap animation on visible rows.
//
// Filters vs. sort: Type pills are filters (they hide rows). Next Open and
// Distance are sorts — they reorder visible rows but never hide any. Distance
// only renders on the board view (not map).
//
// Contract with status.js:
//   - status.js dispatches `sf:status-applied` after it populates STATUS/NEXT
//     and performs the baseline sort. filters.js waits for that event so
//     it reads the correct status cell text and preserves the baseline order
//     when Distance sort is not active.
//
// Contract with main.css (.flap / --flap-index):
//   - Set CSS custom property `--flap-index` on each visible row (integer,
//     0..N-1 in sorted order) and add the `.flap` class. Animation is on
//     the <td> cells; listen for animationend bubbling up to the <tr> and
//     remove the class once, so it can be re-applied on the next change.
//
// No frameworks, plain DOM APIs, progressive enhancement: without JS the
// board still renders and all rows remain visible.

import { computeNextOpenOffset, nowInPacific, sortByRank } from "./helpers/board.mjs";
import { renderBoard } from "./status.js";

const POOL_SESSION_TYPES = new Set(["lap_swim", "family_swim"]);
const EARTH_RADIUS_MILES = 3958.8;
const TYPE_NONE = "none";

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
// Hash tokens this module owns — stripped and rewritten on every state sync.
// Includes the sort token even though sort isn't a filter, because the same
// hash-round-trip logic applies. `next-open` and `open-now` are legacy
// tokens still recognized on read for inbound links; canonical write is `open`.
const OWNED_TOKENS = new Set([
  "open",
  "next-open",
  "open-now",
  "distance",
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
  for (const token of OWNED_TOKENS) tokens.delete(token);
  if (state.sortByNextOpen) tokens.add("open");
  if (state.sortByDistance) tokens.add("distance");
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

// Pure: apply all active filter predicates. If the active type is `none`
// (rendered as the "ALL" pill in the UI),
// every type passes. Otherwise the single selected type must match.
function rowPassesFilters(row, state) {
  const type = activeType(state);
  if (type && type !== TYPE_NONE && !rowMatchesType(row, type)) return false;
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

// When Distance sort is active, order visible rows by ascending distance
// from userCoords. Rows missing lat/lng fall to the end. Stable via index.
function sortRowsByDistance(rows, userCoords) {
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

// Sort visible rows by the soonest time they can be used. Open-water rows
// and currently open pool sessions rank as "now" (0). Pools with no known
// upcoming drop-in session fall to the end. Stable via baseline rank.
function sortRowsByNextOpen(rows, allowedTypes, now) {
  const decorated = rows.map((row, index) => {
    const offset =
      row.getAttribute("data-type") === "open_water"
        ? 0
        : computeNextOpenOffset(readSchedule(row), now, allowedTypes);
    const baselineRank = Number(row.dataset.baselineRank);
    return {
      row,
      index,
      offset,
      baselineRank: Number.isFinite(baselineRank) ? baselineRank : Number.POSITIVE_INFINITY,
    };
  });
  decorated.sort((a, b) => {
    if (a.offset !== b.offset) return a.offset - b.offset;
    if (a.baselineRank !== b.baselineRank) return a.baselineRank - b.baselineRank;
    return a.index - b.index;
  });
  return decorated.map((item) => item.row);
}

function allowedPoolTypes(state) {
  const active = Array.from(state.types).filter((type) => POOL_SESSION_TYPES.has(type));
  return active.length > 0 ? active : null;
}

function activeType(state) {
  const [type] = state.types;
  return type ?? TYPE_NONE;
}

function setPressed(buttons, activeTypeValue) {
  buttons.forEach((button) => {
    const type = button.getAttribute("data-type");
    button.setAttribute("aria-pressed", String(type === activeTypeValue));
  });
}

function collapseExpandedRows(tbody) {
  tbody.querySelectorAll('tr[aria-expanded="true"]').forEach((row) => {
    row.setAttribute("aria-expanded", "false");
  });
  tbody.querySelectorAll("tr.row-detail").forEach((row) => row.remove());
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
// rows (by distance if Distance sort is on, otherwise leave in the baseline
// order that status.js produced), move them to the top of tbody, and flap them.
function applyFilters(tbody, state) {
  collapseExpandedRows(tbody);
  const poolTypes = allowedPoolTypes(state);
  renderBoard(document, poolTypes);
  const rows = Array.from(tbody.querySelectorAll("tr:not(.row-detail)"));
  const visible = [];
  rows.forEach((row) => {
    const passes = rowPassesFilters(row, state);
    row.hidden = !passes;
    if (passes) visible.push(row);
  });

  const ordered =
    state.sortByDistance && state.userCoords
      ? sortRowsByDistance(visible, state.userCoords)
      : state.sortByNextOpen
        ? sortRowsByNextOpen(visible, poolTypes, nowInPacific())
      : sortByRank(visible, (row) => Number(row.dataset.baselineRank));

  // Move visible rows to the top in their new order; hidden rows retain
  // their DOM position at the tail (visually irrelevant since hidden).
  ordered.forEach((row) => tbody.appendChild(row));

  // TEMP column only carries data for beaches and NEXT only for pools.
  // Hide either when its rows aren't visible so pool-only or beach-only
  // views aren't padded with "—" placeholders.
  const hasBeach = ordered.some((row) => row.getAttribute("data-type") === "open_water");
  const hasPool = ordered.some((row) => row.getAttribute("data-type") === "pool");
  const table = tbody.closest("table.board");
  if (table) {
    table.classList.toggle("no-beaches", !hasBeach);
    table.classList.toggle("no-pools", !hasPool);
  }

  triggerFlap(ordered);

  // Broadcast so other modules (map.js) can react to the new visible set.
  document.dispatchEvent(new CustomEvent("sf:filters-applied"));
}

// Wire click handlers. Returns the state object (handlers close over it).
function attachHandlers(tbody, filtersRoot) {
  const state = {
    sortByNextOpen: false,
    types: new Set(),
    sortByDistance: false,
    userCoords: null,
  };

  const distanceButton = document.querySelector('button[data-action="sort-distance"]');
  const nextOpenButton = document.querySelector('button[data-filter="open-now"]');
  if (nextOpenButton) {
    nextOpenButton.setAttribute("aria-pressed", "false");
    nextOpenButton.addEventListener("click", () => {
      state.sortByNextOpen = !state.sortByNextOpen;
      nextOpenButton.setAttribute("aria-pressed", String(state.sortByNextOpen));
      // Mutually exclusive with NEAREST — only one sort active at a time.
      if (state.sortByNextOpen && state.sortByDistance) {
        state.sortByDistance = false;
        state.userCoords = null;
        distanceButton?.setAttribute("aria-pressed", "false");
      }
      applyFilters(tbody, state);
      syncStateToHash(state);
    });
  }

  const typeButtons = filtersRoot.querySelectorAll('button[data-filter="type"]');
  const typeButtonsArray = Array.from(typeButtons);
  typeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.getAttribute("data-type") === TYPE_NONE));
    const type = button.getAttribute("data-type");
    if (!type) return;
    button.addEventListener("click", () => {
      if (type === TYPE_NONE) {
        state.types.clear();
        setPressed(typeButtonsArray, TYPE_NONE);
      } else {
        state.types.clear();
        state.types.add(type);
        setPressed(typeButtonsArray, type);
      }
      applyFilters(tbody, state);
      syncStateToHash(state);
    });
  });

  if (distanceButton) {
    distanceButton.setAttribute("aria-pressed", "false");
    distanceButton.addEventListener("click", () => {
      // Toggle off if already on.
      if (state.sortByDistance) {
        state.sortByDistance = false;
        state.userCoords = null;
        distanceButton.setAttribute("aria-pressed", "false");
        applyFilters(tbody, state);
        syncStateToHash(state);
        return;
      }
      if (!("geolocation" in navigator)) {
        distanceButton.setAttribute("aria-pressed", "false");
        return;
      }
      distanceButton.setAttribute("aria-pressed", "true");
      navigator.geolocation.getCurrentPosition(
        (position) => {
          state.sortByDistance = true;
          state.userCoords = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          };
          // Mutually exclusive with OPEN — only one sort active at a time.
          if (state.sortByNextOpen) {
            state.sortByNextOpen = false;
            nextOpenButton?.setAttribute("aria-pressed", "false");
          }
          applyFilters(tbody, state);
          syncStateToHash(state);
        },
        () => {
          state.sortByDistance = false;
          state.userCoords = null;
          distanceButton.setAttribute("aria-pressed", "false");
        },
      );
    });
  }

  return { state, nextOpenButton, typeButtons, distanceButton };
}

// Apply hash tokens by dispatching clicks on buttons whose desired pressed-
// state differs from current. Reuses existing handlers (which also sync hash,
// idempotently).
function restoreFromHash(controls) {
  const tokens = readHashTokens();
  const { state, nextOpenButton, typeButtons, distanceButton } = controls;

  if (nextOpenButton) {
    const want = tokens.has("open") || tokens.has("next-open") || tokens.has("open-now");
    if (want !== state.sortByNextOpen) nextOpenButton.click();
  }
  const typeButtonsArray = Array.from(typeButtons);
  const desiredTypeButton = typeButtonsArray.find((button) => {
    const type = button.getAttribute("data-type");
    if (!type) return false;
    if (type === TYPE_NONE) return !hasTypeToken(tokens);
    const token = TYPE_TO_TOKEN[type];
    return Boolean(token && tokens.has(token));
  });
  const pressedTypeButton = typeButtonsArray.find(
    (button) => button.getAttribute("aria-pressed") === "true",
  );
  if (desiredTypeButton && desiredTypeButton !== pressedTypeButton) {
    desiredTypeButton.click();
  }
  if (distanceButton) {
    const want = tokens.has("distance");
    if (want !== state.sortByDistance) distanceButton.click();
  }
}

function hasTypeToken(tokens) {
  return Object.keys(TYPE_TOKENS).some((token) => tokens.has(token));
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
