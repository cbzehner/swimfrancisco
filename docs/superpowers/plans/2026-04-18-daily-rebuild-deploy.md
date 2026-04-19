---
status: in_progress
progress:
  - section: "Task 1: Terraform scaffolding"
    status: complete
    notes:
      - "commit 80a2c0a; terraform fmt -check clean"
      - "gap: codex companion transport misparses subjects of form `scope(area):` as model names — use CLI transport for specs containing such literals"
      - "gap: codex sandbox cannot write worktree .git/index — commit step must run from orchestrating shell"
  - section: "Task 2: Terraform DNS + redirect"
    status: complete
    notes:
      - "commit e200d17; terraform init -backend=false + validate clean; provider v5.18.0 installed"
      - "gap: codex-adapter.sh does not auto-fall-back to CLI transport when companion sandbox is read-only — had to invoke CLI directly. Consider patching upstream."
      - "gap: codex sandbox has no network, so terraform init / validate must run from orchestrating shell"
  - section: "Task 3: Terraform KV + Workers Custom Domain + outputs"
    status: complete
    notes:
      - "commit 1f832c1; terraform validate clean"
      - "verified: terraform validate emits expected deprecation warning on `environment` attribute (inline comment already tracks the issue)"
  - section: "Task 4: Terraform README"
    status: complete
    notes:
      - "commit 961c15c"
      - "gap: codex stderr warning about ~/.claude/skills/qmd/SKILL.md missing frontmatter delimiters; non-fatal"
  - section: "Task 5: triggerRebuild helper + TDD test"
    status: complete
    notes:
      - "commit 2a0a8c9; 2/2 tests pass, typecheck clean"
      - "gap: worker/node_modules was absent — subagent ran npm install; future iterations should assume deps already present"
  - section: "Task 5b: classifyTick + DST-aware dispatch tests"
    status: complete
    notes:
      - "commit 5afc476; 5/5 tests pass (PDT/PST midnight rebuild; hourly + off-midnight refresh), typecheck clean"
last_review: 2026-04-19T01:36:00-07:00
iterations: 6
no_progress_count: 0
started_at: 2026-04-19T01:13:14-07:00
---

# Daily Rebuild + Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Terraform-managed Cloudflare infra (KV, DNS, www redirect, Workers Custom Domain), a DST-safe daily rebuild cron in the existing Worker, and removal of the client JS that compensated for the missing rebuild.

**Architecture:** The Worker runs in the unified Workers Builds model (single script serves `[assets]` + `/api/*`). Its existing `scheduled` handler grows a second responsibility: on the daily UTC ticks that map to 00:05 PT, POST to a Workers Builds deploy hook to rebuild the site. Terraform owns the durable infra — KV, DNS, the redirect ruleset, and the apex→Worker binding — with state in R2 (S3-compat backend, conditional-write locking). Templates become authoritative for day-tick-over fields; redundant client-side DOM patching goes away.

**Tech Stack:** Terraform 1.10+ with `cloudflare/cloudflare` provider v5, R2 (S3-compatible) state backend, Cloudflare Workers + Workers Builds, TypeScript (Worker), Zola/Tera (templates), vanilla ES modules (client), `node:test` (unflagged TS type stripping requires Node ≥22.18 — pinned in `devenv.nix`), devenv/Nix.

**Supersedes:** `docs/superpowers/plans/2026-04-18-daily-rebuild-static-cleanup.md` — same end-state intent, lands on Workers Builds with Terraform instead of Pages-only.

---

## File Structure

| Path | Change | Responsibility |
|------|--------|----------------|
| `terraform/versions.tf` | create | Terraform + provider version pins. |
| `terraform/backend.tf` | create | R2 (S3-compat) state backend config. |
| `terraform/main.tf` | create | Cloudflare provider config (reads `CLOUDFLARE_API_TOKEN`). |
| `terraform/variables.tf` | create | `cloudflare_account_id`, `cloudflare_zone_id`, `domain`. |
| `terraform/dns.tf` | create | `www` CNAME, `www → apex` redirect ruleset. |
| `terraform/worker.tf` | create | KV namespaces (prod + preview), Workers Custom Domain binding. |
| `terraform/outputs.tf` | create | KV IDs for pasting into `wrangler.toml`. |
| `terraform/README.md` | create | Bootstrap + apply instructions. |
| `terraform/.gitignore` | create | Ignore `.terraform/`, `*.tfstate*`, `.terraform.lock.hcl` override files. |
| `worker/src/deploy.ts` | create | `triggerRebuild(hookUrl, scheduledTime)` — POST to deploy hook. |
| `worker/src/schedule.ts` | create | `classifyTick(scheduledTime)` — pure dispatch (rebuild vs refresh). |
| `worker/src/index.ts` | modify | `scheduled` handler delegates branch selection to `classifyTick`. |
| `worker/wrangler.toml` | modify | Rename to `swimfrancisco`, add daily crons, fill real KV IDs. |
| `worker/package.json` | modify | `name` field to match. |
| `tests/js/worker-deploy.test.mjs` | create | Unit test for `triggerRebuild`. |
| `tests/js/worker-schedule.test.mjs` | create | DST-aware dispatch tests for `classifyTick`. |
| `templates/spots/page.html` | modify | Server-render `data-today`, drop `data-last-verified`, replace month-label ladder. |
| `static/js/detail.js` | modify | Delete `markTodayColumn` + `applyFreshness`, trim imports. |
| `devenv.nix` | modify | Add `pkgs.terraform`, drop `.env.local` from dotenv filename list. |
| `.env.example` | modify | Document new required keys; drop `or .env.local` phrasing. |
| `.gitignore` | modify | Drop `.env.local` line. |
| `README.md` | modify | Replace `or .env.local` phrasing. |
| `docs/schedules.md` | modify | Replace `or .env.local` phrasing. |
| `docs/plans/schedules.md` | modify | Replace `or .env.local` phrasing. |
| `docs/deploy.md` | modify | Rewrite for Workers Builds + Terraform + daily rebuild. |
| `docs/superpowers/plans/2026-04-18-daily-rebuild-static-cleanup.md` | delete | Superseded by this plan. |

Memory update (`~/.claude/projects/.../memory/project_pacific_time_convention.md`) happens during Task 15.

---

## Task 1: Terraform scaffolding — versions, backend, provider, variables

**Files:**
- Create: `terraform/versions.tf`
- Create: `terraform/backend.tf`
- Create: `terraform/main.tf`
- Create: `terraform/variables.tf`
- Create: `terraform/.gitignore`

- [ ] **Step 1: Create `terraform/.gitignore`**

  ```gitignore
  .terraform/
  *.tfstate
  *.tfstate.*
  *.tfplan
  crash.log
  override.tf
  override.tf.json
  *_override.tf
  *_override.tf.json
  ```

