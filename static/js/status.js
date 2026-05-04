// Swim Francisco board status computation.
// Pure helpers live in ./helpers/board.mjs and are exercised by node:test;
// this file handles the DOM glue.

import { PLACEHOLDER, computeStatus, captureBaselineRanks, nowInPacific } from "./helpers/board.mjs";

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

// Apply computed STATUS/NEXT. Pools compute from their schedule; open-water
// rows have no schedule and are always accessible, so they render as OPEN
// with no NEXT — keeping a consistent visual rhythm with pool rows.
function applyStatuses(root, now, allowedTypes = null) {
  const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
  poolRows.forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (cells.length < 4) return;
    const schedule = readSchedule(row);
    const { status, next } = schedule
      ? computeStatus(schedule, now, allowedTypes)
      : { status: PLACEHOLDER, next: PLACEHOLDER };
    cells[2].textContent = status;
    cells[3].textContent = next;
    row.classList.toggle("is-open", status === "OPEN");
  });

  const beachRows = root.querySelectorAll('table.board tbody tr[data-type="open_water"]');
  beachRows.forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (cells.length < 4) return;
    cells[2].textContent = "OPEN";
    cells[3].textContent = PLACEHOLDER;
    row.classList.add("is-open");
  });
}

// Sort rows: open pools first, then everything else alphabetically by SPOT label.
function sortRows(rows) {
  const decorated = rows.map((row, index) => {
    const cells = row.querySelectorAll("td");
    const isPool = row.getAttribute("data-type") === "pool";
    const statusText = cells.length > 2 ? cells[2].textContent.trim() : "";
    const isOpenPool = isPool && statusText === "OPEN";
    const label = cells.length > 0 ? cells[0].textContent.trim().toUpperCase() : "";
    return { row, index, isOpenPool, label };
  });

  decorated.sort((a, b) => {
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
  applyStatuses(root, now, allowedTypes);
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const sorted = sortRows(rows);
  reorderDom(tbody, sorted);
  captureBaselineRanks(sorted, (row, rank) => {
    row.dataset.baselineRank = String(rank);
  });
}

function init() {
  // All SF pools are in Pacific; reason about "now" in PT regardless of the
  // visitor's browser timezone.
  renderBoard(document);
  // Signal to filters.js that status cells are populated and rows are in
  // their baseline (open-first, alphabetical) order.
  document.dispatchEvent(new CustomEvent("sf:status-applied"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
