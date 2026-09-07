// Swim Francisco pool detail page.
// Reads the schedule embedded in .detail-root[data-schedule], hydrates the
// status slab, today's sessions, and the current weekday marker. Pure
// computation lives in ./helpers/board.mjs (exercised by node:test).

import {
  computeAccessStatus,
  computeDetailStatus,
  formatHHMM,
  parseHHMM,
  readScheduleAttribute,
  resolveActiveSchedule,
  scheduleHasAccessHours,
  scheduleHasSessions,
  sessionsForDate,
} from "./helpers/board.mjs";
import {
  closureReasonLabel,
  dayFullLabel,
  dayShortLabel,
  formatLocalizedISODate,
  programLabel,
  statusLabel,
  statusNextLabel,
  t,
} from "./helpers/i18n.mjs";
import { pacificWallClockDate } from "./helpers/pacific.mjs";
import { isDropInType } from "./helpers/programs.mjs";
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
  if (result.kind === "NOT_VERIFIED" && result.closureTransitionDate) return formatClosureSuffix(result);
  if (!result.nextDropIn) return "—";
  const program = programLabel(result.nextDropIn.program);
  const day = dayShortLabel(result.nextDropIn.day);
  return `${program} · ${day} ${formatHHMM(result.nextDropIn.start)}`;
}

function presentDetail(schedule, now) {
  if (scheduleHasSessions(schedule, now) || !scheduleHasAccessHours(schedule, now)) {
    const result = computeDetailStatus(schedule, now);
    const hideToday = new Set([
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
      today: hideToday.has(result.kind) ? "hide" : "decorate",
    };
  }
  const result = computeAccessStatus(schedule, now);
  return {
    family: "access",
    status: result.status,
    statusText: statusLabel(result.status),
    nextText: statusNextLabel(result),
    today: "hide",
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

function renderTodayBlock(root, schedule, now, view, day) {
  const block = root.querySelector(".today-block");
  if (!block) return;
  const sessions = sessionsForDate(schedule, now).filter((session) => isDropInType(session.type));
  block.dataset.day = day;
  block.hidden = view.today === "hide" || sessions.length === 0;
  const list = block.querySelector(".today-block-list");
  list.replaceChildren();
  if (block.hidden) return;
  const heading = block.querySelector(".today-block-heading");
  if (heading) heading.textContent = `${t("today_caps", "TODAY")} · ${dayFullLabel(day)}`;
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const nextSession = sessions.find(({ start }) => start > nowMinutes);
  for (const session of sessions) {
    const { start, end, type } = session;
    const row = document.createElement("li");
    row.dataset.start = formatHHMM(start);
    row.dataset.end = formatHHMM(end);
    row.dataset.program = type;
    if (session.physical_pool) row.dataset.pool = session.physical_pool;
    const label = start <= nowMinutes && nowMinutes < end
      ? t("status_now", "NOW")
      : session === nextSession ? t("next", "NEXT") : "";
    for (const [className, text] of [
      ["time", `${formatHHMM(start)}–${formatHHMM(end)}`],
      ["program", programLabel(type) + (session.physical_pool ? ` (${session.physical_pool})` : "")],
      ["row-label", label],
    ]) {
      const span = document.createElement("span");
      span.className = className;
      span.textContent = text;
      row.append(span);
    }
    list.append(row);
  }
}

const REFRESH_INTERVAL_MS = 60_000;

function selectScheduleWindow(root, active) {
  const current = root.querySelector("[data-schedule-window]");
  const key = `${active?.effective_start || ""}/${active?.effective_end || ""}`;
  if (!current || current.dataset.scheduleWindow === key) return;
  const templates = [...root.querySelectorAll("template[data-schedule-window-template]")];
  const selected = templates.find((template) => template.dataset.scheduleWindowTemplate === key);
  if (!selected) return;
  current.replaceWith(selected.content.firstElementChild.cloneNode(true));
  if (!templates.some((template) => template.dataset.scheduleWindowTemplate === current.dataset.scheduleWindow)) {
    const previous = document.createElement("template");
    previous.dataset.scheduleWindowTemplate = current.dataset.scheduleWindow;
    previous.content.append(current);
    root.append(previous);
  }
}

function refreshWindowDates(root, active, now) {
  const isoDate = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const today = isoDate(now);
  const windowEnd = new Date(now);
  windowEnd.setDate(windowEnd.getDate() + 14);
  for (const section of root.querySelectorAll("[data-dated-notices]")) {
    for (const notice of section.querySelectorAll("[data-notice-start]")) {
      const { noticeStart: start, noticeEnd: end } = notice.dataset;
      notice.hidden = start > isoDate(windowEnd) || end < today
        || end < (active?.effective_start || "0001-01-01") || start > (active?.effective_end || "9999-12-31");
    }
    section.hidden = ![...section.children].some((notice) => !notice.hidden);
  }
  const effective = root.querySelector(".meta-effective");
  if (effective && active?.effective_start) {
    effective.textContent = `${t("schedule_effective_from", "Schedule effective from")} ${formatLocalizedISODate(active.effective_start)}`
      + (active.effective_end ? ` ${t("to", "to")} ${formatLocalizedISODate(active.effective_end)}` : "");
  }
}

function refresh(root, schedule) {
  const now = pacificWallClockDate();
  const active = resolveActiveSchedule(schedule, now);
  selectScheduleWindow(root, active);
  refreshWindowDates(root, active, now);
  const day = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][now.getDay()];
  const result = applyStatusSlab(root, schedule, now);
  renderTodayBlock(root, schedule, now, result, day);
  for (const cell of root.querySelectorAll(".weekly-grid [data-day]")) {
    if (cell.dataset.day === day) cell.dataset.today = "true";
    else delete cell.dataset.today;
  }
}

function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readScheduleAttribute(root);
  if (!schedule) return;
  // Every SF pool is in Pacific — reason about time in PT regardless of the
  // visitor's browser timezone or the date this static page was built.
  refresh(root, schedule);
  // Refresh the date as well as the time in long-lived and restored tabs.
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
