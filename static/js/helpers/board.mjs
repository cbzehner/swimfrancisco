// Pure helpers for the Swim Francisco board.
//
// Extracted from status.js / filters.js so they can be exercised under
// node:test without a DOM. DOM-facing wrappers live in the parent files and
// delegate to these.

import { isDropInType } from "./programs.mjs";
import { pacificWallClockDate } from "./pacific.mjs";

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

export function getHorizonOptions(now = pacificWallClockDate()) {
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

export function resolveHorizon(id, now = pacificWallClockDate()) {
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

function statusResult(status, next, nextKind = "", nextArgs = {}) {
  return { status, next, nextKind, nextArgs };
}

function scheduleWithoutUpcoming(schedule) {
  if (!schedule || typeof schedule !== "object") return schedule;
  const { upcoming_schedule: _upcoming, ...current } = schedule;
  return current;
}

function scheduleInWindow(schedule, dateISO) {
  if (!schedule || typeof schedule !== "object") return false;
  // The macro emits effective_start / effective_end as strings — either an
  // ISO date or "" when missing. Truthiness alone is enough to distinguish.
  const start = schedule.effective_start || null;
  const end = schedule.effective_end || null;
  if (start && dateISO < start) return false;
  if (end && dateISO > end) return false;
  return true;
}

// Display-time predicate: pick which embedded schedule (current vs. queued
// upcoming) the page should render for `dateISO`. Switches to upcoming as
// soon as current has ended, so gap days surface "Schedule starts <date>"
// from the queued entry via the synthetic PRE_SEASON closure.
//
// Must stay in sync with templates/spots/page.html's `active_extra` block.
// merge.py's _promote_upcoming_schedule is a DIFFERENT concept (writing
// upcoming over current in the frontmatter) and uses a stricter predicate.
function resolveScheduleForDate(schedule, dateISO) {
  if (!schedule || typeof schedule !== "object") return schedule;
  const current = scheduleWithoutUpcoming(schedule);
  const upcoming = scheduleWithoutUpcoming(schedule.upcoming_schedule);
  if (!upcoming) return current;
  if (scheduleInWindow(current, dateISO)) return current;
  const currentEnd = current.effective_end || null;
  if (currentEnd && dateISO > currentEnd) return upcoming;
  return current;
}

export function resolveActiveSchedule(schedule, now = pacificWallClockDate()) {
  const dateISO = typeof now === "string" ? now : formatISODate(now);
  return resolveScheduleForDate(schedule, dateISO);
}

function hasNonEmptyArray(schedule, key) {
  return Boolean(
    schedule
    && typeof schedule === "object"
    && Array.isArray(schedule[key])
    && schedule[key].length > 0,
  );
}

export function scheduleHasSessions(schedule) {
  return hasNonEmptyArray(schedule, "sessions");
}

export function scheduleHasAccessHours(schedule) {
  return hasNonEmptyArray(schedule, "access_hours");
}

// Parse the JSON schedule from a `data-schedule` attribute on the given DOM
// element (a table row on the board, the detail-page root, etc.). Returns
// null on missing attribute or malformed JSON.
export function readScheduleAttribute(element) {
  const raw = element?.getAttribute?.("data-schedule");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

// Return the active closure (if any) covering `now`.
export function findActiveClosure(closures, now) {
  if (!Array.isArray(closures) || closures.length === 0) return null;
  const today = formatISODate(now);
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  for (const closure of closures) {
    if (!closure || typeof closure !== "object") continue;
    const start = typeof closure.start === "string" ? closure.start : null;
    const end = typeof closure.end === "string" ? closure.end : null;
    if (!start || !end) continue;
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
  // line for that is nonsense. The reason field carries the fallback
  // transition message. PRE_SEASON uses the same reason path so schedule
  // transitions read as "Schedule starts <date>" instead of a generic closed
  // line for the day before. Single-day closures with reasons surface the
  // reason; multi-day closures keep the inclusive "Closed through <end>" copy.
  if ((closure.kind === "PRE_SEASON" || closure.kind === "POST_SEASON") && typeof closure.reason === "string") {
    return closure.reason;
  }
  // Partial-day closures show their time window since "Closed through
  // <date>" at 11 AM is misleading when the pool reopens at 3 PM.
  const startMin = parseHHMM(closure.start_time);
  const endMin = parseHHMM(closure.end_time);
  if (startMin !== null && endMin !== null) {
    return `Closed ${formatHHMM(startMin)}–${formatHHMM(endMin)}`;
  }
  if (closure.start === closure.end && typeof closure.reason === "string" && closure.reason) {
    return closure.reason;
  }
  return `Closed through ${formatISODateHuman(closure.end)}`;
}

function closureNext(closure) {
  const startMin = parseHHMM(closure.start_time);
  const endMin = parseHHMM(closure.end_time);
  if (closure.kind === "PRE_SEASON" && typeof closure.transition_date === "string") {
    return { nextKind: "schedule_starts", nextArgs: { iso: closure.transition_date } };
  }
  if (closure.kind === "POST_SEASON" && typeof closure.transition_date === "string") {
    return { nextKind: "schedule_ended", nextArgs: { iso: closure.transition_date } };
  }
  if (startMin !== null && endMin !== null) {
    return { nextKind: "closed_window", nextArgs: { start: formatHHMM(startMin), end: formatHHMM(endMin) } };
  }
  if (closure.start === closure.end && typeof closure.reason === "string" && closure.reason) {
    return {
      nextKind: "closure_reason",
      nextArgs: {
        reason: closure.reason,
        reasonCode: typeof closure.reason_code === "string" ? closure.reason_code : "",
      },
    };
  }
  return { nextKind: "closed_through", nextArgs: { iso: closure.end } };
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

    const candidates = normalized
      .filter((session) => session.day === dayKey)
      .flatMap((session) => {
        const end = typeof session.end === "number" ? session.end : session.start + 1;
        return availableSegmentsAfterClosures(session.start, end, closures, dateISO)
          .map((segment) => ({ ...session, start: segment.start, end: segment.end }));
      })
      .filter((session) => offset > 0 || session.start > nowMinutes)
      .sort((a, b) => a.start - b.start);
    if (candidates.length > 0) {
      return { offset, session: candidates[0] };
    }
  }
  return null;
}

function dateMatchesException(accessException, dateISO) {
  return Boolean(
    accessException &&
    typeof accessException === "object" &&
    accessException.date === dateISO,
  );
}

function normalizeAccessExceptions(accessExceptions) {
  if (!Array.isArray(accessExceptions)) return [];
  const out = [];
  for (const accessException of accessExceptions) {
    if (!accessException || typeof accessException !== "object") continue;
    const date = typeof accessException.date === "string" ? accessException.date : null;
    const start = parseHHMM(accessException.start);
    const end = parseHHMM(accessException.end);
    const label = typeof accessException.label === "string" ? accessException.label : "Access";
    const reason = typeof accessException.reason === "string" ? accessException.reason : "";
    if (!date || start === null || end === null) continue;
    if (end <= start) continue;
    out.push({ date, start, end, label, reason });
  }
  return out;
}

function accessWindowsForDate(schedule, date) {
  const dateISO = formatISODate(date);
  const exceptions = normalizeAccessExceptions(schedule.access_exceptions)
    .filter((accessException) => dateMatchesException(accessException, dateISO))
    .sort((a, b) => a.start - b.start);
  if (exceptions.length > 0) return exceptions;

  const dayKey = DAY_KEYS[date.getDay()];
  return normalizeAccessHours(schedule.access_hours)
    .filter((access) => access.day === dayKey)
    .sort((a, b) => a.start - b.start);
}

function findNextAccessWindow(schedule, closures, now) {
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  for (let offset = 0; offset <= 7; offset += 1) {
    const date = new Date(now);
    date.setDate(date.getDate() + offset);
    const dateISO = formatISODate(date);
    const candidates = accessWindowsForDate(schedule, date)
      .flatMap((access) => availableSegmentsAfterClosures(access.start, access.end, closures, dateISO)
        .map((segment) => ({ ...access, start: segment.start, end: segment.end })))
      .filter((access) => offset > 0 || access.start > nowMinutes)
      .sort((a, b) => a.start - b.start);
    if (candidates.length > 0) {
      return { offset, access: candidates[0] };
    }
  }
  return null;
}

function closureOverlapsWindow(closure, dateISO, windowStart, windowEnd) {
  if (!closure || typeof closure !== "object") return false;
  const start = typeof closure.start === "string" ? closure.start : null;
  const end = typeof closure.end === "string" ? closure.end : null;
  if (!start || !end) return false;
  if (dateISO < start || dateISO > end) return false;

  const closureStart = parseHHMM(closure.start_time);
  const closureEnd = parseHHMM(closure.end_time);
  if (closureStart === null || closureEnd === null) return true;
  return closureEnd > windowStart && closureStart < windowEnd;
}

function availableSegmentsAfterClosures(start, end, closures, dateISO) {
  if (end <= start) return [];
  let segments = [{ start, end }];
  for (const closure of closures) {
    if (!closureOverlapsWindow(closure, dateISO, start, end)) continue;
    const closureStart = parseHHMM(closure.start_time);
    const closureEnd = parseHHMM(closure.end_time);
    if (closureStart === null || closureEnd === null) return [];
    segments = segments.flatMap((segment) => {
      if (closureEnd <= segment.start || closureStart >= segment.end) return [segment];
      const next = [];
      if (segment.start < closureStart) {
        next.push({ start: segment.start, end: Math.min(closureStart, segment.end) });
      }
      if (closureEnd < segment.end) {
        next.push({ start: Math.max(closureEnd, segment.start), end: segment.end });
      }
      return next.filter((candidate) => candidate.end > candidate.start);
    });
    if (segments.length === 0) return [];
  }
  return segments;
}

// Return the next drop-in session (lap / family / senior) that starts strictly
// after `now`, scanning up to 7 days ahead. Skips facility-wide closed days.
// Returns `{ program, day, start }` (start in minutes-of-day) or null if none
// found within the window.
export function findNextDropIn(schedule, now, allowedTypes = null) {
  schedule = resolveActiveSchedule(schedule, now);
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
    const end = parseHHMM(session.end);
    if (!day || !DAY_KEYS.includes(day) || start === null || end === null || end <= start) continue;
    normalized.push({ program: session.type, day, start, end });
  }
  if (normalized.length === 0) return null;

  const best = findNextSession(normalized, closures, now);
  if (!best) return null;
  return {
    program: best.session.program,
    day: best.session.day,
    start: best.session.start,
  };
}

// A schedule's effective window is itself a closure. Pre-season and
// post-season become synthetic closure entries so the rest of the system
// (status copy, dashboard "next" line, detail-page suppression) treats them
// uniformly with explicit closures like Memorial Day or a repair shutdown.
//
// PRE_SEASON range:  far past → schedule_effective_start - 1
// POST_SEASON range: effective_end + 1 → far future
//
// Synthetic closures carry a `kind` so callers that want to distinguish
// data-driven gaps from explicit closures still can.
function derivedClosures(schedule) {
  const out = [];
  const start = schedule.effective_start || null;
  const end = schedule.effective_end || null;
  if (start) {
    const dayBefore = previousISODate(start);
    out.push({
      start: "0001-01-01",
      end: dayBefore,
      reason: `Schedule starts ${formatISODateHuman(start)}`,
      kind: "PRE_SEASON",
      transition_date: start,
    });
  }
  if (end) {
    const dayAfter = nextISODate(end);
    out.push({
      start: dayAfter,
      end: "9999-12-31",
      reason: `Schedule ended ${formatISODateHuman(end)}`,
      kind: "POST_SEASON",
      transition_date: end,
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
  schedule = resolveActiveSchedule(schedule, now);
  const empty = statusResult(PLACEHOLDER, PLACEHOLDER);
  if (!schedule || typeof schedule !== "object") return empty;

  const sessions = Array.isArray(schedule.sessions) ? schedule.sessions : [];
  const allowed = normalizeAllowedTypes(allowedTypes);

  // Pre-season, post-season, and explicit closures all flow through
  // findActiveClosure so the dashboard renders one shape: status=CLOSED
  // with English fallback copy plus structured nextKind/nextArgs for i18n.
  const closures = allClosures(schedule);
  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    const { nextKind, nextArgs } = closureNext(activeClosure);
    return statusResult("CLOSED", closureCopy(activeClosure), nextKind, nextArgs);
  }

  if (sessions.length === 0) {
    return statusResult("CLOSED", "Schedule not yet verified", "not_verified");
  }

  const todayKey = DAY_KEYS[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  const normalized = normalizeSessions(sessions, allowed);
  if (normalized.length === 0) return empty;

  const current = normalized.find(
    (s) => s.day === todayKey && s.start <= nowMinutes && nowMinutes < s.end,
  );
  if (current) {
    return statusResult("OPEN", `Closes ${formatHHMM(current.end)}`, "closes", {
      time: formatHHMM(current.end),
    });
  }

  const best = findNextSession(normalized, closures, now);
  if (!best) return statusResult("CLOSED", PLACEHOLDER);

  const label = best.offset === 0
    ? `Opens ${formatHHMM(best.session.start)}`
    : `Opens ${best.session.day.slice(0, 3).toUpperCase()} ${formatHHMM(best.session.start)}`;

  return statusResult(
    "CLOSED",
    label,
    best.offset === 0 ? "opens_today" : "opens_day",
    { day: best.session.day, time: formatHHMM(best.session.start) },
  );
}

export function computeAccessStatus(schedule, now) {
  schedule = resolveActiveSchedule(schedule, now);
  const empty = statusResult(PLACEHOLDER, PLACEHOLDER);
  if (!schedule || typeof schedule !== "object") return empty;

  const hasAccessHours = normalizeAccessHours(schedule.access_hours).length > 0;
  const hasAccessExceptions = normalizeAccessExceptions(schedule.access_exceptions).length > 0;
  if (!hasAccessHours && !hasAccessExceptions) return empty;

  const closures = allClosures(schedule);
  const activeClosure = findActiveClosure(closures, now);
  if (activeClosure) {
    const { nextKind, nextArgs } = closureNext(activeClosure);
    return statusResult("CLOSED", closureCopy(activeClosure), nextKind, nextArgs);
  }

  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const current = accessWindowsForDate(schedule, now)
    .find((access) => access.start <= nowMinutes && nowMinutes < access.end);
  if (current) {
    return statusResult("ACCESS", `Until ${formatHHMM(current.end)}`, "until", {
      time: formatHHMM(current.end),
    });
  }

  const best = findNextAccessWindow(schedule, closures, now);
  if (!best) return statusResult("CHECK", "OFFICIAL SITE", "official_site");
  const label = best.offset === 0
    ? `Access ${formatHHMM(best.access.start)}`
    : `Access ${DAY_KEYS[dateWithDayOffset(now, best.offset).getDay()].slice(0, 3).toUpperCase()} ${formatHHMM(best.access.start)}`;
  return statusResult(
    "CHECK",
    label,
    best.offset === 0 ? "access_today" : "access_day",
    { day: DAY_KEYS[dateWithDayOffset(now, best.offset).getDay()], time: formatHHMM(best.access.start) },
  );
}

export function computeNextOpenOffset(schedule, now, allowedTypes = null) {
  schedule = resolveActiveSchedule(schedule, now);
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
  if (horizon?.date) schedule = resolveActiveSchedule(schedule, horizon.date);
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
      nextKind: typeof blockingClosure.reason === "string" ? "closure_reason" : "",
      nextArgs: typeof blockingClosure.reason === "string"
        ? {
          reason: blockingClosure.reason,
          reasonCode: typeof blockingClosure.reason_code === "string" ? blockingClosure.reason_code : "",
        }
        : {},
      sortRank: 4,
      bestSession: null,
    };
  }

  if (sessions.length === 0) {
    return {
      kind: "NO_SESSION",
      status: "NO SESSION",
      next: "Schedule not verified",
      nextKind: "not_verified",
      nextArgs: {},
      sortRank: 3,
      bestSession: null,
    };
  }

  const normalized = normalizeSessions(sessions, allowedTypes)
    .filter((session) => isDropInType(session.type))
    .filter((session) => session.day === horizon.day)
    .filter((session) => session.end > horizon.start && session.start < horizon.end)
    .flatMap((session) => availableSegmentsAfterClosures(
      session.start,
      session.end,
      closures,
      horizon.date,
    ).map((segment) => ({
      ...session,
      start: segment.start,
      end: segment.end,
      overlap: Math.min(segment.end, horizon.end) - Math.max(segment.start, horizon.start),
    })))
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

export function computeAccessWindowAvailability(schedule, horizon) {
  if (horizon?.date) schedule = resolveActiveSchedule(schedule, horizon.date);
  if (!horizon || horizon.kind !== "window" || !schedule || typeof schedule !== "object") {
    return { status: PLACEHOLDER, next: PLACEHOLDER, sortRank: 3 };
  }
  const accessHours = normalizeAccessHours(schedule.access_hours);
  const accessExceptions = normalizeAccessExceptions(schedule.access_exceptions);
  if (accessHours.length === 0 && accessExceptions.length === 0) {
    return { status: "CHECK", next: "OFFICIAL SITE", nextKind: "official_site", nextArgs: {}, sortRank: 3 };
  }
  const closures = allClosures(schedule);
  const blockingClosure = closures.find((closure) => (
    closureOverlapsWindow(closure, horizon.date, horizon.start, horizon.end) &&
    (parseHHMM(closure.start_time) === null || parseHHMM(closure.end_time) === null)
  ));
  if (blockingClosure) {
    return { status: "CLOSED", next: PLACEHOLDER, sortRank: 4 };
  }

  const horizonDate = new Date(`${horizon.date}T00:00:00`);
  const overlaps = accessWindowsForDate(schedule, horizonDate)
    .filter((access) => access.end > horizon.start && access.start < horizon.end)
    .flatMap((access) => availableSegmentsAfterClosures(
      access.start,
      access.end,
      closures,
      horizon.date,
    ).map((segment) => ({ ...access, start: segment.start, end: segment.end })))
    .filter((access) => access.end > horizon.start && access.start < horizon.end)
    .sort((a, b) => a.start - b.start);
  if (overlaps.length === 0) {
    return { status: "CHECK", next: PLACEHOLDER, sortRank: 3 };
  }
  const access = overlaps[0];
  return {
    status: "ACCESS",
    next: `${formatHHMM(access.start)}-${formatHHMM(access.end)}`,
    sortRank: 2,
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

function normalizeAccessHours(accessHours) {
  if (!Array.isArray(accessHours)) return [];
  const out = [];
  for (const access of accessHours) {
    if (!access || typeof access !== "object") continue;
    const day = typeof access.day === "string" ? access.day.toLowerCase() : null;
    const start = parseHHMM(access.start);
    const end = parseHHMM(access.end);
    const label = typeof access.label === "string" ? access.label : "Access";
    if (!day || !DAY_KEYS.includes(day) || start === null || end === null) continue;
    if (end <= start) continue;
    out.push({ day, start, end, label });
  }
  return out;
}

export function computeDetailStatus(schedule, now) {
  schedule = resolveActiveSchedule(schedule, now);
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
      closureReasonCode: typeof activeClosure.reason_code === "string" ? activeClosure.reason_code : null,
      closureKind: typeof activeClosure.kind === "string" ? activeClosure.kind : null,
      closureTransitionDate: typeof activeClosure.transition_date === "string" ? activeClosure.transition_date : null,
      closureStart: typeof activeClosure.start === "string" ? activeClosure.start : null,
      closureEnd: typeof activeClosure.end === "string" ? activeClosure.end : null,
      closureStartTime: typeof activeClosure.start_time === "string" ? activeClosure.start_time : null,
      closureEndTime: typeof activeClosure.end_time === "string" ? activeClosure.end_time : null,
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
