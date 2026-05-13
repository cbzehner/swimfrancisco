// Pure helpers for the Swim Francisco board.
//
// Extracted from status.js / filters.js so they can be exercised under
// node:test without a DOM. DOM-facing wrappers live in the parent files and
// delegate to these.

import { isDropInType } from "./programs.mjs";

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
const MIN_USEFUL_WINDOW_OVERLAP_MINUTES = 45;

const HORIZON_DEFINITIONS = Object.freeze([
  { id: "this-morning", label: "This Morning", dayOffset: 0, start: "06:00", end: "11:00" },
  { id: "this-afternoon", label: "This Afternoon", dayOffset: 0, start: "12:00", end: "17:00" },
  { id: "this-evening", label: "This Evening", dayOffset: 0, start: "17:00", end: "21:00" },
  { id: "tomorrow-morning", label: "Tomorrow Morning", dayOffset: 1, start: "06:00", end: "11:00" },
  { id: "tomorrow-afternoon", label: "Tomorrow Afternoon", dayOffset: 1, start: "12:00", end: "17:00" },
  { id: "tomorrow-evening", label: "Tomorrow Evening", dayOffset: 1, start: "17:00", end: "21:00" },
]);

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

function dateWithDayOffset(now, offset) {
  const date = new Date(now);
  date.setDate(date.getDate() + offset);
  return date;
}

function horizonFromDefinition(def, now) {
  const date = dateWithDayOffset(now, def.dayOffset);
  const start = parseHHMM(def.start);
  const end = parseHHMM(def.end);
  return {
    id: def.id,
    label: def.label,
    kind: "window",
    dayOffset: def.dayOffset,
    date: formatISODate(date),
    day: DAY_KEYS[date.getDay()],
    start,
    end,
  };
}

export function getHorizonOptions(now = nowInPacific()) {
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const options = [{ id: "now", label: "Now", kind: "point" }];
  for (const def of HORIZON_DEFINITIONS) {
    const horizon = horizonFromDefinition(def, now);
    if (horizon.start === null || horizon.end === null) continue;
    if (def.dayOffset === 0 && horizon.end <= nowMinutes) continue;
    options.push(horizon);
  }
  return options;
}

export function resolveHorizon(id, now = nowInPacific()) {
  const options = getHorizonOptions(now);
  return options.find((option) => option.id === id) ?? options[0];
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
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  for (const closure of closures) {
    if (!closure || typeof closure !== "object") continue;
    const start = typeof closure.start === "string" ? closure.start : null;
    const end = typeof closure.end === "string" ? closure.end : null;
    if (!start || !end) continue;
    if (typeof closure.pool === "string" && closure.pool.length > 0) continue;
    if (today < start || today > end) continue;
    // Partial-day closures (single-date with start_time/end_time) only block
    // during their explicit window. Outside that window the pool is open
    // even though a closure entry "exists" for the day.
    const startMin = parseHHMM(closure.start_time);
    const endMin = parseHHMM(closure.end_time);
    if (startMin !== null && endMin !== null) {
      if (nowMinutes < startMin || nowMinutes >= endMin) continue;
    }
    return closure;
  }
  return null;
}

