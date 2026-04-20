// Pure helpers for the Swim Francisco board.
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

// Return a Date whose local getters (getFullYear, getMonth, getDate, getDay,
// getHours, getMinutes, getSeconds) reflect the wall-clock in
// America/Los_Angeles. Every Swim Francisco pool is in San Francisco, so the
// entire site should present and reason about time in Pacific, regardless of
// the visitor's browser locale. The returned Date's UTC components are a lie
// — only the local getters are meaningful.
export function nowInPacific(instant) {
  const source = instant instanceof Date ? instant : new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(source);
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  // en-US with hour12:false has historically rendered midnight as "24" on
  // some runtimes; normalize defensively so getHours() returns 0..23.
  let hour = get("hour");
  if (hour === 24) hour = 0;
  return new Date(
    get("year"),
    get("month") - 1,
    get("day"),
    hour,
    get("minute"),
    get("second"),
  );
}

export function formatISODate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function formatISODateHuman(isoDate) {
  if (typeof isoDate !== "string") return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim());
  if (!match) return isoDate;
  const [, year, month, day] = match;
  const monthLabels = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const monthIndex = Number(month) - 1;
  if (monthIndex < 0 || monthIndex >= monthLabels.length) return isoDate;
  return `${monthLabels[monthIndex]} ${Number(day)}, ${year}`;
}

// Return the active facility-wide closure (if any) covering `now`. Closures
// with a non-empty `pool` field are zone-scoped and do NOT close the whole
// facility — they are rendered as detail-page banners but ignored here.
export function findActiveClosure(closures, now) {
  if (!Array.isArray(closures) || closures.length === 0) return null;
  const today = formatISODate(now);
  for (const closure of closures) {
    if (!closure || typeof closure !== "object") continue;
    const start = typeof closure.start === "string" ? closure.start : null;
    const end = typeof closure.end === "string" ? closure.end : null;
    if (!start || !end) continue;
    if (typeof closure.pool === "string" && closure.pool.length > 0) continue;
    if (today >= start && today <= end) return closure;
  }
  return null;
}

// Human-readable copy for an active closure. The end date is inclusive, so
// the pool is closed THROUGH that date (not "until" it — that reads as an
// exclusive upper bound).
export function closureCopy(closure) {
  return `Closed through ${formatISODateHuman(closure.end)}`;
}

const DROP_IN_TYPES = new Set(["lap_swim", "family_swim", "senior_swim"]);

function normalizeAllowedTypes(allowedTypes) {
  if (allowedTypes == null) return null;
  const values = allowedTypes instanceof Set
    ? Array.from(allowedTypes)
    : Array.isArray(allowedTypes)
      ? allowedTypes
      : null;
  if (!values) return null;
  const normalized = new Set(
    values.filter((value) => typeof value === "string" && value.length > 0),
  );
  return normalized;
}

function findNextSession(normalized, closures, now) {
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  for (let offset = 0; offset <= 7; offset += 1) {
    const date = new Date(now);
    date.setDate(date.getDate() + offset);
    if (findActiveClosure(closures, date)) continue;
    const dayKey = DAY_KEYS[date.getDay()];
    const candidates = normalized
      .filter((session) => session.day === dayKey)
      .filter((session) => offset > 0 || session.start > nowMinutes)
      .sort((a, b) => a.start - b.start);
    if (candidates.length > 0) {
      return { offset, session: candidates[0] };
    }
  }
  return null;
}

// Return the next drop-in session (lap / family / senior) that starts strictly
// after `now`, scanning up to 7 days ahead. Skips lessons and facility-wide
// closed days. Returns `{ program, day, start }` (start in minutes-of-day) or
// null if none found within the window.
export function findNextDropIn(schedule, now, allowedTypes = null) {
  if (!schedule || typeof schedule !== "object") return null;
  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];
  if (sessions.length === 0) return null;
  const allowed = normalizeAllowedTypes(allowedTypes);

  const normalized = [];
  for (const session of sessions) {
    if (!session || typeof session !== "object") continue;
    if (!DROP_IN_TYPES.has(session.type)) continue;
    if (allowed && !allowed.has(session.type)) continue;
    const day = typeof session.day === "string" ? session.day.toLowerCase() : null;
    const start = parseHHMM(session.start);
    if (!day || !DAY_KEYS.includes(day) || start === null) continue;
    normalized.push({ program: session.type, day, start });
  }
  if (normalized.length === 0) return null;

  const best = findNextSession(normalized, closures, now);
  return best ? best.session : null;
}

