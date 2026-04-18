// SwimFrancisco pool detail page.
// Reads the schedule embedded in .detail-root[data-schedule], hydrates the
// status slab, injects the today block, marks today's column in the weekly
// grid, and updates the freshness dot. Pure computation lives in
// ./helpers/board.mjs (exercised by node:test).

import {
  DAY_KEYS,
  computeDetailStatus,
  freshnessLabel,
  formatHHMM,
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

function init() {
  const root = document.querySelector(".detail-root");
  if (!root) return;
  const schedule = readSchedule(root);
  if (!schedule) return;
  const now = new Date();
  applyStatusSlab(root, schedule, now);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
