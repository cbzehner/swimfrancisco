<!--
---
status: pending
progress: []
last_review: 2026-04-18T03:00:00-07:00
iterations: 0
no_progress_count: 0
started_at: null
work_unit_granularity: step
engine: codex
---
-->

# Daily Rebuild + Static-First Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pool detail pages correct every day without expanding client-side JavaScript. Adopt a daily rebuild of the static site pinned to 00:05 Pacific Time year-round, move time-dependent UI that the build now safely owns back into Tera, delete the redundant client-side overrides that hid the absence of this rebuild, and collapse one specific piece of Tera ugliness that no longer needs to exist (the 12-branch month-label ladder).

**Architecture:** The static site is already correct for schedule data (hand-curated, quarterly). It is wrong for *date tick-over* — the server bakes "today is Saturday" at build time and serves that HTML unchanged until the next git push, which is weekly at most. A single new moving part (a daily cron in the existing Worker that POSTs to a Cloudflare Pages Deploy Hook, gated to fire only at 00:xx Pacific) makes the server trustworthy for all date-tick-over fields inside a ~1 minute window per day. Client-side JS keeps owning the two things that change intra-day at minute granularity: the STATUS slab and the `●` NOW / `NEXT` decoration on the TODAY block. Nothing else.

**Tech Stack:** Zola (Tera templates), Cloudflare Pages Deploy Hooks, Cloudflare Worker cron (already exists at `worker/src/index.ts`), vanilla ES modules, `node:test`, TypeScript (Worker).

**Not in scope:**
- No change to the STATUS slab computation — it stays client-side.
- No change to the `data-schedule` embedded JSON — it stays.
- No new semantic markup (`<time datetime>`, `<meter>`, etc.) — tracked as a follow-up.
- No unification of `status.js` and `detail.js` — separate refactor.
- No audit of the 7-kind state machine — separate investigation.
- `worker/src/noaa.ts`, `worker/src/ndbc.ts`, `conditions.js` — untouched.

---

## File Structure

| Path | Change | Responsibility |
|------|--------|----------------|
| `worker/wrangler.toml` | **modify** | Replace hourly cron with three: hourly NOAA refresh, plus two daily triggers at `5 7` and `5 8` UTC. Handler gates on local PT hour so only one fires per day year-round (DST-safe). |
| `worker/src/index.ts` | **modify** | In the `scheduled` handler, dispatch by PT hour derived from `event.scheduledTime`: PT hour `0` → deploy-hook trigger; otherwise → existing NOAA refresh. Extend `Env` with `CF_PAGES_DEPLOY_HOOK`. |
| `worker/src/deploy.ts` | **create** | Export `triggerRebuild(hookUrl): Promise<void>`. Logs scheduled time + response status. Throws on non-ok so the call site sees failures. |
| `worker/tests/deploy.test.ts` | **create** | Unit test: `triggerRebuild` throws on non-ok response and no-ops on 200. Uses a stubbed `fetch`. |
| `templates/spots/page.html` | **modify** | Replace the 24-branch month-label if-ladder (lines 181-230) with a 12-entry array + variable index. Add `data-today="true"` to `weekly-grid-dayhead` and `weekly-grid-cell` whose `day` matches today. Remove now-dead `data-last-verified` attribute from `.detail-root`. |
| `static/js/detail.js` | **modify** | Delete `applyFreshness` and its call. Delete `markTodayColumn` and its call. Drop the `freshnessLabel` and `DAY_KEYS` imports if no other consumer remains in this file. No new JS logic — the tight cron window makes client-side sanity checks unnecessary. |
| `static/js/helpers/board.mjs` | **unchanged** | Helpers stay. `freshnessLabel` becomes orphaned at runtime (`detail.js` was its only importer) but the export and its tests remain as API surface; deleting it is a separate cleanup. |
| `tests/js/board-status.test.mjs` | **unchanged** | `freshnessLabel` tests remain. No new tests needed (only deletions and server-side moves, which are covered by the regression sweep). |
| `docs/deploy.md` | **modify** | Document the daily rebuild cron, the `CF_PAGES_DEPLOY_HOOK` secret, manual trigger commands, and how to roll back a bad deploy via Pages deploy history. |