export function computeStatus(schedule, now, allowedTypes = null) {
  const empty = { status: PLACEHOLDER, next: PLACEHOLDER };
  if (!schedule || typeof schedule !== "object") return empty;

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];
  const allowed = normalizeAllowedTypes(allowedTypes);

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return { status: "CLOSED", next: closureCopy(activeClosure) };
  }

  if (sessions.length === 0) return empty;

  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  const normalized = normalizeSessions(sessions, allowed);
  if (normalized.length === 0) return empty;

  const current = normalized.find(
    (s) => s.day === todayKey && s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (current) {
    return { status: "OPEN", next: `Closes ${formatHHMM(current.end)}` };
  }

  const best = findNextSession(normalized, closures, now);
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

const FRESH_WINDOW_DAYS = 30;

// Return "fresh" when `isoDate` (YYYY-MM-DD) is within FRESH_WINDOW_DAYS of
// `now` (inclusive); "stale" otherwise. Missing, empty, or unparseable input
// is treated as stale — we prefer to signal "we don't know" rather than
// overstate freshness.
export function freshnessLabel(isoDate, now) {
  if (typeof isoDate !== "string" || isoDate.length === 0) return "stale";
  const parsed = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "stale";
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const ageMs = today.getTime() - parsed.getTime();
  if (ageMs < 0) return "fresh"; // future-dated counts as fresh
  const ageDays = ageMs / 86_400_000;
  return ageDays <= FRESH_WINDOW_DAYS ? "fresh" : "stale";
}

const EMPTY_DETAIL = Object.freeze({
  kind: "NOT_VERIFIED",
  activePrograms: [],
  activeUntil: null,
  activeLessonsUntil: null,
  nextDropIn: null,
  closureReason: null,
  is_drop_in: false,
});

// Normalize the session list into { day, type, start, end } with minute-of-day
// ints and lowercased day names. Skips malformed rows.
function normalizeSessions(sessions, allowedTypes = null) {
  const out = [];
  const allowed = normalizeAllowedTypes(allowedTypes);
  for (const session of sessions) {
    if (!session || typeof session !== "object") continue;
    const day = typeof session.day === "string" ? session.day.toLowerCase() : null;
    const type = typeof session.type === "string" ? session.type : null;
    if (allowed && !allowed.has(type)) continue;
    const start = parseHHMM(session.start);
    const end = parseHHMM(session.end);
    if (!day || !DAY_KEYS.includes(day) || !type || start === null || end === null) continue;
    if (end <= start) continue;
    out.push({ day, type, start, end });
  }
  return out;
}

export function computeDetailStatus(schedule, now) {
  if (!schedule || typeof schedule !== "object") return { ...EMPTY_DETAIL };

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = Array.isArray(schedule.closures) ? schedule.closures : [];

  const normalized = normalizeSessions(sessions);
  if (normalized.length === 0) {
    return { ...EMPTY_DETAIL, kind: "NOT_VERIFIED" };
  }

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return {
      ...EMPTY_DETAIL,
      kind: "CLOSED_TODAY",
      closureReason: typeof activeClosure.reason === "string" ? activeClosure.reason : null,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const todayAll = normalized.filter((s) => s.day === todayKey);
  const todayDropIn = todayAll.filter((s) => DROP_IN_TYPES.has(s.type));

  const activeDropIn = todayDropIn.filter(
    (s) => s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (activeDropIn.length > 0) {
    return {
      ...EMPTY_DETAIL,
      kind: "OPEN",
      activePrograms: activeDropIn.map((s) => s.type),
      activeUntil: Math.min(...activeDropIn.map((s) => s.end)),
      is_drop_in: true,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const activeLessons = todayAll.find(
    (s) => s.type === "lessons" && s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (activeLessons) {
    return {
      ...EMPTY_DETAIL,
      kind: "LESSONS",
      activeLessonsUntil: activeLessons.end,
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  if (todayDropIn.length === 0 && todayAll.length > 0) {
    return {
      ...EMPTY_DETAIL,
      kind: "NO_DROPIN_TODAY",
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const anyDropInThisWeek = normalized.some((s) => DROP_IN_TYPES.has(s.type));
  if (!anyDropInThisWeek) {
    return { ...EMPTY_DETAIL, kind: "NO_DROPIN_WEEK" };
  }

  return {
    ...EMPTY_DETAIL,
    kind: "CLOSED_HOURS",
    nextDropIn: findNextDropIn(schedule, now),
  };
}
