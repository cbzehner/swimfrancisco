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

// Temp fields are flat (water_temp_f / water_temp_c / temp_observed_at /
// temp_station_id) — the public /api/conditions JSON shape that
// static/js/conditions.js consumes. They are either all set or all null
// (no partial reading); use temp_stale to know whether they were reused
// from the last-good KV value.
export interface SpotConditions {
  slug: string;
  water_temp_f: number | null;
  water_temp_c: number | null;
  temp_observed_at: string | null;
  temp_station_id: string | null;
  temp_station_type: "noaa" | "ndbc" | null;
  tide: TideSummary | null;
  updated_at: string; // ISO 8601 UTC — when this assembly ran
  temp_stale: boolean; // true if temp_* fields were reused from last-good KV value
  tide_stale: boolean; // true if `tide` was reused from last-good KV value
}

interface TempFields {
  water_temp_f: number;
  water_temp_c: number;
  temp_observed_at: string;
  temp_station_id: string;
  temp_station_type: "noaa" | "ndbc";
}

const NULL_TEMP_FIELDS = {
  water_temp_f: null,
  water_temp_c: null,
  temp_observed_at: null,
  temp_station_id: null,
  temp_station_type: null,
} satisfies Pick<SpotConditions, "water_temp_f" | "water_temp_c" | "temp_observed_at" | "temp_station_id" | "temp_station_type">;

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

function tempFromReading(spot: SpotConfig, reading: { waterTempF: number; waterTempC: number; observedAt: string; stationId: string } | null): TempFields | null {
  if (!reading) return null;
  return {
    water_temp_f: reading.waterTempF,
    water_temp_c: reading.waterTempC,
    temp_observed_at: reading.observedAt,
    temp_station_id: reading.stationId,
    temp_station_type: spot.tempStationType,
  };
}

function tempFromPrevious(previous: SpotConditions | null): TempFields | null {
  if (!previous) return null;
  const { water_temp_f, water_temp_c, temp_observed_at, temp_station_id, temp_station_type } = previous;
  if (
    water_temp_f === null ||
    water_temp_c === null ||
    temp_observed_at === null ||
    temp_station_id === null ||
    temp_station_type === null
  ) {
    return null;
  }
  return { water_temp_f, water_temp_c, temp_observed_at, temp_station_id, temp_station_type };
}

function coalesceTemp(
  fresh: TempFields | null,
  previous: SpotConditions | null,
  previousIsFresh: boolean,
): { fields: TempFields | null; stale: boolean } {
  if (fresh !== null) return { fields: fresh, stale: false };
  if (previousIsFresh) {
    const fallback = tempFromPrevious(previous);
    if (fallback) return { fields: fallback, stale: true };
  }
  return { fields: null, stale: false };
}

function coalesceTide(
  fresh: TideSummary | null,
  previous: SpotConditions | null,
  previousIsFresh: boolean,
): { value: TideSummary | null; stale: boolean } {
  if (fresh !== null) return { value: fresh, stale: false };
  if (previousIsFresh && previous?.tide) return { value: previous.tide, stale: true };
  return { value: null, stale: false };
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
  const previousIsFresh = isFreshEnough(previous);
  const temp = coalesceTemp(tempFromReading(spot, reading), previous, previousIsFresh);
  const tide = coalesceTide(tideFromApi, previous, previousIsFresh);

  return {
    slug: spot.slug,
    ...(temp.fields ?? NULL_TEMP_FIELDS),
    tide: tide.value,
    updated_at: updatedAt,
    temp_stale: temp.stale,
    tide_stale: tide.stale,
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
