// Pure helpers for the SwimFrancisco departure board.
//
// Extracted from status.js / filters.js so they can be exercised under
// node:test without a DOM. DOM-facing wrappers live in the parent files and
// delegate to these.

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

export function parseHHMM(value) {
  if (typeof value !== "string") return null;
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
  return hours * 60 + minutes;
}

export function formatHHMM(totalMinutes) {
  const normalized = ((totalMinutes % 1440) + 1440) % 1440;
  const hours = Math.floor(normalized / 60);
  const minutes = normalized % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function formatISODate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// Return the active closure (if any) covering `now`. Closure start/end are
// inclusive ISO dates per the v1 closure contract.
export function findActiveClosure(closures, now) {
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

// Human-readable copy for an active closure. The end date is inclusive, so
// the pool is closed THROUGH that date (not "until" it — that reads as an
// exclusive upper bound).
export function closureCopy(closure) {
  return `Closed through ${closure.end}`;
}

export function computeStatus(schedule, now) {
  const empty = { status: PLACEHOLDER, next: PLACEHOLDER };
  if (!schedule || typeof schedule !== "object") return empty;

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return { status: "CLOSED", next: closureCopy(activeClosure) };
  }

  if (sessions.length === 0) return empty;

  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

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

  const current = normalized.find(
    (s) => s.day === todayKey && s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (current) {
    return { status: "OPEN", next: `Closes ${formatHHMM(current.end)}` };
  }

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

// Assign a baseline rank to each item via the provided setter. Keeps this
// pure (no DOM knowledge here); status.js passes a setter that writes to
// `row.dataset.baselineRank`.
export function captureBaselineRanks(items, setRank) {
  items.forEach((item, index) => setRank(item, index));
  return items;
}

// Sort by ascending rank, pulling items without a rank (undefined/NaN) to
// the tail. Stable for equal ranks.
export function sortByRank(items, getRank) {
  const decorated = items.map((item, index) => ({
    item,
    index,
    rank: normalizeRank(getRank(item)),
  }));
  decorated.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    return a.index - b.index;
  });
  return decorated.map((d) => d.item);
}

function normalizeRank(rank) {
  if (typeof rank !== "number" || !Number.isFinite(rank)) {
    return Number.POSITIVE_INFINITY;
  }
  return rank;
}

export { PLACEHOLDER, DAY_KEYS };
