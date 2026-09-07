import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { checkBuildCI, generatedSchedulePath, promoteScheduleCommit, stageScheduleChanges, waitForCommitCI } from "../../scripts/check-build-ci.mjs";

const commit = "a".repeat(40);
const environment = { WORKERS_CI: "1", WORKERS_CI_BRANCH: "main", WORKERS_CI_COMMIT_SHA: commit };
const successfulRun = { head_sha: commit, head_branch: "main", event: "push", status: "completed", conclusion: "success" };

function gate(responses, overrides = {}) {
  let elapsed = 0;
  const requests = [];
  const sleeps = [];
  const logs = [];
  return {
    requests,
    sleeps,
    logs,
    run: () => checkBuildCI({
      environment,
      readHead: () => commit,
      now: () => elapsed,
      sleep: async (milliseconds) => { sleeps.push(milliseconds); elapsed += milliseconds; },
      log: (message) => { logs.push(message); },
      fetch: async (url, options) => {
        const response = responses[Math.min(requests.length, responses.length - 1)];
        requests.push({ url, options });
        return response instanceof Response ? response : Response.json(response);
      },
      ...overrides,
    }),
  };
}

test("the production gate requires successful CI for the exact main push commit", async () => {
  const check = gate([{ workflow_runs: [successfulRun] }]);
  assert.deepEqual(await check.run(), successfulRun);
  assert.equal(check.requests.length, 1);
  assert.deepEqual(Object.fromEntries(check.requests[0].url.searchParams), {
    head_sha: commit, branch: "main", event: "push", per_page: "1",
  });
  assert.equal(check.requests[0].options.headers.authorization, undefined);
  assert.equal(check.sleeps.length, 0);
});

test("CI lookup reports authentication mode without exposing the token", async () => {
  const anonymous = gate([{ workflow_runs: [successfulRun] }]);
  await anonymous.run();
  assert.ok(anonymous.logs.some((message) => message.includes("unauthenticated") && message.includes("build-only GITHUB_TOKEN")));

  const authenticated = gate([{ workflow_runs: [successfulRun] }], {
    environment: { ...environment, GITHUB_TOKEN: "private-test-token" },
  });
  await authenticated.run();
  assert.equal(authenticated.requests[0].options.headers.authorization, "Bearer private-test-token");
  assert.ok(authenticated.logs.every((message) => !message.includes("private-test-token") && !message.includes("unauthenticated")));
});

test("missing and pending runs wait until the same commit passes", async () => {
  const check = gate([
    { workflow_runs: [] },
    { workflow_runs: [{ ...successfulRun, status: "in_progress", conclusion: null }] },
    { workflow_runs: [successfulRun] },
  ]);
  assert.deepEqual(await check.run(), successfulRun);
  assert.deepEqual(check.sleeps, [30_000, 30_000]);
});

for (const conclusion of ["failure", "cancelled", "timed_out", "skipped", null]) {
  test(`completed ${conclusion} CI fails without polling`, async () => {
    const check = gate([{ workflow_runs: [{ ...successfulRun, conclusion }] }]);
    await assert.rejects(check.run(), /did not complete successfully/);
    assert.equal(check.requests.length, 1);
    assert.equal(check.sleeps.length, 0);
  });
}

test("a newer pending rerun cannot use an older successful result", async () => {
  const pending = { ...successfulRun, run_attempt: 2, status: "queued", conclusion: null };
  const check = gate([
    { workflow_runs: [pending, successfulRun] },
    { workflow_runs: [{ ...pending, status: "completed", conclusion: "failure" }, successfulRun] },
  ]);
  await assert.rejects(check.run(), /did not complete successfully/);
  assert.deepEqual(check.sleeps, [30_000]);
});

test("pending CI times out within ten minutes and at most 21 requests", async () => {
  const check = gate([{ workflow_runs: [] }]);
  await assert.rejects(check.run(), /Timed out/);
  assert.ok(check.requests.length <= 21);
  assert.equal(check.sleeps.reduce((total, milliseconds) => total + milliseconds, 0), 600_000);
});

test("request time counts toward the ten-minute deadline", async () => {
  let elapsed = 0;
  const check = gate([], {
    now: () => elapsed,
    fetch: async () => {
      elapsed = 600_001;
      return Response.json({ workflow_runs: [successfulRun] });
    },
  });
  await assert.rejects(check.run(), /Timed out/);
  assert.equal(check.sleeps.length, 0);
});

