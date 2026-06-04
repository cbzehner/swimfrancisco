// Swim Francisco board status computation.
// Pure helpers live in ./helpers/board.mjs and are exercised by node:test;
// this file handles the DOM glue.

import { PLACEHOLDER, computeStatus, captureBaselineRanks, nowInPacific } from "./helpers/board.mjs";
import {
  computeAccessStatus,
  computeAccessWindowAvailability,
  computeWindowAvailability,
  formatHHMM,
  getHorizonOptions,
  resolveHorizon,
} from "./helpers/board.mjs";
import { PROGRAM_LABEL } from "./helpers/programs.mjs";

let currentHorizon = resolveHorizon(readHorizonParam(), nowInPacific());

const HORIZON_TITLES = {
  "this-morning": "FOG-LIFT WINDOW",
  "this-afternoon": "LUNCH BREAK LANES",
  "this-evening": "AFTER-WORK WATER",
  "tomorrow-morning": "SET THE ALARM",
  "tomorrow-afternoon": "CLEAR THE CALENDAR",
  "tomorrow-evening": "GOLDEN HOUR TOMORROW",
};

function currentTimeTitle(now = nowInPacific()) {
  const hour = now.getHours();
  if (hour < 5) return "NIGHT SWIM";
  if (hour < 10) return "BEFORE BREAKFAST";
  if (hour < 14) return "LUNCH BREAK LANES";
  if (hour < 17) return "POST-FOG SWIM";
  if (hour < 21) return "AFTER-WORK WATER";
  return "NIGHT SWIM";
}

function readHorizonParam() {
  if (typeof window === "undefined") return "now";
  return new URLSearchParams(window.location.search).get("when") || "now";
}

function writeHorizonParam(horizonId) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (horizonId === "now") {
    url.searchParams.delete("when");
  } else {
    url.searchParams.set("when", horizonId);
  }
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function applyHorizonChrome(horizon) {
  const isNow = !horizon || horizon.id === "now";
  const title = isNow ? currentTimeTitle() : HORIZON_TITLES[horizon.id] || horizon.label.toUpperCase();
  document.querySelectorAll("[data-horizon-title]").forEach((node) => {
    node.textContent = `·${title}·`;
  });
  document.querySelectorAll("[data-horizon-button]").forEach((node) => {
    node.textContent = isNow ? "Now" : horizon.label;
  });
  document.querySelectorAll("[data-horizon-stamp-label]").forEach((node) => {
    node.textContent = isNow ? "OPEN NOW" : horizon.label.toUpperCase();
  });

  const banner = document.querySelector("[data-time-banner]");
  if (!banner) return;
  banner.hidden = isNow;
  const label = banner.querySelector("[data-time-banner-label]");
  if (label) label.textContent = isNow ? "Right now" : horizon.label;
}

export function getCurrentHorizon() {
  return currentHorizon;
}

