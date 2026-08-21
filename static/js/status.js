// Swim Francisco board status computation.
// Pure helpers live in ./helpers/board.mjs and are exercised by node:test;
// this file handles the DOM glue.

import {
  OPEN_STATUSES,
  PLACEHOLDER,
  captureBaselineRanks,
  computeAccessStatus,
  computeAccessWindowAvailability,
  computeStatus,
  computeStatusRunKey,
  computeWindowAvailability,
  formatHHMM,
  getHorizonOptions,
  readScheduleAttribute,
  resolveHorizon,
  scheduleHasAccessHours,
  scheduleHasSessions,
} from "./helpers/board.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import {
  programLabel,
  statusLabel,
  statusNextLabel,
  t,
} from "./helpers/i18n.mjs";
import { capture } from "./helpers/analytics.mjs";
import { initHorizonMenu } from "./helpers/horizon-menu.mjs";

let currentHorizon = resolveHorizon(readHorizonParam(), pacificWallClockDate());

const HORIZON_TITLES = {
  "this-morning": ["horizon_fog_lift", "FOG-LIFT WINDOW"],
  "this-afternoon": ["horizon_lunch", "LUNCH BREAK LANES"],
  "this-evening": ["horizon_after_work", "AFTER-WORK WATER"],
  "tomorrow-morning": ["horizon_set_alarm", "SET THE ALARM"],
  "tomorrow-afternoon": ["horizon_clear_calendar", "CLEAR THE CALENDAR"],
  "tomorrow-evening": ["horizon_golden_hour", "GOLDEN HOUR TOMORROW"],
};

const HORIZON_LABEL_KEYS = {
  now: ["now", "Now"],
  "this-morning": ["horizon_this_morning", "This Morning"],
  "this-afternoon": ["horizon_this_afternoon", "This Afternoon"],
  "this-evening": ["horizon_this_evening", "This Evening"],
  "tomorrow-morning": ["horizon_tomorrow_morning", "Tomorrow Morning"],
  "tomorrow-afternoon": ["horizon_tomorrow_afternoon", "Tomorrow Afternoon"],
  "tomorrow-evening": ["horizon_tomorrow_evening", "Tomorrow Evening"],
};

function horizonLabel(horizon) {
  const [key, fallback] = HORIZON_LABEL_KEYS[horizon?.id] || [];
  return key ? t(key, fallback) : horizon?.label || "";
}

function currentTimeTitle(now = pacificWallClockDate()) {
  const hour = now.getHours();
  if (hour < 5) return t("horizon_night_swim", "NIGHT SWIM");
  if (hour < 10) return t("horizon_before_breakfast", "BEFORE BREAKFAST");
  if (hour < 14) return t("horizon_lunch", "LUNCH BREAK LANES");
  if (hour < 17) return t("horizon_post_fog", "POST-FOG SWIM");
  if (hour < 21) return t("horizon_after_work", "AFTER-WORK WATER");
  return t("horizon_night_swim", "NIGHT SWIM");
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
  const titleSource = HORIZON_TITLES[horizon.id];
  const title = isNow
    ? currentTimeTitle()
    : titleSource
      ? t(titleSource[0], titleSource[1])
      : horizonLabel(horizon).toUpperCase();
  const label = horizonLabel(horizon);
  document.querySelectorAll("[data-horizon-title]").forEach((node) => {
    node.textContent = `·${title}·`;
  });
  document.querySelectorAll("[data-horizon-button]").forEach((node) => {
    node.textContent = isNow ? t("now", "Now") : label;
  });
  document.querySelectorAll("[data-horizon-stamp-label]").forEach((node) => {
    node.textContent = isNow ? t("open_now", "OPEN NOW") : label.toUpperCase();
  });

  const banner = document.querySelector("[data-time-banner]");
  if (!banner) return;
  banner.hidden = isNow;
  const bannerLabel = banner.querySelector("[data-time-banner-label]");
  if (bannerLabel) bannerLabel.textContent = isNow ? t("right_now", "Right now") : horizonLabel(horizon);
}

export function getCurrentHorizon() {
  return currentHorizon;
}

function formatWindowNext(result) {
  const session = result.bestSession;
  if (!session) return statusNextLabel(result, PLACEHOLDER);
  const program = programLabel(session.type);
  return `${program} ${formatHHMM(session.start)}\u2013${formatHHMM(session.end)}`;
}

function cell(row, name) {
  return row.querySelector(`[data-cell="${name}"]`);
}

