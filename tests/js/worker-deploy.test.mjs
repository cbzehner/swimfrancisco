// Pin the contract for the daily-rebuild helper. The Worker's scheduled
// handler calls triggerRebuild on the hourly tick that lands at 00:00 PT;
// this test locks in success on 2xx and throw-with-status on non-ok, so a
// silent 5xx cannot go unnoticed in `wrangler tail`.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { triggerRebuild } from "../../worker/src/deploy.ts";
import worker from "../../worker/src/index.ts";

const HOOK = "https://example.invalid/hook";
const SCHEDULED_AT = Date.UTC(2026, 3, 18, 7, 0);

let originalFetch;
let fetchCalls;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchCalls = [];
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("triggerRebuild POSTs to the hook URL and resolves on 2xx", async () => {
  globalThis.fetch = async (url, init) => {
    fetchCalls.push({ url, method: init?.method });
    return new Response("", { status: 200 });
  };

  await triggerRebuild(HOOK, SCHEDULED_AT);

  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, HOOK);
  assert.equal(fetchCalls[0].method, "POST");
});

test("triggerRebuild throws with the status code on non-ok responses", async () => {
  globalThis.fetch = async () => new Response("", { status: 503 });

  await assert.rejects(
    () => triggerRebuild(HOOK, SCHEDULED_AT),
    /deploy hook returned 503/,
  );
});

test("scheduled reports a conditions KV write failure through waitUntil", async () => {
  globalThis.fetch = async () => {
    throw new Error("upstream unavailable");
  };
  const originalConsoleError = console.error;
  console.error = () => {};
  const tasks = [];
  const env = {
    CONDITIONS: {
      get: async () => null,
      put: async () => {
        throw new Error("KV write failed");
      },
    },
    WORKERS_BUILDS_DEPLOY_HOOK: HOOK,
  };
  const ctx = {
    waitUntil(promise) {
      tasks.push(promise);
    },
  };

  try {
    await worker.scheduled({ scheduledTime: Date.UTC(2026, 3, 18, 19, 0) }, env, ctx);
    assert.equal(tasks.length, 1);
    await assert.rejects(tasks[0], /KV write failed/);
  } finally {
    console.error = originalConsoleError;
  }
});