// Read and parse the data-schedule attribute; returns null on error.
function readSchedule(row) {
  const raw = row.getAttribute("data-schedule");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

function formatWindowNext(result) {
  const session = result.bestSession;
  if (!session) return result.next || PLACEHOLDER;
  const program = PROGRAM_LABEL[session.type] || session.type.toUpperCase();
  return `${program} ${formatHHMM(session.start)}\u2013${formatHHMM(session.end)}`;
}

function cell(row, name) {
  return row.querySelector(`[data-cell="${name}"]`);
}

function statusClass(status, type) {
  if (type === "open_water" || status === "OCEAN") return "is-ocean";
  if (status === "OPEN" || status === "AVAILABLE" || status === "LIMITED" || status === "ACCESS") return "is-open";
  if (status === "CHECK") return "is-info";
  if (status.includes("6:30") || status.includes("SOON")) return "is-soon";
  return "is-closed";
}

function setStatus(statusCell, status, type, sublabel = "") {
  let pill = statusCell.querySelector(".status-pill");
  if (!pill) {
    statusCell.textContent = "";
    pill = document.createElement("span");
    pill.className = "status-pill";
    statusCell.append(pill);
  }
  statusCell.dataset.statusValue = status;
  pill.textContent = status;
  pill.className = `status-pill ${statusClass(status, type)}`;

  let sub = statusCell.querySelector(".status-sub");
  if (sublabel) {
    if (!sub) {
      sub = document.createElement("span");
      sub.className = "status-sub";
      statusCell.append(sub);
    }
    sub.textContent = sublabel;
  } else if (sub) {
    sub.remove();
  }
}

// Apply computed STATUS/NEXT. Pools compute from their schedule; open-water
// rows have no schedule and are always accessible, so they render as OCEAN.
function applyStatuses(root, now, allowedTypes = null) {
  const horizon = currentHorizon.id === "now" ? resolveHorizon("now", now) : currentHorizon;
  const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
  poolRows.forEach((row) => {
    const statusCell = cell(row, "status");
    const nextCell = cell(row, "next");
    if (!statusCell || !nextCell) return;
    const schedule = readSchedule(row);
    const hasSessions = schedule && Array.isArray(schedule.sessions) && schedule.sessions.length > 0;
    const hasAccessHours = schedule && Array.isArray(schedule.access_hours) && schedule.access_hours.length > 0;
    if (horizon.kind === "window") {
      const result = hasSessions
        ? computeWindowAvailability(schedule, horizon, allowedTypes)
        : computeAccessWindowAvailability(schedule, horizon);
      setStatus(statusCell, result.status, "pool");
      nextCell.textContent = hasSessions ? formatWindowNext(result) : result.next;
      row.dataset.windowRank = String(result.sortRank);
      row.classList.toggle("is-open", result.status === "AVAILABLE" || result.status === "LIMITED" || result.status === "ACCESS");
      return;
    }

    const accessLabel = row.getAttribute("data-access-label") || "";
    const { status, next } = hasSessions
      ? computeStatus(schedule, now, allowedTypes)
      : hasAccessHours
        ? computeAccessStatus(schedule, now)
      : accessLabel
        ? { status: "CHECK", next: "OFFICIAL SITE" }
        : { status: PLACEHOLDER, next: PLACEHOLDER };
    setStatus(statusCell, status, "pool");
    nextCell.textContent = next;
    row.dataset.windowRank = status === "OPEN" || status === "ACCESS" ? "0" : "3";
    row.classList.toggle("is-open", status === "OPEN" || status === "ACCESS");
  });

  const beachRows = root.querySelectorAll('table.board tbody tr[data-type="open_water"]');
  beachRows.forEach((row) => {
    const statusCell = cell(row, "status");
    const nextCell = cell(row, "next");
    if (!statusCell || !nextCell) return;
    if (horizon.kind === "window") {
      setStatus(statusCell, "OCEAN", "open_water");
      nextCell.textContent = "CHECK CONDITIONS";
      row.dataset.windowRank = "2";
      row.classList.remove("is-open");
    } else {
      setStatus(statusCell, "OCEAN", "open_water", "YEAR-ROUND");
      nextCell.textContent = PLACEHOLDER;
      row.dataset.windowRank = "0";
      row.classList.add("is-open");
    }
  });
}

// Sort rows: pools first, with open/available pools above closed pools, then
// beaches alphabetically at the bottom.
function sortRows(rows, horizon) {
  const decorated = rows.map((row, index) => {
    const isPool = row.getAttribute("data-type") === "pool";
    const statusCell = cell(row, "status");
    const statusText = statusCell?.dataset.statusValue || statusCell?.textContent.trim() || "";
    const isOpenPool = isPool && (statusText === "OPEN" || statusText === "ACCESS");
    const isUnverifiedPool = isPool && (statusText === "CHECK" || statusText === PLACEHOLDER);
    const label = cell(row, "spot")?.textContent.trim().toUpperCase() || "";
    const windowRank = Number(row.dataset.windowRank);
    return {
      row,
      index,
      beachRank: isPool ? 0 : 1,
      isOpenPool,
      isUnverifiedPool,
      windowRank: Number.isFinite(windowRank) ? windowRank : Number.POSITIVE_INFINITY,
      label,
    };
  });

  decorated.sort((a, b) => {
    if (a.beachRank !== b.beachRank) return a.beachRank - b.beachRank;
    if (horizon.kind === "window" && a.windowRank !== b.windowRank) {
      return a.windowRank - b.windowRank;
    }
    if (a.isOpenPool !== b.isOpenPool) return a.isOpenPool ? -1 : 1;
    if (a.isUnverifiedPool !== b.isUnverifiedPool) return a.isUnverifiedPool ? 1 : -1;
    if (a.label < b.label) return -1;
    if (a.label > b.label) return 1;
    return a.index - b.index;
  });

  return decorated.map((item) => item.row);
}

// Re-append rows in sorted order (appendChild on an existing node moves it).
function reorderDom(tbody, sortedRows) {
  sortedRows.forEach((row) => tbody.appendChild(row));
}

export function renderBoard(root, allowedTypes = null, now = nowInPacific()) {
  const tbody = root.querySelector("table.board tbody");
  if (!tbody) return;
  currentHorizon = resolveHorizon(currentHorizon.id, now);
  applyStatuses(root, now, allowedTypes);
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const sorted = sortRows(rows, currentHorizon);
  reorderDom(tbody, sorted);
  captureBaselineRanks(sorted, (row, rank) => {
    row.dataset.baselineRank = String(rank);
  });
}

function findHorizonMenu() {
  return document.querySelector("[data-horizon-menu]");
}

function closeHorizonMenu(control) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = findHorizonMenu();
  if (!button || !menu) return;
  menu.hidden = true;
  button.setAttribute("aria-expanded", "false");
}

