# Daily Rebuild + Deploy — Design

**Status:** Archived 2026-04-21 — shipped via [`docs/plans/archived/2026-04-18-daily-rebuild-deploy.md`](../../plans/archived/2026-04-18-daily-rebuild-deploy.md).
**Date:** 2026-04-18
**Topic:** Daily midnight-PT rebuild of the Swim Francisco static site via a Worker cron firing a Workers Builds deploy hook, Terraform-managed Cloudflare infra, and removal of the client-side JavaScript that compensated for the site not rebuilding daily.

**Supersedes:** `docs/superpowers/plans/2026-04-18-daily-rebuild-static-cleanup.md` — the existing plan targets Cloudflare Pages and manages no infra. This spec keeps the same end-state intent but lands it on Workers Builds with Terraform-backed infra.

## Goals

1. Make the rendered HTML correct every day for date-tick-over fields (today's weekday, closure freshness window, server-rendered freshness dot) by rebuilding the site at 00:05 PT year-round.
2. Delete the client-side JavaScript that compensated for the absence of a daily rebuild (`markTodayColumn`, `applyFreshness`) now that the server is authoritative.
3. Make Cloudflare infra (KV, DNS, `www → apex` redirect, Workers Custom Domain binding) reproducible through Terraform with R2-backed state.
4. Keep developer ergonomics: `devenv shell`, single-origin local dev, no surprise tool sprawl.

## Non-goals

- **GitHub Actions.** The Worker already has a `scheduled` handler; the daily cron lives there. Adding GH Actions would duplicate cron infra for no benefit.
- **Managing Worker code or `wrangler.toml` content via Terraform.** `wrangler` CLI owns the Worker bundle; Workers Builds auto-deploys on push.
- **Managing the Workers Builds project + git integration via Terraform.** The Cloudflare provider does not expose Workers Builds git source (open issue `cloudflare/terraform-provider-cloudflare#6924`). This stays dashboard-managed, one-time.
- **Restructuring the repo layout** (e.g. flattening `worker/` into the root). Tracked as a possible follow-up.
- **Changes to `/api/conditions`, NOAA/NDBC data flow, or the `STATUS` slab.** STATUS stays client-side because it updates intra-day at minute granularity.
- **`freshnessLabel` export removal.** It becomes orphaned by non-test callers but its tests stay. Separate cleanup.

## Architecture

Swim Francisco runs as a single Cloudflare Worker in the unified Workers Builds model. The Worker serves the built Zola site as static assets (via `[assets]` in `wrangler.toml`) and handles `/api/*` in its `fetch` handler. There is no separate Pages project.

Three deploy paths converge on the same Worker:

1. **Push to `main`** — Cloudflare Workers Builds (dashboard-connected to the GitHub repo) runs `zola build && npx wrangler deploy --config worker/wrangler.toml` and deploys.
2. **PR opened** — same builder produces a preview deployment with a `*.workers.dev` URL.
3. **Daily cron at 00:05 PT** — the existing Worker `scheduled` handler, gated on PT hour 0 + minute 5, POSTs to a Workers Builds deploy hook. Workers Builds then runs the same build path against the latest `main`.

Terraform manages the *infra around* the Worker. Workers Builds project + git connection stay dashboard-managed.

## Components

### Terraform configuration (`terraform/`)

```
terraform/
  versions.tf       # required_version + cloudflare provider pin (~> 5.0)
  backend.tf        # R2 (S3-compat) state backend, conditional-write locking
  main.tf           # provider config (reads CLOUDFLARE_API_TOKEN from env)
  variables.tf      # account_id, zone_id, domain
  dns.tf            # www CNAME, www→apex redirect ruleset
  worker.tf         # KV namespaces (prod + preview), Workers Custom Domain
  outputs.tf        # KV ids (pasted into wrangler.toml)
  README.md         # bootstrap and apply instructions
```

Resources managed by TF:

- `cloudflare_workers_kv_namespace.conditions` (production)
- `cloudflare_workers_kv_namespace.conditions_preview`
- `cloudflare_dns_record.www` — CNAME → apex, proxied
- `cloudflare_ruleset.www_redirect` — zone-level dynamic redirect, 301 from `www.swimfrancisco.com` to `https://swimfrancisco.com/${path}`
- `cloudflare_workers_custom_domain.apex` — binds the `swimfrancisco` Worker to `swimfrancisco.com`

Not managed by TF (intentional):

- Workers Builds project + git integration — dashboard-only, provider gap tracked upstream.
- Workers Builds deploy hook URL — created once in the dashboard, stored as a Worker secret (see below).
- Worker code + cron triggers — `wrangler deploy` and `wrangler triggers deploy` handle these.

### State backend — R2

Terraform's S3 backend pointed at Cloudflare R2's S3-compatible endpoint. R2 supports conditional writes, so state locking uses `use_lockfile = true` (TF 1.10+). No DynamoDB needed.

```hcl
backend "s3" {
  bucket = "swimfrancisco-tfstate"
  key    = "swimfrancisco/terraform.tfstate"
  region = "auto"
  endpoints = {
    s3 = "https://d985f954e272a26b858d9f8c5fc53217.r2.cloudflarestorage.com"
  }
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
  skip_s3_checksum            = true
  use_path_style              = true
  use_lockfile                = true
}
```

R2 access keys are read from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars (S3-backend quirk; names are awkward but these are R2 credentials, not AWS).

### Worker code changes

**`worker/wrangler.toml`** — add two daily crons alongside the existing hourly. The combined list:

```toml
[triggers]
crons = ["0 * * * *", "5 7 * * *", "5 8 * * *"]
```

Cron expressions run in UTC. `5 7 UTC` = 00:05 PDT; `5 8 UTC` = 00:05 PST. Handler gates which one actually fires the hook.

Also: rename `name = "swimfrancisco-worker"` → `name = "swimfrancisco"` to match the Workers Builds project name. No prior production deployment exists under the old name (confirmed — no manual CF setup yet), so this is not a cutover.

**`worker/src/deploy.ts` (new):**

```ts
// Fires the Workers Builds deploy hook to rebuild the site.
// Called daily by the Worker cron so date-tick-over fields stay correct.
// The hook URL is the secret — no auth header needed. Logs scheduled
// time and response status so a silent 5xx surfaces in `wrangler tail`.
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

**`worker/src/index.ts`** — extend `scheduled` handler. Pseudo-shape:

```ts
interface Env {
  // ...existing bindings...
  WORKERS_BUILDS_DEPLOY_HOOK: string;
}

async scheduled(event, env, ctx) {
  const scheduledAt = new Date(event.scheduledTime);
  const ptHour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      hour12: false,
    }).format(scheduledAt),
  );
  const minute = scheduledAt.getUTCMinutes();

  if (ptHour === 0 && minute === 5) {
    ctx.waitUntil(triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, event.scheduledTime));
    return;
  }

  ctx.waitUntil(refreshConditions(env));  // existing hourly NOAA/NDBC refresh
}
```

The minute-5 gate is load-bearing: only the two daily crons have minute 5. The hourly cron (minute 0) always falls through to NOAA refresh, including at 00:00 PT. The result is exactly one rebuild per calendar day at 00:05 PT year-round.

**`worker/tests/deploy.test.ts` (new):** unit test `triggerRebuild` — stub `globalThis.fetch`, assert success on 200, assert throw on 500.

### Template changes

**`templates/spots/page.html`:**

- Line ~116–118 (day-header row) and ~132–144 (grid cells): add `data-today="true"` to elements whose `day` matches `today_weekday`. `today_weekday` is already computed at line 61 using `timezone="America/Los_Angeles"`.
- Line ~73 (TODAY block): stamp `data-day="{{ today_weekday }}"` for debugging affordance (stale HTML becomes trivially diagnosable in devtools).
- Line 39: remove `data-last-verified="..."` from `.detail-root` — `applyFreshness` was its only consumer.
- Lines ~181–230: replace the 24-branch month-label if-ladder with a 12-entry array lookup:
  ```tera
  {% set month_labels = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"] %}
  {% set cs_month_label = month_labels[cs_month_i - 1] %}
  {% set ce_month_label = month_labels[ce_month_i - 1] %}
  ```

### JS changes

**`static/js/detail.js`:**

- Delete `markTodayColumn` and its call from `init` (~8 lines). Server now emits `data-today="true"`.
- Delete `applyFreshness` and its call from `init` (~10 lines). Server-rendered freshness dot is now the only source of truth.
- Drop `freshnessLabel` and `DAY_KEYS` imports if no other consumer remains.

**`static/js/helpers/board.mjs`:** unchanged. `freshnessLabel` becomes orphan-at-runtime but its tests still exercise the export. Full removal is a separate follow-up.

### `devenv.nix` additions

```nix
pkgs.terraform   # local plan/apply
```

`dotenv.filename` collapses to `[ ".env" ]` only (see Cleanup).

### Cleanup — `.env.local` removal

Both `.env` and `.env.local` are gitignored, so the dual-file convention is decorative. Collapse to `.env` only:

- `devenv.nix` — `dotenv.filename = [ ".env" ];`
- `.gitignore` — drop the `.env.local` line
- `README.md`, `docs/schedules.md`, `docs/plans/schedules.md`, `.env.example` — remove `or .env.local` phrasing
- `.env.example` — add the new required keys (see Bootstrap)

Operator runs once: append any existing `.env.local` into `.env`, delete `.env.local`.

### Memory retirement

`project_pacific_time_convention.md` currently says "client JS must use `nowInPacific()`, never `new Date()`". Once `markTodayColumn` and `applyFreshness` are deleted, the client JS no longer owns day-tick-over at all. The memory should be updated to reflect the new convention: "day-of-week tick-over is server-rendered via daily 00:05 PT rebuild; client JS only handles intra-day minute-level updates (STATUS slab, NOW/NEXT decoration)." Noted as a follow-up task during implementation, not a blocker.

## Data flow

### Push to main

```
git push → GitHub → CF webhook → Workers Builds runs
  zola build
  npx wrangler deploy --config worker/wrangler.toml
→ swimfrancisco.com serves new bundle (Worker + assets)
```

### Daily rebuild

```
Worker cron fires (5 7 UTC or 5 8 UTC)
  → scheduled handler: PT hour == 0 && minute == 5
  → ctx.waitUntil(triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, ...))
  → CF Workers Builds queues a fresh build of latest main
  → same build path as push deploy
  → swimfrancisco.com serves rebuilt bundle (today's date correct)
```

### Hourly conditions cron (unchanged)

Hourly cron continues populating KV with NOAA/NDBC data. Handler's minute-5 guard lets hourly ticks fall through to the NOAA refresh path, including the 00:00 PT hourly tick. Independent of daily rebuild.

## Bootstrap (one-time human work)

1. **Create R2 bucket + token** for TF state: `swimfrancisco-tfstate`, Object R/W scoped token. Save keys to `.env` as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
2. **Create Cloudflare API token** for TF + wrangler:
   - Account: `Workers Scripts:Edit`, `Workers KV Storage:Edit`, `Workers Routes:Edit`, `Account Settings:Read`
   - Zone: `DNS:Edit`, `Page Rules:Edit`, `Zone:Read`, scoped to `swimfrancisco.com`
   - Save as `CLOUDFLARE_API_TOKEN` in `.env`.
3. **Migrate `.env.local`** (if present) into `.env`, then delete `.env.local`.
4. **First `terraform apply`** — creates KV namespaces, DNS records, redirect ruleset. `cloudflare_workers_custom_domain.apex` is **deferred** until the Worker exists (see Ordering).
5. **Update `worker/wrangler.toml`** — `name = "swimfrancisco"`, paste KV namespace IDs from `terraform output`, commit, push.
6. **Create the Workers Builds project** in the dashboard:
   - Project name: `swimfrancisco`
   - Connect to GitHub: `cbzehner/swimfrancisco`, `main`
   - Build command: `zola build`
   - Deploy command: `npx wrangler deploy --config worker/wrangler.toml`
   - Builds for non-production branches: enabled (gives PR previews)
   - Root directory: `/`
   - Build env var: `ZOLA_VERSION=0.22.1`
   - Click Deploy. First build runs against the pushed commit.
7. **Second `terraform apply`** — with the Worker now existing, `cloudflare_workers_custom_domain.apex` attaches the apex to the deployed Worker.
8. **Create the deploy hook:** Workers Builds → Settings → Triggers → Deploy hooks → Add. Name: `daily-rebuild`. Branch: `main`. Copy the URL.
9. **Bind the hook as a Worker secret:** from `worker/`, run `wrangler secret put WORKERS_BUILDS_DEPLOY_HOOK`, paste the URL. Verify with `wrangler secret list`.
10. **Publish the new cron triggers:** `wrangler deploy && wrangler triggers deploy` (separate commands — `deploy` publishes code, `triggers deploy` registers cron patterns).
11. **Verify end-to-end:**
    - `curl -X POST "$WORKERS_BUILDS_DEPLOY_HOOK"` — manual trigger; Workers Builds shows a new deploy.
    - Within 24 hours: Workers Builds deploy history shows exactly one hook-triggered build at ~00:05 PT.
    - `curl -sSf https://swimfrancisco.com/ | head -5`
    - `curl -sSf https://swimfrancisco.com/api/conditions | head -c 400`

### Ordering note — why two `terraform apply` runs

`cloudflare_workers_custom_domain.apex` references a Worker script by name. If the Worker does not yet exist, the resource fails to create. Workers Builds creates the Worker on the first deploy (step 6), which has to happen after the wrangler.toml updates from step 5. Two `terraform apply` runs (or `terraform apply -target=...` for the first pass to create KV + DNS + redirect, then a second pass to attach the custom domain) is simpler than pre-creating a Worker stub.

The TF config wires this implicitly — the implementation plan will flag the dependency explicitly.

## Local development

`devenv shell` brings in `terraform`. TF state credentials and CF API token come from `.env`:

```sh
cd terraform
terraform init
terraform plan
terraform apply
```

Worker testing: existing `wrangler dev` flow unchanged. The new `triggerRebuild` unit test runs via the Worker project's test runner (`node --test` or `vitest` per `worker/package.json`).

To dry-run the cron handler end-to-end without waiting 24 hours: `curl http://localhost:8787/__scheduled` (already wired via `wrangler dev --test-scheduled`). Manual curl to `$WORKERS_BUILDS_DEPLOY_HOOK` tests the deploy-hook half independently.

## Error handling and rollback

- **Daily rebuild fails** (hook returns 5xx): `triggerRebuild` throws; surfaces in `wrangler tail` and as a failed Worker invocation in the dashboard. Prior deployment continues serving. Re-run manually: `curl -X POST "$WORKERS_BUILDS_DEPLOY_HOOK"`.
- **Workers Builds deploy fails** (build error): Cloudflare keeps previous Worker version live; dashboard shows failed build with logs. Instant rollback via the Workers Builds "Rollback" action on a prior deployment.
- **Worker itself is broken** (code can't run): daily rebuild cron doesn't fire. Mitigation — Workers Builds keeps serving the last working Worker; manual rebuild via dashboard hook or retry of a prior deployment.
- **TF apply fails mid-way**: R2 state is locked via conditional writes; rerun `terraform apply` after fixing. State is consistent because TF doesn't commit partial resource graphs.
- **Need to roll back infra**: `terraform apply` against a prior commit of `terraform/`.

## Testing

- **TF:** `terraform validate` + `terraform plan` on each change. No automated apply in CI; humans do applies.
- **Worker:** existing typecheck + unit tests; new `triggerRebuild` unit test covers success and failure paths.
- **Template smoke tests:** `zola build && grep 'data-today' public/spots/hamilton-pool/index.html | head -5` — server marks today's column without JS.
- **Manual regression sweep** (post-deploy, once): visit a pool with today-activity (e.g. Hamilton's Saturday drop-ins); confirm STATUS slab hydrates, TODAY block shows correct weekday, data-today column highlighted without JS, freshness dot correct, closure banners render month labels correctly. JS-disabled pass repeats the same checks except for STATUS slab (expected em-dashes).
- **End-to-end:** first post-deploy 24-hour window — Workers Builds deploy history shows exactly one hook-triggered build at ~00:05 PT.

## Build-budget impact

The cron adds ~30 builds/month on top of push-triggered builds. Well within Cloudflare's Workers Builds free-plan quota for a low-traffic project like this; occasional content pushes stay comfortable. Confirm current quota during implementation to avoid surprises.

## Open questions / follow-ups

1. **Rebuild-health monitoring.** `console.log` in `triggerRebuild` is enough for `wrangler tail`. If the cron silently skips, we notice only when stale-freshness signals appear. A tiny KV write (`last_rebuild_trigger_at`) plus a sanity check in an HTTP handler would let the site surface "⚠ last rebuilt N days ago". Out of scope unless the cron actually skips in practice.
2. **`freshnessLabel` full removal.** After JS cleanup, only tests import it. Delete export + tests in a follow-up, or keep as documented dead API surface.
3. **Workers Builds project in TF.** Revisit when `cloudflare/terraform-provider-cloudflare#6924` lands. Would let us drop the dashboard step from bootstrap.
4. **Layout flatten.** Moving `worker/` contents into repo root drops the `--config worker/wrangler.toml` flag and the `[assets] directory = "../public"` indirection. Separate focused PR after this ships.
5. **Memory update.** After JS cleanup, update `project_pacific_time_convention.md` to reflect the server-side day-tick-over model.