---

## Task 1: Provision the Cloudflare Pages Deploy Hook + secret

- [ ] **Step 1: Create the deploy hook**
  - In the Cloudflare dashboard: Pages project → *Settings → Builds → Deploy hooks* → **Add deploy hook** named `daily-rebuild` bound to the `main` branch.
  - Copy the generated URL (form: `https://api.cloudflare.com/client/v4/pages/webhooks/deploy_hooks/<uuid>`). The URL itself is the secret — anyone with it can trigger a deploy. No additional token required.
- [ ] **Step 2: Bind the hook as a Worker secret**
  - From `worker/`: `wrangler secret put CF_PAGES_DEPLOY_HOOK`, paste the URL when prompted.
  - Verify: `wrangler secret list`.
- [ ] **Step 3: Test the hook manually**
  - `curl -X POST "<hook_url>"` should return a JSON body with a new `result.id`.
  - Confirm in the Pages dashboard: a new deploy appears under *Deployments* within a few seconds, triggered by "deploy hook".

**Verification:** Manual curl triggers a real Pages deploy. If this step fails, no later task can succeed.

---

## Task 2: Wire the daily cron in the Worker, DST-safe

- [ ] **Step 1: Add two candidate daily crons alongside the existing hourly one**
  - In `worker/wrangler.toml`, change:
    ```toml
    [triggers]
    crons = ["0 * * * *"]
    ```
    to:
    ```toml
    [triggers]
    crons = ["0 * * * *", "5 7 * * *", "5 8 * * *"]
    ```
  - Cloudflare cron expressions run in UTC. `5 7 UTC` is 00:05 PDT (summer); `5 8 UTC` is 00:05 PST (winter). Exactly one matches "midnight PT + 5 minutes" year-round. The handler gates which one actually fires the deploy hook.
- [ ] **Step 2: Create `worker/src/deploy.ts`**
  ```ts
  // Fires the Cloudflare Pages Deploy Hook to rebuild the static site.
  // Called daily by the Worker cron so that every date-tick-over field
  // rendered by Tera (today's weekday, 14-day closure window, freshness
  // class) stays correct. The hook URL is the secret — no auth header
  // needed. Logs scheduled time and response status so a silent 500
  // surfaces in Worker logs.
  export async function triggerRebuild(hookUrl: string, scheduledTime: number): Promise<void> {
    const response = await fetch(hookUrl, { method: "POST" });
    console.log(
      `daily-rebuild scheduledTime=${new Date(scheduledTime).toISOString()} status=${response.status}`,
    );
    if (!response.ok) {
      throw new Error(`deploy hook returned ${response.status}`);
    }
  }
  ```
- [ ] **Step 3: Create `worker/tests/deploy.test.ts`**
  - Two cases: `fetch` returns 200 → `triggerRebuild` resolves; `fetch` returns 500 → `triggerRebuild` throws with the status in the message. Stub `globalThis.fetch`.
  - Run with whatever the Worker project's test runner is (check `worker/package.json` scripts; likely `vitest` or `node --test`).
