import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";

import { handlePosthog } from "../../worker/src/posthog.ts";

const MAX_API_BODY_BYTES = 1024 * 1024;
let originalFetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("PostHog upstream failures return gateway errors with timeout signals", async () => {
  const originalCaches = globalThis.caches;
  globalThis.caches = { default: { match: async () => null, put: async () => {} } };
  try {
    for (const path of ["/ingest/e", "/ingest/static/app.js"]) {
      for (const [error, status] of [[new Error("network"), 502], [new DOMException("timeout", "TimeoutError"), 504]]) {
        globalThis.fetch = async (_url, init) => {
          assert.ok(init.signal instanceof AbortSignal);
          throw error;
        };
        const response = await handlePosthog(new Request(`https://swimfrancisco.com${path}`), { waitUntil() {} });
        assert.equal(response.status, status);
      }
    }
  } finally { globalThis.caches = originalCaches; }
});

test("PostHog caches only successful GET assets", async () => {
  const originalCaches = globalThis.caches;
  let puts = 0;
  globalThis.caches = { default: { match: async () => null, put: async () => { puts++; } } };
  try {
    for (const [method, status, expected] of [["POST", 200, 0], ["GET", 404, 0], ["GET", 200, 1]]) {
      globalThis.fetch = async () => new Response("asset", { status });
      await handlePosthog(new Request("https://swimfrancisco.com/ingest/static/app.js", { method }), { waitUntil() {} });
      assert.equal(puts, expected);
    }
  } finally { globalThis.caches = originalCaches; }
});

test("PostHog proxy preserves a bounded API payload", async () => {
  let forwardedBody;
  let forwardedHeaders;
  globalThis.fetch = async (_url, init) => {
    forwardedBody = init.body;
    forwardedHeaders = init.headers;
    return new Response(null, { status: 204 });
  };
  const request = new Request("https://swimfrancisco.com/ingest/e", {
    method: "POST",
    body: "event",
  });

  const response = await handlePosthog(request, { waitUntil() {} });

  assert.equal(response.status, 204);
  assert.equal(new TextDecoder().decode(forwardedBody), "event");
  assert.equal(forwardedHeaders.has("content-length"), false);
});

test("PostHog proxy rejects a declared oversized API payload before forwarding", async () => {
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return new Response(null, { status: 204 });
  };
  const request = new Request("https://swimfrancisco.com/ingest/e", {
    method: "POST",
    headers: { "content-length": String(MAX_API_BODY_BYTES + 1) },
    body: "event",
  });

  const response = await handlePosthog(request, { waitUntil() {} });

  assert.equal(response.status, 413);
  assert.equal(fetchCalls, 0);
});

test("PostHog proxy enforces actual bytes when Content-Length is understated", async () => {
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return new Response(null, { status: 204 });
  };
  const request = new Request("https://swimfrancisco.com/ingest/e", {
    method: "POST",
    headers: { "content-length": "1" },
    body: new Uint8Array(MAX_API_BODY_BYTES + 1),
  });

  const response = await handlePosthog(request, { waitUntil() {} });

  assert.equal(response.status, 413);
  assert.equal(fetchCalls, 0);
});
