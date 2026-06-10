// Swim Francisco pool detail page.
// Reads the schedule embedded in .detail-root[data-schedule], hydrates the
// status slab, and decorates the today block. Pure computation lives in
// ./helpers/board.mjs (exercised by node:test). Today's column marker is
// server-rendered by the daily rebuild.

import {
  computeAccessStatus,
  computeDetailStatus,
  formatHHMM,
  parseHHMM,
  readScheduleAttribute,
  scheduleHasAccessHours,
  scheduleHasSessions,
} from "./helpers/board.mjs";
import {
  closureReasonLabel,
  dayShortLabel,
  formatLocalizedISODate,
  programLabel,
  statusNextLabel,
  t,
} from "./helpers/i18n.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";

function formatClosureSuffix(result) {
  if (result.closureKind === "PRE_SEASON" && result.closureTransitionDate) {
    return `${t("status_schedule_starts", "Schedule starts")} ${formatLocalizedISODate(result.closureTransitionDate)}`.toUpperCase();
  }
  if (result.closureKind === "POST_SEASON" && result.closureTransitionDate) {
    return `${t("status_schedule_ended", "Schedule ended")} ${formatLocalizedISODate(result.closureTransitionDate)}`.toUpperCase();
  }
  if (result.closureStartTime && result.closureEndTime) {
    return `${t("status_closed_window", "Closed")} ${result.closureStartTime}\u2013${result.closureEndTime}`.toUpperCase();
  }
  return result.closureReason ? closureReasonLabel(result.closureReasonCode, result.closureReason).toUpperCase() : "";
}

function formatStatusLine(result) {
  switch (result.kind) {
    case "OPEN": {
      const programs = result.activePrograms.map((p) => programLabel(p)).join(" + ");
      return `${t("status_open", "OPEN")} — ${programs} ${t("status_until", "UNTIL")} ${formatHHMM(result.activeUntil)}`;
    }
    case "CLOSED_TODAY": {
      const suffix = formatClosureSuffix(result);
      return suffix
        ? `${t("status_closed_today", "CLOSED TODAY")} — ${suffix}`
        : t("status_closed_today", "CLOSED TODAY");
    }
    case "CLOSED_HOURS":
      return t("status_closed", "CLOSED");
    case "NO_DROPIN_TODAY":
      return t("status_no_drop_in_today", "NO DROP-IN TODAY");
    case "NOT_VERIFIED":
      return t("status_not_verified", "SCHEDULE NOT YET VERIFIED");
    case "NO_DROPIN_WEEK":
      return t("status_no_drop_in_week", "NO DROP-IN THIS WEEK");
    default:
      return "—";
  }
}

function formatNextLine(result) {
  if (!result.nextDropIn) return "—";
  const program = programLabel(result.nextDropIn.program);
  const day = dayShortLabel(result.nextDropIn.day);
  return `${program} · ${day} ${formatHHMM(result.nextDropIn.start)}`;
}

function applyStatusSlab(root, schedule, now) {
  const result = scheduleHasSessions(schedule, now) || !scheduleHasAccessHours(schedule, now)
    ? computeDetailStatus(schedule, now)
    : computeAccessStatus(schedule, now);
  const statusEl = root.querySelector('[data-field="status"]');
  const nextEl = root.querySelector('[data-field="next"]');
  if (statusEl) statusEl.textContent = result.kind ? formatStatusLine(result) : result.status;
  if (nextEl) nextEl.textContent = result.kind ? formatNextLine(result) : statusNextLabel(result);
  return result;
}

function decorateTodayBlock(root, now, statusResult) {
  const suppressedKinds = new Set([
    "CLOSED_TODAY",
    "NOT_VERIFIED",
    "NO_DROPIN_WEEK",
    "NO_DROPIN_TODAY",
  ]);

  const block = root.querySelector(".today-block");
  if (!block) return;
  if (suppressedKinds.has(statusResult.kind)) {
    block.remove();
    return;
  }

  const rows = block.querySelectorAll(".today-block-list li");
  if (rows.length === 0) return;

  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const parsedRows = Array.from(rows, (row) => {
    const start = parseHHMM(row.getAttribute("data-start"));
    const end = parseHHMM(row.getAttribute("data-end"));
    return { row, start, end };
  });

  const nextRow = parsedRows.find(({ start, end }) => (
    start !== null && end !== null && start > nowMinutes
  ))?.row || null;

  for (const { row, start, end } of parsedRows) {
    if (start === null || end === null) continue;
    const timeEl = row.querySelector(".time");
    const labelEl = row.querySelector(".row-label");
    if (!timeEl || !labelEl) continue;

    // Stash the server-rendered label once so re-running on the minute tick
    // can clear a NOW/NEXT marker that no longer applies.
    if (labelEl.dataset.baseLabel === undefined) {
      labelEl.dataset.baseLabel = labelEl.textContent;
    }

    if (start <= nowMinutes && nowMinutes < end) {
      labelEl.textContent = t("status_now", "NOW");
    } else if (row === nextRow) {
      labelEl.textContent = t("next", "NEXT");
    } else {
      labelEl.textContent = labelEl.dataset.baseLabel;
    }
  }
}

const REFRESH_INTERVAL_MS = 60_000;

function refresh(root, schedule) {
  const now = pacificWallClockDate();
  const result = applyStatusSlab(root, schedule, now);
  decorateTodayBlock(root, now, result);
}

function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readScheduleAttribute(root);
  if (!schedule) return;
  // Every SF pool is in Pacific — reason about time in PT regardless of the
  // visitor's browser timezone, so the server-rendered today block and the
  // client-side "NOW" marker agree for non-PT visitors.
  refresh(root, schedule);
  // Intra-day refresh: keep the status slab and NOW/NEXT markers honest in
  // a long-lived tab. Day tick-over is server-rendered by the 00:05 PT
  // rebuild; the client owns only minute-level updates within the day.
  setInterval(() => refresh(root, schedule), REFRESH_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh(root, schedule);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
