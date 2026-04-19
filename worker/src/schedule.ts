// Pure dispatch for the Worker `scheduled` handler. Given a cron tick's
// scheduledTime (ms since epoch, UTC), returns which branch should run.
// Extracted so the DST-sensitive PT-hour + UTC-minute logic is unit-testable
// without stubbing the Worker runtime.
export type TickKind = "rebuild" | "refresh";

export function classifyTick(scheduledTime: number): TickKind {
  const at = new Date(scheduledTime);
  const ptHour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      hour12: false,
    }).format(at),
  );
  const minute = at.getUTCMinutes();
  return ptHour === 0 && minute === 5 ? "rebuild" : "refresh";
}
