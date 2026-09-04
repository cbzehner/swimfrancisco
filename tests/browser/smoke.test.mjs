// Real-browser integration smoke tests — the regressions that node:test and
// zola-render tests structurally cannot catch live here. Every scenario in
// this file is a bug that actually shipped:
//   - horizon menu taps swallowed on iOS (WebKit focus semantics)
//   - row-link overlay blanketing the page controls (WebKit containing block)
//   - CJK language labels stacking vertically on narrow screens
// plus a hydration canary for the silent base_url failure mode documented in
// docs/testing-webkit.md.
//
// Runs WebKit (the engine that catches these) and Chromium. The site is
// built fresh with a local base-url and served on an ephemeral port, so a
// stale dev server can never make these tests lie.
//
// Run via `just test-browser` (installs nothing); browsers come from
// `just browsers` once per machine.

import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, rmSync, existsSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, extname, resolve } from "node:path";

import { webkit, chromium, devices } from "playwright-core";

const ROOT = resolve(import.meta.dirname, "..", "..");
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".webmanifest": "application/manifest+json",
  ".xml": "application/xml",
  ".txt": "text/plain",
};

let outDir;
let server;
let baseURL;
const browsers = {};

function serveStatic(dir) {
  return createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    let path = join(dir, decodeURIComponent(url.pathname));
    if (existsSync(path) && statSync(path).isDirectory()) path = join(path, "index.html");
    if (!existsSync(path)) {
      res.writeHead(404).end("not found");
      return;
    }
    res.writeHead(200, { "content-type": MIME[extname(path)] ?? "application/octet-stream" });
    res.end(readFileSync(path));
  });
}

before(async () => {
  outDir = mkdtempSync(join(tmpdir(), "sf-smoke-"));
  server = serveStatic(outDir);
  await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
  baseURL = `http://127.0.0.1:${server.address().port}`;
  // Build AFTER the port is known so module URLs are same-origin — a
  // production base_url here loads JS cross-origin, silently testing a
  // JS-free page (see docs/testing-webkit.md).
  execFileSync("zola", ["build", "--base-url", baseURL, "--output-dir", outDir, "--force"], {
    cwd: ROOT,
    stdio: "pipe",
  });
  for (const [name, engine] of [["webkit", webkit], ["chromium", chromium]]) {
    browsers[name] =
      name === "chromium"
        ? await engine.launch({ channel: "chrome" }).catch(() => engine.launch())
        : await engine.launch();
  }
});

after(async () => {
  for (const browser of Object.values(browsers)) await browser?.close();
  server?.close();
  if (outDir) rmSync(outDir, { recursive: true, force: true });
});

async function boardPage(t, engineName, contextOptions = {}) {
  const context = await browsers[engineName].newContext({
    viewport: { width: 1280, height: 900 },
    ...contextOptions,
  });
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto(`${baseURL}/`, { waitUntil: "networkidle" });
  return { page, errors };
}

async function fixturePage(t, engineName, html) {
  const context = await browsers[engineName].newContext();
  t.after(() => context.close());
  const page = await context.newPage();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install({ time: new Date("2026-09-24T18:58:00Z") });
  await page.clock.pauseAt(new Date("2026-09-24T18:59:00Z"));
  await page.route("**/fixture", (route) => route.fulfill({
    contentType: "text/html",
    body: `<!doctype html><html><head><meta charset="utf-8"></head><body>${html}</body></html>`,
  }));
  return page;
}

