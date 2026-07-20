// AUTO-GENERATED from content/spots/*.md — do not edit by hand.
// Regenerate via `node scripts/generate-worker-spots.mjs`
// (runs automatically from wrangler [build] before dev and deploy).

export type TempStationType = "usgs" | "noaa" | "ndbc" | "erddap" | "sst";

export interface TempSource {
  type: TempStationType;
  id: string;
}

export interface SpotConfig {
  slug: string;
  tempSources: TempSource[];
  tideStationId: string;
}

export const SPOTS: SpotConfig[] = [
  {
    slug: "aquatic-park",
    tempSources: [
      { type: "usgs", id: "374938122251801" },
      { type: "noaa", id: "9414863" },
      { type: "erddap", id: "exploratorium-seabird" },
      { type: "sst", id: "37.81,-122.43" },
    ],
    tideStationId: "9414290",
  },
  {
    slug: "baker-beach",
    tempSources: [
      { type: "ndbc", id: "46237" },
      { type: "sst", id: "37.78,-122.55" },
    ],
    tideStationId: "9414275",
  },
  {
    slug: "china-beach",
    tempSources: [
      { type: "ndbc", id: "46237" },
      { type: "sst", id: "37.79,-122.50" },
    ],
    tideStationId: "9414275",
  },
  {
    slug: "crissy-field",
    tempSources: [
      { type: "usgs", id: "374938122251801" },
      { type: "noaa", id: "9414863" },
      { type: "erddap", id: "exploratorium-seabird" },
      { type: "sst", id: "37.81,-122.45" },
    ],
    tideStationId: "9414290",
  },
  {
    slug: "ocean-beach",
    tempSources: [
      { type: "ndbc", id: "46237" },
      { type: "sst", id: "37.76,-122.52" },
    ],
    tideStationId: "9414275",
  },
];
