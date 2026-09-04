// USGS NWIS instantaneous-values fetch. The SF Bay water-quality network
// (eight real-time stations, e.g. Alcatraz NE shore 374938122251801)
// reports water temperature as parameter 00010 in °C.
// Docs: https://waterservices.usgs.gov/docs/instantaneous-values/

import { readingFromC, type TempReading } from "./temp.ts";

const BASE = "https://waterservices.usgs.gov/nwis/iv/";
const FETCH_TIMEOUT_MS = 10_000;
// USGS marks missing/invalid readings with large negative sentinels.
const MISSING_SENTINEL_CEILING = -100;

interface NwisResponse {
  value?: {
    timeSeries?: Array<{
      values?: Array<{ value?: Array<{ value: string; dateTime: string }> }>;
    }>;
  };
}

// observedAt is ISO 8601 with UTC offset, as reported by NWIS.
export async function fetchUsgsTemp(stationId: string): Promise<TempReading | null> {
  const query = new URLSearchParams({
    sites: stationId,
    parameterCd: "00010",
    period: "PT4H",
    format: "json",
  });
  const res = await fetch(`${BASE}?${query}`, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`USGS ${stationId} HTTP ${res.status}`);
  const body = (await res.json()) as NwisResponse;

  for (const series of body.value?.timeSeries ?? []) {
    for (const block of series.values ?? []) {
      const points = block.value ?? [];
      for (let i = points.length - 1; i >= 0; i--) {
        const waterTempC = Number(points[i].value);
        if (!Number.isFinite(waterTempC) || waterTempC <= MISSING_SENTINEL_CEILING) continue;
        return readingFromC(stationId, waterTempC, points[i].dateTime);
      }
    }
  }
  return null;
}