test("response parsing time counts toward the ten-minute deadline", async () => {
  let elapsed = 0;
  const check = gate([], {
    now: () => elapsed,
    fetch: async () => ({
      ok: true,
      json: async () => {
        elapsed = 600_001;
        return { workflow_runs: [successfulRun] };
      },
    }),
  });
  await assert.rejects(check.run(), /Timed out/);
  assert.equal(check.sleeps.length, 0);
});

test("temporary API and network failures retry without exposing failure details", async () => {
  const check = gate([
    new Response("upstream diagnostic", { status: 503 }),
    new Response("request expired", { status: 408 }),
    { workflow_runs: [successfulRun] },
  ]);
  assert.deepEqual(await check.run(), successfulRun);
  assert.deepEqual(check.sleeps, [30_000, 30_000]);
  assert.ok(check.logs.every((message) => !message.includes("upstream diagnostic") && !message.includes("request expired")));
  assert.ok(check.logs.some((message) => message.includes("HTTP 503") && message.includes("30 seconds")));

  const disconnected = gate([], { fetch: async () => { throw new Error("token=secret"); } });
  await assert.rejects(disconnected.run(), /Timed out/);
  assert.ok(disconnected.logs.every((message) => !message.includes("token=secret")));
  assert.ok(disconnected.logs.some((message) => message.includes("network error or request timeout")));
});

test("rate-limit retries honor Retry-After and reset headers", async () => {
  const retryAfter = gate([
    new Response(null, { status: 429, headers: { "retry-after": "45" } }),
    { workflow_runs: [successfulRun] },
  ]);
  await retryAfter.run();
  assert.deepEqual(retryAfter.sleeps, [45_000]);

  const reset = gate([
    new Response(null, { status: 429, headers: { "x-ratelimit-remaining": "0", "x-ratelimit-reset": "120" } }),
    { workflow_runs: [successfulRun] },
  ]);
  await reset.run();
  assert.deepEqual(reset.sleeps, [120_000]);
});

test("rate-limit retries use a normal poll delay for zero or past waits", async () => {
  const retryAfter = gate([
    new Response(null, { status: 429, headers: { "retry-after": "0" } }),
    { workflow_runs: [successfulRun] },
  ]);
  await retryAfter.run();
  assert.deepEqual(retryAfter.sleeps, [30_000]);

  const reset = gate([
    new Response(null, { status: 429, headers: { "x-ratelimit-remaining": "0", "x-ratelimit-reset": "0" } }),
    { workflow_runs: [successfulRun] },
  ], { now: () => 60_000 });
  await reset.run();
  assert.deepEqual(reset.sleeps, [30_000]);
});

test("an unknown rate limit waits at least one minute and backs off", async () => {
  const check = gate([
    new Response(null, { status: 429 }),
    new Response(null, { status: 429 }),
    { workflow_runs: [successfulRun] },
  ]);
  await check.run();
  assert.deepEqual(check.sleeps, [60_000, 120_000]);
});

test("a rate-limited 403 without a reset time waits at least one minute", async () => {
  const check = gate([
    new Response(null, { status: 403, headers: { "x-ratelimit-remaining": "0" } }),
    new Response(null, { status: 403, headers: { "x-ratelimit-remaining": "0" } }),
    { workflow_runs: [successfulRun] },
  ]);
  await check.run();
  assert.deepEqual(check.sleeps, [60_000, 120_000]);
});

test("Retry-After dates are honored without exceeding the deadline", async () => {
  const retryAt = gate([
    new Response(null, { status: 429, headers: { "retry-after": new Date(90_000).toUTCString() } }),
    { workflow_runs: [successfulRun] },
  ]);
  await retryAt.run();
  assert.deepEqual(retryAt.sleeps, [90_000]);

  const beyondDeadline = gate([
    new Response(null, { status: 429, headers: { "retry-after": "3600" } }),
    { workflow_runs: [successfulRun] },
  ]);
  await assert.rejects(beyondDeadline.run(), /Timed out/);
  assert.deepEqual(beyondDeadline.sleeps, [600_000]);
  assert.equal(beyondDeadline.requests.length, 1);
  assert.ok(beyondDeadline.logs.some((message) => message.includes("HTTP 429") && message.includes("600 seconds") && message.includes("reaches the build deadline")));
});

test("a temporary network failure can recover on the next attempt", async () => {
  let attempts = 0;
  const check = gate([], {
    fetch: async () => {
      if (++attempts === 1) throw new DOMException("request timed out", "TimeoutError");
      return Response.json({ workflow_runs: [successfulRun] });
    },
  });
  assert.deepEqual(await check.run(), successfulRun);
  assert.deepEqual(check.sleeps, [30_000]);
  assert.equal(attempts, 2);
});

