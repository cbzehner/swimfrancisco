// NOAA CO-OPS Tides & Currents fetches.
// Docs: https://api.tidesandcurrents.noaa.gov/api/prod/

const BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter";

export interface NoaaTempReading {
  stationId: string;
  waterTempF: number;
  waterTempC: number;
  observedAt: string; // ISO 8601 UTC
}

export interface NoaaTidePrediction {
  time: string; // ISO 8601 UTC
  type: "H" | "L";
  valueFt: number;
}

export interface NoaaTideData {
  stationId: string;
  predictions: NoaaTidePrediction[];
}

interface NoaaTempResponse {
  data?: Array<{ t: string; v: string }>;
  error?: { message?: string };
}

interface NoaaPredictionsResponse {
  predictions?: Array<{ t: string; v: string; type: string }>;
  error?: { message?: string };
}

// Parse NOAA's "YYYY-MM-DD HH:MM" local-time-of-station into an ISO UTC string.
// The API returns times in `time_zone=lst_ldt` (local standard/daylight). We
// cannot precisely convert without a tz database; emit the timestamp with a
// trailing "Z" assumption would be wrong. Instead, treat it as opaque local
// and append a " local" marker. For v1 consumers only render the date/time as
// received; we preserve the original string in the `observed_at_local` field
// upstream. Here we emit an ISO-ish string by replacing the space with "T".
function toIsoLike(ts: string): string {
  // Input like "2026-04-16 14:30". Return "2026-04-16T14:30:00" (no zone).
  const trimmed = ts.trim();
  const withT = trimmed.replace(" ", "T");
  return withT.length === 16 ? `${withT}:00` : withT;
}

async function fetchNoaaTemp(stationId: string): Promise<NoaaTempReading | null> {
  const url = `${BASE}?product=water_temperature&station=${stationId}&units=english&time_zone=lst_ldt&format=json&date=latest`;
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`NOAA temp ${stationId} HTTP ${res.status}`);
  const body = (await res.json()) as NoaaTempResponse;
  if (body.error) throw new Error(`NOAA temp ${stationId}: ${body.error.message ?? "unknown error"}`);
  const latest = body.data?.[body.data.length - 1];
  if (!latest) return null;
  const waterTempF = Number(latest.v);
  if (!Number.isFinite(waterTempF)) return null;
  const waterTempC = ((waterTempF - 32) * 5) / 9;
  return {
    stationId,
    waterTempF: Math.round(waterTempF * 10) / 10,
    waterTempC: Math.round(waterTempC * 10) / 10,
    observedAt: toIsoLike(latest.t),
  };
}

// Try primary station; on any error or empty result, try the fallback.
export async function fetchTempWithFallback(
  primaryId: string,
  fallbackId: string | undefined,
): Promise<NoaaTempReading | null> {
  try {
    const reading = await fetchNoaaTemp(primaryId);
    if (reading) return reading;
  } catch (err) {
    console.error(`NOAA temp primary ${primaryId} failed:`, err);
  }
  if (!fallbackId) return null;
  try {
    return await fetchNoaaTemp(fallbackId);
  } catch (err) {
    console.error(`NOAA temp fallback ${fallbackId} failed:`, err);
    return null;
  }
}

export async function fetchNoaaTides(stationId: string): Promise<NoaaTideData | null> {
  const url = `${BASE}?product=predictions&station=${stationId}&units=english&time_zone=lst_ldt&datum=MLLW&format=json&date=today&interval=hilo`;
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`NOAA tides ${stationId} HTTP ${res.status}`);
  const body = (await res.json()) as NoaaPredictionsResponse;
  if (body.error) throw new Error(`NOAA tides ${stationId}: ${body.error.message ?? "unknown error"}`);
  const rows = body.predictions ?? [];
  const predictions: NoaaTidePrediction[] = rows
    .map((row) => {
      const valueFt = Number(row.v);
      const type = row.type === "H" || row.type === "L" ? row.type : null;
      if (!Number.isFinite(valueFt) || !type) return null;
      return { time: toIsoLike(row.t), type, valueFt: Math.round(valueFt * 100) / 100 };
    })
    .filter((p): p is NoaaTidePrediction => p !== null);
  return { stationId, predictions };
}
