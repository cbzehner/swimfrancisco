// SwimFrancisco departure-board status computation.
// Pure helpers live in ./helpers/board.mjs and are exercised by node:test;
// this file handles the DOM glue.

import { PLACEHOLDER, computeStatus, captureBaselineRanks } from "./helpers/board.mjs";

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

// Apply computed STATUS/NEXT to every pool row. Open-water rows are skipped.
function applyStatuses(root, now) {
  const rows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
  rows.forEach((row) => {
    const cells = row.querySelectorAll("td");
    if (cells.length < 4) return;
    const schedule = readSchedule(row);
    const { status, next } = schedule
      ? computeStatus(schedule, now)
      : { status: PLACEHOLDER, next: PLACEHOLDER };
    cells[2].textContent = status;
    cells[3].textContent = next;
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

function init() {
  const tbody = document.querySelector("table.board tbody");
  if (!tbody) return;
  const now = new Date();
  applyStatuses(document, now);
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const sorted = sortRows(rows);
  reorderDom(tbody, sorted);
  // Stamp each row with its baseline-sort rank so filters.js can restore
  // this order after Near Me (which resorts by distance) turns off.
  captureBaselineRanks(sorted, (row, rank) => {
    row.dataset.baselineRank = String(rank);
  });
  // Signal to filters.js that status cells are populated and rows are in
  // their baseline (open-first, alphabetical) order.
  document.dispatchEvent(new CustomEvent("sf:status-applied"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
