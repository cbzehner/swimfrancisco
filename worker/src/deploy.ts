// Fires the Workers Builds deploy hook to rebuild the site.
// Called daily by the Worker cron so date-tick-over fields (today's
// weekday, closure freshness window, server-rendered freshness dot)
// stay correct. The hook URL is the secret — no auth header needed.
// Logs scheduled time and response status so a silent 5xx surfaces
// in `wrangler tail`.
export async function triggerRebuild(
  hookUrl: string,
  scheduledTime: number,
): Promise<void> {
  const response = await fetch(hookUrl, { method: "POST" });
  console.log(
    `daily-rebuild scheduledTime=${new Date(scheduledTime).toISOString()} status=${response.status}`,
  );
  if (!response.ok) {
    throw new Error(`deploy hook returned ${response.status}`);
  }
}
