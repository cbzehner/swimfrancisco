// Shared TOML front-matter parsing for content/spots/*.md, used by the i18n,
// agent-data, and worker-spots generators.

import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "smol-toml";

const LOCALES_PATH = join(dirname(fileURLToPath(import.meta.url)), "../../i18n/locales.toml");

export const FRONTMATTER_RE = /^\+\+\+\n([\s\S]*?)\n\+\+\+\n?/;

const TEMP_SOURCE_TYPES = ["usgs", "noaa", "ndbc", "erddap", "sst"];

// Splits already-read text into parsed TOML front matter and the remaining
// body text (untrimmed). `missingMessage` lets callers preserve their own
// wording for the "no front matter found" error.
export function splitFrontMatter(text, label, { missingMessage } = {}) {
  const match = FRONTMATTER_RE.exec(text);
  if (!match) throw new Error(missingMessage ?? `${label}: missing TOML frontmatter`);
  return { front: parse(match[1]), body: text.slice(match[0].length) };
}

// Reads a spot markdown file from disk and splits its front matter.
export async function readSpotFrontmatter(filePath, { label = filePath, missingMessage } = {}) {
  const text = await readFile(filePath, "utf8");
  const { front, body } = splitFrontMatter(text, label, { missingMessage });
  return { front, body, text };
}

export function parseOpenWaterStations(extra, label) {
  const tideStationId = extra?.noaa_tide_station;
  if (!tideStationId || typeof tideStationId !== "string") {
    throw new Error(`${label}: missing noaa_tide_station`);
  }
  const rawSources = extra?.temp_sources;
  if (!Array.isArray(rawSources) || rawSources.length === 0) {
    throw new Error(`${label}: temp_sources must be a non-empty array of {type, id}`);
  }
  const temp_sources = [];
  for (const source of rawSources) {
    if (!TEMP_SOURCE_TYPES.includes(source?.type)) {
      throw new Error(
        `${label}: temp source type must be one of ${TEMP_SOURCE_TYPES.join(", ")}, got ${source?.type}`,
      );
    }
    if (!source.id || typeof source.id !== "string") {
      throw new Error(`${label}: temp source of type ${source.type} is missing an id`);
    }
    temp_sources.push({ type: source.type, id: source.id });
  }
  return { temp_sources, noaa_tide_station: tideStationId };
}

export function isLocalizedSpotFile(fileName, localeCodes) {
  return localeCodes.some((code) => fileName.endsWith(`.${code}.md`));
}

async function sourceLocaleCodes() {
  const locales = parse(await readFile(LOCALES_PATH, "utf8"));
  return locales.locales.map((locale) => locale.code);
}

export async function listCanonicalSpotFiles(spotsDir) {
  const localeCodes = await sourceLocaleCodes();
  const entries = (await readdir(spotsDir))
    .filter((name) => name.endsWith(".md") && !name.startsWith("_index"))
    .filter((name) => !isLocalizedSpotFile(name, localeCodes))
    .sort();

  const files = [];
  const seenSlugs = new Set();
  for (const fileName of entries) {
    const filePath = join(spotsDir, fileName);
    const { front, body, text } = await readSpotFrontmatter(filePath);
    const stem = fileName.replace(/\.md$/, "");
    if (front.slug !== stem) {
      throw new Error(`${filePath}: canonical spot slug must match filename (${stem})`);
    }
    if (seenSlugs.has(front.slug)) {
      throw new Error(`${filePath}: duplicate canonical slug ${front.slug}`);
    }
    seenSlugs.add(front.slug);
    files.push({ fileName, filePath, front, body, text });
  }
  return files;
}
