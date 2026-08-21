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

import {
  computeNextOpenOffset,
  readScheduleAttribute,
  resolveActiveSchedule,
  sortByRank,
} from "./helpers/board.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { TYPE_TOKENS, TYPE_TO_TOKEN, isDropInType } from "./helpers/programs.mjs";
import { getCurrentHorizon, renderBoard } from "./status.js";
import { capture } from "./helpers/analytics.mjs";

const EARTH_RADIUS_MILES = 3958.8;
const TYPE_NONE = "none";

// Hash routing: short tokens in window.location.hash, joined by "+".
// Filters own the hash. The `/map/` vs `/` switch is a real navigation
// (plain <a href> in chrome.html), not a hash token.
// Hash tokens this module owns — stripped and rewritten on every state sync.
// Includes the sort token even though sort isn't a filter, because the same
// hash-round-trip logic applies. `next-open` and `open-now` are legacy
// tokens still recognized on read for inbound links; canonical write is `open`.
const OWNED_TOKENS = new Set([
  "open",
  "next-open",
  "open-now",
  "distance",
  "memberships",
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
function sortKind(state) {
  return state.sort?.kind || "default";
}

function applySortAria(state, nextOpenButton, distanceButton) {
  const kind = sortKind(state);
  nextOpenButton?.setAttribute("aria-pressed", String(kind === "open"));
  distanceButton?.setAttribute(
    "aria-pressed",
    String(kind === "distance" || kind === "distance-pending"),
  );
}

function syncStateToHash(state) {
  const tokens = readHashTokens();
  for (const token of OWNED_TOKENS) tokens.delete(token);
  const kind = sortKind(state);
  if (kind === "open") tokens.add("open");
  if (kind === "distance") tokens.add("distance");
  if (state.includeMemberships) tokens.add("memberships");
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
  document.querySelectorAll("[data-target-path]").forEach((link) => {
    const target = link.dataset.targetPath;
    if (!target) return;
    link.setAttribute("href", target + window.location.search + window.location.hash);
  });
}

// Parse a numeric data-* attribute; returns null if absent or non-finite.
function readNumber(row, attr) {
  const raw = row.getAttribute(attr);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function isBeach(row) {
  return row.getAttribute("data-type") === "open_water";
}

// Pure: does this row match a single type-pill selection?
// For `open_water` → match rows whose data-type is "open_water".
// For pool session types (lap_swim/family_swim) → true iff any
// session inside data-schedule has a matching `type` field.
function rowMatchesType(row, type) {
  if (type === "open_water") {
    return isBeach(row);
  }
  if (!isDropInType(type)) return false;
  if (row.getAttribute("data-type") !== "pool") return false;
  const horizon = getCurrentHorizon();
  const schedule = resolveActiveSchedule(
    readScheduleAttribute(row),
    horizon?.kind === "window" ? horizon.date : pacificWallClockDate(),
  );
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
  // Default board = truly walk-in-able places (access_mode "public": city
  // pools + beaches). The toggle opts into the broader set — membership
  // clubs, private facilities, day-pass and campus pools.
  const accessMode = row.getAttribute("data-access-mode") || "public";
  if (!state.includeMemberships && accessMode !== "public") {
    return false;
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

// When Distance sort is active, order visible rows by ascending distance
// from userCoords, keeping beaches below pools when both are visible. Rows
// missing lat/lng fall to the end of their group. Stable via index.
function sortRowsByDistance(rows, userCoords) {
  const decorated = rows.map((row, index) => {
    const lat = readNumber(row, "data-lat");
    const lng = readNumber(row, "data-lng");
    const distance =
      lat !== null && lng !== null
        ? haversineMiles(userCoords.latitude, userCoords.longitude, lat, lng)
        : Number.POSITIVE_INFINITY;
    return { row, index, distance, beachRank: isBeach(row) ? 1 : 0 };
  });
  decorated.sort((a, b) => {
    if (a.beachRank !== b.beachRank) return a.beachRank - b.beachRank;
    if (a.distance !== b.distance) return a.distance - b.distance;
    return a.index - b.index;
  });
  return decorated.map((item) => item.row);
}

function readWindowRank(row) {
  const windowRank = Number(row.dataset.windowRank);
  return Number.isFinite(windowRank) ? windowRank : Number.POSITIVE_INFINITY;
}

// Sort visible rows by the soonest pool time, keeping beaches below pools
// when both are visible. Pools with no known upcoming drop-in session fall
// to the end of the pool group. Stable via baseline rank.
function sortRowsByNextOpen(rows, allowedTypes, now, horizon) {
  const decorated = rows.map((row, index) => {
    // Window ranks come from applyStatuses via renderBoard, which
    // applyFilters always runs first. Recomputing here diverged for
    // access-hours pools (ACCESS ranked as NO SESSION).
    const offset = horizon?.kind === "window"
      ? readWindowRank(row)
      : isBeach(row)
        ? 0
        : computeNextOpenOffset(readScheduleAttribute(row), now, allowedTypes);
    const baselineRank = Number(row.dataset.baselineRank);
    return {
      row,
      index,
      beachRank: isBeach(row) ? 1 : 0,
      offset,
      baselineRank: Number.isFinite(baselineRank) ? baselineRank : Number.POSITIVE_INFINITY,
    };
  });
  decorated.sort((a, b) => {
    if (a.beachRank !== b.beachRank) return a.beachRank - b.beachRank;
    if (a.offset !== b.offset) return a.offset - b.offset;
    if (a.baselineRank !== b.baselineRank) return a.baselineRank - b.baselineRank;
    return a.index - b.index;
  });
  return decorated.map((item) => item.row);
}

function allowedPoolTypes(state) {
  const active = Array.from(state.types).filter((type) => isDropInType(type));
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
function applyFilters(tbody, state, { flap = true } = {}) {
  const poolTypes = allowedPoolTypes(state);
  renderBoard(document, poolTypes);
  const horizon = getCurrentHorizon();
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const visible = [];
  rows.forEach((row) => {
    const passes = rowPassesFilters(row, state);
    row.hidden = !passes;
    if (passes) visible.push(row);
  });

  const kind = sortKind(state);
  const ordered =
    kind === "distance"
      ? sortRowsByDistance(visible, state.sort.coords)
      : kind === "open"
        ? sortRowsByNextOpen(visible, poolTypes, pacificWallClockDate(), horizon)
      : sortByRank(visible, (row) => Number(row.dataset.baselineRank));

  // Move visible rows to the top in their new order; hidden rows retain
  // their DOM position at the tail (visually irrelevant since hidden).
  ordered.forEach((row) => tbody.appendChild(row));

  if (flap) triggerFlap(ordered);

  // Broadcast so other modules (map.js) can react to the new visible set.
  document.dispatchEvent(new CustomEvent("sf:filters-applied"));
}

// Emit a product event describing the filter/sort state a user just chose.
// `result_count` is the number of rows left visible — a zero here means the
// filter combination returned nothing, which is the friction we most want to
// see. `when` reflects the active time horizon (owned by status.js, mirrored
// in the URL). Fired only from user gestures, never from hash restore or the
// minute tick, so the event count tracks real intent.
function captureFilter(trigger, state, tbody) {
  capture("filter_applied", {
    trigger,
    program: activeType(state),
    sort: sortKind(state) === "distance-pending" ? "distance" : sortKind(state),
    memberships: state.includeMemberships,
    when: new URLSearchParams(window.location.search).get("when") || "now",
    result_count: tbody.querySelectorAll("tr:not([hidden])").length,
  });
}

// Wire click handlers. Returns the state object (handlers close over it).
function attachHandlers(tbody, filtersRoot) {
  const state = {
    sort: { kind: "default" },
    types: new Set(),
    includeMemberships: false,
  };

  const distanceButton = document.querySelector('button[data-action="sort-distance"]');
  const nextOpenButton = document.querySelector('button[data-filter="open-now"]');
  const membershipButton = document.querySelector('button[data-filter="access"][data-access="memberships"]');
  if (membershipButton) {
    membershipButton.setAttribute("aria-pressed", "false");
    membershipButton.addEventListener("click", () => {
      state.includeMemberships = !state.includeMemberships;
      membershipButton.setAttribute("aria-pressed", String(state.includeMemberships));
      applyFilters(tbody, state);
      captureFilter("memberships", state, tbody);
      syncStateToHash(state);
    });
  }
  if (nextOpenButton) {
    nextOpenButton.setAttribute("aria-pressed", "false");
    nextOpenButton.addEventListener("click", () => {
      state.sort = sortKind(state) === "open" ? { kind: "default" } : { kind: "open" };
      applySortAria(state, nextOpenButton, distanceButton);
      applyFilters(tbody, state);
      captureFilter("open_sort", state, tbody);
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
      captureFilter("program", state, tbody);
      syncStateToHash(state);
    });
  });

  if (distanceButton) {
    distanceButton.setAttribute("aria-pressed", "false");
    distanceButton.addEventListener("click", () => {
      if (sortKind(state) === "distance-pending") return;
      if (sortKind(state) === "distance") {
        state.sort = { kind: "default" };
        applySortAria(state, nextOpenButton, distanceButton);
        applyFilters(tbody, state);
        captureFilter("distance_sort", state, tbody);
        syncStateToHash(state);
        return;
      }
      if (!("geolocation" in navigator)) {
        distanceButton.setAttribute("aria-pressed", "false");
        return;
      }
      state.sort = { kind: "distance-pending" };
      applySortAria(state, nextOpenButton, distanceButton);
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (sortKind(state) !== "distance-pending") return;
          state.sort = {
            kind: "distance",
            coords: {
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
            },
          };
          applySortAria(state, nextOpenButton, distanceButton);
          applyFilters(tbody, state);
          captureFilter("distance_sort", state, tbody);
          syncStateToHash(state);
        },
        () => {
          if (sortKind(state) !== "distance-pending") return;
          state.sort = { kind: "default" };
          applySortAria(state, nextOpenButton, distanceButton);
        },
      );
    });
  }

  return { state, tbody, nextOpenButton, typeButtons, distanceButton, membershipButton };
}

// Apply hash tokens without dispatching button clicks. Distance sorting needs
// an explicit user gesture because it can prompt for geolocation.
function restoreFromHash(controls) {
  const tokens = readHashTokens();
  const { state, tbody, nextOpenButton, typeButtons, distanceButton, membershipButton } = controls;
  let changed = false;

  if (nextOpenButton) {
    const want = tokens.has("open") || tokens.has("next-open") || tokens.has("open-now");
    const isOpen = sortKind(state) === "open";
    if (want !== isOpen) {
      state.sort = want ? { kind: "open" } : { kind: "default" };
      applySortAria(state, nextOpenButton, distanceButton);
      changed = true;
    }
  }

  if (membershipButton) {
    const wantMemberships = tokens.has("memberships");
    if (wantMemberships !== state.includeMemberships) {
      state.includeMemberships = wantMemberships;
      membershipButton.setAttribute("aria-pressed", String(wantMemberships));
      changed = true;
    }
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
    const desiredType = desiredTypeButton.getAttribute("data-type");
    state.types.clear();
    if (desiredType && desiredType !== TYPE_NONE) state.types.add(desiredType);
    setPressed(typeButtonsArray, desiredType || TYPE_NONE);
    changed = true;
  }

  const kind = sortKind(state);
  if (kind === "distance-pending") {
    state.sort = { kind: "default" };
    applySortAria(state, nextOpenButton, distanceButton);
    changed = true;
  }
  const shouldDropDistanceToken = tokens.has("distance") && sortKind(state) !== "distance";
  if (distanceButton && sortKind(state) === "distance" && !tokens.has("distance")) {
    state.sort = { kind: "default" };
    applySortAria(state, nextOpenButton, distanceButton);
    changed = true;
  }

  if (changed) applyFilters(tbody, state);
  if (changed || shouldDropDistanceToken || tokens.has("next-open") || tokens.has("open-now")) {
    syncStateToHash(state);
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
  applyFilters(tbody, controls.state);
  updateViewSwitcherHref();
  // Keep state in sync if the hash changes (back/forward, manual edit).
  window.addEventListener("hashchange", () => {
    restoreFromHash(controls);
    updateViewSwitcherHref();
  });
  document.addEventListener("sf:horizon-changed", () => {
    applyFilters(tbody, controls.state);
    updateViewSwitcherHref();
  });
  // Minute tick from status.js: re-apply filter/sort state on top of the
  // fresh statuses without retriggering the split-flap animation.
  document.addEventListener("sf:board-refreshed", () => {
    applyFilters(tbody, controls.state, { flap: false });
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
