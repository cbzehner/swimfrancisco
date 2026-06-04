const PACIFIC_TIME_ZONE = "America/Los_Angeles";

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