function closeHorizonMenuAndFocusButton(control) {
  closeHorizonMenu(control);
  control.querySelector("[data-horizon-button]")?.focus();
}

function positionHorizonMenu(button) {
  const rect = button.getBoundingClientRect();
  const top = rect.bottom + 4;
  const isMobile = window.matchMedia("(max-width: 640px)").matches;
  const left = isMobile ? 16 : rect.left;
  const width = isMobile ? window.innerWidth - 32 : Math.max(rect.width, 256);
  const root = document.documentElement.style;
  root.setProperty("--horizon-menu-top", `${Math.round(top)}px`);
  root.setProperty("--horizon-menu-left", `${Math.round(left)}px`);
  root.setProperty("--horizon-menu-width", `${Math.round(width)}px`);
}

function openHorizonMenu(control) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = findHorizonMenu();
  if (!button || !menu) return;
  menu.hidden = false;
  positionHorizonMenu(button);
  button.setAttribute("aria-expanded", "true");
}

function horizonMenuItems(menu = findHorizonMenu()) {
  return menu ? Array.from(menu.querySelectorAll("button[role='menuitemradio']")) : [];
}

function focusHorizonMenuItem(direction = 1) {
  const items = horizonMenuItems();
  if (!items.length) return;
  const checkedIndex = items.findIndex((item) => item.getAttribute("aria-checked") === "true");
  const targetIndex = checkedIndex >= 0 ? checkedIndex : direction < 0 ? items.length - 1 : 0;
  items[targetIndex].focus();
}

function focusAdjacentHorizonItem(direction) {
  const items = horizonMenuItems();
  if (!items.length) return;
  const currentIndex = items.indexOf(document.activeElement);
  const nextIndex = currentIndex < 0
    ? direction < 0 ? items.length - 1 : 0
    : (currentIndex + direction + items.length) % items.length;
  items[nextIndex].focus();
}

