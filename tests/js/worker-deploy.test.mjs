// Pin the scheduled handler contract: every hourly tick enqueues one
// conditions refresh and does not depend on the removed Workers Builds hook.
//
// Imported directly from the TypeScript source; Node 22.6+ strips types.

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import worker from "../../worker/src/index.ts";

const HOOK = "https://example.invalid/hook";

let originalFetch;
let fetchCalls;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchCalls = [];
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

async function runHourlyRefresh(scheduledTime, includeObsoleteBinding) {
  const tasks = [];
  const writes = [];
  const env = {
    CONDITIONS: {
      get: async () => null,
      put: async (key, value) => writes.push({ key, value }),
    },
  };
  if (includeObsoleteBinding) env.WORKERS_BUILDS_DEPLOY_HOOK = HOOK;

  const originalConsoleError = console.error;
  console.error = () => {};
  globalThis.fetch = async (url, init) => {
    fetchCalls.push({ url, method: init?.method });
    throw new Error("upstream unavailable");
  };

  try {
    await worker.scheduled({ scheduledTime }, env, {
      waitUntil(promise) {
        tasks.push(promise);
      },
    });
    assert.equal(tasks.length, 1);
    await tasks[0];
    assert.equal(writes.length, 1);
    assert.equal(fetchCalls.some(({ url }) => url === HOOK), false);
  } finally {
    console.error = originalConsoleError;
  }
}

for (const [label, scheduledTime] of [
  ["standard time", Date.UTC(2026, 0, 15, 8, 0)],
  ["daylight time", Date.UTC(2026, 5, 15, 7, 0)],
]) {
  for (const includeObsoleteBinding of [false, true]) {
    test(`scheduled refreshes conditions at ${label} ${includeObsoleteBinding ? "with" : "without"} the obsolete binding`, async () => {
      await runHourlyRefresh(scheduledTime, includeObsoleteBinding);
    });
  }
}

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

test("map config exposes only the trimmed CARTO key", async () => {
  const response = await worker.fetch(
    new Request("https://swimfrancisco.com/api/map-config"),
    {
      CARTO_BASEMAP_API_KEY: "  fake-carto-key  ",
      OTHER_SECRET: "must-not-leak",
    },
    {},
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("access-control-allow-origin"), null);
  assert.deepEqual(await response.json(), { carto_basemap_key: "fake-carto-key" });
});

test("map config rejects a missing or blank CARTO key", async () => {
  for (const value of [undefined, "", "   "]) {
    const response = await worker.fetch(
      new Request("https://swimfrancisco.com/api/map-config"),
      { CARTO_BASEMAP_API_KEY: value },
      {},
    );

    assert.equal(response.status, 503);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), { error: "map configuration unavailable" });
  }
});

test("map config rejects non-GET requests", async () => {
  const response = await worker.fetch(
    new Request("https://swimfrancisco.com/api/map-config", { method: "POST" }),
    { CARTO_BASEMAP_API_KEY: "fake-carto-key" },
    {},
  );

  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), { error: "method not allowed" });
});

test("map config reads the CARTO key on every request", async () => {
  const request = () => new Request("https://swimfrancisco.com/api/map-config");
  const first = await worker.fetch(request(), { CARTO_BASEMAP_API_KEY: "fake-key-one" }, {});
  const second = await worker.fetch(request(), { CARTO_BASEMAP_API_KEY: "fake-key-two" }, {});

  assert.deepEqual(await first.json(), { carto_basemap_key: "fake-key-one" });
  assert.deepEqual(await second.json(), { carto_basemap_key: "fake-key-two" });
});

// Negative responses: the two "no data yet" answers are worth a short edge
// cache, a rejected method is not. Pins that split so a shared helper cannot
// quietly start caching a 405.
test("a rejected method sends no cache-control; the miss responses keep theirs", async () => {
  const rejected = await worker.fetch(
    new Request("https://swimfrancisco.com/api/conditions", { method: "POST" }),
    {},
    {},
  );
  assert.equal(rejected.status, 405);
  assert.equal(rejected.headers.get("cache-control"), null);
  assert.equal(await rejected.text(), "method not allowed");

  const missing = await worker.fetch(new Request("https://swimfrancisco.com/nope"), {}, {});
  assert.equal(missing.status, 404);
  assert.equal(missing.headers.get("cache-control"), "public, max-age=60");

  const originalCaches = globalThis.caches;
  globalThis.caches = { default: { match: async () => undefined, put: async () => {} } };
  try {
    const empty = await worker.fetch(
      new Request("https://swimfrancisco.com/api/conditions"),
      { CONDITIONS: { get: async () => null } },
      { waitUntil() {} },
    );
    assert.equal(empty.status, 503);
    assert.equal(empty.headers.get("cache-control"), "public, max-age=60");
    assert.equal(await empty.text(), "conditions not yet available");
  } finally {
    if (originalCaches === undefined) delete globalThis.caches;
    else globalThis.caches = originalCaches;
  }
});
