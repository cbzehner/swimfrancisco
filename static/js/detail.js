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
  statusLabel,
  statusNextLabel,
  t,
} from "./helpers/i18n.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { capture } from "./helpers/analytics.mjs";

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

function presentDetail(schedule, now) {
  if (scheduleHasSessions(schedule, now) || !scheduleHasAccessHours(schedule, now)) {
    const result = computeDetailStatus(schedule, now);
    const removeToday = new Set([
      "CLOSED_TODAY",
      "NOT_VERIFIED",
      "NO_DROPIN_WEEK",
      "NO_DROPIN_TODAY",
    ]);
    return {
      family: "sessions",
      kind: result.kind,
      statusText: formatStatusLine(result),
      nextText: formatNextLine(result),
      today: removeToday.has(result.kind) ? "remove" : "decorate",
    };
  }
  const result = computeAccessStatus(schedule, now);
  return {
    family: "access",
    status: result.status,
    statusText: statusLabel(result.status),
    nextText: statusNextLabel(result),
    today: "keep",
  };
}

function applyStatusSlab(root, schedule, now) {
  const view = presentDetail(schedule, now);
  const statusEl = root.querySelector('[data-field="status"]');
  const nextEl = root.querySelector('[data-field="next"]');
  if (statusEl) statusEl.textContent = view.statusText;
  if (nextEl) nextEl.textContent = view.nextText;
  return view;
}

function decorateTodayBlock(root, now, view) {
  const block = root.querySelector(".today-block");
  if (!block) return;
  if (view.today === "remove") {
    block.remove();
    return;
  }
  if (view.today === "keep") return;

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

// Outbound link tracking — the clearest signal that a visit "converted" into
// action (booking on the official site, getting directions). Independent of
// the schedule slab so it still fires on spots with no schedule. `destination`
// uses the template's explicit data-outbound where present, then a maps-URL
// sniff, then "external". Slug comes from the path so we don't depend on any
// one element being rendered.
function spotSlug() {
  const match = window.location.pathname.match(/\/spots\/([^/]+)\//);
  return match ? match[1] : "";
}

function classifyOutbound(link) {
  const explicit = link.getAttribute("data-outbound");
  if (explicit) return explicit;
  const href = link.getAttribute("href") || "";
  if (/maps\.apple\.com|google\.[^/]+\/maps/.test(href)) return "directions";
  return "external";
}

function initOutboundTracking() {
  const slug = spotSlug();
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[target="_blank"]');
    if (!link) return;
    capture("outbound_click", {
      slug,
      destination: classifyOutbound(link),
      href: link.getAttribute("href") || "",
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    init();
    initOutboundTracking();
  });
} else {
  init();
  initOutboundTracking();
}
