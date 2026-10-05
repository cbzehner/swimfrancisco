import { readFileSync } from "node:fs";
import { parse } from "smol-toml";
import { test, beforeEach } from "@e2e-dev/web";
import { expect } from "e2e";

beforeEach(async ({ browser }) => {
  await browser.addInitScript(() => { const native = window.matchMedia.bind(window); window.matchMedia = (query) => { const result = native(query); if (query === "(prefers-reduced-motion: reduce)") Object.defineProperty(result, "matches", { value: true }); return result; }; });
  await browser.addInitScript("const NativeDate = Date; const clockOffset = NativeDate.parse('2026-09-24T18:59:00Z') - NativeDate.now(); window.Date = class extends NativeDate { constructor(...args) { if (args.length) super(...args); else super(NativeDate.now() + clockOffset); } static now() { return NativeDate.now() + clockOffset; } };");
  // Analytics and basemap providers are outside the local app contract.
  await browser.route("**/ingest/**", (route) => route.fulfill({ status: 204, body: "" }));
  await browser.route("https://*.basemaps.cartocdn.com/**", (route) => route.abort());
});

const conditionsFixture = { "aquatic-park": { water_temp_f: 61.2, updated_at: "2026-09-24T18:00:00Z" } };

const visibleRows = "table.board tbody tr:not([hidden])";

