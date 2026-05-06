// AUTO-GENERATED from content/spots/*.md — do not edit by hand.
// Regenerate via `node scripts/generate-worker-spots.mjs`
// (runs automatically from wrangler [build] before dev and deploy).

export type TempStationType = "noaa" | "ndbc";

export interface SpotConfig {
  slug: string;
  title: string;
  tempStationId: string;
  tempStationType: TempStationType;
  tempFallbackStationId?: string;
  tideStationId: string;
}

export const SPOTS: SpotConfig[] = [
  {
    slug: "aquatic-park",
    title: "Aquatic Park",
    tempStationId: "9414290",
    tempStationType: "noaa",
    tempFallbackStationId: "9414750",
    tideStationId: "9414290",
  },
  {
    slug: "baker-beach",
    title: "Baker Beach",
    tempStationId: "46237",
    tempStationType: "ndbc",
    tideStationId: "9414275",
  },
  {
    slug: "china-beach",
    title: "China Beach",
    tempStationId: "46237",
    tempStationType: "ndbc",
    tideStationId: "9414275",
  },
  {
    slug: "crissy-field",
    title: "Crissy Field / East Beach",
    tempStationId: "9414290",
    tempStationType: "noaa",
    tempFallbackStationId: "9414750",
    tideStationId: "9414290",
  },
  {
    slug: "ocean-beach",
    title: "Ocean Beach",
    tempStationId: "46237",
    tempStationType: "ndbc",
    tideStationId: "9414275",
  },
];
