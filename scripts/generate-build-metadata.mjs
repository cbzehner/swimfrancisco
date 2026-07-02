#!/usr/bin/env node

import { execFile } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const defaultOutputDir = join(repoRoot, "public/agent");

function argValue(name) {
  const prefix = `${name}=`;
  const match = process.argv.slice(2).find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : null;
}

async function gitValue(args) {
  const { stdout } = await execFileAsync("git", args, { cwd: repoRoot });
  return stdout.trim();
}

export async function generateBuildMetadata({
  outputDir = defaultOutputDir,
  generatedAt = new Date().toISOString(),
  gitCommit = null,
} = {}) {
  const metadata = {
    site: "Swim Francisco",
    generated_at: generatedAt,
    git_commit: gitCommit || await gitValue(["rev-parse", "HEAD"]),
    build_command: "npm run build",
  };

  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, "build.json"), `${JSON.stringify(metadata, null, 2)}\n`);
  return metadata;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const outputDir = argValue("--out-dir") || defaultOutputDir;
  generateBuildMetadata({ outputDir })
    .then(() => {
      console.log(`Wrote build metadata to ${relative(repoRoot, join(outputDir, "build.json"))}`);
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
