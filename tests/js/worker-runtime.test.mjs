// HTTP contracts in workerd with real local KV and Cache API storage.
// Browser journeys own rendered behavior; these cases need no browser.
import { after, before, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { parse } from "smol-toml";
import { createTestHarness } from "wrangler";

const conditions = {
  "aquatic-park": { water_temp_f: 61.2, updated_at: "2026-09-24T18:00:00Z" },
};
let server;
let assets;

before(async () => {
  // Use Miniflare's offline Request.cf fixture instead of fetching geolocation.
  process.env.CLOUDFLARE_CF_FETCH_ENABLED = "false";
  assets = mkdtempSync(join(tmpdir(), "sf-worker-test-"));
  writeFileSync(join(assets, "index.html"), "<h1>Static asset</h1>");
  writeFileSync(join(assets, "404.html"), "<h1>Page not found</h1>");
  const config = parse(readFileSync("worker/wrangler.toml", "utf8"));
  server = createTestHarness({ workers: [{ config: {
    ...config,
    main: resolve("worker", config.main),
    assets: { ...config.assets, directory: assets },
  } }] });
  await server.listen();
});

// Resets KV AND the Cache API before every case, including a focused run.
beforeEach(async () => { await server.reset(); });
after(async () => {
  await server?.close();
  if (assets) rmSync(assets, { recursive: true, force: true });
});

async function seedConditions() {
  const { CONDITIONS } = await server.getWorker().getEnv();
  await CONDITIONS.put("conditions", JSON.stringify(conditions));
}

test("conditions preserve readings without granting cross-origin browser access", async () => {
  await seedConditions();
  for (const origin of ["https://swimfrancisco.com", "https://untrusted.example", "http://localhost:8787", null, "https://swimfrancisco.com"]) {
    const response = await server.fetch("/api/conditions", { headers: origin ? { origin } : {} });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), conditions);
    assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
    assert.equal(response.headers.get("cache-control"), "public, max-age=900, s-maxage=3600");
    assert.equal(response.headers.get("vary"), null);
    assert.equal(response.headers.get("access-control-allow-origin"), null);
  }
});

// Deliberately follows a populated case: leaked KV or edge cache must fail here.
test("empty conditions recover after population, including the trailing-slash route", async () => {
  for (const path of ["/api/conditions", "/api/conditions/"]) {
    const response = await server.fetch(path);
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("content-type"), "text/plain; charset=utf-8");
    assert.equal(response.headers.get("cache-control"), "public, max-age=60");
    assert.equal(await response.text(), "conditions not yet available");
  }
  await seedConditions();
  for (const path of ["/api/conditions/", "/api/conditions"]) {
    const response = await server.fetch(path);
    assert.equal(response.status, 200, "an earlier 503 must not mask newly available readings");
    assert.deepEqual(await response.json(), conditions);
  }
});

test("conditions reject preflight and unsupported methods before population", async () => {
  for (const method of ["OPTIONS", "POST", "PUT", "DELETE"]) {
    const response = await server.fetch("/api/conditions", { method, headers: { origin: "https://untrusted.example" } });
    assert.equal(response.status, 405);
    assert.equal(await response.text(), "method not allowed");
    assert.equal(response.headers.get("access-control-allow-origin"), null);
  }
});

test("missing map configuration and API routes fail without falling through to assets", async () => {
  const config = await server.fetch("/api/map-config");
  assert.equal(config.status, 503);
  assert.equal(config.headers.get("cache-control"), "no-store");
  assert.deepEqual(await config.json(), { error: "map configuration unavailable" });
  const missing = await server.fetch("/api/unknown");
  assert.equal(missing.status, 404);
  assert.equal(await missing.text(), "not found");
});

test("non-API requests use configured static assets and the custom 404 page", async () => {
  const page = await server.fetch("/");
  assert.equal(page.status, 200);
  assert.equal(await page.text(), "<h1>Static asset</h1>");
  const missing = await server.fetch("/does-not-exist/");
  assert.equal(missing.status, 404);
  assert.equal(await missing.text(), "<h1>Page not found</h1>");
});
