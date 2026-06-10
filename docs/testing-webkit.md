# Verifying on Safari / iOS WebKit

How to reproduce and test Safari-specific behavior locally with Playwright
WebKit, without a device or the iOS Simulator. Written after the horizon
("time travel") menu shipped broken on iOS for exactly the kind of
engine-specific behavior Chrome-side testing can't catch.

## Why Chrome testing isn't enough

WebKit (iOS Safari, desktop Safari) differs from Chromium in ways that have
already bitten this codebase:

- **Buttons don't receive focus on tap/click.** Chrome focuses a `<button>`
  on mousedown; WebKit does not. Instead WebKit moves focus to the nearest
  ancestor with a `tabindex` — on every page here that is the skip-link
  target `<main id="main" tabindex="-1">`.
- Consequence: a tap on a control inside an open popover fires `focusout`
  on whatever was programmatically focused, with `relatedTarget` set to
  `<main>` (an "outside" element) — *before* the tap's `click` event
  dispatches. Any "close on focus leaving" logic that doesn't account for
  this hides the target mid-gesture and swallows the click. That was the
  horizon-menu bug (fixed in `e530880`: only treat focus landing on a
  keyboard-reachable element, `tabIndex >= 0`, as Tab-out).
- **Safari's Tab key skips buttons and links** by default (text fields
  only), so keyboard-dismiss paths behave differently per engine too.
- **`position: relative` on `<tr>` is not a containing block in WebKit.**
  A stretched-link overlay (`a::after { position: absolute; inset: 0 }`)
  anchored to a relative table row escapes the row and blankets the page —
  every click in that region hits an invisible row link. This silently
  swallowed the BACK TO NOW button (and any control above the board) in
  WKWebView/Safari while working perfectly in Chrome. Anchor such overlays
  to a `<td>`, never a `<tr>`; Playwright's actionability log names the
  intercepting element, which is how this one was found.

Rule of thumb: anything involving focus, `focusout`/`blur`, popover
dismissal, or tap-vs-click ordering must be verified in WebKit before it
counts as verified.

## Setup (one-time per machine)

Playwright-core is already vendored under `.browser-artifacts/node_modules`.
Install the WebKit build:

```sh
node .browser-artifacts/node_modules/playwright-core/cli.js install webkit
```

## Build and serve locally — the base_url trap

`just build` bakes the **production** `base_url`, so module scripts in the
built HTML point at `https://swimfrancisco.com/js/*.js`. Served locally,
those load cross-origin and are CORS-blocked — the page renders but **no JS
runs**, and your test silently exercises nothing. Always rebuild with a
local base-url:

```sh
zola build --base-url http://localhost:8923 --force
(cd public && python3 -m http.server 8923 &)
```

Sanity check before trusting any result: the board's STATUS column should
show pills (OPEN/CLOSED/OCEAN), not em-dashes. Em-dashes everywhere means
the JS never ran.

`/api/conditions` 404s locally; conditions.js fails silently by design, so
temps show placeholders. That's fine for UI-behavior testing. Use `just dev`
(wrangler) if you need live conditions data.

## Driving emulated iPhone WebKit

playwright-core is CommonJS; import the package entry directly and
destructure:

```js
// /tmp/repro.mjs — run with: node /tmp/repro.mjs
import pw from "<repo>/.browser-artifacts/node_modules/playwright-core/index.js";
const { webkit, chromium, devices } = pw;

const browser = await webkit.launch();
const ctx = await browser.newContext({ ...devices["iPhone 13"] });
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await page.goto("http://localhost:8923/", { waitUntil: "networkidle" });

await page.locator("[data-horizon-button]").tap();   // .tap() needs a touch device context
await page.locator("[data-horizon-menu] button[role='menuitemradio']").nth(2).tap();
console.log("when:", new URL(page.url()).searchParams.get("when"));
await browser.close();
```

Useful debugging instrumentation when an interaction mysteriously no-ops:

```js
await page.evaluate(() => {
  document.addEventListener("focusout", (e) => {
    console.log("FOCUSOUT", e.target.tagName, "->", e.relatedTarget?.tagName ?? null);
  }, true);
  document.addEventListener("click", (e) => {
    console.log("CLICK", e.target.tagName, e.target.className);
  }, true);
});
page.on("console", (m) => console.log("CONSOLE", m.text()));
```

The horizon bug's signature in this output: the menu's `hidden` flips to
true *before* any CLICK line, and the CLICK then lands on `MAIN` (the
element under the finger once the menu vanished).

## Regression matrix for popover/focus changes

Run all of these before calling a focus- or menu-related change done. All
verified green for the horizon control as of `e530880`:

| Check | Engine / device | Expectation |
|---|---|---|
| Tap option in menu | WebKit + iPhone 13 | selection applies (`?when=` set, button relabels) |
| Tap option in menu | Chromium + Pixel 7 | same |
| Click option | Chromium desktop | same |
| Escape with menu open | WebKit desktop | menu closes |
| Tab out of menu | Chromium desktop | menu closes (Tab traverses buttons in Chromium) |
| Tab with menu open | WebKit desktop | menu may stay open — Safari's Tab skips buttons, focus leaves the page; Escape/outside-click still close. Accepted trade-off. |

## Cleanup

```sh
pkill -f "http.server 8923"
```