for (const engine of ["webkit", "chromium"]) {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 320, height: 700 }]) {
    test(`[${engine}/${viewport.width}px] real map fills the viewport and markers open popups`, async (t) => {
      const context = await browsers[engine].newContext({ viewport, reducedMotion: "reduce" });
      t.after(() => context.close());
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("https://*.basemaps.cartocdn.com/**", (route) => route.abort());
      await page.route("**/api/conditions", (route) => route.fulfill({ json: {} }));
      await page.goto(`${baseURL}/map/`, { waitUntil: "networkidle" });
      await page.locator(".sf-marker").first().waitFor();

      const map = await page.locator("#map-view").boundingBox();
      assert.ok(map && map.height > 300, `map must have usable height, got ${map?.height}px`);
      assert.ok(map.y + map.height <= viewport.height + 1, "map bottom must fit below the site header");
      assert.ok(map.width >= viewport.width - 2, "map must fill the viewport width");
      if (viewport.width <= 640) {
        const navigation = await page.locator(".site-header-actions").boundingBox();
        assert.ok(map.y + map.height <= navigation.y + 1, "map must not overlap the bottom navigation");
        assert.ok(navigation.y + navigation.height <= viewport.height + 1, "bottom navigation must fit the viewport");
      }
      const attribution = await page.locator(".leaflet-control-attribution").boundingBox();
      assert.ok(attribution.y + attribution.height <= map.y + map.height + 1, "map attribution must remain visible");

      const markerIndex = await page.locator(".sf-marker").evaluateAll((markers) => markers.findIndex((marker) => {
        const box = marker.getBoundingClientRect();
        const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
        return hit && marker.contains(hit);
      }));
      assert.ok(markerIndex >= 0, "at least one real marker must receive pointer input");
      await page.locator(".sf-marker").nth(markerIndex).click();
      await page.locator(".sf-map-popup").waitFor({ state: "visible" });
      assert.match(await page.locator(".sf-map-popup-title").getAttribute("href"), /\/spots\/[^/]+\//);
      await page.evaluate(() => document.dispatchEvent(new CustomEvent("sf:conditions-loaded")));
      assert.equal(await page.locator(".sf-map-popup").isVisible(), true);
      await page.locator(`.site-nav-link[data-target-path="${baseURL}/"]`).click();
      await page.waitForURL(`${baseURL}/`);
      assert.deepEqual(errors, []);
    });
  }

  test(`[${engine}] detail restores today's sessions after a partial closure`, async (t) => {
    const schedule = {
      sessions: [{ day: "thursday", type: "lap_swim", start: "11:00", end: "15:00" }],
      closures: [{ start: "2026-09-24", end: "2026-09-24", start_time: "12:00", end_time: "14:00" }],
    };
    const page = await fixturePage(t, engine, `
      <div class="detail-root" data-schedule='${JSON.stringify(schedule)}'>
        <span data-field="status"></span><span data-field="next"></span>
        <section class="today-block"><ul class="today-block-list">
          <li data-start="11:00" data-end="15:00"><span class="time">11:00–15:00</span><span class="row-label"></span></li>
        </ul></section>
      </div><script type="module" src="/js/detail.js"></script>`);
    await page.goto(`${baseURL}/fixture`);
    assert.match(await page.locator('[data-field="status"]').textContent(), /UNTIL 12:00/);
    await page.clock.fastForward(60_000);
    assert.equal(await page.locator(".today-block").isHidden(), true);
    await page.clock.fastForward(2 * 60 * 60_000);
    assert.equal(await page.locator(".today-block").isVisible(), true);
    assert.match(await page.locator('[data-field="status"]').textContent(), /UNTIL 15:00/);
    assert.equal(await page.locator(".row-label").textContent(), "NOW");
  });

  test(`[${engine}] detail conditions retry, refresh, and clear withdrawn readings`, async (t) => {
    const page = await fixturePage(t, engine, `
      <div class="bulletin-strip" data-bay-slugs="aquatic-park"><span data-bay-temp-strip>—</span></div>
      <section class="conditions" data-slug="aquatic-park"><span data-field="water_temp">—</span><span data-field="tide">—</span></section>
      <script type="module" src="/js/conditions.js"></script>`);
    let requests = 0;
    let conditions = { "aquatic-park": {
      water_temp_f: 58, temp_stale: true,
      tide: { predictions: [{ time: "2026-09-24T12:01:00", type: "H", value_ft: 4 }] },
    } };
    await page.route("**/api/conditions", (route) => {
      requests += 1;
      return route.fulfill({ status: requests === 1 ? 503 : 200, json: conditions });
    });
    await page.goto(`${baseURL}/fixture`);
    await page.waitForFunction(() => document.querySelector('[data-field="water_temp"]').textContent === "—");
    const retry = page.waitForResponse("**/api/conditions");
    await page.clock.fastForward(60_000);
    await retry;
    await page.waitForFunction(() => document.querySelector('[data-field="water_temp"]').textContent === "58°F");
    assert.equal(requests, 2);
    assert.equal(await page.locator('[data-field="water_temp"]').getAttribute("data-temp-stale"), "true");
    assert.match(await page.locator('[data-field="tide"]').textContent(), /12:01/);
    await page.clock.fastForward(2 * 60_000);
    assert.equal(await page.locator('[data-field="tide"]').textContent(), "—");
    assert.equal(requests, 2, "minute updates must respect the fetch throttle");

    conditions = { "aquatic-park": { water_temp_f: null, water_temp_c: null, tide: null } };
    await page.evaluate(() => Object.defineProperty(document, "hidden", { configurable: true, value: true }));
    await page.clock.fastForward(15 * 60_000);
    assert.equal(requests, 2, "hidden detail pages must not poll");
    const refreshed = page.waitForResponse("**/api/conditions");
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, value: false });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await refreshed;
    await page.waitForFunction(() => document.querySelector('[data-field="water_temp"]').textContent === "—");
    assert.equal(requests, 3);
    assert.equal(await page.locator('[data-bay-temp-strip]').textContent(), "—");
    assert.equal(await page.locator('[data-field="water_temp"]').getAttribute("data-temp-stale"), null);
  });

  test(`[${engine}] map refresh preserves markers and open popups`, async (t) => {
    const page = await fixturePage(t, engine, `
      <table class="board" hidden><tbody><tr data-slug="test-pool" data-type="pool" data-lat="37.7749" data-lng="-122.4459">
        <td data-cell="spot"><a href="/spots/test-pool/">Test Pool</a></td>
        <td data-cell="status" data-status-value="AVAILABLE"></td><td data-cell="next">LAP 12:00–15:00</td>
      </tr></tbody></table>
      <div id="map-view" style="height:600px;width:800px"></div>
      <script type="module" src="/js/map.js"></script>`);
    await page.route("https://*.basemaps.cartocdn.com/**", (route) => route.abort());
    await page.goto(`${baseURL}/fixture`);
    await page.locator(".sf-marker-open").waitFor();
    await page.evaluate(() => { window.retainedMarker = document.querySelector(".sf-marker"); });
    await page.locator(".sf-marker").click();
    assert.equal(await page.locator(".sf-map-popup").isVisible(), true);
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("sf:filters-applied"));
      document.dispatchEvent(new CustomEvent("sf:conditions-loaded"));
    });
    assert.equal(await page.evaluate(() => window.retainedMarker === document.querySelector(".sf-marker")), true);
    assert.equal(await page.locator(".sf-map-popup").isVisible(), true);
    await page.evaluate(() => {
      document.querySelector('[data-cell="next"]').textContent = "LAP 14:00–15:00";
      document.dispatchEvent(new CustomEvent("sf:filters-applied"));
    });
    assert.match(await page.locator(".sf-map-popup").textContent(), /14:00–15:00/);
    assert.equal(await page.locator(".sf-map-popup").isVisible(), true);
    for (const status of ["LIMITED", "ACCESS", "CLOSED"]) {
      await page.evaluate((value) => {
        document.querySelector('[data-cell="status"]').dataset.statusValue = value;
        document.dispatchEvent(new CustomEvent("sf:filters-applied"));
      }, status);
      assert.equal(await page.locator(".sf-marker-open").count(), status === "CLOSED" ? 0 : 1);
    }
    await page.evaluate(() => {
      document.querySelector("tbody tr").hidden = true;
      document.dispatchEvent(new CustomEvent("sf:filters-applied"));
    });
    assert.equal(await page.locator(".sf-marker").count(), 0);
  });

  test(`[${engine}] board hydrates: statuses computed, no page errors`, async (t) => {
    const { page, errors } = await boardPage(t, engine);
    const pill = await page.locator('[data-cell="status"] .status-pill').first().textContent();
    assert.notEqual(pill.trim(), "—", "status pills still show em-dash placeholders — JS never ran");
    assert.deepEqual(errors, []);
  });

  test(`[${engine}] default board shows only access_mode=public rows; PRIVATE reveals the rest`, async (t) => {
    const { page } = await boardPage(t, engine);
    const counts = () =>
      page.evaluate(() => ({
        visible: document.querySelectorAll("table.board tbody tr:not([hidden])").length,
        publicRows: document.querySelectorAll('table.board tbody tr[data-access-mode="public"]').length,
        total: document.querySelectorAll("table.board tbody tr").length,
      }));
    const before = await counts();
    assert.equal(before.visible, before.publicRows, "default visible set must equal the public rows");
    await page.locator('button[data-access="memberships"]').click();
    const afterToggle = await counts();
    assert.equal(afterToggle.visible, afterToggle.total, "toggle must reveal every row");
  });

  test(`[${engine}] BACK TO NOW resets the horizon without navigating`, async (t) => {
    const { page } = await boardPage(t, engine);
    await page.goto(`${baseURL}/?when=tomorrow-morning`, { waitUntil: "networkidle" });
    await page.locator("[data-time-banner-reset]").click();
    await page.waitForTimeout(200);
    const url = new URL(page.url());
    assert.equal(url.pathname, "/", "reset must not navigate away from the board");
    assert.equal(url.searchParams.get("when"), null, "?when= must be cleared");
    assert.equal((await page.locator("[data-horizon-button]").textContent()).trim(), "Now");
  });

  test(`[${engine}] whole-row click navigates; spot link and filters still work`, async (t) => {
    const { page } = await boardPage(t, engine);
    await page.locator('tr[data-slug="balboa-pool"] [data-cell="water"]').click();
    await page.waitForURL("**/spots/balboa-pool/**");
    await page.goBack({ waitUntil: "networkidle" });
    await page.locator('tr[data-slug="coffman-pool"] [data-cell="spot"] a').click();
    await page.waitForURL("**/spots/coffman-pool/**");
    await page.goBack({ waitUntil: "networkidle" });
    const lap = page.locator('button[data-type="lap_swim"]');
    await lap.click();
    assert.equal(await lap.getAttribute("aria-pressed"), "true");
  });
}

