// SwimFrancisco pool detail page.
// Reads the schedule embedded in .detail-root[data-schedule], hydrates the
// status slab, decorates the today block, marks today's column in the weekly
// grid, and updates the freshness dot. Pure computation lives in
// ./helpers/board.mjs (exercised by node:test).

import {
  computeDetailStatus,
  DAY_KEYS,
  formatHHMM,
  freshnessLabel,
  parseHHMM,
} from "./helpers/board.mjs";

const PROGRAM_LABEL = {
  lap_swim: "LAP",
  family_swim: "FAMILY",
  senior_swim: "SENIOR",
};

const DAY_LABEL_SHORT = {
  sunday: "SUN",
  monday: "MON",
  tuesday: "TUE",
  wednesday: "WED",
  thursday: "THU",
  friday: "FRI",
  saturday: "SAT",
};

function parseHHMMSafe(value) {
  return parseHHMM(typeof value === "string" ? value : "");
}

function readSchedule(root) {
  const raw = root.getAttribute("data-schedule");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

function formatStatusLine(result) {
  switch (result.kind) {
    case "OPEN": {
      const programs = result.activePrograms.map((p) => PROGRAM_LABEL[p] || p.toUpperCase()).join(" + ");
      return `OPEN — ${programs} UNTIL ${formatHHMM(result.activeUntil)}`;
    }
    case "LESSONS":
      return `LESSONS UNTIL ${formatHHMM(result.activeLessonsUntil)}`;
    case "CLOSED_TODAY":
      return result.closureReason
        ? `CLOSED TODAY — ${result.closureReason.toUpperCase()}`
        : "CLOSED TODAY";
    case "CLOSED_HOURS":
    case "NO_DROPIN_TODAY": {
      if (!result.nextDropIn) return "CLOSED";
      const program = PROGRAM_LABEL[result.nextDropIn.program] || result.nextDropIn.program.toUpperCase();
      const day = DAY_LABEL_SHORT[result.nextDropIn.day] || result.nextDropIn.day.toUpperCase();
      const time = formatHHMM(result.nextDropIn.start);
      const prefix = result.kind === "NO_DROPIN_TODAY" ? "NO DROP-IN TODAY" : "CLOSED";
      return `${prefix} — NEXT ${program} ${day} ${time}`;
    }
    case "NOT_VERIFIED":
      return "SCHEDULE NOT YET VERIFIED";
    case "NO_DROPIN_WEEK":
      return "NO DROP-IN THIS WEEK";
    default:
      return "—";
  }
}

function formatNextLine(result) {
  // The STATUS line already carries NEXT info for these kinds.
  const inlineKinds = new Set([
    "CLOSED_TODAY", "CLOSED_HOURS", "NO_DROPIN_TODAY", "NOT_VERIFIED", "NO_DROPIN_WEEK",
  ]);
  if (inlineKinds.has(result.kind)) return "—";
  if (!result.nextDropIn) return "—";
  const program = PROGRAM_LABEL[result.nextDropIn.program] || result.nextDropIn.program.toUpperCase();
  const day = DAY_LABEL_SHORT[result.nextDropIn.day] || result.nextDropIn.day.toUpperCase();
  return `${program} · ${day} ${formatHHMM(result.nextDropIn.start)}`;
}

function applyStatusSlab(root, schedule, now) {
  const result = computeDetailStatus(schedule, now);
  const statusEl = root.querySelector('[data-field="status"]');
  const nextEl = root.querySelector('[data-field="next"]');
  if (statusEl) statusEl.textContent = formatStatusLine(result);
  if (nextEl) nextEl.textContent = formatNextLine(result);
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
    const start = parseHHMMSafe(row.getAttribute("data-start"));
    const end = parseHHMMSafe(row.getAttribute("data-end"));
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

    if (start <= nowMinutes && nowMinutes < end) {
      if (!timeEl.textContent.startsWith("● ")) {
        timeEl.textContent = `● ${timeEl.textContent}`;
      }
      labelEl.textContent = "NOW";
      continue;
    }

    if (row === nextRow) {
      labelEl.textContent = "NEXT";
    }
  }
}

function applyFreshness(root, now) {
  const el = root.querySelector('[data-field="freshness"]');
  if (!el) return;
  const iso = root.getAttribute("data-last-verified");
  const label = freshnessLabel(iso, now);
  el.setAttribute("data-freshness", label);
  const labelEl = el.querySelector(".freshness-label");
  if (labelEl) labelEl.textContent = label.toUpperCase();
}

function markTodayColumn(root, now) {
  const todayKey = DAY_KEYS[now.getDay()];
  const dayheads = root.querySelectorAll(`.weekly-grid-dayhead[data-day="${todayKey}"]`);
  dayheads.forEach((el) => el.setAttribute("data-today", "true"));
  const cells = root.querySelectorAll(`.weekly-grid-cell[data-day="${todayKey}"]`);
  cells.forEach((el) => el.setAttribute("data-today", "true"));
}

function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readSchedule(root);
  if (!schedule) return;
  const now = new Date();
  const result = applyStatusSlab(root, schedule, now);
  decorateTodayBlock(root, now, result);
  markTodayColumn(root, now);
  applyFreshness(root, now);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