test("permanent API failures and invalid JSON fail without retrying", async () => {
  for (const status of [400, 401, 403, 404, 422]) {
    const check = gate([new Response("do not expose this body", { status })]);
    await assert.rejects(check.run(), new RegExp(`HTTP ${status}`));
    assert.equal(check.requests.length, 1);
    assert.equal(check.sleeps.length, 0);
  }

  const invalidJson = gate([new Response("{", { headers: { "content-type": "application/json" } })]);
  await assert.rejects(invalidJson.run(), /invalid workflow runs/);
  assert.equal(invalidJson.requests.length, 1);
  assert.equal(invalidJson.sleeps.length, 0);
});

test("a rate-limited 403 retries, while other 403 responses fail", async () => {
  const rateLimited = gate([
    new Response(null, { status: 403, headers: { "x-ratelimit-remaining": "0", "x-ratelimit-reset": "120" } }),
    { workflow_runs: [successfulRun] },
  ]);
  await rateLimited.run();
  assert.deepEqual(rateLimited.sleeps, [120_000]);

  const forbidden = gate([new Response("forbidden", { status: 403 })]);
  await assert.rejects(forbidden.run(), /HTTP 403/);
  assert.equal(forbidden.sleeps.length, 0);
});

for (const mismatch of [{ head_sha: "b".repeat(40) }, { head_branch: "preview" }, { event: "pull_request" }]) {
  test(`CI cannot approve mismatched ${Object.keys(mismatch)[0]}`, async () => {
    const check = gate([{ workflow_runs: [{ ...successfulRun, ...mismatch }] }]);
    await assert.rejects(check.run(), /does not match/);
    assert.equal(check.sleeps.length, 0);
  });
}

for (const buildEnvironment of [{}, { GITHUB_ACTIONS: "true", CI: "true" }, { WORKERS_CI: "1", WORKERS_CI_BRANCH: "preview" }]) {
  test(`local, GitHub, and preview builds skip without git or network: ${JSON.stringify(buildEnvironment)}`, async () => {
    const check = gate([], {
      environment: buildEnvironment,
      readHead: () => assert.fail("skip must not read git"),
      fetch: () => assert.fail("skip must not query CI and wait on itself"),
    });
    assert.equal(await check.run(), null);
    assert.equal(check.sleeps.length, 0);
  });
}

test("main Workers Builds fail closed on absent metadata or a different checkout", async () => {
  for (const invalid of [
    { WORKERS_CI: "1" },
    { ...environment, WORKERS_CI_COMMIT_SHA: undefined },
    { ...environment, WORKERS_CI_COMMIT_SHA: "abc123" },
  ]) {
    const check = gate([], { environment: invalid });
    await assert.rejects(check.run(), /Workers Builds/);
    assert.equal(check.requests.length, 0);
  }
  const check = gate([], { readHead: () => "b".repeat(40) });
  await assert.rejects(check.run(), /does not match git HEAD/);
  assert.equal(check.requests.length, 0);
});

test("a checkout change after waiting for CI stops the build", async () => {
  const changedCommit = "b".repeat(40);
  const check = gate([
    { workflow_runs: [] },
    { workflow_runs: [successfulRun] },
  ], {
    readHead: () => check.sleeps.length ? changedCommit : commit,
  });
  await assert.rejects(check.run(), /does not match git HEAD/);
  assert.equal(check.requests.length, 1);
});

test("a checkout change before CI approval stops the build", async () => {
  const check = gate([{ workflow_runs: [successfulRun] }], {
    readHead: () => check.requests.length ? "b".repeat(40) : commit,
  });
  await assert.rejects(check.run(), /does not match git HEAD/);
  assert.equal(check.requests.length, 1);
});

test("malformed response failures stop the build", async () => {
  const unavailable = gate([], { fetch: async () => new Response("unavailable", { status: 503 }) });
  await assert.rejects(unavailable.run(), /Timed out/);
  const malformed = gate([{ message: "unexpected response" }]);
  await assert.rejects(malformed.run(), /invalid workflow runs/);
  const invalidRun = gate([{ workflow_runs: [{}] }]);
  await assert.rejects(invalidRun.run(), /invalid workflow runs/);
  for (const run of [null, 0]) {
    const check = gate([{ workflow_runs: [run] }]);
    await assert.rejects(check.run(), /invalid workflow runs/);
  }
});

