#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = fileURLToPath(new URL("../", import.meta.url));
const workflowURL = "https://api.github.com/repos/cbzehner/swimfrancisco/actions/workflows/ci.yml/runs";
const timeoutMilliseconds = 10 * 60_000;
const pollMilliseconds = 30_000;
const secondaryRateLimitInitialDelayMilliseconds = 60_000;
const workflowStatuses = new Set(["queued", "in_progress", "completed", "waiting", "requested", "pending"]);

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

function assertHeadMatches(commit, readHead) {
  if (readHead().trim().toLowerCase() !== commit) {
    throw new Error("WORKERS_CI_COMMIT_SHA does not match git HEAD");
  }
}

function retryAfterMilliseconds(response, now) {
  const retryAfter = response?.headers?.get("retry-after");
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1_000;
    const retryAt = Date.parse(retryAfter);
    if (!Number.isNaN(retryAt)) return Math.max(0, retryAt - now);
  }

  if (response?.headers?.get("x-ratelimit-remaining") === "0") {
    const resetHeader = response.headers.get("x-ratelimit-reset");
    if (resetHeader) {
      const reset = Number(resetHeader);
      if (Number.isFinite(reset)) return Math.max(0, reset * 1_000 - now);
    }
  }

  return null;
}

function temporaryResponse(response) {
  const rateLimited = response.headers.get("retry-after") !== null
    || response.headers.get("x-ratelimit-remaining") === "0";
  return response.status === 408 || response.status === 429 || response.status >= 500
    || (response.status === 403 && rateLimited);
}

function retryDelayMilliseconds(response, retryCount, now) {
  const retryAfter = retryAfterMilliseconds(response, now);
  if (retryAfter !== null) return retryAfter > 0 ? retryAfter : pollMilliseconds;
  if (response?.status === 429) {
    return secondaryRateLimitInitialDelayMilliseconds * 2 ** retryCount;
  }
  return pollMilliseconds;
}

function validRun(run) {
  return run && typeof run === "object"
    && typeof run.head_sha === "string"
    && typeof run.head_branch === "string"
    && typeof run.event === "string"
    && workflowStatuses.has(run.status)
    && (run.conclusion === null || typeof run.conclusion === "string");
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
  let retryCount = 0;

  for (let attempt = 0; attempt < 21; attempt += 1) {
    const remaining = deadline - now();
    if (remaining <= 0) break;
    let response;
    let data;
    try {
      response = await fetch(url, {
        headers,
        signal: AbortSignal.timeout(Math.min(15_000, remaining)),
      });
    } catch {
      const waitMilliseconds = Math.min(pollMilliseconds, deadline - now());
      if (waitMilliseconds <= 0 || attempt === 20) break;
      log("Waiting to retry GitHub CI lookup.");
      await sleep(waitMilliseconds);
      assertHeadMatches(commit, readHead);
      retryCount += 1;
      continue;
    }
    if (now() >= deadline) break;
    if (!response.ok) {
      if (!temporaryResponse(response)) {
        throw new Error(`GitHub CI lookup failed with HTTP ${response.status}`);
      }
      const waitMilliseconds = Math.min(retryDelayMilliseconds(response, retryCount, now()), deadline - now());
      if (waitMilliseconds <= 0 || attempt === 20) break;
      log("Waiting to retry GitHub CI lookup.");
      await sleep(waitMilliseconds);
      assertHeadMatches(commit, readHead);
      retryCount += 1;
      continue;
    }
    try {
      data = await response.json();
    } catch {
      throw new Error("GitHub CI lookup returned invalid workflow runs");
    }
    if (now() >= deadline) break;
    retryCount = 0;
    if (!Array.isArray(data?.workflow_runs)) throw new Error("GitHub CI lookup returned invalid workflow runs");
    const run = data.workflow_runs[0];
    if (data.workflow_runs.length > 0) {
      if (!validRun(run)) throw new Error("GitHub CI lookup returned invalid workflow runs");
      if (run.head_sha !== commit || run.head_branch !== "main" || run.event !== "push") {
        throw new Error("GitHub CI run does not match the main push commit being built");
      }
      if (run.status === "completed") {
        if (run.conclusion !== "success") {
          throw new Error("CI did not complete successfully");
        }
        assertHeadMatches(commit, readHead);
        log(`CI passed for ${commit}.`);
        return run;
      }
    }
    const waitMilliseconds = Math.min(pollMilliseconds, deadline - now());
    if (waitMilliseconds <= 0 || attempt === 20) break;
    log(`Waiting for CI on ${commit}.`);
    await sleep(waitMilliseconds);
    assertHeadMatches(commit, readHead);
  }
  throw new Error(`Timed out waiting for successful CI on ${commit} after ten minutes`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  checkBuildCI().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
