// SwimFrancisco departure-board status computation.
// Pure helpers are testable; the DOM-mutating helpers are called on DOMContentLoaded.

const DAY_KEYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
];

const PLACEHOLDER = "\u2014"; // em dash

// Parse "HH:MM" into minutes since midnight. Returns null on malformed input.
function parseHHMM(value) {
  if (typeof value !== "string") return null;
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
  return hours * 60 + minutes;
}

// Format a minutes-since-midnight value back as "HH:MM" (24-hour).
function formatHHMM(totalMinutes) {
  const normalized = ((totalMinutes % 1440) + 1440) % 1440;
  const hours = Math.floor(normalized / 60);
  const minutes = normalized % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

// Format a Date as YYYY-MM-DD in local time.
function formatISODate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// Return the active closure (if any) covering `now`. Closure `start`/`end` are
// inclusive ISO dates (YYYY-MM-DD). Closures are facility-wide and all-day per
// the v1 contract — see docs/schedules.md ("Closure Contract").
function findActiveClosure(closures, now) {
  if (!Array.isArray(closures) || closures.length === 0) return null;
  const today = formatISODate(now);
  for (const closure of closures) {
    if (!closure || typeof closure !== "object") continue;
    const start = typeof closure.start === "string" ? closure.start : null;
    const end = typeof closure.end === "string" ? closure.end : null;
    if (!start || !end) continue;
    if (today >= start && today <= end) return closure;
  }
  return null;
}

// Compute STATUS and NEXT for a single pool row.
// schedule shape: { sessions: [{day, type, start, end}, ...], closures: [{start, end, reason}, ...] }
function computeStatus(schedule, now) {
  const empty = { status: PLACEHOLDER, next: PLACEHOLDER };
  if (!schedule || typeof schedule !== "object") return empty;

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return {
      status: "CLOSED",
      next: `Closed until ${activeClosure.end}`,
    };
  }

  if (sessions.length === 0) return empty;

  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  // Normalize and validate sessions. Drop malformed ones.
  const normalized = [];
  for (const session of sessions) {
    if (!session || typeof session !== "object") continue;
    const day = typeof session.day === "string" ? session.day.toLowerCase() : null;
    const start = parseHHMM(session.start);
    const end = parseHHMM(session.end);
    if (!day || !DAY_KEYS.includes(day) || start === null || end === null) continue;
    if (end <= start) continue;
    normalized.push({ day, start, end });
  }
  if (normalized.length === 0) return empty;

  // Is a session currently active today?
  const current = normalized.find(
    (s) => s.day === todayKey && s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (current) {
    return { status: "OPEN", next: `Closes ${formatHHMM(current.end)}` };
  }

  // Find the next upcoming session within a 7-day window.
  let best = null;
  for (let offset = 0; offset < 7; offset += 1) {
    const dayIndex = (now.getDay() + offset) % 7;
    const dayKey = DAY_KEYS[dayIndex];
    const candidates = normalized
      .filter((s) => s.day === dayKey)
      .filter((s) => offset > 0 || s.start > nowMinutes)
      .sort((a, b) => a.start - b.start);
    if (candidates.length > 0) {
      best = { offset, session: candidates[0] };
      break;
    }
  }

  if (!best) return { status: "CLOSED", next: PLACEHOLDER };

  const label = best.offset === 0
    ? `Opens ${formatHHMM(best.session.start)}`
    : `Opens ${best.session.day.slice(0, 3).toUpperCase()} ${formatHHMM(best.session.start)}`;

  return { status: "CLOSED", next: label };
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
  // Signal to filters.js (Step 12) that status cells are populated and rows
  // are in their baseline (open-first, alphabetical) order.
  document.dispatchEvent(new CustomEvent("sf:status-applied"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
