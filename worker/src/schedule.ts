// Pure helper for the Worker `scheduled` handler. Returns true when the
// hourly cron tick lands at 00:00 PT — the moment the daily rebuild should
// also fire. `Intl.DateTimeFormat` with `America/Los_Angeles` handles the
// PST/PDT shift transparently, so the caller doesn't need DST awareness.
// Extracted so it can be unit-tested without stubbing the Worker runtime.

export function isPtMidnight(scheduledTime: number): boolean {
  const ptHour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      hour12: false,
    }).format(new Date(scheduledTime)),
  );
  return ptHour === 0;
}
