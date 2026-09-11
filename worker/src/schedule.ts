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
      // Some ICU builds render midnight as "24" under hour12:false; h23
      // pins the cycle to 00-23 so the equality below is portable.
      hourCycle: "h23",
    }).format(new Date(scheduledTime)),
  );
  return ptHour === 0;
}