- [ ] **Step 4: Gate dispatch on local PT hour in `scheduled`**
  - In `worker/src/index.ts`:
    ```ts
    import { triggerRebuild } from "./deploy";

    interface Env {
      // ...existing bindings...
      CF_PAGES_DEPLOY_HOOK: string;
    }

    async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
      // Derive PT hour from the scheduled UTC instant so the Worker stays
      // DST-correct without a second cron pattern per half-year.
      const ptHour = Number(
        new Intl.DateTimeFormat("en-US", {
          timeZone: "America/Los_Angeles",
          hour: "2-digit",
          hour12: false,
        }).format(new Date(event.scheduledTime)),
      );

      if (ptHour === 0) {
        ctx.waitUntil(triggerRebuild(env.CF_PAGES_DEPLOY_HOOK, event.scheduledTime));
        return;
      }

      // Existing hourly NOAA refresh path.
      ctx.waitUntil(refreshConditions(env));
    }
    ```
  - The two daily crons fire six months each — one at PT hour `0`, the other at PT hour `23`. Only PT hour `0` triggers a deploy, so exactly one rebuild per calendar day.
  - The hourly cron (`0 * * * *`) will also hit PT hour `0` at the top of every midnight PT. That's fine — the guard still matches, but the hourly path runs first at `00:00 PT` and the daily path runs at `00:05 PT`. Both firing is harmless (idempotent rebuild); we just don't want both to *race*. The `ptHour === 0` guard applies equally to both, so the 00:00 PT hourly tick will also trigger a rebuild. That's one extra build/day. **Decision for Step 4**: narrow the guard to only the two daily cron patterns by also checking the minute:
    ```ts
    const minute = new Date(event.scheduledTime).getUTCMinutes();
    if (ptHour === 0 && minute === 5) {
      ctx.waitUntil(triggerRebuild(env.CF_PAGES_DEPLOY_HOOK, event.scheduledTime));
      return;
    }
    ```
  - Only the `5 7 * * *` / `5 8 * * *` crons have minute `5`. The hourly cron has minute `0` and falls through to NOAA refresh.
- [ ] **Step 5: Push the cron triggers**
  - `wrangler deploy` alone publishes the Worker code but **does not** update the cron trigger list on existing deployments. Run `wrangler triggers deploy` after `wrangler deploy` to register the new crons.

**Verification:**
- `npm --prefix worker run typecheck` clean.
- Worker tests pass (both the new deploy test and any existing suite).
- `wrangler deploy && wrangler triggers deploy` both succeed.
- In the Cloudflare dashboard: Worker triggers show three cron patterns.
- Within 24 hours of deploy, Pages deploy history shows exactly one hook-triggered build at approximately 00:05 PT.

---

## Task 3: Mark today's column + today-block weekday at build time

- [ ] **Step 1: Verify `today_weekday` is already in scope**
  - `templates/spots/page.html:61` computes `today_weekday` for the TODAY block using `timezone="America/Los_Angeles"`. No new computation needed — reuse.
- [ ] **Step 2: Add `data-today="true"` to the day-header row**
  - Replace `templates/spots/page.html:116-118`:
    ```tera
    <span class="weekly-grid-dayhead" role="columnheader"
          data-day="{{ day_order[loop.index0] }}"
          {% if day_order[loop.index0] == today_weekday %}data-today="true"{% endif %}>
      {{ label }}
    </span>
    ```
- [ ] **Step 3: Add `data-today="true"` to matching grid cells**
  - Replace `templates/spots/page.html:132-144`:
    ```tera
    <span class="weekly-grid-cell" role="cell"
          data-day="{{ day }}"
          data-day-short="{{ day_labels[loop.index0] }}"
          {% if day == today_weekday %}data-today="true"{% endif %}
          {% if cell | length == 0 %}data-empty="true"{% endif %}>
    ```
- [ ] **Step 4: Stamp the weekday on the TODAY block for observability**
  - Replace `templates/spots/page.html:73`:
    ```tera
    <section class="today-block" data-field="today" data-day="{{ today_weekday }}">
    ```
  - This is not consumed by JS (no sanity check — the <1 minute rebuild window makes that unnecessary). It's a debugging affordance that makes stale HTML trivially diagnosable in the browser devtools.
- [ ] **Step 5: Delete `markTodayColumn` from `static/js/detail.js`**
  - Delete the function (~8 lines) and its call from `init`.
  - If `DAY_KEYS` is no longer referenced in `detail.js`, drop it from the import list.