test("public board hydrates; each program and membership filter round trips", async ({ app, browser, screen }) => {
  await app.open("/");
  await expect(screen.getByRole("button", "ALL")).toHaveAttribute("aria-pressed", "true");
  await expect(browser.locator(`${visibleRows}[data-access-mode='public']`)).toHaveCount(14);
  await expect(browser.locator(`${visibleRows}:not([data-access-mode='public'])`)).toHaveCount(0);
  await expect(browser.locator(`${visibleRows}[data-type='pool'] .status-pill`)).toHaveCount(9);
  await expect.poll(() => browser.evaluate(() => Array.from(document.querySelectorAll("table.board tbody tr:not([hidden])[data-type=pool] .status-pill")).every((cell) => /^(OPEN|CLOSED|CHECK|ACCESS|LIMITED)$/.test(cell.textContent?.trim() ?? "")))).toBe(true);
  for (const [label, token, type] of [["LAP", "lap", "lap_swim"], ["FAMILY", "family", "family_swim"], ["SENIOR", "senior", "senior_swim"], ["BEACH", "beach", "open_water"]]) {
    await screen.getByRole("button", label).tap();
    await expect(browser).toHaveURL(new RegExp(`#${token}$`));
    await expect(screen.getByRole("button", label)).toHaveAttribute("aria-pressed", "true");
    const matching = await browser.evaluate(({ selector, program }) => Array.from(document.querySelectorAll(selector)).every((row) => program === "open_water" ? row.getAttribute("data-type") === program : (() => { const schedule = JSON.parse(row.getAttribute("data-schedule")!); return (schedule.schedules ?? [schedule]).some((s: any) => s.sessions?.some((session: any) => session.type === program)); })()), { selector: visibleRows, program: type });
    await expect(matching).toBe(true);
    await expect(await browser.locator(visibleRows).count()).toBeGreaterThan(0);
    await browser.reload();
    await expect(screen.getByRole("button", label)).toHaveAttribute("aria-pressed", "true");
  }
  await screen.getByRole("button", "ALL").tap();
  await screen.getByRole("button", "Include private, membership, and day-pass pools").tap();
  await expect(browser.locator(visibleRows)).toHaveCount(30);
  await expect(browser).toHaveURL(/#memberships$/);
  await screen.getByRole("button", "Include private, membership, and day-pass pools").tap();
  await expect(browser.locator(visibleRows)).toHaveCount(14);
});

test("horizon, program and access survive board/map navigation and reset", async ({ app, browser, screen }) => {
  await app.open("/?when=tomorrow-morning#beach+memberships");
  await expect(browser.locator("[data-time-banner]")).toBeVisible();
  await expect(browser.locator(visibleRows)).toHaveCount(5);
  await screen.getByRole("link", "View map").tap();
  await expect(browser).toHaveURL(/\/map\/\?when=tomorrow-morning#beach\+memberships$/);
  await expect(browser.locator(".sf-marker")).toHaveCount(5);
  await screen.getByRole("link", "View board").tap();
  await expect(browser).toHaveURL(/\/\?when=tomorrow-morning#beach\+memberships$/);
  await browser.locator("[data-time-banner-reset]").tap();
  await expect(browser).toHaveURL(/\/#beach\+memberships$/);
  await expect(browser.locator("[data-time-banner]")).not.toBeVisible();
  await browser.locator("[data-horizon-button]").tap();
  await expect(browser.locator("[data-horizon-menu]")).toBeVisible();
  await browser.keyboard.press("Escape");
  await expect(browser.locator("[data-horizon-menu]")).not.toBeVisible();
});

test("board to pool detail, directions, other lap pools and back", async ({ app, browser, screen }) => {
  await app.open("/");
  await browser.locator("tr[data-slug='mission-community-pool'] [data-cell='spot'] a").tap();
  await expect(browser).toHaveURL(/\/spots\/mission-community-pool\/$/);
  await expect(browser.locator("h1")).toContainText("MISSION");
  // The reviewed September 24 training closure cancels the 11:15 lap session.
  await expect(browser.locator("[data-field='status']")).toHaveText("CLOSED");
  await expect(browser.locator("[data-field='next']")).toHaveText("LAP · THU 14:00");
  await expect(browser.locator(".today-block .time")).toHaveText(["07:30–09:00", "09:15–11:00", "14:00–15:30", "15:45–17:15", "17:45–19:00"]);
  await expect(browser.locator(".weekly-grid").first()).toBeVisible();
  for (const provider of ["APPLE", "GOOGLE"]) {
    const link = screen.getByRole("link", provider);
    const destination = new URL((await link.getAttribute("href"))!);
    await expect(destination.origin).toBe(provider === "APPLE" ? "https://maps.apple.com" : "https://www.google.com");
    await expect(destination.pathname).toBe(provider === "APPLE" ? "/" : "/maps/dir/");
    await expect(destination.searchParams.get(provider === "APPLE" ? "daddr" : "destination")).toBe("101 Linda St, San Francisco, CA 94110");
    await expect(link).toHaveAttribute("target", "_blank");
  }
  await browser.locator(".weekly-grid-crossnav[href$='#lap']:visible").first().tap();
  await expect(browser).toHaveURL(/\/#lap$/);
  await expect(screen.getByRole("button", "LAP")).toHaveAttribute("aria-pressed", "true");
  await browser.back();
  await expect(browser).toHaveURL(/\/spots\/mission-community-pool\/$/);
  await browser.locator(".back a").tap();
  await expect(browser).toHaveURL(/\/$/);
});

test("every supported language has board, map and translated spot navigation", async ({ app, browser }) => {
  await app.open("/");
  const locales = await browser.evaluate(() => Array.from(document.querySelectorAll(".language-switcher a")).map((link) => ({ lang: link.getAttribute("lang"), href: link.getAttribute("href") })));
  await expect(locales.map((locale) => locale.lang)).toEqual((parse(readFileSync("i18n/locales.toml", "utf8")).locales as any[]).map((locale) => locale.code));
  for (const locale of locales) {
    const labels = JSON.parse(readFileSync(`data/i18n/${locale.lang}.json`, "utf8"));
    await browser.goto(locale.href!);
    await expect(browser.locator("html")).toHaveAttribute("lang", locale.lang!);
    await expect(browser.locator(".language-switcher [aria-current='page']")).toHaveAttribute("lang", locale.lang!);
    await expect(browser.locator("[data-type='family_swim']")).toHaveText(labels.family);
    await browser.locator("tr[data-slug='mission-community-pool'] [data-cell='spot'] a").tap();
    await expect(browser.locator("html")).toHaveAttribute("lang", locale.lang!);
    await expect(browser.locator("[data-field='status']")).toHaveText(labels.status_closed);
    await expect(browser.locator(".today-block-heading")).toHaveText(`${labels.today_caps} · ${labels.day_thursday}`);
    await browser.locator(".back a").tap();
    await browser.locator(".site-nav-link[data-target-path*='/map/']").tap();
    await expect(browser.locator("html")).toHaveAttribute("lang", locale.lang!);
    await expect(browser.locator("[data-type='family_swim']")).toHaveText(labels.family);
    await expect(browser.locator(".sf-marker")).toHaveCount(14);
  }
});

test("map survives missing configuration and marker opens the correct spot", async ({ app, browser }) => {
  let tileRequests = 0;
  await browser.route("https://*.basemaps.cartocdn.com/**", (route) => { tileRequests++; return route.abort(); });
  await app.open("/map/#beach");
  await expect(browser.locator(".sf-marker")).toHaveCount(5);
  // The central visible marker receives a real pointer click on both viewports.
  const visibleMarker = await browser.evaluate(() => Array.from(document.querySelectorAll(".sf-marker")).findIndex((marker) => { const box = marker.getBoundingClientRect(); const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2); return !!hit && marker.contains(hit); }));
  await expect(visibleMarker).toBeGreaterThanOrEqual(0);
  const expectedHref = await browser.locator("table.board tbody tr:not([hidden]) [data-cell=spot] a").nth(visibleMarker).getAttribute("href");
  await expect(tileRequests).toBe(0);
  await browser.locator(".sf-marker").nth(visibleMarker).tap();
  await expect(browser.locator(".sf-map-popup")).toBeVisible();
  await expect(browser.locator(".sf-map-popup-title")).toHaveAttribute("href", expectedHref!);
  await browser.locator(".sf-map-popup-title").tap();
  await expect(browser).toHaveURL(expectedHref!);
  await expect(browser.locator(".condition-slab")).toBeVisible();
});

test("open-water conditions load and unavailable data leaves navigation usable", async ({ app, browser }) => {
  // Only this browser context sees the fixture; the shared Worker stays empty.
  await browser.route("**/api/conditions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(conditionsFixture) }));
  await app.open("/spots/aquatic-park/");
  await expect(browser.locator("[data-field='water_temp']")).toHaveText("61°F");
  await browser.route("**/api/conditions", (route) => route.fulfill({ status: 503, contentType: "text/plain", body: "conditions not yet available" }));
  await browser.reload();
  await expect(browser.locator("[data-field='water_temp']")).toHaveText("—");
  await browser.locator(".back a").tap();
  await expect(browser.locator("table.board")).toBeVisible();
});

// Control the permission callback rather than OS prompts to cover both engines.
async function deferredGeolocation(browser: any) {
  await browser.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition: (success: any, failure: any) => { (window as any).__geo = { success, failure }; } } });
  });
}

