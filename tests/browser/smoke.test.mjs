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

for (const engine of ["webkit", "chromium"]) {
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