// Human-readable copy for an active closure. The end date is inclusive, so
// the pool is closed THROUGH that date (not "until" it — that reads as an
// exclusive upper bound).
export function closureCopy(closure) {
  // Synthetic POST_SEASON closures end in year 9999 — a "closed through"
  // line for that is nonsense. The reason field already carries the
  // human-readable transition message ("Schedule ended JUN 6, 2026"), so
  // surface that verbatim. Everything else (explicit closures + the
  // PRE_SEASON synthetic, whose end is a real date) keeps the standard
  // "Closed through <end>" copy.
  if (closure.kind === "POST_SEASON" && typeof closure.reason === "string") {
    return closure.reason;
  }
  // Partial-day closures show their time window since "Closed through
  // <date>" at 11 AM is misleading when the pool reopens at 3 PM.
  const startMin = parseHHMM(closure.start_time);
  const endMin = parseHHMM(closure.end_time);
  if (startMin !== null && endMin !== null) {
    return `Closed ${formatHHMM(startMin)}–${formatHHMM(endMin)}`;
  }
  return `Closed through ${formatISODateHuman(closure.end)}`;
}

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
    const dayKey = DAY_KEYS[date.getDay()];
    const dateISO = formatISODate(date);

    // All-day closures cover the whole day. Partial-day closures only block
    // sessions whose start lands inside the partial window.
    const dayClosures = closures.filter((c) => {
      if (!c || typeof c !== "object") return false;
      if (typeof c.pool === "string" && c.pool.length > 0) return false;
      const start = typeof c.start === "string" ? c.start : null;
      const end = typeof c.end === "string" ? c.end : null;
      return Boolean(start && end && dateISO >= start && dateISO <= end);
    });
    const allDay = dayClosures.find(
      (c) => typeof c.start_time !== "string" || typeof c.end_time !== "string",
    );
    if (allDay) continue;
    const partialWindows = dayClosures
      .map((c) => ({ start: parseHHMM(c.start_time), end: parseHHMM(c.end_time) }))
      .filter((w) => w.start !== null && w.end !== null);

    const candidates = normalized
      .filter((session) => session.day === dayKey)
      .filter((session) => offset > 0 || session.start > nowMinutes)
      .filter((session) => !partialWindows.some(
        (w) => session.start >= w.start && session.start < w.end,
      ))
      .sort((a, b) => a.start - b.start);
    if (candidates.length > 0) {
      return { offset, session: candidates[0] };
    }
  }
  return null;
}

function closureOverlapsWindow(closure, dateISO, windowStart, windowEnd) {
  if (!closure || typeof closure !== "object") return false;
  if (typeof closure.pool === "string" && closure.pool.length > 0) return false;
  const start = typeof closure.start === "string" ? closure.start : null;
  const end = typeof closure.end === "string" ? closure.end : null;
  if (!start || !end) return false;
  if (dateISO < start || dateISO > end) return false;

  const closureStart = parseHHMM(closure.start_time);
  const closureEnd = parseHHMM(closure.end_time);
  if (closureStart === null || closureEnd === null) return true;
  return closureEnd > windowStart && closureStart < windowEnd;
}

function sessionOverlapsClosure(session, closures, dateISO) {
  return closures.some((closure) => {
    if (!closureOverlapsWindow(closure, dateISO, session.start, session.end)) return false;
    const closureStart = parseHHMM(closure.start_time);
    const closureEnd = parseHHMM(closure.end_time);
    if (closureStart === null || closureEnd === null) return true;
    return closureEnd > session.start && closureStart < session.end;
  });
}