- [ ] **Step 2: Create `terraform/versions.tf`**

  ```hcl
  terraform {
    required_version = ">= 1.10"
    required_providers {
      cloudflare = {
        source  = "cloudflare/cloudflare"
        version = "~> 5.0"
      }
    }
  }
  ```

- [ ] **Step 3: Create `terraform/backend.tf`**

  ```hcl
  terraform {
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
  }
  ```

- [ ] **Step 4: Create `terraform/main.tf`**

  ```hcl
  # API token is read from CLOUDFLARE_API_TOKEN env var.
  # R2 credentials are read from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  # by the S3 backend (naming is an S3-backend quirk; these are R2 keys).
  provider "cloudflare" {}
  ```

- [ ] **Step 5: Create `terraform/variables.tf`**

  ```hcl
  variable "cloudflare_account_id" {
    type        = string
    description = "Cloudflare account that owns the Workers/KV/Pages resources."
    default     = "d985f954e272a26b858d9f8c5fc53217"
  }

  variable "cloudflare_zone_id" {
    type        = string
    description = "Cloudflare zone for swimfrancisco.com."
    default     = "1daf29ffafa64dbdda65c32727337eb8"
  }

  variable "domain" {
    type        = string
    description = "Apex domain served by the Worker."
    default     = "swimfrancisco.com"
  }

  variable "worker_name" {
    type        = string
    description = "Script name of the Worker serving the site. Must match the `name` in worker/wrangler.toml."
    default     = "swimfrancisco"
  }
  ```

- [ ] **Step 6: Verify `terraform fmt` is clean**

  Run: `cd terraform && terraform fmt -check`
  Expected: exit 0, no output.

- [ ] **Step 7: Commit**

  ```bash
  git add terraform/.gitignore terraform/versions.tf terraform/backend.tf terraform/main.tf terraform/variables.tf
  git commit -m "feat(terraform): scaffold provider, R2 backend, and variables"
  ```

---

## Task 2: Terraform — DNS records + `www → apex` redirect ruleset

**Files:**
- Create: `terraform/dns.tf`

- [ ] **Step 1: Create `terraform/dns.tf`**

  ```hcl
  # The apex A/CNAME is created automatically by Cloudflare when the
  # Workers Custom Domain (terraform/worker.tf) attaches the Worker to
  # the apex. We only manage the www CNAME explicitly.
  resource "cloudflare_dns_record" "www" {
    zone_id = var.cloudflare_zone_id
    name    = "www"
    type    = "CNAME"
    content = var.domain
    ttl     = 1 # 1 = auto (required when proxied)
    proxied = true
  }

  # Permanent 301 from www.swimfrancisco.com to https://swimfrancisco.com/<path>.
  # Implemented as a zone-level dynamic redirect ruleset so the path and query
  # are preserved without any Pages/Worker involvement.
  resource "cloudflare_ruleset" "www_redirect" {
    zone_id = var.cloudflare_zone_id
    name    = "www to apex redirect"
    kind    = "zone"
    phase   = "http_request_dynamic_redirect"

    rules = [{
      action      = "redirect"
      expression  = "(http.host eq \"www.${var.domain}\")"
      description = "Redirect www to apex"
      action_parameters = {
        from_value = {
          status_code = 301
          target_url = {
            expression = "concat(\"https://${var.domain}\", http.request.uri.path)"
          }
          preserve_query_string = true
        }
      }
    }]
  }
  ```

- [ ] **Step 2: Verify formatting and validation**

  ```bash
  cd terraform
  terraform fmt -check
  terraform init -backend=false   # skips the R2 backend so validate works without creds
  terraform validate
  ```
  Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

  ```bash
  git add terraform/dns.tf
  git commit -m "feat(terraform): manage www CNAME and www→apex redirect"
  ```

---

## Task 3: Terraform — KV namespaces, Workers Custom Domain, outputs

**Files:**
- Create: `terraform/worker.tf`
- Create: `terraform/outputs.tf`

- [ ] **Step 1: Create `terraform/worker.tf`**

  ```hcl
  resource "cloudflare_workers_kv_namespace" "conditions" {
    account_id = var.cloudflare_account_id
    title      = "swimfrancisco-conditions"
  }

  resource "cloudflare_workers_kv_namespace" "conditions_preview" {
    account_id = var.cloudflare_account_id
    title      = "swimfrancisco-conditions-preview"
  }

  # Binds the apex swimfrancisco.com to the Worker named var.worker_name.
  # The Worker must already exist (created by the first Workers Builds deploy)
  # before this applies successfully. Use a two-phase apply: create KV + DNS +
  # redirect first, then deploy the Worker via Workers Builds, then apply again
  # to attach the custom domain. See docs/deploy.md for the runbook.
  #
  # `environment` is still accepted by provider v5 but marked deprecated for
  # scripts without environments (cloudflare/terraform-provider-cloudflare#5618).
  # Keep explicit for now; remove when the provider clarifies the default.
  resource "cloudflare_workers_custom_domain" "apex" {
    account_id  = var.cloudflare_account_id
    zone_id     = var.cloudflare_zone_id
    hostname    = var.domain
    service     = var.worker_name
    environment = "production"
  }
  ```

- [ ] **Step 2: Create `terraform/outputs.tf`**

  ```hcl
  output "kv_namespace_id" {
    description = "Paste into worker/wrangler.toml [[kv_namespaces]] id."
    value       = cloudflare_workers_kv_namespace.conditions.id
  }

  output "kv_preview_namespace_id" {
    description = "Paste into worker/wrangler.toml [[kv_namespaces]] preview_id."
    value       = cloudflare_workers_kv_namespace.conditions_preview.id
  }
  ```

- [ ] **Step 3: Verify**

  ```bash
  cd terraform
  terraform fmt -check
  terraform init -backend=false
  terraform validate
  ```
  Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

  ```bash
  git add terraform/worker.tf terraform/outputs.tf
  git commit -m "feat(terraform): manage KV namespaces and apex Workers Custom Domain"
  ```

---

## Task 4: Terraform — README with bootstrap + apply instructions

**Files:**
- Create: `terraform/README.md`

