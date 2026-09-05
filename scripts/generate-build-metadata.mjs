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

function expectedMainCommit(environment) {
  if (environment.WORKERS_CI !== "1" || environment.WORKERS_CI_BRANCH !== "main") return null;
  const commit = environment.WORKERS_CI_COMMIT_SHA;
  if (!/^[a-f\d]{40}$/i.test(commit || "")) {
    throw new Error("Workers Builds requires a full WORKERS_CI_COMMIT_SHA for main");
  }
  return commit.toLowerCase();
}

export async function generateBuildMetadata({
  outputDir = defaultOutputDir,
  generatedAt = new Date().toISOString(),
  gitCommit = null,
  environment = process.env,
  readHead = () => gitValue(["rev-parse", "HEAD"]),
} = {}) {
  const expectedCommit = expectedMainCommit(environment);
  const head = expectedCommit || !gitCommit ? (await readHead()).trim().toLowerCase() : null;
  if (expectedCommit && head.toLowerCase() !== expectedCommit) {
    throw new Error("WORKERS_CI_COMMIT_SHA does not match git HEAD");
  }
  const metadata = {
    site: "Swim Francisco",
    generated_at: generatedAt,
    git_commit: expectedCommit || gitCommit || head,
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