test("denied nearest sorting keeps the previous open sort coherent", async ({ app, browser, screen }) => {
  await deferredGeolocation(browser);
  await app.open("/#open");
  await expect(browser.locator("[data-filter='open-now']")).toHaveAttribute("aria-pressed", "true");
  const order = await browser.evaluate(() => Array.from(document.querySelectorAll("table.board tbody tr:not([hidden])")).map((row) => row.getAttribute("data-slug")));
  await screen.getByRole("button", "Sort by distance").tap();
  await browser.evaluate(() => (window as any).__geo.failure({ code: 1 }));
  await expect(browser.locator("[data-action='sort-distance']")).toHaveAttribute("aria-pressed", "false");
  await expect(browser.locator("[data-filter='open-now']")).toHaveAttribute("aria-pressed", "true");
  await expect(browser).toHaveURL(/#open$/);
  await expect(await browser.evaluate(() => Array.from(document.querySelectorAll("table.board tbody tr:not([hidden])")).map((row) => row.getAttribute("data-slug")))).toEqual(order);
});

test("choosing open sort cancels a pending nearest result", async ({ app, browser, screen }) => {
  await deferredGeolocation(browser);
  await app.open("/");
  await screen.getByRole("button", "Sort by distance").tap();
  await screen.getByRole("button", "Sort by next open time").tap();
  await browser.evaluate(() => (window as any).__geo.success({ coords: { latitude: 37.77, longitude: -122.42 } }));
  await expect(browser).toHaveURL(/#open$/);
  await expect(browser.locator("[data-action='sort-distance']")).toHaveAttribute("aria-pressed", "false");
  await expect(browser.locator("[data-filter='open-now']")).toHaveAttribute("aria-pressed", "true");
});


test("nearest success sorts pools by distance and clears on reload", async ({ app, browser, screen }) => {
  await deferredGeolocation(browser);
  await app.open("/");
  await screen.getByRole("button", "Sort by distance").tap();
  await browser.evaluate(() => (window as any).__geo.success({ coords: { latitude: 37.759, longitude: -122.414 } }));
  await expect(browser).toHaveURL(/#distance$/);
  await expect(browser.locator("[data-action='sort-distance']")).toHaveAttribute("aria-pressed", "true");
  await expect(browser.locator("table.board tbody tr:not([hidden])").first()).toHaveAttribute("data-slug", "mission-community-pool");
  await browser.reload();
  await expect(browser).toHaveURL(/\/$/);
  await expect(browser.locator("[data-action='sort-distance']")).toHaveAttribute("aria-pressed", "false");
});

test("hash navigation cancels stale location callbacks even after a new request", async ({ app, browser, screen }) => {
  await deferredGeolocation(browser);
  await app.open("/");
  await screen.getByRole("button", "Sort by distance").tap();
  await browser.evaluate(() => { (window as any).__oldGeo = (window as any).__geo; window.location.hash = "beach"; });
  await expect(screen.getByRole("button", "BEACH")).toHaveAttribute("aria-pressed", "true");
  await screen.getByRole("button", "Sort by distance").tap();
  await browser.evaluate(() => (window as any).__oldGeo.success({ coords: { latitude: 0, longitude: 0 } }));
  await expect(browser).toHaveURL(/#beach$/);
  await browser.evaluate(() => (window as any).__geo.failure({ code: 1 }));
  await expect(browser.locator("[data-action='sort-distance']")).toHaveAttribute("aria-pressed", "false");
});
