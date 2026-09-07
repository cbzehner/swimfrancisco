#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { isDeepStrictEqual } from "node:util";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = fileURLToPath(new URL("../", import.meta.url));
const workflowURL = "https://api.github.com/repos/cbzehner/swimfrancisco/actions/workflows/ci.yml/runs";
const timeoutMilliseconds = 10 * 60_000;
const pollMilliseconds = 30_000;
const secondaryRateLimitInitialDelayMilliseconds = 60_000;
const workflowStatuses = new Set(["queued", "in_progress", "completed", "waiting", "requested", "pending"]);
const automationBranch = /^auto\/schedules\/\d+-\d+-[12]$/;

export function generatedSchedulePath(path) {
  return /^(?:data\/(?:bulletin|dynamic-labels)\.json|data\/i18n\/(?:en|es|fi|fil|vi|zh-Hant)\.json)$/.test(path)
    || /^schedule-tools\/src\/schedules\/(?:registry|quarantine)\.toml$/.test(path)
    || /^content\/spots\/[a-z0-9]+(?:-[a-z0-9]+)*(?:\.(?:es|fi|fil|vi|zh-Hant))?\.md$/.test(path)
    || /^data\/[a-z0-9]+(?:-[a-z0-9]+)*\/\d{4}-\d{2}-\d{2}-[a-f\d]{12}\/(?:source\.(?:pdf|html|csv|xlsx|sha256)|reviewed\.json|source-bundle\.json|openai-pool-bundle\.json|openai-gpt-5\.5-2026-04-23\.json|direct-[a-z0-9-]+\.json)$/.test(path);
}

export function stageScheduleChanges({ git = (args) => execFileSync("git", args, { cwd: repoRoot, encoding: "utf8" }) } = {}) {
  const paths = [...new Set([
    ...git(["ls-files", "--modified", "--others", "--deleted", "--exclude-standard", "-z"]).split("\0"),
    ...git(["diff", "--cached", "--name-only", "-z"]).split("\0"),
  ].filter(Boolean))];
  if (paths.some((path) => !generatedSchedulePath(path))) throw new Error("Unexpected generated paths; nothing may be committed");
  if (!paths.length) return { changed: false, paths: [] };
  git(["add", "--", ...paths]);
  for (const path of paths) {
    if (!/^100644 [a-f\d]{40} 0\t[^\0]+\0$/.test(git(["ls-files", "--stage", "-z", "--", path]))) {
      throw new Error("Staging only permits regular generated files, without deletions");
    }
  }
  const changed = paths.some((path) => {
    if (!/\/direct-[a-z0-9-]+\.json$/.test(path)) return true;
    try {
      const semantic = (text) => {
        const value = JSON.parse(text);
        if (value.provider !== "direct" || !value.payload) throw new Error("Not a direct extraction");
        const { extracted_at, payload, ...rest } = value;
        const { effective_start, ...facts } = payload;
        return { ...rest, payload: facts };
      };
      return !isDeepStrictEqual(semantic(git(["show", `HEAD:${path}`])), semantic(git(["show", `:${path}`])));
    } catch {
      return true;
    }
  });
  return { changed, paths };
}

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
  if (response?.status === 429 || response?.status === 403) {
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

export async function waitForCommitCI({
  commit,
  branch,
  environment = process.env,
  readHead = () => execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }),
  fetch = globalThis.fetch,
  now = Date.now,
  sleep = delay,
  log = console.log,
} = {}) {
  if (!/^[a-f\d]{40}$/.test(commit || "") ||
      !(branch === "main" || automationBranch.test(branch || ""))) {
    throw new Error("CI lookup requires an exact commit and supported publication branch");
  }
  assertHeadMatches(commit, readHead);

  const url = new URL(workflowURL);
  url.search = new URLSearchParams({ head_sha: commit, branch, event: "push", per_page: "1" });
  const headers = {
    accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "swimfrancisco-build-ci",
  };
  if (environment.GITHUB_TOKEN) headers.authorization = `Bearer ${environment.GITHUB_TOKEN}`;
  else log("GitHub CI lookup is unauthenticated. Configure a build-only GITHUB_TOKEN with Actions read access to avoid shared-IP rate limits.");
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
      log(`GitHub CI lookup encountered a network error or request timeout; retrying in ${Math.ceil(waitMilliseconds / 1_000)} seconds.`);
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
      log(`GitHub CI lookup returned HTTP ${response.status}; waiting ${Math.ceil(waitMilliseconds / 1_000)} seconds before retrying${waitMilliseconds >= deadline - now() ? " (the retry delay reaches the build deadline)" : ""}.`);
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
      if (run.head_sha !== commit || run.head_branch !== branch || run.event !== "push") {
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

export async function checkBuildCI(options = {}) {
  const environment = options.environment || process.env;
  const readHead = options.readHead || (() => execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }));
  const commit = buildCommit(environment, readHead);
  if (!commit) {
    (options.log || console.log)("CI deployment gate skipped outside main Workers Builds.");
    return null;
  }
  return waitForCommitCI({ ...options, environment, readHead, commit, branch: "main" });
}

