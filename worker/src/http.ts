// Shared fetch plumbing for the upstream conditions sources. One timeout and
// one `!res.ok` throw live here so each source module only parses its own
// payload. Sources that need the body of an error response (ERDDAP answers an
// empty result set with 404) use `fetchWithTimeout` and inspect it themselves.

const FETCH_TIMEOUT_MS = 10_000;

export function fetchWithTimeout(url: string, accept: string): Promise<Response> {
  return fetch(url, { headers: { accept }, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
}

export async function fetchJson(label: string, url: string, accept = "application/json"): Promise<unknown> {
  const res = await fetchWithTimeout(url, accept);
  if (!res.ok) throw new Error(`${label} HTTP ${res.status}`);
  return res.json();
}

export async function fetchText(label: string, url: string, accept = "text/plain"): Promise<string> {
  const res = await fetchWithTimeout(url, accept);
  if (!res.ok) throw new Error(`${label} HTTP ${res.status}`);
  return res.text();
}
