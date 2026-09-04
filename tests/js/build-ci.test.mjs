import { test } from "node:test";
import assert from "node:assert/strict";

import { checkBuildCI } from "../../scripts/check-build-ci.mjs";

const commit = "a".repeat(40);
const environment = { WORKERS_CI: "1", WORKERS_CI_BRANCH: "main", WORKERS_CI_COMMIT_SHA: commit };
const successfulRun = { head_sha: commit, head_branch: "main", event: "push", status: "completed", conclusion: "success" };

function gate(responses, overrides = {}) {
  let elapsed = 0;
  const requests = [];
  const sleeps = [];
  return {
    requests,
    sleeps,
    run: () => checkBuildCI({
      environment,
      readHead: () => commit,
      now: () => elapsed,
      sleep: async (milliseconds) => { sleeps.push(milliseconds); elapsed += milliseconds; },
      log: () => {},
      fetch: async (url, options) => {
        const response = responses[Math.min(requests.length, responses.length - 1)];
        requests.push({ url, options });
        return Response.json(response);
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
    await assert.rejects(check.run(), /completed with/);
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
  await assert.rejects(check.run(), /completed with failure/);
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

test("GitHub API and malformed response failures stop the build", async () => {
  const unavailable = gate([], { fetch: async () => new Response("unavailable", { status: 503 }) });
  await assert.rejects(unavailable.run(), /HTTP 503/);
  const malformed = gate([{ message: "unexpected response" }]);
  await assert.rejects(malformed.run(), /invalid workflow runs/);
  const disconnected = gate([], { fetch: async () => { throw new Error("network unavailable"); } });
  await assert.rejects(disconnected.run(), /network unavailable/);
});

test("an optional GitHub token only authenticates the read request", async () => {
  const check = gate([{ workflow_runs: [successfulRun] }], { environment: { ...environment, GITHUB_TOKEN: "test-token" } });
  await check.run();
  assert.equal(check.requests[0].options.headers.authorization, "Bearer test-token");
  assert.equal(check.requests[0].options.method, undefined);
});
