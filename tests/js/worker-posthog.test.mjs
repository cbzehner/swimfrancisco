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
