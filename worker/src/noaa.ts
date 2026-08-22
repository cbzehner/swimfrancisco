// NOAA CO-OPS Tides & Currents fetches.
// Docs: https://api.tidesandcurrents.noaa.gov/api/prod/

import { readingFromF, type TempReading } from "./temp.ts";

const BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter";
const APPLICATION = "SwimFrancisco";
const FETCH_TIMEOUT_MS = 10_000;

// observedAt is station-local time, zoneless ISO (NOAA lst_ldt).
export type NoaaTempReading = TempReading;

export interface NoaaTidePrediction {
  time: string; // Station-local time, zoneless ISO (NOAA lst_ldt)
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

// Normalize NOAA's "YYYY-MM-DD HH:MM" station-local timestamp into an
// ISO-like form "YYYY-MM-DDTHH:MM:SS" (no trailing zone). We do NOT assume
// UTC — the API returns `time_zone=lst_ldt` (local standard / daylight) and
// we lack a tz database to convert precisely. Downstream consumers tolerate
// zoneless strings.
export function toLocalIso(ts: string): string {
  // Input like "2026-04-16 14:30". Return "2026-04-16T14:30:00" (no zone).
  const trimmed = ts.trim();
  const withT = trimmed.replace(" ", "T");
  return withT.length === 16 ? `${withT}:00` : withT;
}

async function noaaGet<T extends { error?: { message?: string } }>(
  label: string,
  stationId: string,
  params: Record<string, string>,
): Promise<T> {
  const query = new URLSearchParams({
    station: stationId,
    units: "english",
    time_zone: "lst_ldt",
    format: "json",
    application: APPLICATION,
    ...params,
  });
  const res = await fetch(`${BASE}?${query}`, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`${label} ${stationId} HTTP ${res.status}`);
  const body = (await res.json()) as T;
  if (body.error) throw new Error(`${label} ${stationId}: ${body.error.message ?? "unknown error"}`);
  return body;
}

export async function fetchNoaaTemp(stationId: string): Promise<NoaaTempReading | null> {
  const body = await noaaGet<NoaaTempResponse>("NOAA temp", stationId, {
    product: "water_temperature",
    date: "latest",
  });
  const latest = body.data?.[body.data.length - 1];
  if (!latest) return null;
  const waterTempF = Number(latest.v);
  if (!Number.isFinite(waterTempF)) return null;
  return readingFromF(stationId, waterTempF, toLocalIso(latest.t));
}

// YYYYMMDD in America/Los_Angeles — all our stations are Pacific, so we
// anchor the tide window to the station-local calendar day. Using the
// Worker's UTC date would silently skip up to 7 hours of predictions
// during PT evenings (when UTC has already rolled to "tomorrow").
function stationLocalDateYmd(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(new Date()).replace(/-/g, "");
}

export async function fetchNoaaTides(stationId: string): Promise<NoaaTideData | null> {
  // 48-hour window forward from station-local today-midnight. Covers
  // today + tomorrow of hi/lo predictions so the client always has at
  // least one future entry no matter the hour of day.
  const body = await noaaGet<NoaaPredictionsResponse>("NOAA tides", stationId, {
    product: "predictions",
    datum: "MLLW",
    begin_date: stationLocalDateYmd(),
    range: "48",
    interval: "hilo",
  });
  const rows = body.predictions ?? [];
  const predictions: NoaaTidePrediction[] = rows
    .map((row) => {
      const valueFt = Number(row.v);
      const type = row.type === "H" || row.type === "L" ? row.type : null;
      if (!Number.isFinite(valueFt) || !type) return null;
      return { time: toLocalIso(row.t), type, valueFt: Math.round(valueFt * 100) / 100 };
    })
    .filter((p): p is NoaaTidePrediction => p !== null);
  return { stationId, predictions };
}