- [ ] **Step 1: Create `terraform/README.md`**

  ````markdown
  # SwimFrancisco Terraform

  Manages the Cloudflare infrastructure around the `swimfrancisco` Worker:
  KV namespaces, the `www` CNAME + redirect, and the apex→Worker custom-domain
  binding. State lives in a Cloudflare R2 bucket (`swimfrancisco-tfstate`).

  ## One-time bootstrap

  1. **Create the R2 state bucket.** Dashboard → R2 → Create bucket:
     `swimfrancisco-tfstate`, automatic location, no public access.
  2. **Create an R2 API token** scoped to that bucket, permissions "Object
     Read & Write". Save `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` into
     `.env` at the repo root.
  3. **Create a Cloudflare API token** with:
     - Account: `Workers Scripts:Edit`, `Workers KV Storage:Edit`,
       `Workers Routes:Edit`, `Account Settings:Read`
     - Zone: `DNS:Edit`, `Page Rules:Edit`, `Zone:Read`, scoped to
       `swimfrancisco.com`

     Save it as `CLOUDFLARE_API_TOKEN` in `.env`.
  4. **Enter the devenv shell** so `terraform` is on PATH and `.env` is
     loaded:

     ```sh
     devenv shell
     ```

  ## First apply (two phases)

  `cloudflare_workers_custom_domain.apex` requires the Worker script to exist
  before it can bind the apex. The Worker is created by the first Workers
  Builds deploy (dashboard-connected to the GitHub repo). Apply in two phases:

  ```sh
  cd terraform
  terraform init

  # Phase 1 — create infra the Worker does NOT depend on.
  terraform apply \
    -target=cloudflare_workers_kv_namespace.conditions \
    -target=cloudflare_workers_kv_namespace.conditions_preview \
    -target=cloudflare_dns_record.www \
    -target=cloudflare_ruleset.www_redirect
  terraform output
  ```

  Paste the KV IDs into `worker/wrangler.toml`, commit, push. The push
  triggers the first Workers Builds deploy.

  ```sh
  # Phase 2 — attach the apex now that the Worker exists.
  terraform apply
  ```

  Subsequent changes are single-phase: `terraform plan` → `terraform apply`.

  ## Outputs

  - `kv_namespace_id` — production KV binding id for `worker/wrangler.toml`.
  - `kv_preview_namespace_id` — preview KV binding id for
    `worker/wrangler.toml` (used by `wrangler dev`).

  ## Not managed here

  - **Workers Builds project + git integration.** The Cloudflare provider does
    not yet expose Workers Builds git source (see
    [cloudflare/terraform-provider-cloudflare#6924]). Created once in the
    dashboard; see `docs/deploy.md` for the field values.
  - **Workers Builds deploy hook URL.** Generated in the dashboard,
    stored as the `WORKERS_BUILDS_DEPLOY_HOOK` Worker secret via
    `wrangler secret put`.
  - **Worker code, cron triggers.** `wrangler deploy` and
    `wrangler triggers deploy` own these.

  [cloudflare/terraform-provider-cloudflare#6924]: https://github.com/cloudflare/terraform-provider-cloudflare/issues/6924
  ````

- [ ] **Step 2: Commit**

  ```bash
  git add terraform/README.md
  git commit -m "docs(terraform): bootstrap and apply runbook"
  ```

---

## Task 5: Worker — `triggerRebuild` helper + unit test

**Files:**
- Create: `worker/src/deploy.ts`
- Create: `tests/js/worker-deploy.test.mjs`

- [ ] **Step 1: Write the failing test first**

  Create `tests/js/worker-deploy.test.mjs`:

  ```js
  // Pin the contract for the daily-rebuild helper. The Worker's scheduled
  // handler calls triggerRebuild exactly once per day at 00:05 PT; this test
  // locks in success on 2xx and throw-with-status on non-ok, so a silent 5xx
  // cannot go unnoticed in `wrangler tail`.
  //
  // Imported directly from the TypeScript source; Node 22.6+ strips types.

  import { test, beforeEach, afterEach } from "node:test";
  import assert from "node:assert/strict";

  import { triggerRebuild } from "../../worker/src/deploy.ts";

  const HOOK = "https://example.invalid/hook";
  const SCHEDULED_AT = Date.UTC(2026, 3, 18, 7, 5);

  let originalFetch;
  let fetchCalls;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchCalls = [];
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test("triggerRebuild POSTs to the hook URL and resolves on 2xx", async () => {
    globalThis.fetch = async (url, init) => {
      fetchCalls.push({ url, method: init?.method });
      return new Response("", { status: 200 });
    };

    await triggerRebuild(HOOK, SCHEDULED_AT);

    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].url, HOOK);
    assert.equal(fetchCalls[0].method, "POST");
  });

  test("triggerRebuild throws with the status code on non-ok responses", async () => {
    globalThis.fetch = async () => new Response("", { status: 503 });

    await assert.rejects(
      () => triggerRebuild(HOOK, SCHEDULED_AT),
      /deploy hook returned 503/,
    );
  });
  ```

- [ ] **Step 2: Run the test to confirm it fails**

  Run: `node --test tests/js/worker-deploy.test.mjs`
  Expected: FAIL — `Cannot find module '../../worker/src/deploy.ts'`.

- [ ] **Step 3: Create `worker/src/deploy.ts` with minimal implementation**

  ```ts
  // Fires the Workers Builds deploy hook to rebuild the site.
  // Called daily by the Worker cron so date-tick-over fields (today's
  // weekday, closure freshness window, server-rendered freshness dot)
  // stay correct. The hook URL is the secret — no auth header needed.
  // Logs scheduled time and response status so a silent 5xx surfaces
  // in `wrangler tail`.
  export async function triggerRebuild(
    hookUrl: string,
    scheduledTime: number,
  ): Promise<void> {
    const response = await fetch(hookUrl, { method: "POST" });
    console.log(
      `daily-rebuild scheduledTime=${new Date(scheduledTime).toISOString()} status=${response.status}`,
    );
    if (!response.ok) {
      throw new Error(`deploy hook returned ${response.status}`);
    }
  }
  ```

- [ ] **Step 4: Run the test to confirm it passes**

  Run: `node --test tests/js/worker-deploy.test.mjs`
  Expected: PASS — both test cases.

- [ ] **Step 5: Typecheck**

  Run: `npm --prefix worker run typecheck`
  Expected: exit 0, no output.

- [ ] **Step 6: Commit**

  ```bash
  git add worker/src/deploy.ts tests/js/worker-deploy.test.mjs
  git commit -m "feat(worker): add triggerRebuild helper for daily Workers Builds deploys"
  ```

---

## Task 5b: Worker — pull PT-gate into a pure dispatch helper + test the four tick shapes

**Rationale:** The dispatch logic (PT hour 0 + minute 5 → rebuild; else → NOAA refresh) is
the highest-stakes piece of this plan. Testing it directly keeps DST-transition-day
correctness from depending on visual inspection.

**Files:**
- Create: `worker/src/schedule.ts`
- Create: `tests/js/worker-schedule.test.mjs`

- [ ] **Step 1: Write the failing test**

  Create `tests/js/worker-schedule.test.mjs`:

  ```js
  // Locks in the branch selection for the scheduled handler. Two UTC crons
  // cover the year (`5 7 UTC` = 00:05 PDT; `5 8 UTC` = 00:05 PST), and the
  // hourly `0 * * * *` must always fall through to NOAA refresh — including
  // at 00:00 PT. These inputs cover PDT midnight, PST midnight, the hourly
  // edge case at 00:00 PT, and an arbitrary non-midnight tick.

  import { test } from "node:test";
  import assert from "node:assert/strict";

  import { classifyTick } from "../../worker/src/schedule.ts";

  test("PDT midnight (5 7 UTC on 2026-06-15) → rebuild", () => {
    assert.equal(classifyTick(Date.UTC(2026, 5, 15, 7, 5)), "rebuild");
  });

  test("PST midnight (5 8 UTC on 2026-01-15) → rebuild", () => {
    assert.equal(classifyTick(Date.UTC(2026, 0, 15, 8, 5)), "rebuild");
  });

  test("hourly tick at 00:00 PT (PDT, 2026-06-15 07:00 UTC) → refresh", () => {
    assert.equal(classifyTick(Date.UTC(2026, 5, 15, 7, 0)), "refresh");
  });

  test("hourly tick at 12:00 PT (PST, 2026-01-15 20:00 UTC) → refresh", () => {
    assert.equal(classifyTick(Date.UTC(2026, 0, 15, 20, 0)), "refresh");
  });

  test("off-PT-midnight daily tick (PST on 2026-06-15 08:05 UTC = 01:05 PDT) → refresh", () => {
    // During PDT, the PST cron `5 8 UTC` lands at 01:05 PT, not midnight.
    assert.equal(classifyTick(Date.UTC(2026, 5, 15, 8, 5)), "refresh");
  });
  ```

- [ ] **Step 2: Run the test to confirm it fails**

  Run: `node --test tests/js/worker-schedule.test.mjs`
  Expected: FAIL — `Cannot find module '../../worker/src/schedule.ts'`.

- [ ] **Step 3: Create `worker/src/schedule.ts`**

  ```ts
  // Pure dispatch for the Worker `scheduled` handler. Given a cron tick's
  // scheduledTime (ms since epoch, UTC), returns which branch should run.
  // Extracted so the DST-sensitive PT-hour + UTC-minute logic is unit-testable
  // without stubbing the Worker runtime.
  export type TickKind = "rebuild" | "refresh";

  export function classifyTick(scheduledTime: number): TickKind {
    const at = new Date(scheduledTime);
    const ptHour = Number(
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles",
        hour: "2-digit",
        hour12: false,
      }).format(at),
    );
    const minute = at.getUTCMinutes();
    return ptHour === 0 && minute === 5 ? "rebuild" : "refresh";
  }
  ```

- [ ] **Step 4: Run the test to confirm it passes**

  Run: `node --test tests/js/worker-schedule.test.mjs`
  Expected: PASS — all five tests.

- [ ] **Step 5: Typecheck**

  Run: `npm --prefix worker run typecheck`
  Expected: exit 0.

- [ ] **Step 6: Commit**

  ```bash
  git add worker/src/schedule.ts tests/js/worker-schedule.test.mjs
  git commit -m "feat(worker): add classifyTick dispatch helper with DST-aware tests"
  ```

---

## Task 6: Worker — extend `scheduled` handler with PT-hour/minute gate

**Files:**
- Modify: `worker/src/index.ts`

- [ ] **Step 1: Extend the `Env` interface and import helpers**

  At the top of `worker/src/index.ts`, update the imports and `Env` shape:

  ```ts
  import { assembleAndPersist } from "./assemble";
  import { readAllRaw, readSpotRaw } from "./kv";
  import { corsHeaders, preflight } from "./cors";
  import { triggerRebuild } from "./deploy";
  import { classifyTick } from "./schedule";

  export interface Env {
    CONDITIONS: KVNamespace;
    WORKERS_BUILDS_DEPLOY_HOOK: string;
  }
  ```

- [ ] **Step 2: Replace the `scheduled` handler**

  Replace the existing `scheduled` method at the bottom of the default export:

  ```ts
    async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
      // Daily rebuild: fires once per calendar day at 00:05 PT year-round.
      // Two daily crons in wrangler.toml cover PST (`5 8 UTC`) and PDT (`5 7 UTC`);
      // `classifyTick` gates on PT hour 0 + UTC minute 5 so the hourly cron
      // (minute 0) always falls through to the NOAA refresh path, including at
      // 00:00 PT. Dispatch logic lives in ./schedule.ts and is unit-tested.
      if (classifyTick(event.scheduledTime) === "rebuild") {
        ctx.waitUntil(
          triggerRebuild(env.WORKERS_BUILDS_DEPLOY_HOOK, event.scheduledTime).catch((err) => {
            console.error("triggerRebuild failed:", err);
          }),
        );
        return;
      }

      ctx.waitUntil(
        assembleAndPersist(env.CONDITIONS).catch((err) => {
          console.error("assembleAndPersist failed:", err);
        }),
      );
    },
  ```

- [ ] **Step 3: Typecheck**

  Run: `npm --prefix worker run typecheck`
  Expected: exit 0, no output.

- [ ] **Step 4: Run all Worker-facing tests**

  Run: `node --test tests/js/*.test.mjs`
  Expected: all tests pass (`worker-deploy`, `worker-schedule`, plus existing
  `board-status`, `conditions`, `noaa`).

- [ ] **Step 5: Commit**

  ```bash
  git add worker/src/index.ts
  git commit -m "feat(worker): gate scheduled handler on PT 00:05 to fire daily rebuild"
  ```

---

## Task 7: Worker — rename script, add daily crons

**Files:**
- Modify: `worker/wrangler.toml`
- Modify: `worker/package.json`

- [ ] **Step 1: Update `worker/wrangler.toml` `name` and `[triggers]`**

  Change line 1:

  ```toml
  name = "swimfrancisco"
  ```

  Replace the `[triggers]` block (currently `crons = ["0 * * * *"]`) with:

  ```toml
  # Three crons:
  #  - `0 * * * *` — hourly NOAA/NDBC refresh (unchanged).
  #  - `5 7 * * *` and `5 8 * * *` — daily rebuild candidates. Cron expressions
  #    run in UTC; one maps to 00:05 PT each half of the year (PDT = `5 7 UTC`,
  #    PST = `5 8 UTC`). The `scheduled` handler gates on PT hour 0 + minute 5
  #    so exactly one rebuild fires per calendar day.
  [triggers]
  crons = ["0 * * * *", "5 7 * * *", "5 8 * * *"]
  ```

  Update the stale comment on line 13 (currently references "served by Pages"):

  ```toml
  # Unified Workers Builds model. Wrangler serves the built Zola output from
  # ../public as static assets and invokes this Worker for /api/* and
  # /__scheduled. Same origin locally and in production.
  ```

  Leave `[[kv_namespaces]]` with `id = "REPLACE_ME"` placeholders for now — they
  get filled during the bootstrap runbook (Task 15), once `terraform apply`
  returns the real IDs.

- [ ] **Step 2: Update `worker/package.json` `name` field**

  Change line 2:

  ```json
  "name": "swimfrancisco",
  ```

- [ ] **Step 3: Typecheck**

  Run: `npm --prefix worker run typecheck`
  Expected: exit 0, no output.

- [ ] **Step 4: Commit**

  ```bash
  git add worker/wrangler.toml worker/package.json
  git commit -m "feat(worker): rename to swimfrancisco, add DST-safe daily crons"
  ```

---

## Task 8: Templates — server-render `data-today` on the weekly grid

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Mark the day-head column with `data-today`**

  At `templates/spots/page.html:117`, replace the single-line `<span class="weekly-grid-dayhead" ...>` with a multi-line version that adds `data-today`:

  ```tera
                <span class="weekly-grid-dayhead"
                      role="columnheader"
                      data-day="{{ day_order[loop.index0] }}"
                      {% if day_order[loop.index0] == today_weekday %}data-today="true"{% endif %}>
                  {{ label }}
                </span>
  ```

- [ ] **Step 2: Mark the matching grid cells with `data-today`**

  At `templates/spots/page.html:134`, change the single-line `<span class="weekly-grid-cell" ...>` opener to:

  ```tera
                  <span class="weekly-grid-cell"
                        role="cell"
                        data-day="{{ day }}"
                        data-day-short="{{ day_labels[loop.index0] }}"
                        {% if day == today_weekday %}data-today="true"{% endif %}
                        {% if cell | length == 0 %}data-empty="true"{% endif %}>
  ```

- [ ] **Step 3: Stamp the TODAY block with `data-day` for devtools diagnosis**

  At `templates/spots/page.html:73`, replace:

  ```tera
          <section class="today-block" data-field="today">
  ```

  with:

  ```tera
          <section class="today-block" data-field="today" data-day="{{ today_weekday }}">
  ```

  This is purely diagnostic — `data-day` lets devtools show at a glance which weekday the server baked in, so stale HTML after a missed rebuild is trivially identifiable.

- [ ] **Step 4: Build and grep for server-rendered today markers**

  Run: `zola build`
  Expected: clean build, "Done: ... N pages."

  Run: `grep -o 'data-today="true"' public/spots/hamilton-pool/index.html | wc -l`
  Expected: at least 2 (day-head + one or more cells for today's column).

- [ ] **Step 5: Commit**

  ```bash
  git add templates/spots/page.html
  git commit -m "feat(spots): server-render data-today on weekly grid and TODAY block"
  ```

---

## Task 9: Templates — drop `data-last-verified` from `.detail-root`

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Remove the attribute**

  At `templates/spots/page.html:37-39`, change:

  ```tera
      <div class="detail-root"
           data-schedule='{{ schedule_json | safe }}'
           data-last-verified="{{ extra.last_verified_at | default(value='') }}">
  ```

  to:

  ```tera
      <div class="detail-root"
           data-schedule='{{ schedule_json | safe }}'>
  ```

  The attribute's only consumer was `applyFreshness` in `static/js/detail.js`, which Task 12 deletes. The server-rendered freshness dot in the footer (line 266) remains the single source of truth.

- [ ] **Step 2: Build and confirm the attribute is gone**

  Run: `zola build && grep -c 'data-last-verified' public/spots/hamilton-pool/index.html`
  Expected: `0`.

- [ ] **Step 3: Commit**

  ```bash
  git add templates/spots/page.html
  git commit -m "refactor(spots): drop data-last-verified (consumer removed next)"
  ```

---

## Task 10: Templates — replace 12-branch month-label ladder with array lookup

**Files:**
- Modify: `templates/spots/page.html`

- [ ] **Step 1: Introduce the lookup array near the closure loop**

  At `templates/spots/page.html`, directly after the `{% if upcoming_closures | length > 0 %}` line (currently line 172), but before `<section class="closure-banners" ...>`, insert the lookup:

  ```tera
        {# Tera 0.22.1 supports variable array indexing (used for day_order /
           day_labels above), so a 12-entry lookup replaces the hand-unrolled
           month-label if-ladder that used to live below. #}
        {% set month_labels = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"] %}
  ```

- [ ] **Step 2: Replace the two 12-branch if-ladders inside the closure loop**

  Delete the entire block from line 181 (`{% if cs_month_i == 1 %}`) through line 230 (`{% endif %}`) — both the `cs_month_label` ladder and the `ce_month_label` ladder (~50 lines).

  Insert in their place, immediately after `{% set ce_day_i = ce_parts[2] | int %}`:

  ```tera
              {% set cs_month_label = month_labels[cs_month_i - 1] %}
              {% set ce_month_label = month_labels[ce_month_i - 1] %}
  ```

  The downstream `{% set cs_label = cs_month_label ~ " " ~ cs_day_i %}` and `{% set ce_label = ... %}` lines stay unchanged.

- [ ] **Step 3: Build and spot-check closure labels**

  Run: `zola build`
  Expected: clean build.

  Run: `grep -h 'closure-banner-date' public/spots/*/index.html | head -5`
  Expected: output contains month abbreviations (e.g., `APR`, `JUN`) formatted as before the refactor. Specifically, at least one pool with month-crossing closures (Hamilton, `2026-06-06`) still renders `JUN` correctly.

- [ ] **Step 4: Commit**

  ```bash
  git add templates/spots/page.html
  git commit -m "refactor(spots): replace 12-branch month-label ladder with array lookup"
  ```

---

## Task 11: JS — delete `markTodayColumn`

**Files:**
- Modify: `static/js/detail.js`

- [ ] **Step 1: Delete the `markTodayColumn` function**

  Remove lines 156–162 of `static/js/detail.js` (the `function markTodayColumn(root, now) { ... }` block).

- [ ] **Step 2: Delete the call site**

  In the `init` function, remove the `markTodayColumn(root, now);` line (currently line 175).

- [ ] **Step 3: Drop the `DAY_KEYS` import if no other use remains**

  Check: `grep -n DAY_KEYS static/js/detail.js`
  If no matches remain, drop `DAY_KEYS,` from the import at line 9.

- [ ] **Step 4: Run tests and build**

  Run: `node --test tests/js/*.test.mjs`
  Expected: all tests pass.

  Run: `zola build`
  Expected: clean build.

- [ ] **Step 5: Manual sanity check**

  Open `public/spots/hamilton-pool/index.html` in a browser with JS disabled.
  Expected: today's column is highlighted (server-rendered `data-today="true"` + existing CSS rule).

- [ ] **Step 6: Commit**

  ```bash
  git add static/js/detail.js
  git commit -m "refactor(detail): delete markTodayColumn — server now marks today's column"
  ```

---

## Task 12: JS — delete `applyFreshness` and trim imports

**Files:**
- Modify: `static/js/detail.js`

- [ ] **Step 1: Delete the `applyFreshness` function**

  Remove lines 146–154 of `static/js/detail.js` (the `function applyFreshness(root, now) { ... }` block).

- [ ] **Step 2: Delete the call site**

  In the `init` function, remove the `applyFreshness(root, now);` line.

- [ ] **Step 3: Drop the `freshnessLabel` import**

  Remove `freshnessLabel,` from the import at the top of the file (line 11). Leave `nowInPacific`, `computeDetailStatus`, `parseHHMM`, `formatHHMM` — they're still used by the status slab + today-block decoration.

- [ ] **Step 4: Run tests and build**

  Run: `node --test tests/js/*.test.mjs`
  Expected: all tests pass. Note — `freshnessLabel` is still exported from `board.mjs` and exercised by `tests/js/board-status.test.mjs`. Keeping the export as documented API surface is intentional; full removal is tracked as a follow-up.

  Run: `zola build`
  Expected: clean build.

- [ ] **Step 5: Manual sanity check with JS disabled**

  Open `public/spots/hamilton-pool/index.html` in a browser with JS disabled.
  Expected: footer freshness dot shows the correct class (`fresh` or `stale`) and label — rendered entirely by the server (lines 253–270 of `templates/spots/page.html`).

- [ ] **Step 6: Commit**

  ```bash
  git add static/js/detail.js
  git commit -m "refactor(detail): delete applyFreshness — server freshness dot is authoritative"
  ```

---

## Task 13: devenv — add `pkgs.terraform`, drop `.env.local` from dotenv

**Files:**
- Modify: `devenv.nix`
- Modify: `.gitignore`

- [ ] **Step 1: Update `devenv.nix` packages list**

  Change lines 4–8:

  ```nix
    packages = [
      pkgs.git
      pkgs.zola
      pkgs.watchexec
      pkgs.terraform
      # Node ≥22.18 — unflagged TS type stripping for `node --test` against
      # `worker/src/*.ts`. nixpkgs currently ships 22.22+, which clears the bar.
      pkgs.nodejs_22
    ];
  ```

- [ ] **Step 2: Collapse `dotenv.filename` to `.env` only**

  Change line 16:

  ```nix
    dotenv.filename = [ ".env" ];
  ```

- [ ] **Step 3: Drop `.env.local` from `.gitignore`**

  At `.gitignore` line 9, remove the `.env.local` entry (leave the preceding `.env` line intact). The resulting direnv section should be:

  ```gitignore
  # direnv
  .direnv
  .env
  ```

- [ ] **Step 4: Migrate any existing `.env.local` in the worktree**

  Run: `[ -f .env.local ] && cat .env.local >> .env && rm .env.local || echo "no .env.local"`
  Expected: either "no .env.local" or the merge runs.

- [ ] **Step 5: Reload the devenv shell and confirm toolchain versions**

  Run: `devenv shell -c 'terraform version && node --version'`
  Expected: Terraform ≥ 1.10 and Node ≥ 22.18 (required for unflagged TS
  type stripping in `node --test`).

- [ ] **Step 6: Commit**

  ```bash
  git add devenv.nix .gitignore
  git commit -m "chore(devenv): add terraform and collapse dotenv to .env only"
  ```

---

## Task 14: Docs + `.env.example` cleanup

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/schedules.md`
- Modify: `docs/plans/schedules.md`

- [ ] **Step 1: Update `.env.example`**

  Replace the current contents of `.env.example` with:

  ```dotenv
  # Copy this file to `.env` for local-only secrets. Both `.env` and the file
  # below are gitignored.

  # Schedule extractor (docs/schedules.md).
  GOOGLE_API_KEY=
  ANTHROPIC_API_KEY=

  # Optional model/provider overrides.
  SCHEDULES_PROVIDER=gemini
  # SCHEDULES_GEMINI_MODEL=gemini-3.1-flash-lite-preview
  # SCHEDULES_ANTHROPIC_MODEL=claude-sonnet-4-6

  # Terraform / wrangler (terraform/README.md, docs/deploy.md).
  CLOUDFLARE_API_TOKEN=

  # R2-backed Terraform state. These ARE R2 credentials — the AWS_* naming is
  # a Terraform S3 backend quirk, not an actual AWS dependency.
  AWS_ACCESS_KEY_ID=
  AWS_SECRET_ACCESS_KEY=
  ```

- [ ] **Step 2: Update `README.md` line 55**

  Replace:

  ```
  reads provider credentials from a gitignored `.env` or `.env.local` loaded by `devenv`'s built-in dotenv integration
  ```

  with:

  ```
  reads provider credentials from a gitignored `.env` loaded by `devenv`'s built-in dotenv integration
  ```

- [ ] **Step 3: Update `docs/schedules.md`**

  At line 13, replace `Copy \`.env.example\` to \`.env\` or \`.env.local\`, then fill in one provider key:` with `Copy \`.env.example\` to \`.env\`, then fill in one provider key:`.

  At line 31, replace `dotenv.filename = [ ".env" ".env.local" ];` with `dotenv.filename = [ ".env" ];`.

  At line 40, replace `After editing \`.env\` or \`.env.local\`, reload your environment:` with `After editing \`.env\`, reload your environment:`.

- [ ] **Step 4: Update `docs/plans/schedules.md`**

  At line 162, replace `or \`.env.local\`,` with nothing (leaving the sentence describing `.env` alone).

  At line 337, replace `\`.env\` / \`.env.local\` — hold \`ANTHROPIC_API_KEY\` / \`GOOGLE_API_KEY\` locally` with `\`.env\` — holds \`ANTHROPIC_API_KEY\` / \`GOOGLE_API_KEY\` locally`.

- [ ] **Step 5: Commit**

  ```bash
  git add .env.example README.md docs/schedules.md docs/plans/schedules.md
  git commit -m "docs: drop .env.local dual-file convention, note new required keys"
  ```

---

## Task 15: Rewrite `docs/deploy.md` for Workers Builds + Terraform + daily rebuild

**Files:**
- Modify: `docs/deploy.md`
- Delete: `docs/superpowers/plans/2026-04-18-daily-rebuild-static-cleanup.md`

- [ ] **Step 1: Replace the contents of `docs/deploy.md`**

  The existing file describes the Pages + separate-Worker model, which no longer applies. Rewrite it end-to-end:

  ````markdown
  # SwimFrancisco Deploy Guide

  Deploy is a single Cloudflare Worker (`swimfrancisco`) running in the
  unified Workers Builds model: the same script serves the built Zola site
  as static assets and handles `/api/*` requests. Terraform owns the durable
  infrastructure around it (KV, DNS, the `www → apex` redirect, the apex
  custom-domain binding).

  Push to `main` auto-deploys via Workers Builds. A Worker cron at 00:05 PT
  POSTs to a Workers Builds deploy hook to daily-rebuild the site so that
  date-tick-over fields in the rendered HTML stay correct.

  ---

  ## One-time bootstrap

  Follow in this order. Each step depends on the previous.

  ### 1. `.env` setup

  Create the root `.env` file from `.env.example`. Fill in:

  - `CLOUDFLARE_API_TOKEN` — token with the scopes listed in `terraform/README.md`.
  - `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — R2 credentials for the
    Terraform state bucket. (These ARE R2 credentials; the `AWS_` naming is a
    Terraform S3 backend quirk.)
  - `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` — for the schedule extractor.
    Unrelated to deploy, but `.env` is the one file that holds both.

  ### 2. R2 state bucket for Terraform

  Dashboard → R2 → Create bucket `swimfrancisco-tfstate`, private, automatic
  location. Then R2 → Manage API Tokens → Create token scoped to that bucket
  with Object Read & Write.

  ### 3. Terraform — phase 1 (KV + DNS + redirect)

  Preflight: if a `www` CNAME already exists in the zone, Terraform's create
  will fail. Check and clean up first:

  ```sh
  dig +short www.swimfrancisco.com
  ```

  If anything returns, delete it in Dashboard → DNS → Records OR
  `terraform import cloudflare_dns_record.www <zone_id>/<record_id>` before
  continuing.

  ```sh
  devenv shell
  cd terraform
  terraform init
  terraform plan \
    -target=cloudflare_workers_kv_namespace.conditions \
    -target=cloudflare_workers_kv_namespace.conditions_preview \
    -target=cloudflare_dns_record.www \
    -target=cloudflare_ruleset.www_redirect
  # Review the plan, then apply the same targets:
  terraform apply \
    -target=cloudflare_workers_kv_namespace.conditions \
    -target=cloudflare_workers_kv_namespace.conditions_preview \
    -target=cloudflare_dns_record.www \
    -target=cloudflare_ruleset.www_redirect
  terraform output
  ```

  Save the two KV namespace IDs.

  ### 4. Wire the KV IDs into `worker/wrangler.toml`

  Replace the `REPLACE_ME` placeholders in the `[[kv_namespaces]]` block with
  the IDs from step 3 (`kv_namespace_id` → `id`,
  `kv_preview_namespace_id` → `preview_id`). Commit and push to `main`.

  ### 5. Create the Workers Builds project

  Dashboard → Workers & Pages → Create → Workers → Connect to Git. Select
  `cbzehner/swimfrancisco`, branch `main`. Configure:

  | Field | Value |
  |---|---|
  | Project name | `swimfrancisco` |
  | Build command | `zola build` |
  | Deploy command | `npx wrangler deploy --config worker/wrangler.toml` |
  | Root directory | `/` |
  | Builds for non-production branches | Enabled (gives PR previews) |
  | Build env var | `ZOLA_VERSION=0.22.1` |

  Click Deploy. The first build should succeed now that `worker/wrangler.toml`
  has real KV IDs and the `swimfrancisco` script name.

  ### 6. Terraform — phase 2 (apex custom domain)

  With the Worker now existing:

  ```sh
  cd terraform
  terraform plan
  ```

  Expected plan diff: exactly one resource to add
  (`cloudflare_workers_custom_domain.apex`); zero to change, zero to destroy.
  If anything else shows up, stop and investigate — phase-1 resources should
  already be in the state and unchanged.

  ```sh
  terraform apply
  ```

  This creates `cloudflare_workers_custom_domain.apex`, binding
  `swimfrancisco.com` to the Worker.

  ### 7. Deploy hook + Worker secret

  Workers Builds → `swimfrancisco` → Settings → Triggers → Deploy hooks →
  Add. Name: `daily-rebuild`, Branch: `main`. Copy the URL.

  ```sh
  cd worker
  wrangler secret put WORKERS_BUILDS_DEPLOY_HOOK
  # paste the hook URL when prompted
  wrangler secret list   # confirm WORKERS_BUILDS_DEPLOY_HOOK is bound
  ```

  ### 8. Publish cron triggers

  ```sh
  cd worker
  wrangler deploy
  wrangler triggers deploy
  ```

  `deploy` publishes Worker code; `triggers deploy` registers cron patterns.
  In the dashboard: Worker → Settings → Triggers should show three crons
  (`0 * * * *`, `5 7 * * *`, `5 8 * * *`).

  ### 9. Bootstrap KV immediately

  Fresh KV returns `503 conditions not yet available` until the first hourly
  cron tick. Force a populate via the dashboard: Workers & Pages →
  `swimfrancisco` → Triggers → Cron Triggers → next to `0 * * * *`, click
  **Run**. (Wrangler 4 has no standalone `cron trigger` subcommand; the
  dashboard invoker is the official production path.)

  ### 10. Verify end-to-end

  ```sh
  curl -X POST "$WORKERS_BUILDS_DEPLOY_HOOK"          # manual rebuild test
  curl -sSf https://swimfrancisco.com/ | head -5      # site served
  curl -sSf https://swimfrancisco.com/api/conditions | head -c 400   # API served
  ```

  Within 24 hours, Workers Builds → Deployments should show exactly one
  hook-triggered build at ~00:05 PT in addition to any push-triggered builds.

  ---

  ## Daily rebuild cron

  The Worker's `scheduled` handler dispatches by PT hour + minute derived from
  `event.scheduledTime`:

  - **PT hour 0, minute 5** → calls `triggerRebuild(WORKERS_BUILDS_DEPLOY_HOOK, …)`.
    Two UTC crons cover the year (`5 7 * * *` = 00:05 PDT,
    `5 8 * * *` = 00:05 PST); exactly one matches PT midnight on any
    given day.
  - **Any other tick** → calls `assembleAndPersist(env.CONDITIONS)` (hourly
    NOAA/NDBC refresh).

  The minute-5 gate is load-bearing: the hourly cron has minute 0 and always
  falls through to the NOAA refresh, including the 00:00 PT hourly tick.

  Tail the Worker to watch a firing:

  ```sh
  cd worker
  wrangler tail --format pretty
  ```

  You should see one `daily-rebuild scheduledTime=...T07:05Z status=200`
  line per day.

  ### Manual rebuild

  ```sh
  curl -X POST "$WORKERS_BUILDS_DEPLOY_HOOK"
  ```

  Also available in the dashboard: Workers Builds → Deployments → Trigger.

  ### Rollback

  - **Bad deploy.** Workers Builds → Deployments → pick a prior successful
    deploy → Rollback. Instant; no rebuild.
  - **Bad Worker code.** `cd worker && wrangler rollback`.
  - **Bad infra.** `git revert` the relevant commit in `terraform/` and
    `terraform apply`.

  ### Cron health

  `triggerRebuild` logs scheduled time and response status. A silent 5xx
  surfaces as a non-200 status in `wrangler tail`. If the cron stops firing,
  the `scheduled` invocation list in the dashboard shows gaps — check before
  assuming KV data is stale.
  ````

- [ ] **Step 2: Delete the superseded plan**

  ```sh
  git rm docs/superpowers/plans/2026-04-18-daily-rebuild-static-cleanup.md
  ```

- [ ] **Step 3: Build the site to confirm nothing else referenced the old deploy doc**

  Run: `zola build`
  Expected: clean build.

- [ ] **Step 4: Commit**

  ```bash
  git add docs/deploy.md
  git commit -m "docs(deploy): rewrite runbook for Workers Builds + Terraform + daily rebuild"
  ```

---

## Task 16: Memory retirement — update `project_pacific_time_convention.md`

**Files:**
- Modify: `~/.claude/projects/-Users-cbzehner-Developer-Personal-swimfrancisco/memory/project_pacific_time_convention.md`

- [ ] **Step 1: Rewrite the memory body**

  Open the file with your editor. Replace the existing body (previously:
  "all pools are in SF; client JS must use `nowInPacific()` from board.mjs,
  never `new Date()`") with:

  ```markdown
  ---
  name: Pacific Time convention
  description: Day-of-week tick-over is server-rendered via the daily 00:05 PT rebuild; client JS only owns intra-day minute-level updates.
  type: project
  ---

  All pools are in SF. After the daily-rebuild work, day-tick-over fields
  (today's weekday on the weekly grid, closure freshness window, freshness
  dot) are server-rendered by Tera at build time, and the Worker cron
  rebuilds the site at 00:05 PT year-round.

  **Why:** Relying on client-side `new Date()` and manual `markToday` /
  `applyFreshness` compensations produced per-visitor divergence (visitors
  in non-PT timezones saw the wrong "today"), and the client had to
  second-guess the server. The daily rebuild makes the server authoritative.

  **How to apply:** Intra-day minute-level UI (the STATUS slab, the
  `● NOW` / `NEXT` decoration on the TODAY block) still runs in the
  browser — use `nowInPacific()` from `static/js/helpers/board.mjs`, never
  `new Date()` directly. Anything at day granularity goes in the template
  (`templates/spots/page.html`).
  ```

- [ ] **Step 2: Confirm `MEMORY.md` pointer still matches**

  Check: `grep 'Pacific Time' ~/.claude/projects/-Users-cbzehner-Developer-Personal-swimfrancisco/memory/MEMORY.md`
  Expected: existing bullet points at `project_pacific_time_convention.md`. Update the one-line hook after the `— ` to match the new `description` field if it's drifted.

  Note: no git commit — these files are user-level memory, not part of the repo.

---

## Task 17: Bootstrap + deploy (operator runbook)

The code changes are all landed at this point; this task is the human-driven
bootstrap of the Cloudflare side, following `docs/deploy.md`. None of these
steps are automated by this plan.

- [ ] **Step 1: Follow `docs/deploy.md` bootstrap sections 1–9**

  Each numbered section in the rewritten `docs/deploy.md` is a prerequisite
  for the next. Stop at any section that fails; do not skip.

- [ ] **Step 2: Post-bootstrap verification**

  ```sh
  curl -X POST "$WORKERS_BUILDS_DEPLOY_HOOK"
  ```
  Expected: `{"result":{"id":"...",...}}` and a new deploy appears in the
  Workers Builds dashboard within ~30 seconds.

  ```sh
  curl -sSf https://swimfrancisco.com/ | head -5
  ```
  Expected: HTML page served from the Worker.

  ```sh
  curl -sSf https://swimfrancisco.com/api/conditions | head -c 400
  ```
  Expected: JSON payload keyed by spot slug.

- [ ] **Step 3: 24-hour soak**

  Within 24 hours of Worker deploy, confirm exactly one hook-triggered
  build appears at ~00:05 PT in Workers Builds → Deployments. Tail the
  Worker to catch the firing:

  ```sh
  cd worker
  wrangler tail --format pretty
  ```

  Expected log line: `daily-rebuild scheduledTime=...T07:05Z status=200`
  (during PDT) or `T08:05Z` (during PST).

- [ ] **Step 4: JS-disabled regression sweep**

  Load `https://swimfrancisco.com/spots/hamilton-pool/` with JS disabled.
  Expected:
  - Today's column highlighted via `data-today="true"` + CSS.
  - TODAY block shows correct weekday label.
  - Closure banners render month labels correctly.
  - Footer freshness dot shows correct `fresh` / `stale` class.
  - STATUS slab shows em-dashes (expected — client-computed).

---

## Verification Gates

Run these at the end of the plan, before the operator bootstrap in Task 17.

- `cd terraform && terraform fmt -check && terraform init -backend=false && terraform validate` — clean.
- `npm --prefix worker run typecheck` — clean.
- `node --test tests/js/*.test.mjs` — all tests pass (existing + `worker-deploy.test.mjs`).
- `zola build` — clean.
- `grep -c 'data-today="true"' public/spots/hamilton-pool/index.html` — ≥ 2.
- `grep -c 'data-last-verified' public/spots/hamilton-pool/index.html` — 0.
- `grep -l '\.env\.local' README.md docs/schedules.md docs/plans/schedules.md .env.example devenv.nix .gitignore` — empty (no matches).
- Manual: rendered pool page shows correct TODAY weekday, `data-today` on the right column, and server-rendered freshness dot without JS.

## Open Questions (tracked, not blocking)

1. **Rebuild-health visibility.** `console.log` in `triggerRebuild` plus the Worker invocation list is enough for manual diagnosis. If the cron silently skips, we notice only when stale-freshness signals surface. A tiny KV write (`last_rebuild_trigger_at`) plus a check in an HTTP handler would let the site surface "⚠ last rebuilt N days ago". Out of scope unless the cron actually skips in practice.
2. **`freshnessLabel` full removal.** After Task 12 only `tests/js/board-status.test.mjs` imports it. Delete export + tests in a follow-up, or keep as documented dead API surface.
3. **Workers Builds project in TF.** Revisit when [`cloudflare/terraform-provider-cloudflare#6924`](https://github.com/cloudflare/terraform-provider-cloudflare/issues/6924) lands. Would let us drop the dashboard project-creation step from bootstrap.
4. **Layout flatten.** Moving `worker/` contents into the repo root drops the `--config worker/wrangler.toml` flag and the `[assets] directory = "../public"` indirection. Separate focused PR after this ships.