export async function promoteScheduleCommit({
  base,
  branch,
  environment = process.env,
  git = (args) => execFileSync("git", args, { cwd: repoRoot, encoding: "utf8", timeout: 60_000 }),
  waitForCI = waitForCommitCI,
} = {}) {
  if (!/^[a-f\d]{40}$/.test(base || "") || !automationBranch.test(branch || "")) {
    throw new Error("Promotion requires the base commit and a run-specific automation branch");
  }
  const commit = git(["rev-parse", "HEAD"]).trim();
  if (!/^[a-f\d]{40}$/.test(commit) || git(["rev-list", "--parents", "-n", "1", commit]).trim() !== `${commit} ${base}`) {
    throw new Error("Promotion requires exactly one generated commit above the recorded main head");
  }
  if (git(["status", "--porcelain", "--untracked-files=no"]).trim()) throw new Error("Promotion requires a clean tracked worktree");
  const paths = git(["diff", "--name-only", "-z", base, commit]).split("\0").filter(Boolean);
  if (!paths.length || paths.some((path) => !generatedSchedulePath(path))) throw new Error("Promotion contains unexpected generated paths");
  for (const path of paths) {
    const entry = git(["ls-tree", "-z", commit, "--", path]);
    if (!/^100644 blob [a-f\d]{40}\t[^\0]+\0$/.test(entry)) throw new Error("Promotion only permits regular generated files, without deletions");
  }
  const readRemote = (ref) => git(["ls-remote", "--heads", "origin", `refs/heads/${ref}`]).trim().split(/\s/)[0];
  const existing = readRemote(branch);
  if (existing && existing !== commit) throw new Error("Automation branch already points to another commit");
  git(["push", "--porcelain", "origin", `${commit}:refs/heads/${branch}`]);
  const check = await waitForCI({ commit, branch, environment, readHead: () => git(["rev-parse", "HEAD"]) });
  if (!check || check.head_sha !== commit || check.head_branch !== branch || check.event !== "push"
      || check.status !== "completed" || check.conclusion !== "success") throw new Error("Promotion requires successful CI for its exact commit");
  assertHeadMatches(commit, () => git(["rev-parse", "HEAD"]));
  const currentMain = readRemote("main");
  if (currentMain !== base) return { status: "stale", commit, main: currentMain, check_url: check.html_url || null };
  try {
    git(["push", "--porcelain", "origin", `${commit}:refs/heads/main`]);
  } catch {
    const currentMain = readRemote("main");
    if (currentMain !== commit) {
      if (currentMain !== base) return { status: "stale", commit, main: currentMain, check_url: check.html_url || null };
      throw new Error("Main promotion failed; branch protection or the publication token rejected the push");
    }
  }
  if (readRemote("main") !== commit) throw new Error("Main advanced after promotion; publication requires a new revision check");
  return { status: "promoted", commit, check_url: check.html_url || null };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const action = process.argv[2] === "stage"
    ? Promise.resolve().then(() => console.log(JSON.stringify(stageScheduleChanges())))
    : process.argv[2] === "promote"
    ? promoteScheduleCommit({ base: process.argv[3], branch: process.argv[4] }).then((result) => {
      console.log(JSON.stringify(result));
      if (result.status === "stale") process.exitCode = 2;
    })
    : checkBuildCI();
  action.catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
