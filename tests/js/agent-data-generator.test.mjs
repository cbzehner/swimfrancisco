import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { generateAgentData, normalizeIsoDate } from "../../scripts/generate-agent-data.mjs";
import { generateBuildMetadata } from "../../scripts/generate-build-metadata.mjs";
import { assertConditionsFresh, assertSpotMatchesContent } from "../../scripts/smoke-production.mjs";
import { listCanonicalSpotFiles } from "../../scripts/lib/spot-frontmatter.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const SPOTS_DIR = join(ROOT, "content/spots");

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

test("agent data generator writes index and canonical spot detail records", async () => {
  const dir = await mkdtemp(join(tmpdir(), "swimfrancisco-agent-"));
  try {
    await generateAgentData({
      outputDir: dir,
      generatedAt: "2026-06-16T15:05:00.000Z",
    });

    const index = await readJson(join(dir, "index.json"));
    assert.equal(index.agent_data_version, 2);
    assert.equal(index.generated_at, "2026-06-16T15:05:00.000Z");
    assert.ok(index.spots.length >= 1);

    const aquaticParkEntry = index.spots.find((spot) => spot.slug === "aquatic-park");
    assert.ok(aquaticParkEntry);
    assert.equal(aquaticParkEntry.agent_json, "https://swimfrancisco.com/agent/spots/aquatic-park.json");
    assert.equal(Object.hasOwn(aquaticParkEntry, "agent_markdown"), false);

    const aquaticPark = await readJson(join(dir, "spots", "aquatic-park.json"));
    assert.equal(aquaticPark.type, "open_water");
    assert.equal(aquaticPark.canonical_url, "https://swimfrancisco.com/spots/aquatic-park/");
    assert.equal(aquaticPark.live_conditions.condition_key, "aquatic-park");
    assert.equal(aquaticPark.pool, undefined);
    assert.equal(aquaticPark.open_water.noaa_tide_station, "9414290");
    assert.deepEqual(aquaticPark.open_water.temp_sources, [
      { type: "usgs", id: "374938122251801" },
      { type: "noaa", id: "9414863" },
      { type: "erddap", id: "exploratorium-seabird" },
      { type: "sst", id: "37.81,-122.43" },
    ]);
    assert.equal(Object.hasOwn(aquaticPark.open_water, "temp_station_id"), false);
    assert.equal(Object.hasOwn(aquaticPark.open_water, "temp_station_type"), false);
    assert.equal(Object.hasOwn(aquaticPark.open_water, "temp_fallback_station_id"), false);
    assert.ok(aquaticPark.sources.some((source) => source.url === "https://serc.com/faq"));

    const slugs = index.spots.map((spot) => spot.slug);
    assert.equal(new Set(slugs).size, slugs.length);

    const hamilton = await readJson(join(dir, "spots", "hamilton-pool.json"));
    assert.equal(hamilton.type, "pool");
    assert.ok(Array.isArray(hamilton.pool.schedules));
    assert.match(hamilton.freshness.last_verified_at, /^\d{4}-\d{2}-\d{2}$/);
    assert.equal(hamilton.live_conditions, undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("agent open-water condition keys match worker spot slugs", async () => {
  const dir = await mkdtemp(join(tmpdir(), "swimfrancisco-agent-"));
  try {
    await generateAgentData({
      outputDir: dir,
      generatedAt: "2026-06-16T15:05:00.000Z",
    });
    const index = await readJson(join(dir, "index.json"));
    const agentOpenWaterSlugs = index.spots
      .filter((spot) => spot.type === "open_water")
      .map((spot) => spot.slug)
      .sort();

    const workerSpots = await readFile("worker/src/spots.ts", "utf8");
    const workerSlugs = Array.from(workerSpots.matchAll(/slug: "([^"]+)"/g), (match) => match[1]).sort();

    assert.deepEqual(agentOpenWaterSlugs, workerSlugs);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("canonical spot membership skips localized files and duplicate slugs", async () => {
  const files = await listCanonicalSpotFiles(SPOTS_DIR);
  const slugs = files.map((file) => file.front.slug);
  assert.equal(new Set(slugs).size, slugs.length);
  const names = new Set(files.map((file) => file.fileName));
  assert.equal(names.has("aquatic-park.md"), true);
  assert.equal(names.has("aquatic-park.es.md"), false);
  for (const file of files) {
    assert.equal(file.front.extra?.localized_from, undefined);
    assert.equal(file.front.slug, file.fileName.replace(/\.md$/, ""));
  }
});

test("canonical membership skips locale filenames even without localized_from", async () => {
  const dir = await mkdtemp(join(tmpdir(), "swimfrancisco-canonical-"));
  try {
    await writeFile(
      join(dir, "hamilton-pool.md"),
      "+++\ntitle = \"Hamilton\"\nslug = \"hamilton-pool\"\n[extra]\ntype = \"pool\"\n+++\n",
    );
    await writeFile(
      join(dir, "hamilton-pool.es.md"),
      "+++\ntitle = \"Hamilton\"\nslug = \"hamilton-pool\"\n[extra]\n+++\n",
    );
    const files = await listCanonicalSpotFiles(dir);
    assert.deepEqual(files.map((file) => file.fileName), ["hamilton-pool.md"]);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("normalizeIsoDate accepts TOML date strings and Date objects", () => {
  assert.equal(normalizeIsoDate("2026-06-16"), "2026-06-16");
  assert.equal(normalizeIsoDate(new Date("2026-06-16T00:00:00.000Z")), "2026-06-16");
  assert.equal(normalizeIsoDate("06/16/2026"), null);
});

test("production smoke accepts the expected season and rejects older content", () => {
  const expected = {
    slug: "north-beach-pool",
    pool: { schedules: [{ effective_start: "2027-01-01", effective_end: "2027-04-30" }] },
  };
  assert.doesNotThrow(() => assertSpotMatchesContent({ ...expected, generated_at: "2027-02-01T00:00:00Z" }, expected));
  assert.throws(() => assertSpotMatchesContent({
    ...expected,
    pool: { schedules: [{ effective_start: "2026-08-11", effective_end: "2026-08-29" }] },
  }, expected), /north-beach-pool deployed data does not match/);
});

test("production smoke rejects old observations even when the latest assembly labels them fresh", () => {
  const now = Date.now();
  const record = {
    updated_at: new Date(now).toISOString(),
    temp_observed_at: new Date(now - 32 * 24 * 3_600_000).toISOString(),
    water_temp_f: 58,
    temp_station_type: "ndbc",
    temp_stale: false,
  };
  assert.throws(() => assertConditionsFresh({ "ocean-beach": record }), /ocean-beach temperature observed_at.*old/);
  assert.doesNotThrow(() => assertConditionsFresh({
    "ocean-beach": { ...record, water_temp_f: null, temp_observed_at: null },
  }));
});

test("build metadata generator writes a production smoke marker", async () => {
  const dir = await mkdtemp(join(tmpdir(), "swimfrancisco-build-"));
  try {
    await generateBuildMetadata({
      outputDir: dir,
      generatedAt: "2026-07-02T22:00:00.000Z",
      gitCommit: "abc123",
    });

    const metadata = await readJson(join(dir, "build.json"));
    assert.equal(metadata.site, "Swim Francisco");
    assert.equal(metadata.generated_at, "2026-07-02T22:00:00.000Z");
    assert.equal(metadata.git_commit, "abc123");
    assert.equal(metadata.build_command, "npm run build");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("main Workers Builds metadata requires the checked out commit", async () => {
  const dir = await mkdtemp(join(tmpdir(), "swimfrancisco-build-"));
  const expectedCommit = "a".repeat(40);
  try {
    await assert.rejects(generateBuildMetadata({
      outputDir: dir,
      gitCommit: expectedCommit,
      environment: {
        WORKERS_CI: "1",
        WORKERS_CI_BRANCH: "main",
        WORKERS_CI_COMMIT_SHA: expectedCommit,
      },
      readHead: async () => "b".repeat(40),
    }), /does not match git HEAD/);

    const metadata = await generateBuildMetadata({
      outputDir: dir,
      gitCommit: "b".repeat(40),
      environment: {
        WORKERS_CI: "1",
        WORKERS_CI_BRANCH: "main",
        WORKERS_CI_COMMIT_SHA: expectedCommit,
      },
      readHead: async () => expectedCommit,
    });
    assert.equal(metadata.git_commit, expectedCommit);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
