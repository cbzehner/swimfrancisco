// ERDDAP fetches for two source kinds:
//
// - Station (tabledap): IOOS sensors ERDDAP datasets such as
//   `exploratorium-seabird` (the Wired Pier SeaBird CTD at Pier 15).
//   Constrained to the last 24 h so a dead sensor yields null instead of
//   months-old data. ERDDAP answers an EMPTY result set with HTTP 404
//   ("nRows = 0") — that is "no data", not an error.
//
// - Satellite SST (griddap): NASA JPL MUR 0.01° daily analysed SST via
//   NOAA CoastWatch. Station id encodes the grid point as "lat,lon";
//   pick water cells (nearshore land cells return null). ~1 day latency,
//   known cold bias inside the bay — last-resort layer only.

const STATION_BASE = "https://erddap.sensors.ioos.us/erddap/tabledap";
const SST_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.json";
const FETCH_TIMEOUT_MS = 10_000;

export interface ErddapReading {
  stationId: string;
  waterTempC: number;
  waterTempF: number;
  observedAt: string; // ISO 8601 UTC
}

interface ErddapTable {
  table?: {
    columnNames?: string[];
    rows?: Array<Array<string | number | null>>;
  };
}

function reading(stationId: string, waterTempC: number, observedAt: string): ErddapReading {
  const waterTempF = (waterTempC * 9) / 5 + 32;
  return {
    stationId,
    waterTempC: Math.round(waterTempC * 10) / 10,
    waterTempF: Math.round(waterTempF * 10) / 10,
    observedAt,
  };
}

async function erddapGet(label: string, url: string): Promise<ErddapTable | null> {
  const res = await fetch(url, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (res.status === 404) {
    // Distinguish "query matched nothing" from a genuinely missing dataset:
    // both are 404, but the empty-result body names nRows.
    const body = await res.text();
    if (body.includes("nRows = 0") || body.includes("no matching results")) return null;
    throw new Error(`${label} HTTP 404: ${body.slice(0, 120)}`);
  }
  if (!res.ok) throw new Error(`${label} HTTP ${res.status}`);
  return (await res.json()) as ErddapTable;
}

export async function fetchErddapStationTemp(datasetId: string): Promise<ErddapReading | null> {
  const query =
    'time,sea_water_temperature&time>=now-1day&sea_water_temperature!=NaN&orderByMax("time")';
  const body = await erddapGet(
    `ERDDAP ${datasetId}`,
    `${STATION_BASE}/${datasetId}.json?${encodeURI(query).replace(/"/g, "%22")}`,
  );
  const row = body?.table?.rows?.[0];
  if (!row) return null;
  const [time, temp] = row;
  const waterTempC = Number(temp);
  if (typeof time !== "string" || !Number.isFinite(waterTempC)) return null;
  return reading(datasetId, waterTempC, time);
}

export async function fetchMurSst(gridPoint: string): Promise<ErddapReading | null> {
  const [lat, lon] = gridPoint.split(",").map((part) => Number(part.trim()));
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error(`SST grid point must be "lat,lon", got: ${gridPoint}`);
  }
  const query = `analysed_sst[(last)][(${lat}):(${lat})][(${lon}):(${lon})]`;
  const body = await erddapGet(`MUR SST ${gridPoint}`, `${SST_BASE}?${encodeURIComponent(query)}`);
  const row = body?.table?.rows?.[0];
  if (!row) return null;
  const [time, , , sst] = row;
  const waterTempC = Number(sst);
  if (typeof time !== "string" || sst === null || !Number.isFinite(waterTempC)) return null;
  return reading(gridPoint, waterTempC, time);
}
