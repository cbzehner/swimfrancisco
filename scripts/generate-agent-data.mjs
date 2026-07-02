#!/usr/bin/env node
// Generates agent-readable JSON from canonical content/spots/*.md.
// The default output is public/agent so Zola can build first and this script
// can add ignored deploy artifacts without dirtying the source tree.

import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join, relative } from "node:path";
import { parse } from "smol-toml";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const spotsDir = join(repoRoot, "content/spots");
const defaultOutputDir = join(repoRoot, "static/agent");
const siteUrl = "https://swimfrancisco.com";
const agentDataVersion = 1;

const FRONTMATTER_RE = /^\+\+\+\n([\s\S]*?)\n\+\+\+\n?/;

function argValue(name) {
  const prefix = `${name}=`;
  const match = process.argv.slice(2).find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : null;
}

function pageUrl(slug) {
  return `${siteUrl}/spots/${slug}/`;
}

function agentSpotUrl(slug) {
  return `${siteUrl}/agent/spots/${slug}.json`;
}

function defaultGeneratedAt() {
  return new Date().toISOString();
}

function cleanBody(text) {
  return text.trim();
}

export function normalizeIsoDate(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toISOString().slice(0, 10);
  }
  return null;
}

function maxIsoDate(values) {
  const dates = values.map(normalizeIsoDate).filter(Boolean);
  return dates.length ? dates.sort().at(-1) : null;
}

function collectLastVerifiedAt(extra) {
  const values = [];
  if (extra.last_verified_at) values.push(extra.last_verified_at);
  for (const schedule of Array.isArray(extra.schedules) ? extra.schedules : []) {
    if (schedule?.last_verified_at) values.push(schedule.last_verified_at);
  }
  return maxIsoDate(values);
}

function collectScheduleEffectiveAt(extra) {
  const values = [];
  if (extra.schedule_effective) values.push(extra.schedule_effective);
  for (const schedule of Array.isArray(extra.schedules) ? extra.schedules : []) {
    if (schedule?.effective_start) values.push(schedule.effective_start);
  }
  return maxIsoDate(values);
}

function pushSource(sources, seen, source) {
  if (!source.url || seen.has(source.url)) return;
  seen.add(source.url);
  sources.push(source);
}

function collectSources(extra) {
  const sources = [];
  const seen = new Set();

  pushSource(sources, seen, { kind: "official_site", url: extra.website });

  for (const item of Array.isArray(extra.pricing) ? extra.pricing : []) {
    pushSource(sources, seen, {
      kind: "access_or_pricing",
      label: item.label,
      url: item.url,
    });
  }

  for (const club of Array.isArray(extra.clubs) ? extra.clubs : []) {
    pushSource(sources, seen, {
      kind: "club",
      label: club.name,
      url: club.source_url || club.url,
    });
  }

  for (const schedule of Array.isArray(extra.schedules) ? extra.schedules : []) {
    pushSource(sources, seen, {
      kind: "schedule",
      url: schedule.source_url,
      last_verified_at: schedule.last_verified_at,
    });
  }

  return sources;
}

function pick(extra, keys) {
  return Object.fromEntries(
    keys
      .filter((key) => extra[key] !== undefined)
      .map((key) => [key, extra[key]]),
  );
}

function buildSpotRecord(front, body) {
  const extra = front.extra || {};
  const slug = front.slug;
  const type = extra.type;
  const record = {
    agent_data_version: agentDataVersion,
    slug,
    name: front.title,
    type,
    canonical_url: pageUrl(slug),
    description_short: extra.description_short || null,
    body_markdown: cleanBody(body),
    location: {
      address: extra.address || null,
      label: extra.locale_label || null,
      lat: extra.lat ?? null,
      lng: extra.lng ?? null,
    },
    access: pick(extra, [
      "access",
      "access_mode",
      "access_summary",
      "access_notes",
      "cost",
      "payment_model",
      "pricing",
      "website",
    ]),
    freshness: {
      last_verified_at: collectLastVerifiedAt(extra),
      schedule_effective: collectScheduleEffectiveAt(extra),
    },
    sources: collectSources(extra),
  };

  if (type === "pool") {
    record.pool = pick(extra, [
      "subtype",
      "setpoint_label",
      "schedules",
      "sessions",
      "closures",
    ]);
  }

  if (type === "open_water") {
    record.open_water = pick(extra, [
      "water_body",
      "hazards",
      "common_distances",
      "clubs",
      "noaa_tide_station",
      "temp_station_id",
      "temp_station_type",
      "temp_fallback_station_id",
    ]);
    record.live_conditions = {
      api_url: `${siteUrl}/api/conditions`,
      condition_key: slug,
    };
  }

  return record;
}

async function readSpot(fileName) {
  if (fileName === "_index.md" || fileName.startsWith("_index.")) return null;
  const path = join(spotsDir, fileName);
  const text = await readFile(path, "utf8");
  const match = text.match(FRONTMATTER_RE);
  if (!match) throw new Error(`${path}: missing TOML frontmatter`);

  const front = parse(match[1]);
  const extra = front.extra || {};
  if (extra.localized_from) return null;
  const expectedSlug = fileName.replace(/\.md$/, "");
  if (front.slug !== expectedSlug) {
    throw new Error(`${path}: canonical spot slug must match filename (${expectedSlug})`);
  }
  if (!front.title || !front.slug || !extra.type) {
    throw new Error(`${path}: missing title, slug, or extra.type`);
  }

  return buildSpotRecord(front, text.slice(match[0].length));
}

function buildIndex(spots, generatedAt) {
  return {
    site: "Swim Francisco",
    agent_data_version: agentDataVersion,
    generated_at: generatedAt,
    local_timezone: "America/Los_Angeles",
    spots: spots.map((spot) => ({
      slug: spot.slug,
      name: spot.name,
      type: spot.type,
      canonical_url: spot.canonical_url,
      agent_json: agentSpotUrl(spot.slug),
      description_short: spot.description_short,
      access_mode: spot.access.access_mode || null,
      payment_model: spot.access.payment_model || null,
      last_verified_at: spot.freshness.last_verified_at,
    })),
  };
}

export async function generateAgentData({
  outputDir = defaultOutputDir,
  generatedAt = null,
} = {}) {
  generatedAt = generatedAt || defaultGeneratedAt();

  const entries = (await readdir(spotsDir))
    .filter((name) => name.endsWith(".md"))
    .sort();

  const spots = [];
  for (const entry of entries) {
    const spot = await readSpot(entry);
    if (spot) spots.push(spot);
  }
  if (spots.length === 0) {
    throw new Error("Found zero canonical spots - refusing to write agent data");
  }

  await rm(outputDir, { recursive: true, force: true });
  await mkdir(join(outputDir, "spots"), { recursive: true });

  const index = buildIndex(spots, generatedAt);
  await writeFile(join(outputDir, "index.json"), `${JSON.stringify(index, null, 2)}\n`);

  for (const spot of spots) {
    const payload = { ...spot, generated_at: generatedAt };
    await writeFile(
      join(outputDir, "spots", `${spot.slug}.json`),
      `${JSON.stringify(payload, null, 2)}\n`,
    );
  }

  return { outputDir, count: spots.length };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const outputDir = argValue("--out-dir") || defaultOutputDir;
  generateAgentData({ outputDir })
    .then(({ count, outputDir }) => {
      console.log(`Wrote ${count} agent spot records to ${relative(repoRoot, outputDir)}`);
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