function activateFocusedHorizonItem(control) {
  const item = document.activeElement;
  if (!item || item.getAttribute("role") !== "menuitemradio" || !item.value) return;
  applyHorizon(item.value);
  populateHorizonMenu(control, nowInPacific());
  closeHorizonMenuAndFocusButton(control);
}

function toggleHorizonMenu(control) {
  const menu = findHorizonMenu();
  if (!menu) return;
  if (menu.hidden) {
    openHorizonMenu(control);
    focusHorizonMenuItem();
  } else {
    closeHorizonMenu(control);
  }
}

function applyHorizon(id, now = nowInPacific()) {
  currentHorizon = resolveHorizon(id, now);
  writeHorizonParam(currentHorizon.id);
  applyHorizonChrome(currentHorizon);
  renderBoard(document);
  document.dispatchEvent(new CustomEvent("sf:horizon-changed", { detail: currentHorizon }));
}

function populateHorizonMenu(control, now) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = findHorizonMenu();
  if (!button || !menu) return;
  const options = getHorizonOptions(now);
  const selected = options.some((option) => option.id === currentHorizon.id)
    ? currentHorizon.id
    : "now";
  currentHorizon = resolveHorizon(selected, now);
  button.textContent = currentHorizon.label;
  applyHorizonChrome(currentHorizon);
  menu.replaceChildren(
    ...options.map((option) => {
      const el = document.createElement("button");
      el.type = "button";
      el.setAttribute("role", "menuitemradio");
      el.value = option.id;
      el.textContent = option.label;
      el.setAttribute("aria-checked", String(option.id === selected));
      el.addEventListener("click", () => {
        applyHorizon(option.id);
        populateHorizonMenu(control, nowInPacific());
        closeHorizonMenuAndFocusButton(control);
      });
      return el;
    }),
  );
  writeHorizonParam(currentHorizon.id);
}

function initHorizonControl(now) {
  const control = document.querySelector(".horizon-control");
  if (!control) {
    applyHorizonChrome(currentHorizon);
    return;
  }
  const button = control.querySelector("[data-horizon-button]");
  if (!button) return;
  populateHorizonMenu(control, now);

  button.addEventListener("click", () => {
    populateHorizonMenu(control, nowInPacific());
    toggleHorizonMenu(control);
  });

  button.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    populateHorizonMenu(control, nowInPacific());
    openHorizonMenu(control);
    focusHorizonMenuItem(event.key === "ArrowUp" ? -1 : 1);
  });

  document.addEventListener("click", (event) => {
    const menu = findHorizonMenu();
    if (control.contains(event.target)) return;
    if (menu && menu.contains(event.target)) return;
    closeHorizonMenu(control);
  });

  document.addEventListener("keydown", (event) => {
    const menu = findHorizonMenu();
    if (!menu || menu.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeHorizonMenuAndFocusButton(control);
      return;
    }
    if (!menu.contains(document.activeElement)) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusAdjacentHorizonItem(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusAdjacentHorizonItem(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      horizonMenuItems()[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      horizonMenuItems().at(-1)?.focus();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateFocusedHorizonItem(control);
    }
  });

  window.addEventListener("resize", () => {
    if (button.getAttribute("aria-expanded") === "true") positionHorizonMenu(button);
  });

  window.addEventListener("scroll", () => {
    if (button.getAttribute("aria-expanded") === "true") positionHorizonMenu(button);
  });

  document.querySelector("[data-time-banner-reset]")?.addEventListener("click", () => {
    applyHorizon("now");
    populateHorizonMenu(control, nowInPacific());
  });
}

function init() {
  // All SF pools are in Pacific; reason about "now" in PT regardless of the
  // visitor's browser timezone.
  const now = nowInPacific();
  initHorizonControl(now);
  renderBoard(document, null, now);
  // Signal to filters.js that status cells are populated and rows are in
  // their baseline (open-first, alphabetical) order.
  document.dispatchEvent(new CustomEvent("sf:status-applied"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
