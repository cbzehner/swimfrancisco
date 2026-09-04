#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = fileURLToPath(new URL("../", import.meta.url));
const workflowURL = "https://api.github.com/repos/cbzehner/swimfrancisco/actions/workflows/ci.yml/runs";
const timeoutMilliseconds = 10 * 60_000;
const pollMilliseconds = 30_000;

function buildCommit(environment, readHead) {
  if (environment.WORKERS_CI !== "1") return null;
  if (!environment.WORKERS_CI_BRANCH?.trim()) {
    throw new Error("Workers Builds is missing WORKERS_CI_BRANCH");
  }
  if (environment.WORKERS_CI_BRANCH !== "main") return null;
  const commit = environment.WORKERS_CI_COMMIT_SHA;
  if (!/^[a-f\d]{40}$/i.test(commit || "")) {
    throw new Error("Workers Builds requires a full WORKERS_CI_COMMIT_SHA for main");
  }
  if (readHead().trim().toLowerCase() !== commit.toLowerCase()) {
    throw new Error("WORKERS_CI_COMMIT_SHA does not match git HEAD");
  }
  return commit.toLowerCase();
}

export async function checkBuildCI({
  environment = process.env,
  readHead = () => execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }),
  fetch = globalThis.fetch,
  now = Date.now,
  sleep = delay,
  log = console.log,
} = {}) {
  const commit = buildCommit(environment, readHead);
  if (!commit) {
    log("CI deployment gate skipped outside main Workers Builds.");
    return null;
  }

  const url = new URL(workflowURL);
  url.search = new URLSearchParams({ head_sha: commit, branch: "main", event: "push", per_page: "1" });
  const headers = {
    accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "swimfrancisco-build-ci",
  };
  if (environment.GITHUB_TOKEN) headers.authorization = `Bearer ${environment.GITHUB_TOKEN}`;
  const deadline = now() + timeoutMilliseconds;

  for (let attempt = 0; attempt < 21; attempt += 1) {
    const remaining = deadline - now();
    if (remaining <= 0) break;
    const response = await fetch(url, {
      headers,
      signal: AbortSignal.timeout(Math.min(15_000, remaining)),
    });
    if (!response.ok) throw new Error(`GitHub CI lookup returned HTTP ${response.status}`);
    const data = await response.json();
    if (now() >= deadline) break;
    if (!Array.isArray(data?.workflow_runs)) throw new Error("GitHub CI lookup returned invalid workflow runs");
    const run = data.workflow_runs[0];
    if (run) {
      if (run.head_sha !== commit || run.head_branch !== "main" || run.event !== "push") {
        throw new Error("GitHub CI run does not match the main push commit being built");
      }
      if (run.status === "completed") {
        if (run.conclusion !== "success") {
          throw new Error(`CI for ${commit} completed with ${run.conclusion || "no conclusion"}`);
        }
        log(`CI passed for ${commit}.`);
        return run;
      }
    }
    const waitMilliseconds = Math.min(pollMilliseconds, deadline - now());
    if (waitMilliseconds <= 0 || attempt === 20) break;
    log(`Waiting for CI on ${commit}: ${run?.status || "not yet started"}.`);
    await sleep(waitMilliseconds);
  }
  throw new Error(`Timed out waiting for successful CI on ${commit} after ten minutes`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  checkBuildCI().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