function statusClass(status, type) {
  if (type === "open_water" || status === "OCEAN") return "is-ocean";
  if (OPEN_STATUSES.has(status)) return "is-open";
  if (status === "CHECK") return "is-info";
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
  pill.textContent = statusLabel(status);
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

// Guards the expensive part of applyStatuses (parsing every row's
// data-schedule and running computeStatus/computeWindowAvailability) against
// re-running when nothing that could change its output has changed. status.js
// calls renderBoard on load, on the minute tick, and on horizon change —
// all cases where time or horizon genuinely moved. filters.js also calls
// renderBoard on every filter/sort click so it can pick up the active
// program-type filter, but most of those clicks (memberships, sort toggles,
// a repeated click with the same type selected) leave (horizon, now-minute,
// allowedTypes) unchanged, so the recompute would just re-derive and re-write
// the same values. See computeStatusRunKey for what's actually significant.
let lastStatusRunKey = null;

// Apply computed STATUS/NEXT. Pools compute from their schedule; open-water
// rows have no schedule and are always accessible, so they render as OCEAN.
function applyStatuses(root, now, allowedTypes = null) {
  const horizon = currentHorizon.id === "now" ? resolveHorizon("now", now) : currentHorizon;
  const runKey = computeStatusRunKey(horizon, now, allowedTypes);
  if (runKey === lastStatusRunKey) return;
  lastStatusRunKey = runKey;
  const poolRows = root.querySelectorAll('table.board tbody tr[data-type="pool"]');
  poolRows.forEach((row) => {
    const statusCell = cell(row, "status");
    const nextCell = cell(row, "next");
    if (!statusCell || !nextCell) return;
    const schedule = readScheduleAttribute(row);
    const asOf = horizon.kind === "window" ? horizon.date : now;
    const hasSessions = scheduleHasSessions(schedule, asOf);
    const hasAccessHours = scheduleHasAccessHours(schedule, asOf);
    if (horizon.kind === "window") {
      const result = hasSessions
        ? computeWindowAvailability(schedule, horizon, allowedTypes)
        : computeAccessWindowAvailability(schedule, horizon);
      setStatus(statusCell, result.status, "pool");
      nextCell.textContent = hasSessions ? formatWindowNext(result) : statusNextLabel(result, PLACEHOLDER);
      row.dataset.windowRank = String(result.sortRank);
      row.classList.toggle("is-open", OPEN_STATUSES.has(result.status));
      return;
    }

    const accessMode = row.getAttribute("data-access-mode") || "public";
    const showsCheck = accessMode !== "public";
    const result = hasSessions
      ? computeStatus(schedule, now, allowedTypes)
      : hasAccessHours
        ? computeAccessStatus(schedule, now)
      : showsCheck
        ? { status: "CHECK", next: "OFFICIAL SITE", nextKind: "official_site", nextArgs: {} }
        : { status: PLACEHOLDER, next: PLACEHOLDER };
    setStatus(statusCell, result.status, "pool");
    nextCell.textContent = statusNextLabel(result, PLACEHOLDER);
    row.dataset.windowRank = result.status === "OPEN" || result.status === "ACCESS" ? "0" : "3";
    row.classList.toggle("is-open", OPEN_STATUSES.has(result.status));
  });

  const beachRows = root.querySelectorAll('table.board tbody tr[data-type="open_water"]');
  beachRows.forEach((row) => {
    const statusCell = cell(row, "status");
    const nextCell = cell(row, "next");
    if (!statusCell || !nextCell) return;
    if (horizon.kind === "window") {
      setStatus(statusCell, "OCEAN", "open_water");
      nextCell.textContent = t("status_check_conditions", "CHECK CONDITIONS");
      row.dataset.windowRank = "2";
      row.classList.remove("is-open");
    } else {
      setStatus(statusCell, "OCEAN", "open_water", t("status_year_round", "YEAR-ROUND"));
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

export function renderBoard(root, allowedTypes = null, now = pacificWallClockDate()) {
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

function applyHorizon(id, now = pacificWallClockDate()) {
  currentHorizon = resolveHorizon(id, now);
  writeHorizonParam(currentHorizon.id);
  applyHorizonChrome(currentHorizon);
  renderBoard(document);
  document.dispatchEvent(new CustomEvent("sf:horizon-changed", { detail: currentHorizon }));
}

function populateHorizonMenu(horizonMenu, now) {
  const options = getHorizonOptions(now);
  const selected = options.some((option) => option.id === currentHorizon.id)
    ? currentHorizon.id
    : "now";
  currentHorizon = resolveHorizon(selected, now);
  applyHorizonChrome(currentHorizon);
  horizonMenu.render({
    buttonLabel: horizonLabel(currentHorizon),
    items: options.map((option) => ({
      id: option.id,
      label: horizonLabel(option),
      selected: option.id === selected,
    })),
  });
  writeHorizonParam(currentHorizon.id);
}

function initHorizonControl(now) {
  const control = document.querySelector(".horizon-control");
  if (!control) {
    applyHorizonChrome(currentHorizon);
    return;
  }
  const horizonMenu = initHorizonMenu(control, {
    refresh: () => populateHorizonMenu(horizonMenu, pacificWallClockDate()),
    onSelect: (id, source) => {
      applyHorizon(id);
      if (source === "click") capture("filter_applied", { trigger: "when", when: id });
      populateHorizonMenu(horizonMenu, pacificWallClockDate());
    },
  });
  if (!horizonMenu) return;
  populateHorizonMenu(horizonMenu, now);

  document.querySelector("[data-time-banner-reset]")?.addEventListener("click", () => {
    applyHorizon("now");
    capture("filter_applied", { trigger: "when", when: "now" });
    populateHorizonMenu(horizonMenu, pacificWallClockDate());
  });
}

const REFRESH_INTERVAL_MS = 60_000;

// Intra-day refresh. Day tick-over is server-rendered by the 00:05 PT
// rebuild; client JS owns the minute-level updates within the day, so a tab
// left open doesn't keep asserting "OPEN" hours after closing. filters.js
// listens for sf:board-refreshed and re-applies filter/sort state on top of
// the fresh statuses; conditions.js refreshes the bulletin clock and count.
function refreshBoard() {
  const now = pacificWallClockDate();
  currentHorizon = resolveHorizon(currentHorizon.id, now);
  applyHorizonChrome(currentHorizon);
  renderBoard(document, null, now);
  document.dispatchEvent(new CustomEvent("sf:board-refreshed"));
}

function startIntraDayRefresh() {
  setInterval(refreshBoard, REFRESH_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshBoard();
  });
}

// Whole-row navigation. The spot link's CSS overlay covers only its own cell
// (a row-wide overlay is impossible cross-engine: WebKit doesn't make
// <tr position:relative> a containing block, so it escaped the row and
// swallowed clicks on the controls). Clicks elsewhere on a row follow the
// row's spot link; real links/buttons and modified clicks pass through.
function initRowNavigation(tbody) {
  tbody.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (event.target.closest("a, button")) return;
    if (window.getSelection && String(window.getSelection())) return;
    const row = event.target.closest("tr");
    const href = row?.querySelector('[data-cell="spot"] a')?.getAttribute("href");
    if (href) {
      captureSpotOpened(row, "board_row");
      window.location.assign(href);
    }
  });
  // Direct clicks on the spot link itself bypass the overlay branch above
  // (it ignores clicks on <a>), so capture those here. Modified/middle clicks
  // that open a new tab still register intent — that's worth counting.
  tbody.addEventListener("click", (event) => {
    const link = event.target.closest('[data-cell="spot"] a');
    if (link) captureSpotOpened(link.closest("tr"), "board_link");
  });
}

// Record a spot-detail open from the board, keyed by slug (locale-proof,
// unlike the autocaptured link text). `status_at_click` lets us see whether
// people open spots that are currently open or closed.
function captureSpotOpened(row, source) {
  if (!row) return;
  const statusCell = row.querySelector('[data-cell="status"]');
  capture("spot_opened", {
    slug: row.getAttribute("data-slug") || "",
    spot_type: row.getAttribute("data-type") || "",
    source,
    status_at_click:
      statusCell?.dataset.statusValue ||
      statusCell?.querySelector(".status-pill")?.textContent.trim() ||
      "",
  });
}

function init() {
  // All SF pools are in Pacific; reason about "now" in PT regardless of the
  // visitor's browser timezone.
  const now = pacificWallClockDate();
  initHorizonControl(now);
  renderBoard(document, null, now);
  const tbody = document.querySelector("table.board tbody");
  if (tbody) initRowNavigation(tbody);
  // Signal to filters.js that status cells are populated and rows are in
  // their baseline (open-first, alphabetical) order.
  document.dispatchEvent(new CustomEvent("sf:status-applied"));
  if (document.querySelector("table.board")) startIntraDayRefresh();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
