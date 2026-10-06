# e2e user journeys

This single-repository pilot uses [tester-army/e2e](https://github.com/tester-army/e2e),
with exact interactions and assertions. The committed suite needs no model,
subscription login, or API key. Natural-language `agent.act` / `agent.assert`
and their replay cache have not been evaluated in this first pass.

## Run

Use the [project sandbox](sandboxes.md). Its source setup installs the locked
npm dependencies and both suites' browsers. On another machine, install
browsers once with `devenv shell -- just browsers`.

```sh
devenv shell -- just test-e2e
# Focus a journey or engine; npm forwards arguments to the runner:
devenv shell -- npm run test:e2e -- --target chromium --grep nearest
# Full repository gate, including existing WebKit regressions:
devenv shell -- just check
```

The runner starts its own Worker on an allocated loopback port, builds Zola
assets with that same origin, and removes its temporary assets and local KV
store on shutdown. It does not reuse the development server or contact
production bindings. Browser journeys never write the shared KV store. The
conditions journey supplies responses only to its own browser context, so it
can run alone or in any order without leaving data for another journey.

`tests/js/worker-runtime.test.mjs`, included in `just test-js`, owns the real
Worker HTTP contracts. Wrangler's `createTestHarness` runs the production Worker
and routing configuration with disposable static asset fixtures. Every case
resets both local KV and Cache API storage. It verifies populated responses,
empty-store recovery, same-origin responses, rejected methods, and API/static
404 routing without running the same API assertions in two browsers. No extra
test framework or dependency is needed. To focus these checks:

```sh
devenv shell -- node --test tests/js/worker-runtime.test.mjs
```

Chromium uses a desktop viewport; WebKit uses a 390×844 viewport. This is
narrow-screen coverage, not iPhone device emulation; the existing browser
regressions also exercise iPhone touch behavior. Both journey targets use
Asia/Tokyo to exercise Pacific-time logic from a different time zone. A
fixed September 24, 2026 browser clock keeps reviewed schedules active;
reduced motion keeps map transitions deterministic.

## Business logic verification

The `swim decisions` cases in `tests/browser/smoke.test.mjs` exercise the real
page entrypoint and board adapter with small, hand-authored schedules. Their
expected statuses, next sessions, visible locations, and order are literal
values; they never call the application's schedule helpers to derive an answer.
They verify:

- Lap, family, and senior selections recompute recommendations, with membership
  access remaining opt-in.
- Minute refresh preserves the selected program; session starts are inclusive
  and ends exclusive.
- Plan-ahead links, horizon changes, and returning to now retain the program.

`tests/js/board-model.test.mjs` tests `evaluateBoard` and `transitionBoard`
directly. Rule-only ordering and access cases moved here from the two-engine
suite: default ordering, Open/Next ordering, access-versus-swimming counts, and
program eligibility. It also checks distance ties/missing coordinates, selected
schedule windows, empty summaries, URL canonicalization, and geolocation races.
The shared fixture file supplies literal schedules, never expected answers.

Both WebKit and Chromium use a controlled Pacific instant from a Tokyo browser.
The clock stays paused during navigation. Mounting renders synchronously, and
the tests wait for initialized controls with a fixed date, so a refresh cannot
hide an incorrect initial render. Direct loads at session boundaries
are checked as well as tabs left open across them. The fixtures use the shipped
English dictionary and pre-rendered status pills. Run this focused set in the
project sandbox:

```sh
devenv shell -- node --test --test-name-pattern 'swim decisions' tests/browser/smoke.test.mjs
devenv shell -- node --test tests/js/board-model.test.mjs tests/js/conditions-client.test.mjs
devenv shell -- just check
```

These fixtures establish business rules independently of the current facility
catalog. Existing real-page checks establish that Zola embeds the reviewed
content and wires the controls correctly. Checks that use application helpers
to compare deployed output are consistency checks, not independent proof of
schedule correctness. Keep the Python source-review fixtures and provenance
checks for that separate boundary.

Conditions-client tests use a controlled clock and deferred responses to verify
single-flight requests, success-based throttling, retries, withdrawal, and late
completion after disposal. Browser tests verify imports have no effects and
that board, detail, conditions, menu, and map components can be disposed and
mounted again without duplicate handlers or timers. The iPhone test waits for
the selected URL horizon instead of sleeping. Cached page transitions preserve
the map viewport and popup; a decorative bulletin does not start conditions polling.

`tests/js/worker-assemble.test.mjs` tests complete refreshes through injected
providers and fake storage: shared-source requests, outages, repeated carries,
expiry, recovery, and storage failures. It leaves global fetch untouched; the
real Worker HTTP tests above retain responsibility for routing and storage.
Python publication tests inject projection and partial-write failures at the
shared transaction boundary, checking content and existing reviewed-file bytes.

The redesign reuses the existing browser harness. Duplicate membership and
return-to-now smoke cases are consolidated into the Worker-backed journeys;
the independent browser wiring fixtures and iPhone interaction regressions remain.
Tests of the deleted DOM rank helpers and module-global memo key were removed;
their decisions are covered through the public board evaluator.
Runner migration is deferred. Validation can run entirely locally.
No GitHub Actions run is needed during development. The existing automatic CI
configuration remains in place because production deployment and schedule
publication require a successful push run for the exact commit; a manual
workflow run does not satisfy that gate. See [deployment](deploy.md) before
changing CI triggers.

## Flow coverage

- Public board hydration; lap, family, senior, beach filters; reload/hash restoration;
  membership opt-in and reset.
- Horizon deep links, menu dismissal, return to now, and board/map state preservation.
- Board → pool detail → other lap pools → browser back → board; the reviewed
  Mission training closure and next session, schedule visibility, and exact
  external directions providers and address.
- All catalog locales through board, detail, and map; translated program labels,
  status and Pacific weekday headings, correct language and navigation.
- Map markers and popup → matching spot, with unavailable basemap configuration and
  no unauthenticated tile requests.
- Open-water conditions rendering from a context-local fixture; controlled 503
  clears the reading and leaves navigation usable. Real KV/HTTP behavior is
  covered by the Worker tests above.
- Distance permission success/denial, reload without prompting, later sort choice,
  hash navigation, and stale callbacks after a new location request.

The existing browser/unit/render suites retain coverage of schedule transitions,
closures, access hours, pool identity, refresh/retry behavior, hydration errors,
map configuration success, and mobile layout regressions. Field Notes is draft
content and is not part of the publicly built site. External provider availability,
real location permission dialogs, and production deployment are outside this pilot.

## Reports and framework evaluation

`npm run test:e2e` disables anonymous e2e telemetry. It writes `.e2e/report.json`
and app logs under `.e2e/logs/worker.log`; failed journeys also retain screenshots,
semantic screen dumps, and Playwright traces. These artifacts are gitignored;
CI uploads them when verification fails. To produce Markdown too:

```sh
devenv shell -- npm run test:e2e -- --reporter list,markdown
```

The pilot pins `e2e` 0.17.0 and `@e2e-dev/web` 0.12.0. The web engine pins
Playwright 1.63.0 internally, while existing regressions and the shared sandbox
browser keep Playwright 1.61.1. Install both browser sets; do not override the
engine's dependency to make the cache appear compatible. The framework remains
pre-1.0, so upgrades require reviewing its bundled `node_modules/e2e/docs` and
running both engines. Node 24 is used in CI; the project devenv provides a
compatible runtime.

The first run reproduced two real distance-sort bugs in both engines: denying
location permission cleared the pressed sort while retaining `#open`, and a
late location result replaced a newer Open Next selection. The fixes preserve
the previous sort on denial and invalidate stale request callbacks. The new
suite includes regressions for both, plus hash navigation and a subsequent
location request.

The root npm override pins Miniflare’s Sharp dependency to 0.35.5, the fix for
[GHSA-wq5f-xc86-pv6w](https://github.com/advisories/GHSA-wq5f-xc86-pv6w).
Remove that override when Wrangler’s dependency tree includes the patched release.