- [ ] **Step 6: Spot-check rendered output**
  - `zola build && grep 'data-today' public/spots/hamilton-pool/index.html | head -5` should show server-rendered markers on the correct weekday.

**Verification:**
- `zola build` clean.
- Rendered pool page shows `data-today="true"` on today's column with no JS running.
- CSS rule targeting `[data-today="true"]` still matches and still styles the correct column.

---

## Task 4: Delete the client-side freshness override

- [ ] **Step 1: Delete `applyFreshness` and its call**
  - In `static/js/detail.js`, remove the function (~10 lines) and the `applyFreshness(root, now)` call in `init`.
  - Remove the `freshnessLabel` import from `detail.js`.
- [ ] **Step 2: Remove the now-dead `data-last-verified` attribute**
  - At `templates/spots/page.html:39`: delete `data-last-verified="{{ extra.last_verified_at | default(value='') }}"` from `.detail-root`. `applyFreshness` was its only consumer.
- [ ] **Step 3: Leave the server-rendered freshness dot in place**
  - `templates/spots/page.html:253-269` already renders `data-freshness="fresh|stale"` and a label. After this task it is the only source of truth. Daily rebuild keeps it within ~1 day of a 30-day window — noise.
- [ ] **Step 4: Do not delete `freshnessLabel` from `board.mjs`**
  - After this task, `freshnessLabel` is imported only by `tests/js/board-status.test.mjs`. Keeping a tested pure helper as API surface is cheap; deleting it is a separate cleanup and out of scope here.

**Verification:**
- `grep -n 'freshnessLabel\|data-last-verified' static/js/detail.js templates/spots/page.html` returns nothing.
- `node --test tests/js/board-status.test.mjs` passes (the `freshnessLabel` tests exercise the export, not the DOM).
- Rendered pool page still shows the freshness dot with the correct class.

---

## Task 5: Replace the 12-branch month-label ladder with an array lookup

- [ ] **Step 1: Confirm Tera variable indexing works**
  - Existing template already uses `day_order[loop.index0]` and `day_labels[loop.index0]` (`page.html:117, 134`), so variable array indexing is proven in Zola 0.22.1 for this build. The worry in the existing code comment is about *nested array literals in `{% set %}`*, a different feature.
- [ ] **Step 2: Introduce the lookup table**
  - Near the top of the pool branch (before the upcoming-closures loop at `page.html:163`):
    ```tera
    {% set month_labels = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"] %}
    ```
- [ ] **Step 3: Replace both if-ladders (`page.html:181-230`)**
  - Delete the ~50 lines of `{% if cs_month_i == 1 %}…{% elif … %}…{% endif %}` blocks.
  - Replace with:
    ```tera
    {% set cs_idx = cs_month_i - 1 %}
    {% set ce_idx = ce_month_i - 1 %}
    {% set cs_month_label = month_labels[cs_idx] %}
    {% set ce_month_label = month_labels[ce_idx] %}
    ```
  - Leave the `cs_label` / `ce_label` composition lines below unchanged.
- [ ] **Step 4: Preserve the "parallel flat arrays" comment**
  - `page.html:100` comment describes a different Tera workaround (parallel `program_keys` / `program_labels` arrays). It stays accurate — do not delete.

**Verification:**
- `zola build` clean.
- `grep 'closure-banner-date' public/spots/*/index.html` shows correctly-formatted labels (e.g. `APR 16`, `JUN 6`).
- Pools with month-crossing closures (Hamilton has `2026-06-06`) still render month labels correctly.

---

## Task 6: Document the daily rebuild + rollback in `docs/deploy.md`

