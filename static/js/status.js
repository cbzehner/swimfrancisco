// Swim Francisco board status computation.
// Pure helpers live in ./helpers/board.mjs and are exercised by node:test;
// this file handles the DOM glue.

import { PLACEHOLDER, computeStatus, captureBaselineRanks, nowInPacific } from "./helpers/board.mjs";
import {
  computeWindowAvailability,
  formatHHMM,
  getHorizonOptions,
  resolveHorizon,
} from "./helpers/board.mjs";
import { PROGRAM_LABEL } from "./helpers/programs.mjs";

let currentHorizon = resolveHorizon(readHorizonParam(), nowInPacific());

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

// Apply computed STATUS/NEXT. Pools compute from their schedule; open-water
// rows have no schedule and are always accessible, so they render as OPEN
// with no NEXT — keeping a consistent visual rhythm with pool rows.
function applyStatuses(root, now, allowedTypes = null) {
  const horizon = currentHorizon.id === "now" ? resolveHorizon("now", now) : currentHorizon;
  const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
  poolRows.forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (cells.length < 4) return;
    const schedule = readSchedule(row);
    if (horizon.kind === "window") {
      const result = computeWindowAvailability(schedule, horizon, allowedTypes);
      cells[2].textContent = result.status;
      cells[3].textContent = formatWindowNext(result);
      row.dataset.windowRank = String(result.sortRank);
      row.classList.toggle("is-open", result.status === "AVAILABLE" || result.status === "LIMITED");
      return;
    }

    const { status, next } = schedule
      ? computeStatus(schedule, now, allowedTypes)
      : { status: PLACEHOLDER, next: PLACEHOLDER };
    cells[2].textContent = status;
    cells[3].textContent = next;
    row.dataset.windowRank = status === "OPEN" ? "0" : "3";
    row.classList.toggle("is-open", status === "OPEN");
  });

  const beachRows = root.querySelectorAll('table.board tbody tr[data-type="open_water"]');
  beachRows.forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (cells.length < 4) return;
    if (horizon.kind === "window") {
      cells[2].textContent = "ACCESS";
      cells[3].textContent = "CHECK CONDITIONS";
      row.dataset.windowRank = "2";
      row.classList.remove("is-open");
    } else {
      cells[2].textContent = "OPEN";
      cells[3].textContent = PLACEHOLDER;
      row.dataset.windowRank = "0";
      row.classList.add("is-open");
    }
  });
}

// Sort rows: open pools first, then everything else alphabetically by SPOT label.
function sortRows(rows, horizon) {
  const decorated = rows.map((row, index) => {
    const cells = row.querySelectorAll("td");
    const isPool = row.getAttribute("data-type") === "pool";
    const statusText = cells.length > 2 ? cells[2].textContent.trim() : "";
    const isOpenPool = isPool && statusText === "OPEN";
    const label = cells.length > 0 ? cells[0].textContent.trim().toUpperCase() : "";
    const windowRank = Number(row.dataset.windowRank);
    return {
      row,
      index,
      isOpenPool,
      windowRank: Number.isFinite(windowRank) ? windowRank : Number.POSITIVE_INFINITY,
      label,
    };
  });

  decorated.sort((a, b) => {
    if (horizon.kind === "window" && a.windowRank !== b.windowRank) {
      return a.windowRank - b.windowRank;
    }
    if (a.isOpenPool !== b.isOpenPool) return a.isOpenPool ? -1 : 1;
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

function closeHorizonMenu(control) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = control.querySelector("[data-horizon-menu]");
  if (!button || !menu) return;
  menu.hidden = true;
  button.setAttribute("aria-expanded", "false");
}

function openHorizonMenu(control) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = control.querySelector("[data-horizon-menu]");
  if (!button || !menu) return;
  menu.hidden = false;
  button.setAttribute("aria-expanded", "true");
}

function toggleHorizonMenu(control) {
  const menu = control.querySelector("[data-horizon-menu]");
  if (!menu) return;
  if (menu.hidden) {
    openHorizonMenu(control);
  } else {
    closeHorizonMenu(control);
  }
}

function applyHorizon(id, now = nowInPacific()) {
  currentHorizon = resolveHorizon(id, now);
  writeHorizonParam(currentHorizon.id);
  renderBoard(document);
  document.dispatchEvent(new CustomEvent("sf:horizon-changed", { detail: currentHorizon }));
}

function populateHorizonMenu(control, now) {
  const button = control.querySelector("[data-horizon-button]");
  const menu = control.querySelector("[data-horizon-menu]");
  if (!button || !menu) return;
  const options = getHorizonOptions(now);
  const selected = options.some((option) => option.id === currentHorizon.id)
    ? currentHorizon.id
    : "now";
  currentHorizon = resolveHorizon(selected, now);
  button.textContent = currentHorizon.label;
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
        closeHorizonMenu(control);
      });
      return el;
    }),
  );
  writeHorizonParam(currentHorizon.id);
}

function initHorizonControl(now) {
  const control = document.querySelector(".horizon-control");
  if (!control) return;
  const button = control.querySelector("[data-horizon-button]");
  if (!button) return;
  populateHorizonMenu(control, now);

  button.addEventListener("click", () => {
    populateHorizonMenu(control, nowInPacific());
    toggleHorizonMenu(control);
  });

  document.addEventListener("click", (event) => {
    if (!control.contains(event.target)) closeHorizonMenu(control);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeHorizonMenu(control);
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
