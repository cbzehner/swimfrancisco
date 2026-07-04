#!/usr/bin/env node
// Generates worker/src/spots.ts from content/spots/*.md frontmatter so the
// open-water spot → station mapping has a single source of truth. Runs from
// wrangler's [build] hook before dev/deploy and from `npm run typecheck`.

import { readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { readSpotFrontmatter } from "./lib/spot-frontmatter.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const spotsDir = join(repoRoot, "content/spots");
const outputPath = join(repoRoot, "worker/src/spots.ts");

async function readSpot(path) {
  const { front } = await readSpotFrontmatter(path);
  const extra = front.extra || {};
  if (extra.type !== "open_water") return null;

  const spot = {
    slug: front.slug,
    tempStationId: extra.temp_station_id,
    tempStationType: extra.temp_station_type,
    tempFallbackStationId: extra.temp_fallback_station_id,
    tideStationId: extra.noaa_tide_station,
  };

  for (const key of ["slug", "tempStationId", "tempStationType", "tideStationId"]) {
    if (!spot[key]) throw new Error(`${path}: missing required field ${key}`);
  }
  if (spot.tempStationType !== "noaa" && spot.tempStationType !== "ndbc") {
    throw new Error(`${path}: temp_station_type must be "noaa" or "ndbc"`);
  }
  return spot;
}

function renderSpot(spot) {
  const lines = ["  {"];
  lines.push(`    slug: ${JSON.stringify(spot.slug)},`);
  lines.push(`    tempStationId: ${JSON.stringify(spot.tempStationId)},`);
  lines.push(`    tempStationType: ${JSON.stringify(spot.tempStationType)},`);
  if (spot.tempFallbackStationId) {
    lines.push(`    tempFallbackStationId: ${JSON.stringify(spot.tempFallbackStationId)},`);
  }
  lines.push(`    tideStationId: ${JSON.stringify(spot.tideStationId)},`);
  lines.push("  },");
  return lines.join("\n");
}

async function main() {
  const entries = (await readdir(spotsDir))
    .filter((name) => name.endsWith(".md") && name !== "_index.md")
    .sort();

  const spotResults = await Promise.all(
    entries.map((name) => readSpot(join(spotsDir, name)))
  );
  const spots = spotResults.filter(Boolean);
  if (spots.length === 0) {
    throw new Error("Found zero open-water spots — refusing to overwrite worker/src/spots.ts");
  }

  const body = [
    "// AUTO-GENERATED from content/spots/*.md — do not edit by hand.",
    "// Regenerate via `node scripts/generate-worker-spots.mjs`",
    "// (runs automatically from wrangler [build] before dev and deploy).",
    "",
    'export type TempStationType = "noaa" | "ndbc";',
    "",
    "export interface SpotConfig {",
    "  slug: string;",
    "  tempStationId: string;",
    "  tempStationType: TempStationType;",
    "  tempFallbackStationId?: string;",
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
