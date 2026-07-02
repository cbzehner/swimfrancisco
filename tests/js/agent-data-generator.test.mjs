import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { generateAgentData, normalizeIsoDate } from "../../scripts/generate-agent-data.mjs";
import { generateBuildMetadata } from "../../scripts/generate-build-metadata.mjs";

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
    assert.equal(index.agent_data_version, 1);
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
    assert.ok(aquaticPark.sources.some((source) => source.url === "https://serc.com/faq"));

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

test("normalizeIsoDate accepts TOML date strings and Date objects", () => {
  assert.equal(normalizeIsoDate("2026-06-16"), "2026-06-16");
  assert.equal(normalizeIsoDate(new Date("2026-06-16T00:00:00.000Z")), "2026-06-16");
  assert.equal(normalizeIsoDate("06/16/2026"), null);
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
