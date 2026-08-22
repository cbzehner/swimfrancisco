// NDBC realtime2 parser — fixed-width text format.
// Example header:
//   #YY  MM DD hh mm WDIR WSPD GST  WVHT ... WTMP ...
//   #yr  mo dy hr mn degT m/s  m/s  m ...  degC ...
// Data rows: "2026 04 16 18 20 270 ... 12.3 ..."
// Column 14 (0-indexed) is WTMP in Celsius; "MM" means missing.

import { readingFromC, type TempReading } from "./temp.ts";

// observedAt is ISO 8601 UTC.
export type NdbcReading = TempReading;

function parseTimestampUtc(year: string, mo: string, dy: string, hr: string, mn: string): string | null {
  const y = Number(year);
  const m = Number(mo);
  const d = Number(dy);
  const h = Number(hr);
  const min = Number(mn);
  if ([y, m, d, h, min].some((n) => !Number.isFinite(n))) return null;
  const date = new Date(Date.UTC(y, m - 1, d, h, min, 0));
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

const FETCH_TIMEOUT_MS = 10_000;

export async function fetchNdbc(stationId: string): Promise<NdbcReading | null> {
  const url = `https://www.ndbc.noaa.gov/data/realtime2/${stationId}.txt`;
  const res = await fetch(url, { headers: { accept: "text/plain" }, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
  if (!res.ok) throw new Error(`NDBC ${stationId} HTTP ${res.status}`);
  const text = await res.text();
  const lines = text.split("\n");

  // First non-comment line is the newest observation.
  let headerCols: string[] | null = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("#")) {
      if (headerCols === null) {
        headerCols = line.replace(/^#/, "").trim().split(/\s+/);
      }
      continue;
    }
    const cols = line.split(/\s+/);
    if (cols.length < 15) continue;
    const wtmpIdx = headerCols ? headerCols.indexOf("WTMP") : 14;
    const idx = wtmpIdx >= 0 ? wtmpIdx : 14;
    const wtmpRaw = cols[idx];
    if (!wtmpRaw || wtmpRaw === "MM") continue;
    const waterTempC = Number(wtmpRaw);
    if (!Number.isFinite(waterTempC)) continue;
    const observedAt = parseTimestampUtc(cols[0], cols[1], cols[2], cols[3], cols[4]);
    if (!observedAt) continue;
    return readingFromC(stationId, waterTempC, observedAt);
  }
  return null;
}
