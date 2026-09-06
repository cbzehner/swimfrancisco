#!/usr/bin/env node

import { execFile } from "node:child_process";
import { isDeepStrictEqual, promisify } from "node:util";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildSpotRecord } from "./generate-agent-data.mjs";
import { splitFrontMatter } from "./lib/spot-frontmatter.mjs";
import { computeDetailStatus, resolveActiveSchedule, scheduleHasAccessHours, scheduleHasSessions } from "../static/js/helpers/board.mjs";
import { pacificWallClockDate } from "../static/js/helpers/pacific.mjs";
import { isDropInType } from "../static/js/helpers/programs.mjs";

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
    if (arg === "--browser") {
      if (seen.has(arg)) throw new Error("duplicate --browser");
      seen.add(arg);
      options.browser = true;
      continue;
    }
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

async function expectedSpotRecords(commit) {
  const { stdout } = await execFileAsync("git", ["ls-tree", "-r", "--name-only", commit, "--", "content/spots/"], { cwd: repoRoot });
  const slugs = stdout.split("\n").flatMap((path) => {
    const match = /^content\/spots\/([a-z0-9-]+)\.md$/.exec(path);
    return match ? [match[1]] : [];
  });
  assert(slugs.length > 0, "expected commit has no canonical spots");
  return Promise.all(slugs.map((slug) => expectedSpotRecord(slug, commit)));
}

export function assertSpotMatchesContent(actual, expected) {
  const { generated_at, ...record } = actual;
  assert(
    isDeepStrictEqual(record, JSON.parse(JSON.stringify(expected))),
    `${expected.slug} deployed data does not match the expected commit's content`,
  );
}

export async function verifySpotRecords(index, expected, loadSpot) {
  const actualSlugs = index.spots?.map((spot) => spot.slug).sort();
  const expectedSlugs = expected.map((spot) => spot.slug).sort();
  assert(expected.length > 0 && isDeepStrictEqual(actualSlugs, expectedSlugs),
    "deployed index does not contain exactly the expected canonical spots");
  for (let offset = 0; offset < expected.length; offset += 5) {
    await Promise.all(expected.slice(offset, offset + 5).map(async (spot) => {
      assertSpotMatchesContent(await loadSpot(spot.slug), spot);
    }));
  }
}

export async function verifyPoolPage(page, expected, instant) {
  await page.waitForFunction(() => document.querySelector(".today-block")?.dataset.day);
  const actual = await page.locator(".detail-root").evaluate((root) => ({
    schedule: JSON.parse(root.dataset.schedule),
    day: root.querySelector(".today-block").dataset.day,
    hidden: root.querySelector(".today-block").hidden,
    heading: root.querySelector(".today-block-heading").textContent,
    rows: [...root.querySelectorAll(".today-block-list li")].map((row) => ({
      start: row.dataset.start, end: row.dataset.end, type: row.dataset.program,
    })),
    window: root.querySelector("[data-schedule-window]")?.dataset.scheduleWindow,
    highlightedDays: [...root.querySelectorAll('.weekly-grid [data-today="true"]')].map((cell) => cell.dataset.day),
  }));
  const schedule = JSON.parse(JSON.stringify({ schedules: expected.pool.schedules || [] }));
  assert(isDeepStrictEqual(actual.schedule, schedule), `${expected.slug} page embeds stale schedule data`);
  const now = pacificWallClockDate(instant);
  const day = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", weekday: "long" }).format(instant).toLowerCase();
  assert(actual.day === day, `${expected.slug} Today block uses the wrong Pacific weekday`);
  assert(actual.highlightedDays.every((value) => value === day), `${expected.slug} highlights the wrong weekday`);
  const active = resolveActiveSchedule(schedule, now);
  if (active) assert(actual.window === `${active.effective_start || ""}/${active.effective_end || ""}`, `${expected.slug} displays the wrong weekly window`);
  const accessOnly = !scheduleHasSessions(schedule, now) && scheduleHasAccessHours(schedule, now);
  const hide = accessOnly || ["CLOSED_TODAY", "NOT_VERIFIED", "NO_DROPIN_WEEK", "NO_DROPIN_TODAY"].includes(computeDetailStatus(schedule, now).kind);
  const rows = hide ? [] : (active?.sessions || [])
    .filter((session) => session.day === day && isDropInType(session.type))
    .map(({ start, end, type }) => ({ start, end, type })).sort((a, b) => a.start.localeCompare(b.start));
  assert(actual.hidden === (rows.length === 0), `${expected.slug} Today visibility is incorrect`);
  assert(isDeepStrictEqual(actual.rows, rows), `${expected.slug} Today rows differ from the expected schedule`);
  if (rows.length) assert(actual.heading.toLowerCase().includes(day), `${expected.slug} Today heading has the wrong day`);
}

async function verifyLiveBrowsers(baseUrl, expected) {
  const { webkit, chromium } = await import("playwright-core");
  for (const engine of [webkit, chromium]) {
    const browser = await engine.launch();
    try {
      const context = await browser.newContext({ timezoneId: "Asia/Tokyo" });
      const page = await context.newPage();
      page.setDefaultTimeout(15_000);
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const instant = new Date();
      await page.clock.setFixedTime(instant);
      for (const spot of expected.filter((spot) => spot.type === "pool")) {
        const response = await page.goto(new URL(`/spots/${spot.slug}/`, baseUrl).href, { waitUntil: "load" });
        assert(response?.ok(), `${spot.slug} pool page failed to load`);
        await verifyPoolPage(page, spot, instant);
      }
      const response = await page.goto(new URL("/map/", baseUrl).href, { waitUntil: "load" });
      assert(response?.ok(), "Map page failed to load");
      await page.waitForFunction(() => [...document.querySelectorAll("img.leaflet-tile")].some((tile) => tile.complete && tile.naturalWidth > 0));
      assert(errors.length === 0, `Live browser reported ${errors.length} JavaScript errors`);
    } finally {
      await browser.close();
    }
  }
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
  const { baseUrl, maxGeneratedAgeHours, commit, browser } = parseArgs(process.argv.slice(2));
  const expectedCommit = commit.kind === "skip"
    ? null
    : commit.kind === "exact"
      ? await resolveCommit(commit.expectedCommit)
      : await resolveCommit();

  assert(
    Number.isFinite(maxGeneratedAgeHours) && maxGeneratedAgeHours > 0,
    "--max-generated-age-hours must be a positive number",
  );

  const [build, index, conditions, mapConfig] = await Promise.all([
    fetchJson(baseUrl, "/agent/build.json"),
    fetchJson(baseUrl, "/agent/index.json"),
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
  assert(typeof build.git_commit === "string" && /^[0-9a-f]{40}$/.test(build.git_commit), "build marker has no valid git commit");
  const contentCommit = expectedCommit || await resolveCommit(build.git_commit);
  const expected = await expectedSpotRecords(contentCommit);
  await verifySpotRecords(index, expected, (slug) => fetchJson(baseUrl, `/agent/spots/${slug}.json`));

  const aquaticPark = conditions["aquatic-park"];
  assertConditionsFresh(conditions);
  assert(aquaticPark?.water_temp_f != null, "Aquatic Park temperature is missing");
  assert(aquaticPark.temp_stale === false, "Aquatic Park temperature is marked stale");
  assert(aquaticPark.tide_stale === false, "Aquatic Park tide is marked stale");

  if (browser) await verifyLiveBrowsers(baseUrl, expected);

  console.log(`Production smoke passed for ${baseUrl}: ${contentCommit}, all ${expected.length} canonical spots`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error(err.message);
    process.exit(1);
  });
}
