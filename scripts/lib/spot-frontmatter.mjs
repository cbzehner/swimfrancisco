// Shared TOML front-matter parsing for content/spots/*.md, used by the i18n,
// agent-data, and worker-spots generators.

import { readFile } from "node:fs/promises";
import { parse } from "smol-toml";

export const FRONTMATTER_RE = /^\+\+\+\n([\s\S]*?)\n\+\+\+\n?/;

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
