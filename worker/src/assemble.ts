// Compose per-spot conditions records from fetched NOAA / NDBC data,
// falling back to last-good KV values when an upstream source failed.

import { SPOTS, type SpotConfig, type TempSource, type TempStationType } from "./spots.ts";
import { fetchNoaaTemp, fetchNoaaTides, type NoaaTideData } from "./noaa.ts";
import { fetchNdbc } from "./ndbc.ts";
import { fetchUsgsTemp } from "./usgs.ts";
import { fetchErddapStationTemp, fetchMurSst } from "./erddap.ts";
import { readConditions, writeConditions } from "./kv.ts";

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
  temp_station_type: TempStationType | null;
  tide: TideSummary | null;
  updated_at: string; // ISO 8601 UTC — when this assembly ran
  temp_stale: boolean; // true if temp_* fields were reused from last-good KV value
  tide_stale: boolean; // true if `tide` was reused from last-good KV value
  temp_carried_since: string | null; // updated_at of the run that observed the carried temp; null when fresh
  tide_carried_since: string | null; // updated_at of the run that observed the carried tide; null when fresh
}

interface TempFields {
  water_temp_f: number;
  water_temp_c: number;
  temp_observed_at: string;
  temp_station_id: string;
  temp_station_type: TempStationType;
}

const NULL_TEMP_FIELDS = {
  water_temp_f: null,
  water_temp_c: null,
  temp_observed_at: null,
  temp_station_id: null,
  temp_station_type: null,
} satisfies Pick<SpotConditions, "water_temp_f" | "water_temp_c" | "temp_observed_at" | "temp_station_id" | "temp_station_type">;

export type Conditions = Record<string, SpotConditions>;

const FRESHNESS_CEILING_MS = 24 * 60 * 60 * 1000;

// Gate last-good reuse on the age of the run that actually observed the
// value (`*_carried_since`), not on the previous assembly's `updated_at`:
// `updated_at` resets every hourly run even when fields were copied forward,
// so gating on it alone would let a week-old reading look one hour old
// forever. Both timestamps are proper UTC ISO (set by `assembleAndPersist`),
// safe to parse regardless of whether individual upstream timestamps are
// zoneless (NOAA) or UTC (NDBC).
export function withinFreshnessCeiling(sinceIso: string, now: number = Date.now()): boolean {
  const ts = Date.parse(sinceIso);
  if (!Number.isFinite(ts)) return false;
  return now - ts < FRESHNESS_CEILING_MS;
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

interface TempReading {
  stationId: string;
  waterTempC: number;
  waterTempF: number;
  observedAt: string;
}

type TempFetcher = (id: string) => Promise<TempReading | null>;

const TEMP_FETCHERS: Record<TempStationType, TempFetcher> = {
  usgs: fetchUsgsTemp,
  noaa: fetchNoaaTemp,
  ndbc: fetchNdbc,
  erddap: fetchErddapStationTemp,
  sst: fetchMurSst,
};

// Walk the spot's ordered source chain; the first usable reading wins.
// A source that errors or returns null falls through to the next one, so
// a decommissioned sensor (NOAA SF/Alameda) or a dark one (the
// Exploratorium SeaBird) costs one request, not the reading.
export async function firstTempFromSources(
  slug: string,
  sources: TempSource[],
  fetchers: Record<TempStationType, TempFetcher> = TEMP_FETCHERS,
): Promise<{ reading: TempReading; sourceType: TempStationType } | null> {
  for (const source of sources) {
    try {
      const reading = await fetchers[source.type](source.id);
      if (reading) return { reading, sourceType: source.type };
    } catch (err) {
      console.error(`Temp source ${source.type}:${source.id} failed for ${slug}:`, err);
    }
  }
  return null;
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

function tempFromReading(result: { reading: TempReading; sourceType: TempStationType } | null): TempFields | null {
  if (!result) return null;
  return {
    water_temp_f: result.reading.waterTempF,
    water_temp_c: result.reading.waterTempC,
    temp_observed_at: result.reading.observedAt,
    temp_station_id: result.reading.stationId,
    temp_station_type: result.sourceType,
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

export function coalesceTemp(
  fresh: TempFields | null,
  previous: SpotConditions | null,
  now: number = Date.now(),
): { fields: TempFields | null; stale: boolean; carriedSince: string | null } {
  if (fresh !== null) return { fields: fresh, stale: false, carriedSince: null };
  const fallback = tempFromPrevious(previous);
  if (fallback && previous) {
    // Records written before carried-since tracking lack the field entirely.
    const carriedSince = previous.temp_carried_since ?? previous.updated_at;
    if (withinFreshnessCeiling(carriedSince, now)) {
      return { fields: fallback, stale: true, carriedSince };
    }
  }
  return { fields: null, stale: false, carriedSince: null };
}

export function coalesceTide(
  fresh: TideSummary | null,
  previous: SpotConditions | null,
  now: number = Date.now(),
): { value: TideSummary | null; stale: boolean; carriedSince: string | null } {
  if (fresh !== null) return { value: fresh, stale: false, carriedSince: null };
  if (previous?.tide) {
    const carriedSince = previous.tide_carried_since ?? previous.updated_at;
    if (withinFreshnessCeiling(carriedSince, now)) {
      return { value: previous.tide, stale: true, carriedSince };
    }
  }
  return { value: null, stale: false, carriedSince: null };
}

// For a single spot: fetch temp (primary path based on station type) and the
// shared NOAA tide prediction in parallel. Reuse last-good KV values on any failure.
async function assembleSpot(
  spot: SpotConfig,
  tideCache: Map<string, Promise<TideSummary | null>>,
  updatedAt: string,
  previous: SpotConditions | null,
): Promise<SpotConditions> {
  const [tempResult, tideFromApi] = await Promise.all([
    firstTempFromSources(spot.slug, spot.tempSources),
    getOrFetchTide(tideCache, spot.tideStationId),
  ]);
  const temp = coalesceTemp(tempFromReading(tempResult), previous);
  const tide = coalesceTide(tideFromApi, previous);

  return {
    slug: spot.slug,
    ...(temp.fields ?? NULL_TEMP_FIELDS),
    tide: tide.value,
    updated_at: updatedAt,
    temp_stale: temp.stale,
    tide_stale: tide.stale,
    temp_carried_since: temp.carriedSince,
    tide_carried_since: tide.carriedSince,
  };
}

// Assemble every spot and write the single conditions key.
export async function assembleAndPersist(kv: KVNamespace): Promise<Conditions> {
  const updatedAt = new Date().toISOString();
  const tideCache = new Map<string, Promise<TideSummary | null>>();
  const previous = (await readConditions(kv)) ?? {};

  const records = await Promise.all(
    SPOTS.map((spot) => assembleSpot(spot, tideCache, updatedAt, previous[spot.slug] ?? null)),
  );

  const next: Conditions = Object.fromEntries(records.map((r) => [r.slug, r]));

  try {
    await writeConditions(kv, next);
  } catch (err) {
    console.error("KV write failed:", err);
  }

  return next;
}
