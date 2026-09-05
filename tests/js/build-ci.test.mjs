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

  const disconnected = gate([], { fetch: async () => { throw new Error("token=secret"); } });
  await assert.rejects(disconnected.run(), /Timed out/);
  assert.ok(disconnected.logs.every((message) => !message.includes("token=secret")));
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
  let reads = 0;
  const check = gate([{ workflow_runs: [successfulRun] }], {
    readHead: () => ++reads === 1 ? commit : "b".repeat(40),
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
