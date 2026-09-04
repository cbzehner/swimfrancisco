#!/usr/bin/env node
// Generates worker/src/spots.ts from content/spots/*.md frontmatter so the
// open-water spot → station mapping has a single source of truth. The output
// is committed; `npm run typecheck` (worker/) regenerates it first and
// tests/test_worker_spots.py fails on drift.

import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { listCanonicalSpotFiles, parseOpenWaterStations } from "./lib/spot-frontmatter.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const spotsDir = join(repoRoot, "content/spots");
const outputPath = join(repoRoot, "worker/src/spots.ts");

function renderSpot(spot) {
  const lines = ["  {"];
  lines.push(`    slug: ${JSON.stringify(spot.slug)},`);
  lines.push("    tempSources: [");
  for (const source of spot.tempSources) {
    lines.push(`      { type: ${JSON.stringify(source.type)}, id: ${JSON.stringify(source.id)} },`);
  }
  lines.push("    ],");
  lines.push(`    tideStationId: ${JSON.stringify(spot.tideStationId)},`);
  lines.push("  },");
  return lines.join("\n");
}

async function main() {
  const files = await listCanonicalSpotFiles(spotsDir);
  const spots = [];
  for (const { filePath, front } of files) {
    const extra = front.extra || {};
    if (extra.type !== "open_water") continue;
    const stations = parseOpenWaterStations(extra, filePath);
    spots.push({
      slug: front.slug,
      tempSources: stations.temp_sources,
      tideStationId: stations.noaa_tide_station,
    });
  }
  if (spots.length === 0) {
    throw new Error("Found zero open-water spots — refusing to overwrite worker/src/spots.ts");
  }

  const body = [
    "// AUTO-GENERATED from content/spots/*.md — do not edit by hand.",
    "// Regenerate via `node scripts/generate-worker-spots.mjs`",
    "// (also runs before `npm run typecheck` in worker/).",
    "",
    'export type TempStationType = "usgs" | "noaa" | "ndbc" | "erddap" | "sst";',
    "",
    "export interface TempSource {",
    "  type: TempStationType;",
    "  id: string;",
    "}",
    "",
    "export interface SpotConfig {",
    "  slug: string;",
    "  tempSources: TempSource[];",
    "  tideStationId: string;",
    "}",
    "",
    "export const SPOTS: SpotConfig[] = [",
    spots.map(renderSpot).join("\n"),
    "];",
    "",
  ].join("\n");

  await writeFile(outputPath, body);
  console.log(`Wrote ${spots.length} spots to ${outputPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
