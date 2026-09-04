#!/usr/bin/env node

import { execFile } from "node:child_process";
import { isDeepStrictEqual, promisify } from "node:util";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildSpotRecord } from "./generate-agent-data.mjs";
import { splitFrontMatter } from "./lib/spot-frontmatter.mjs";

const execFileAsync = promisify(execFile);
const defaultBaseUrl = "https://swimfrancisco.com";
const defaultMaxGeneratedAgeHours = 36;
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function parseArgs(argv) {
  const seen = new Set();
  const options = {
    baseUrl: defaultBaseUrl,
    maxGeneratedAgeHours: defaultMaxGeneratedAgeHours,
    commit: { kind: "git-head" },
  };
  for (const arg of argv) {
    if (arg === "--skip-commit") {
      if (seen.has("commit")) throw new Error("conflicting commit options");
      seen.add("commit");
      options.commit = { kind: "skip" };
      continue;
    }
    const eq = arg.indexOf("=");
    const name = eq === -1 ? arg : arg.slice(0, eq);
    const value = eq === -1 ? "" : arg.slice(eq + 1);
    if (name === "--base-url") {
      if (seen.has(name)) throw new Error("duplicate --base-url");
      if (!value) throw new Error("--base-url must not be empty");
      seen.add(name);
      options.baseUrl = value;
      continue;
    }
    if (name === "--max-generated-age-hours") {
      if (seen.has(name)) throw new Error("duplicate --max-generated-age-hours");
      if (!value) throw new Error("--max-generated-age-hours must not be empty");
      seen.add(name);
      options.maxGeneratedAgeHours = Number(value);
      continue;
    }
    if (name === "--expected-commit") {
      if (seen.has("commit")) throw new Error("conflicting commit options");
      if (!value) throw new Error("--expected-commit must not be empty");
      seen.add("commit");
      options.commit = { kind: "exact", expectedCommit: value };
      continue;
    }
    throw new Error(`unknown option: ${arg}`);
  }
  return options;
}

async function resolveCommit(ref = "HEAD") {
  const { stdout } = await execFileAsync("git", ["rev-parse", "--verify", "--end-of-options", `${ref}^{commit}`], { cwd: repoRoot });
  return stdout.trim();
}

async function expectedSpotRecord(slug, commit) {
  const file = `content/spots/${slug}.md`;
  const { stdout } = await execFileAsync("git", ["show", `${commit}:${file}`], { cwd: repoRoot });
  const { front, body } = splitFrontMatter(stdout, file);
  return buildSpotRecord(front, body, file);
}

export function assertSpotMatchesContent(actual, expected) {
  const { generated_at, ...record } = actual;
  assert(
    isDeepStrictEqual(record, JSON.parse(JSON.stringify(expected))),
    `${expected.slug} deployed data does not match the expected commit's content`,
  );
}

async function fetchJson(baseUrl, path) {
  const url = new URL(path, baseUrl);
  const response = await fetch(url, { signal: AbortSignal.timeout(15_000) });
  if (!response.ok) {
    throw new Error(`${url.href} returned ${response.status}`);
  }
  return response.json();
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertFreshIso(label, isoValue, maxAgeHours) {
  const timestamp = Date.parse(isoValue);
  assert(Number.isFinite(timestamp), `${label} is not a valid ISO timestamp: ${isoValue}`);

  const ageHours = (Date.now() - timestamp) / 3_600_000;
  assert(ageHours >= 0, `${label} is in the future: ${isoValue}`);
  assert(ageHours <= maxAgeHours, `${label} is ${ageHours.toFixed(1)}h old; max is ${maxAgeHours}h`);
}

export function assertConditionsFresh(conditions) {
  for (const [slug, record] of Object.entries(conditions)) {
    assertFreshIso(`${slug} conditions updated_at`, record.updated_at, 3);
    if (record.water_temp_f !== null) {
      assertFreshIso(`${slug} temperature observed_at`, record.temp_observed_at, record.temp_station_type === "sst" ? 72 : 24);
    }
  }
}

async function main() {
  const { baseUrl, maxGeneratedAgeHours, commit } = parseArgs(process.argv.slice(2));
  const expectedCommit = commit.kind === "skip"
    ? null
    : commit.kind === "exact"
      ? await resolveCommit(commit.expectedCommit)
      : await resolveCommit();

  assert(
    Number.isFinite(maxGeneratedAgeHours) && maxGeneratedAgeHours > 0,
    "--max-generated-age-hours must be a positive number",
  );

  const [build, index, ocean, northBeach, conditions, mapConfig] = await Promise.all([
    fetchJson(baseUrl, "/agent/build.json"),
    fetchJson(baseUrl, "/agent/index.json"),
    fetchJson(baseUrl, "/agent/spots/24-hour-fitness-ocean.json"),
    fetchJson(baseUrl, "/agent/spots/north-beach-pool.json"),
    fetchJson(baseUrl, "/api/conditions"),
    fetchJson(baseUrl, "/api/map-config"),
  ]);

  assert(typeof mapConfig?.carto_basemap_key === "string" && mapConfig.carto_basemap_key.trim().length > 0, "map configuration is missing its CARTO key");

  assert(build.build_command === "npm run build", "production build marker was not generated by npm run build");
  assertFreshIso("build marker generated_at", build.generated_at, maxGeneratedAgeHours);
  if (commit.kind !== "skip") {
    assert(
      build.git_commit === expectedCommit,
      `production commit ${build.git_commit} does not match expected ${expectedCommit}`,
    );
  }

  assertFreshIso("agent index generated_at", index.generated_at, maxGeneratedAgeHours);
  assert(
    index.spots?.some((spot) => spot.slug === "24-hour-fitness-ocean"),
    "agent index is missing 24 Hour Fitness Ocean",
  );
  assert(
    index.spots?.some((spot) => spot.slug === "north-beach-pool"),
    "agent index is missing North Beach Pool",
  );

  assert(typeof build.git_commit === "string" && /^[0-9a-f]{40}$/.test(build.git_commit), "build marker has no valid git commit");
  const contentCommit = expectedCommit || await resolveCommit(build.git_commit);
  const [expectedOcean, expectedNorthBeach] = await Promise.all([
    expectedSpotRecord("24-hour-fitness-ocean", contentCommit),
    expectedSpotRecord("north-beach-pool", contentCommit),
  ]);
  assertSpotMatchesContent(ocean, expectedOcean);
  assertSpotMatchesContent(northBeach, expectedNorthBeach);

  const aquaticPark = conditions["aquatic-park"];
  assertConditionsFresh(conditions);
  assert(aquaticPark?.water_temp_f != null, "Aquatic Park temperature is missing");
  assert(aquaticPark.temp_stale === false, "Aquatic Park temperature is marked stale");
  assert(aquaticPark.tide_stale === false, "Aquatic Park tide is marked stale");

  console.log(`Production smoke passed for ${baseUrl}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error(err.message);
    process.exit(1);
  });
}
