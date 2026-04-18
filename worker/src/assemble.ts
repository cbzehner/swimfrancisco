// Compose per-spot conditions records from fetched NOAA / NDBC data,
// falling back to last-good KV values when an upstream source failed.

import { SPOTS, type SpotConfig } from "./spots";
import { fetchTempWithFallback, fetchNoaaTides, type NoaaTideData } from "./noaa";
import { fetchNdbc } from "./ndbc";
import { readSpot, writeSpot, writeAll } from "./kv";

export interface TideSummary {
  station_id: string;
  predictions: Array<{ time: string; type: "H" | "L"; value_ft: number }>;
}

export interface SpotConditions {
  slug: string;
  water_temp_f: number | null;
  water_temp_c: number | null;
  temp_observed_at: string | null;
  temp_station_id: string | null;
  temp_station_type: "noaa" | "ndbc" | null;
  tide: TideSummary | null;
  updated_at: string; // ISO 8601 UTC — when this assembly ran
  stale: boolean; // true if any field reused from last-good KV value
}

export type AllConditions = Record<string, SpotConditions>;

const FRESHNESS_CEILING_MS = 24 * 60 * 60 * 1000;

// Gate all last-good reuse on assembly age. `updated_at` is always a proper
// UTC ISO (set by `assembleAndPersist`), safe to parse regardless of whether
// individual upstream timestamps are zoneless (NOAA) or UTC (NDBC).
function isFreshEnough(previous: SpotConditions | null): boolean {
  if (!previous) return false;
  const ts = Date.parse(previous.updated_at);
  if (!Number.isFinite(ts)) return false;
  return Date.now() - ts < FRESHNESS_CEILING_MS;
}

function tideToSummary(data: NoaaTideData | null): TideSummary | null {
  if (!data) return null;
  return {
    station_id: data.stationId,
    predictions: data.predictions.map((p) => ({
      time: p.time,
      type: p.type,
      value_ft: p.valueFt,
    })),
  };
}

async function fetchTempForSpot(spot: SpotConfig) {
  try {
    return spot.tempStationType === "noaa"
      ? await fetchTempWithFallback(spot.tempStationId, spot.tempFallbackStationId)
      : await fetchNdbc(spot.tempStationId);
  } catch (err) {
    console.error(`Temp fetch failed for ${spot.slug}:`, err);
    return null;
  }
}

function getOrFetchTide(
  tideCache: Map<string, Promise<TideSummary | null>>,
  stationId: string,
): Promise<TideSummary | null> {
  const cached = tideCache.get(stationId);
  if (cached) return cached;
  const promise = fetchNoaaTides(stationId)
    .then(tideToSummary)
    .catch((err) => {
      console.error(`Tide fetch failed for station ${stationId}:`, err);
      return null;
    });
  tideCache.set(stationId, promise);
  return promise;
}

// For a single spot: fetch temp (primary path based on station type) and the
// shared NOAA tide prediction in parallel. Reuse last-good KV values on any failure.
async function assembleSpot(
  spot: SpotConfig,
  tideCache: Map<string, Promise<TideSummary | null>>,
  updatedAt: string,
  kv: KVNamespace,
): Promise<SpotConditions> {
  const [previous, reading, tideFromApi] = await Promise.all([
    readSpot(kv, spot.slug),
    fetchTempForSpot(spot),
    getOrFetchTide(tideCache, spot.tideStationId),
  ]);
  const fresh = isFreshEnough(previous);
  let stale = false;

  let waterTempF: number | null = reading?.waterTempF ?? null;
  let waterTempC: number | null = reading?.waterTempC ?? null;
  let tempObservedAt: string | null = reading?.observedAt ?? null;
  let tempStationId: string | null = reading?.stationId ?? null;

  if (waterTempF === null && previous && fresh) {
    waterTempF = previous.water_temp_f;
    waterTempC = previous.water_temp_c;
    tempObservedAt = previous.temp_observed_at;
    tempStationId = previous.temp_station_id;
    stale = previous.water_temp_f !== null;
  }

  let tide: TideSummary | null = tideFromApi;
  if (tide === null && previous?.tide && fresh) {
    tide = previous.tide;
    stale = true;
  }

  return {
    slug: spot.slug,
    water_temp_f: waterTempF,
    water_temp_c: waterTempC,
    temp_observed_at: tempObservedAt,
    temp_station_id: tempStationId,
    temp_station_type: tempStationId ? spot.tempStationType : null,
    tide,
    updated_at: updatedAt,
    stale,
  };
}

// Assemble every spot, write per-slug keys and the `all` bulk key.
export async function assembleAndPersist(kv: KVNamespace): Promise<AllConditions> {
  const updatedAt = new Date().toISOString();
  const tideCache = new Map<string, Promise<TideSummary | null>>();

  const records = await Promise.all(
    SPOTS.map(async (spot) => {
      const record = await assembleSpot(spot, tideCache, updatedAt, kv);
      try {
        await writeSpot(kv, spot.slug, record);
      } catch (err) {
        console.error(`KV write failed for ${spot.slug}:`, err);
      }
      return record;
    }),
  );

  const all: AllConditions = Object.fromEntries(records.map((r) => [r.slug, r]));

  try {
    await writeAll(kv, all);
  } catch (err) {
    console.error("KV write failed for `all`:", err);
  }

  return all;
}