test("[webkit/iPhone] horizon menu tap applies the selection", async (t) => {
  const { page } = await boardPage(t, "webkit", devices["iPhone 13"]);
  await page.locator("[data-horizon-button]").tap();
  const items = page.locator("[data-horizon-menu] button[role='menuitemradio']");
  const label = (await items.nth(2).textContent()).trim();
  await items.nth(2).tap();
  await page.waitForTimeout(300);
  assert.ok(new URL(page.url()).searchParams.get("when"), "tap must set ?when=");
  assert.equal((await page.locator("[data-horizon-button]").textContent()).trim(), label);
  assert.equal(await page.locator("[data-time-banner]").isHidden(), false);
});

test("[webkit/320px] language switcher labels stay horizontal", async (t) => {
  const { page } = await boardPage(t, "webkit", {
    viewport: { width: 320, height: 700 },
    isMobile: true,
    hasTouch: true,
  });
  const box = await page.locator('.language-switcher a[lang="zh-Hant"]').boundingBox();
  assert.ok(box, "zh-Hant link must render");
  assert.ok(box.height < 30, `CJK label is stacking vertically (height ${box.height}px)`);
});

test("[webkit/320px] conditions and filters remain visible and legible", async (t) => {
  const { page } = await boardPage(t, "webkit", {
    viewport: { width: 320, height: 700 },
    isMobile: true,
    hasTouch: true,
  });
  const layout = await page.evaluate(() => {
    const strip = document.querySelector(".bulletin-strip");
    const stripCells = [...strip.children].map((cell) => cell.getBoundingClientRect());
    const filterButtons = [...document.querySelectorAll(".filters button")];
    return {
      stripFits: strip.scrollWidth <= strip.clientWidth,
      stripRows: new Set(stripCells.map((cell) => Math.round(cell.top))).size,
      filterRows: new Set(filterButtons.map((button) => Math.round(button.getBoundingClientRect().top))).size,
      filterFontSizes: filterButtons.map((button) => Number.parseFloat(getComputedStyle(button).fontSize)),
      statusSubFontSize: Number.parseFloat(getComputedStyle(document.querySelector(".status-sub")).fontSize),
    };
  });
  assert.equal(layout.stripFits, true, "conditions strip must fit without horizontal scrolling");
  assert.equal(layout.stripRows, 2, "conditions strip must show two rows");
  assert.equal(layout.filterRows, 2, "filters must show two rows");
  assert.ok(layout.filterFontSizes.every((size) => size >= 10.5), "filter labels must remain readable");
  assert.ok(layout.statusSubFontSize >= 11, "next-status text must remain readable");
});