- [ ] **Step 1: Add a section: "Daily rebuild cron"**
  - Where the deploy hook lives (Cloudflare Pages → *Settings → Builds → Deploy hooks*).
  - Secret binding name: `CF_PAGES_DEPLOY_HOOK`.
  - Cadence: two crons (`5 7` / `5 8` UTC) gated to PT hour `0` + minute `5` → exactly one rebuild per day at 00:05 PT year-round.
  - Manual trigger: `curl -X POST "$CF_PAGES_DEPLOY_HOOK"`.
  - How to spot-check: Worker logs (`wrangler tail`) on the daily firing, and Pages deploy history for the corresponding build.
- [ ] **Step 2: Add a section: "Rollback"**
  - Cloudflare Pages supports instant rollback from the deploy history UI: *Deployments → [failed deploy] → Rollback*. That restores the previous working deploy without a rebuild.
  - If the daily rebuild itself is the problem (e.g. a Tera change that only fails for today's date), rolling back restores a known-good build; the fix is then "edit the template, push to main".
- [ ] **Step 3: Note the build-budget impact**
  - ~30 Pages builds/month from the cron. Cloudflare Pages free tier cap: 500/month. Occasional content pushes stay comfortable.

**Verification:** `docs/deploy.md` renders cleanly on GitHub and mentions every knob needed to diagnose a missing daily rebuild and recover from a bad one.

---

## Task 7: Regression sweep

- [ ] **Step 1: Mechanical gates**
  - `zola build` — 14 pages, 0 orphan, clean.
  - `node --test tests/js/board-status.test.mjs tests/js/conditions.test.mjs tests/js/noaa.test.mjs` — 39/39 pass.
  - `npm --prefix worker run typecheck` — clean (catches any `Env` / `deploy.ts` / `scheduled` regressions).
  - Worker unit tests — new `triggerRebuild` cases pass; existing tests unchanged.
- [ ] **Step 2: Simulate tomorrow (optional)**
  - Zola has no built-in date spoofing. Low-cost sanity check: add a temporary `{{ today_weekday }}` dump to the template, build, confirm it matches the actual local weekday, then remove the dump.
- [ ] **Step 3: Manual visual sweep**
  - Visit a pool with activity today (e.g. Hamilton — three Saturday drop-in sessions).
  - STATUS slab hydrates correctly.
  - TODAY block matches today's weekday label.
  - `data-today` column highlighted in the weekly grid without JS.
  - Freshness dot shows correct class without JS.
  - Closure banners render month labels correctly.
- [ ] **Step 4: JS-disabled sweep**
  - Disable JS in the browser.
  - Today's column still highlighted (server-rendered). ✓
  - TODAY block still present (or correctly absent if today has no drop-in sessions). ✓
  - Closure banners still render. ✓
  - STATUS slab shows em-dashes (expected; client-computed). ✓

---

## Verification Gates (summary)

- `zola build` → 14 pages, 0 orphan.
- `node --test …` → all existing JS tests pass (39/39).
- `npm --prefix worker run typecheck` → clean.
- Worker `triggerRebuild` unit test passes.
- `grep 'data-today' public/spots/hamilton-pool/index.html` → server marks today's column.
- Manual: rendered pool page shows correct TODAY weekday, freshness class, and month-formatted closure dates without JS.
- Manual: within 24 hours of Worker deploy, Pages deploy history shows exactly one hook-triggered build at ~00:05 PT.

## Open Questions

1. **Do we want a Worker-side rebuild-health metric?** The `console.log` in `triggerRebuild` is enough for `wrangler tail`, but if we want "alert me when daily rebuilds stop", a tiny KV write (`last_rebuild_trigger_at`) plus a check in one of the HTTP handlers (or a separate monitoring endpoint) would let the homepage surface "⚠ site last rebuilt N days ago" if the cron silently breaks. Out of scope unless we've seen the cron skip.
2. **`freshnessLabel` full removal.** After Task 4 it has no non-test consumer. Delete the export and its three tests in a follow-up, or leave it as documented dead API surface?
3. **Cloudflare Pages rollback discoverability.** Task 6 documents the rollback UI but we've never exercised it in production. Worth a dry run? (Non-blocking.)
