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

// For a single spot: fetch temp (primary path based on station type) and the
// shared NOAA tide prediction. Reuse last-good KV values on any failure.
async function assembleSpot(
  spot: SpotConfig,
  tideCache: Map<string, TideSummary | null>,
  updatedAt: string,
  kv: KVNamespace,
): Promise<SpotConditions> {
  const previous = await readSpot(kv, spot.slug);
  let stale = false;

  // Temperature
  let waterTempF: number | null = null;
  let waterTempC: number | null = null;
  let tempObservedAt: string | null = null;
  let tempStationId: string | null = null;
  const tempStationType: "noaa" | "ndbc" = spot.tempStationType;

  try {
    if (spot.tempStationType === "noaa") {
      const reading = await fetchTempWithFallback(spot.tempStationId, spot.tempFallbackStationId);
      if (reading) {
        waterTempF = reading.waterTempF;
        waterTempC = reading.waterTempC;
        tempObservedAt = reading.observedAt;
        tempStationId = reading.stationId;
      }
    } else {
      const reading = await fetchNdbc(spot.tempStationId);
      if (reading) {
        waterTempF = reading.waterTempF;
        waterTempC = reading.waterTempC;
        tempObservedAt = reading.observedAt;
        tempStationId = reading.stationId;
      }
    }
  } catch (err) {
    console.error(`Temp fetch failed for ${spot.slug}:`, err);
  }

  if (waterTempF === null && previous) {
    waterTempF = previous.water_temp_f;
    waterTempC = previous.water_temp_c;
    tempObservedAt = previous.temp_observed_at;
    tempStationId = previous.temp_station_id;
    stale = stale || previous.water_temp_f !== null;
  }

  // Tide — cache per station to avoid refetching the shared 9414290 station.
  let tide: TideSummary | null = null;
  if (tideCache.has(spot.tideStationId)) {
    tide = tideCache.get(spot.tideStationId) ?? null;
  } else {
    try {
      const data = await fetchNoaaTides(spot.tideStationId);
      tide = tideToSummary(data);
    } catch (err) {
      console.error(`Tide fetch failed for station ${spot.tideStationId}:`, err);
      tide = null;
    }
    tideCache.set(spot.tideStationId, tide);
  }

  if (tide === null && previous?.tide) {
    tide = previous.tide;
    stale = true;
  }

  return {
    slug: spot.slug,
    water_temp_f: waterTempF,
    water_temp_c: waterTempC,
    temp_observed_at: tempObservedAt,
    temp_station_id: tempStationId,
    temp_station_type: tempStationId ? tempStationType : null,
    tide,
    updated_at: updatedAt,
    stale,
  };
}

// Assemble every spot, write per-slug keys and the `all` bulk key.
export async function assembleAndPersist(kv: KVNamespace): Promise<AllConditions> {
  const updatedAt = new Date().toISOString();
  const tideCache = new Map<string, TideSummary | null>();
  const all: AllConditions = {};

  for (const spot of SPOTS) {
    const record = await assembleSpot(spot, tideCache, updatedAt, kv);
    all[spot.slug] = record;
    try {
      await writeSpot(kv, spot.slug, record);
    } catch (err) {
      console.error(`KV write failed for ${spot.slug}:`, err);
    }
  }

  try {
    await writeAll(kv, all);
  } catch (err) {
    console.error("KV write failed for `all`:", err);
  }

  return all;
}
