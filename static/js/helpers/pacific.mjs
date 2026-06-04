const PACIFIC_TIME_ZONE = "America/Los_Angeles";

// Return a Date whose local getters (getFullYear, getMonth, getDate, getDay,
// getHours, getMinutes, getSeconds) reflect the wall-clock in Pacific time.
// The returned Date's absolute instant is intentionally synthetic; use it only
// for local schedule/tide comparisons, not display formatting.
export function pacificWallClockDate(instant) {
  const source = instant instanceof Date ? instant : new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC_TIME_ZONE,
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

export function formatPacificDate(instant) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC_TIME_ZONE,
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(instant);
}

export function formatPacificTime(instant) {
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC_TIME_ZONE,
    hour: "numeric",
    minute: "2-digit",
  }).format(instant);
  return `${time} PT`;
}