// Return the next drop-in session (lap / family / senior) that starts strictly
// after `now`, scanning up to 7 days ahead. Skips facility-wide closed days.
// Returns `{ program, day, start }` (start in minutes-of-day) or null if none
// found within the window.
export function findNextDropIn(schedule, now, allowedTypes = null) {
  if (!schedule || typeof schedule !== "object") return null;
  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  // Pull in derived closures so pre-season pools skip days that fall
  // outside the schedule's effective window when looking for the next
  // session. Without this, a pre-season pool would surface a session in
  // its yet-to-start schedule as "today" or a same-week day.
  const closures = allClosures(schedule);
  if (sessions.length === 0) return null;
  const allowed = normalizeAllowedTypes(allowedTypes);

  const normalized = [];
  for (const session of sessions) {
    if (!session || typeof session !== "object") continue;
    if (!isDropInType(session.type)) continue;
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

// A schedule's effective window is itself a closure. Pre-season and
// post-season become synthetic closure entries so the rest of the system
// (status copy, dashboard "next" line, detail-page suppression) treats them
// uniformly with explicit closures like Memorial Day or a repair shutdown.
//
// PRE_SEASON range:  far past → schedule_effective_start - 1
// POST_SEASON range: schedule_effective_end + 1 → far future
//
// Synthetic closures carry a `kind` so callers that want to distinguish
// data-driven gaps from explicit closures still can.
function derivedClosures(schedule) {
  const out = [];
  const start =
    typeof schedule.effective_start === "string" && schedule.effective_start
      ? schedule.effective_start
      : null;
  const end =
    typeof schedule.effective_end === "string" && schedule.effective_end
      ? schedule.effective_end
      : null;
  if (start) {
    const dayBefore = previousISODate(start);
    out.push({
      start: "0001-01-01",
      end: dayBefore,
      reason: `Schedule starts ${formatISODateHuman(start)}`,
      kind: "PRE_SEASON",
    });
  }
  if (end) {
    const dayAfter = nextISODate(end);
    out.push({
      start: dayAfter,
      end: "9999-12-31",
      reason: `Schedule ended ${formatISODateHuman(end)}`,
      kind: "POST_SEASON",
    });
  }
  return out;
}

function shiftISODate(iso, delta) {
  // iso is "YYYY-MM-DD". Returns the date `delta` days away in the same
  // shape. All math is done in UTC so the runtime's local TZ never shifts
  // the calendar day (formatISODate reads local-time getters, so we must
  // not round-trip through it here).
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const t = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) + delta * 86400000;
  const d = new Date(t);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function previousISODate(iso) {
  return shiftISODate(iso, -1);
}

function nextISODate(iso) {
  return shiftISODate(iso, 1);
}

function allClosures(schedule) {
  const explicit = Array.isArray(schedule.closures) ? schedule.closures : [];
  return [...explicit, ...derivedClosures(schedule)];
}

export function computeStatus(schedule, now, allowedTypes = null) {
  const empty = { status: PLACEHOLDER, next: PLACEHOLDER };
  if (!schedule || typeof schedule !== "object") return empty;

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const allowed = normalizeAllowedTypes(allowedTypes);

  // Pre-season, post-season, and explicit closures all flow through
  // findActiveClosure so the dashboard renders one shape: status=CLOSED,
  // next=closureCopy. Schedule transitions render naturally because the
  // synthetic PRE_SEASON closure carries "Schedule starts <date>" as its
  // reason, which findActiveClosure surfaces unchanged.
  const closures = allClosures(schedule);
  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return { status: "CLOSED", next: closureCopy(activeClosure) };
  }

  if (sessions.length === 0) {
    return { status: "CLOSED", next: "Schedule not yet verified" };
  }

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

export function computeNextOpenOffset(schedule, now, allowedTypes = null) {
  if (!schedule || typeof schedule !== "object") return Number.POSITIVE_INFINITY;

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = allClosures(schedule);
  if (sessions.length === 0) return Number.POSITIVE_INFINITY;

  const normalized = normalizeSessions(sessions, allowedTypes);
  if (normalized.length === 0) return Number.POSITIVE_INFINITY;

  const activeClosure = findActiveClosure(closures, now);
  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  if (!activeClosure) {
    const current = normalized.find(
      (s) => s.day === todayKey && s.start <= nowMinutes && nowMinutes < s.end,
    );
    if (current) return 0;
  }

  const best = findNextSession(normalized, closures, now);
  if (!best) return Number.POSITIVE_INFINITY;
  return best.offset * 1440 + best.session.start - nowMinutes;
}

export function computeWindowAvailability(schedule, horizon, allowedTypes = null) {
  if (!horizon || horizon.kind !== "window") {
    return {
      kind: "INVALID",
      status: PLACEHOLDER,
      next: PLACEHOLDER,
      sortRank: Number.POSITIVE_INFINITY,
      bestSession: null,
    };
  }
  if (!schedule || typeof schedule !== "object") {
    return {
      kind: "NO_SESSION",
      status: "NO SESSION",
      next: PLACEHOLDER,
      sortRank: 3,
      bestSession: null,
    };
  }

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const closures = allClosures(schedule);
  const blockingClosure = closures.find((closure) => (
    closureOverlapsWindow(closure, horizon.date, horizon.start, horizon.end) &&
    (parseHHMM(closure.start_time) === null || parseHHMM(closure.end_time) === null)
  ));

  if (blockingClosure) {
    return {
      kind: "CLOSED",
      status: "CLOSED",
      next: typeof blockingClosure.reason === "string"
        ? blockingClosure.reason.toUpperCase()
        : PLACEHOLDER,
      sortRank: 4,
      bestSession: null,
    };
  }

  if (sessions.length === 0) {
    return {
      kind: "NO_SESSION",
      status: "NO SESSION",
      next: "Schedule not verified",
      sortRank: 3,
      bestSession: null,
    };
  }

  const normalized = normalizeSessions(sessions, allowedTypes)
    .filter((session) => isDropInType(session.type))
    .filter((session) => session.day === horizon.day)
    .filter((session) => session.end > horizon.start && session.start < horizon.end)
    .filter((session) => !sessionOverlapsClosure(session, closures, horizon.date))
    .map((session) => ({
      ...session,
      overlap: Math.min(session.end, horizon.end) - Math.max(session.start, horizon.start),
    }))
    .filter((session) => session.overlap > 0)
    .sort((a, b) => {
      if (a.start !== b.start) return a.start - b.start;
      return b.overlap - a.overlap;
    });

  if (normalized.length === 0) {
    return {
      kind: "NO_SESSION",
      status: "NO SESSION",
      next: PLACEHOLDER,
      sortRank: 3,
      bestSession: null,
    };
  }

  const bestSession = normalized[0];
  const limited = bestSession.overlap < MIN_USEFUL_WINDOW_OVERLAP_MINUTES;
  return {
    kind: limited ? "LIMITED" : "AVAILABLE",
    status: limited ? "LIMITED" : "AVAILABLE",
    next: PLACEHOLDER,
    sortRank: limited ? 1 : 0,
    bestSession,
  };
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

const EMPTY_DETAIL = Object.freeze({
  kind: "NOT_VERIFIED",
  activePrograms: [],
  activeUntil: null,
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
  // Pre-season and post-season are synthetic closures so the detail page
  // collapses them into the same CLOSED_TODAY rendering used for repair
  // shutdowns and holiday closures.
  const closures = allClosures(schedule);

  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    return {
      ...EMPTY_DETAIL,
      kind: "CLOSED_TODAY",
      closureReason: typeof activeClosure.reason === "string" ? activeClosure.reason : null,
      closureKind: typeof activeClosure.kind === "string" ? activeClosure.kind : null,
      nextDropIn: activeClosure.kind === "POST_SEASON" ? null : findNextDropIn(schedule, now),
    };
  }

  const normalized = normalizeSessions(sessions);
  if (normalized.length === 0) {
    return { ...EMPTY_DETAIL, kind: "NOT_VERIFIED" };
  }

  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const todayAll = normalized.filter((s) => s.day === todayKey);
  const todayDropIn = todayAll.filter((s) => isDropInType(s.type));

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

  if (todayDropIn.length === 0 && todayAll.length > 0) {
    return {
      ...EMPTY_DETAIL,
      kind: "NO_DROPIN_TODAY",
      nextDropIn: findNextDropIn(schedule, now),
    };
  }

  const anyDropInThisWeek = normalized.some((s) => isDropInType(s.type));
  if (!anyDropInThisWeek) {
    return { ...EMPTY_DETAIL, kind: "NO_DROPIN_WEEK" };
  }

  return {
    ...EMPTY_DETAIL,
    kind: "CLOSED_HOURS",
    nextDropIn: findNextDropIn(schedule, now),
  };
}