test("an optional GitHub token only authenticates the read request", async () => {
  const check = gate([{ workflow_runs: [successfulRun] }], { environment: { ...environment, GITHUB_TOKEN: "test-token" } });
  await check.run();
  assert.equal(check.requests[0].options.headers.authorization, "Bearer test-token");
  assert.equal(check.requests[0].options.method, undefined);
});

test("automation CI lookup pins the temporary branch and never accepts main's run", async () => {
  const branch = "auto/schedules/123-1-1";
  for (const returnedBranch of [branch, "main"]) {
    const options = {
      commit, branch, environment: {}, readHead: () => commit, log: () => {},
      fetch: async (url) => {
        assert.equal(url.searchParams.get("head_sha"), commit);
        assert.equal(url.searchParams.get("branch"), branch);
        return Response.json({ workflow_runs: [{ ...successfulRun, head_branch: returnedBranch }] });
      },
    };
    if (returnedBranch === branch) assert.equal((await waitForCommitCI(options)).conclusion, "success");
    else await assert.rejects(waitForCommitCI(options), /does not match/);
  }
});

test("generated path allowlist excludes credentials, source code, and unexpected artifact names", () => {
  for (const path of [
    "content/spots/mission-community-pool.md", "content/spots/mission-community-pool.zh-Hant.md",
    "data/bulletin.json", "data/i18n/en.json", "schedule-tools/src/schedules/registry.toml",
    "data/i18n/dynamic-labels.json",
    "data/mission-community-pool/2026-09-02-67f2a420e8fc/source.pdf",
    "data/mission-community-pool/2026-09-02-67f2a420e8fc/openai-gpt-5-5-2026-04-23.json",
    "data/north-beach-pool/2026-09-06-67f2a420e8fc/source-bundle.json",
    "data/north-beach-pool/2026-09-06-67f2a420e8fc/openai-pool-bundle.json",
  ]) assert.equal(generatedSchedulePath(path), true, path);
  for (const path of [
    ".env", ".github/workflows/ci.yml", "schedule-tools/src/schedules/publish.py",
    "content/spots/../../.env", "content/spots/pool.md\n", "data/i18n/private.json",
    "data/dynamic-labels.json",
    "data/pool/2026-09-02-67f2a420e8fc/request.json", "data/pool/2026-09-02-67f2a420e8fc/gemini-model.json",
    "data/north-beach-pool/2026-09-06-67f2a420e8fc/bundle.json",
  ]) assert.equal(generatedSchedulePath(path), false, path);
});

function promotionRepository(t, { path = "content/spots/test-pool.md", symlink = false } = {}) {
  const directory = mkdtempSync(join(tmpdir(), "swim-promotion-test-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const remote = join(directory, "origin.git");
  const work = join(directory, "work");
  const command = (cwd, args) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  command(directory, ["init", "--bare", "--initial-branch=main", remote]);
  command(directory, ["clone", remote, work]);
  const git = (args) => command(work, args);
  git(["config", "user.name", "Schedule test"]);
  git(["config", "user.email", "test@example.invalid"]);
  writeFileSync(join(work, "seed.txt"), "baseline\n");
  git(["add", "seed.txt"]);
  git(["commit", "-m", "Baseline"]);
  git(["push", "origin", "main"]);
  const base = git(["rev-parse", "HEAD"]).trim();
  mkdirSync(join(work, "content/spots"), { recursive: true });
  if (symlink) symlinkSync("../../seed.txt", join(work, path));
  else writeFileSync(join(work, path), "generated schedule\n");
  git(["add", path]);
  git(["commit", "-m", "Accepted schedule"]);
  const candidate = git(["rev-parse", "HEAD"]).trim();
  const branch = "auto/schedules/123-1-1";
  const remoteHead = (ref = "main") => command(remote, ["rev-parse", `refs/heads/${ref}`]).trim();
  const advanceMain = () => {
    const other = join(directory, "other");
    command(directory, ["clone", remote, other]);
    command(other, ["config", "user.name", "Concurrent author"]);
    command(other, ["config", "user.email", "other@example.invalid"]);
    writeFileSync(join(other, "user-change.txt"), "preserve me\n");
    command(other, ["add", "user-change.txt"]);
    command(other, ["commit", "-m", "Concurrent change"]);
    command(other, ["push", "origin", "main"]);
    return remoteHead();
  };
  return { work, base, candidate, branch, git, remoteHead, advanceMain,
    options: { base, branch, git, environment: {}, waitForCI: async ({ commit, branch }) => {
      assert.equal(remoteHead(branch), commit);
      assert.equal(remoteHead(), base);
      return { ...successfulRun, head_sha: commit, head_branch: branch, html_url: "https://example.invalid/check" };
    } },
  };
}

test("stage rejects unexpected paths before changing the index", (t) => {
  const repository = promotionRepository(t);
  writeFileSync(join(repository.work, ".env"), "do not publish\n");
  writeFileSync(join(repository.work, "content/spots/test-pool.md"), "updated\n");
  assert.throws(() => stageScheduleChanges(repository), /Unexpected/);
  assert.equal(repository.git(["diff", "--cached", "--name-only"]), "");
});

test("stage recognizes direct clock metadata without suppressing real source changes", (t) => {
  const repository = promotionRepository(t);
  const path = "data/test-pool/2026-09-02-67f2a420e8fc/direct-test.json";
  mkdirSync(join(repository.work, "data/test-pool/2026-09-02-67f2a420e8fc"), { recursive: true });
  const artifact = { provider: "direct", extracted_at: "yesterday", payload: { effective_start: "2026-09-01", sessions: [] } };
  writeFileSync(join(repository.work, path), JSON.stringify(artifact));
  repository.git(["add", path]);
  repository.git(["commit", "-m", "Direct capture"]);
  writeFileSync(join(repository.work, path), JSON.stringify({ ...artifact, extracted_at: "today", payload: { ...artifact.payload, effective_start: "2026-09-02" } }));
  assert.equal(stageScheduleChanges(repository).changed, false);
  writeFileSync(join(repository.work, path), JSON.stringify({ ...artifact, payload: { ...artifact.payload, sessions: [{ day: "monday" }] } }));
  assert.equal(stageScheduleChanges(repository).changed, true);
});

test("stage treats PDF dates as facts, not direct-source clock metadata", (t) => {
  const repository = promotionRepository(t);
  const path = "data/test-pool/2026-09-02-67f2a420e8fc/openai-gpt-5-5-2026-04-23.json";
  mkdirSync(join(repository.work, "data/test-pool/2026-09-02-67f2a420e8fc"), { recursive: true });
  writeFileSync(join(repository.work, path), JSON.stringify({ provider: "openai", payload: { effective_start: "2026-09-01" } }));
  repository.git(["add", path]);
  repository.git(["commit", "-m", "PDF capture"]);
  writeFileSync(join(repository.work, path), JSON.stringify({ provider: "openai", payload: { effective_start: "2026-09-02" } }));
  assert.equal(stageScheduleChanges(repository).changed, true);
});

test("promotion checks the exact temporary-branch commit before fast-forwarding main", async (t) => {
  const repository = promotionRepository(t);
  const result = await promoteScheduleCommit(repository.options);
  assert.equal(result.status, "promoted");
  assert.equal(result.commit, repository.candidate);
  assert.equal(repository.remoteHead(), repository.candidate);
  assert.equal(result.check_url, "https://example.invalid/check");
});

test("failed CI never updates main", async (t) => {
  const repository = promotionRepository(t);
  await assert.rejects(promoteScheduleCommit({ ...repository.options, waitForCI: async () => {
    throw new Error("CI failed");
  } }), /CI failed/);
  assert.equal(repository.remoteHead(), repository.base);
});

for (const race of ["during checks", "during push"]) {
  test(`a concurrent main update ${race} is preserved and requires rebuilding`, async (t) => {
    const repository = promotionRepository(t);
    let newMain;
    const result = await promoteScheduleCommit({ ...repository.options,
      waitForCI: async (options) => {
        const check = await repository.options.waitForCI(options);
        if (race === "during checks") newMain = repository.advanceMain();
        return check;
      },
      git: (args) => {
        if (race === "during push" && args[0] === "push" && args.at(-1).endsWith(":refs/heads/main")) newMain = repository.advanceMain();
        return repository.git(args);
      },
    });
    assert.equal(result.status, "stale");
    assert.equal(repository.remoteHead(), newMain);
  });
}

for (const options of [{ path: ".env" }, { symlink: true }]) {
  test(`promotion rejects unsafe generated changes: ${JSON.stringify(options)}`, async (t) => {
    const repository = promotionRepository(t, options);
    await assert.rejects(promoteScheduleCommit(repository.options), /unexpected generated paths|regular generated files/);
    assert.equal(repository.remoteHead(), repository.base);
  });
}
