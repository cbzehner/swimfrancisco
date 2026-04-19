# Terraform + GitHub Actions Deploy — Design

**Status:** Draft
**Date:** 2026-04-18
**Topic:** Move SwimFrancisco's Cloudflare deploy from manual dashboard/wrangler steps to a Terraform-managed infra layer plus a GitHub Actions daily rebuild.

## Goals

1. Make Cloudflare infra (DNS, KV, custom domain, redirect rule) reproducible through Terraform.
2. Trigger a daily site rebuild near 12:05 AM Pacific so date-sensitive UI (today's pool sessions) rolls over without depending on a human pushing a commit.
3. Keep the existing developer ergonomics: `devenv shell`, single-origin local dev, no surprise tool sprawl.

## Non-goals

- Managing Worker code or `wrangler.toml` content via Terraform. The `wrangler` CLI continues to own the Worker bundle.
- A full CI build pipeline. Cloudflare Workers Builds owns push-to-main builds. GitHub Actions exists only for the cron.
- Restructuring the repo layout (e.g. moving Zola into `site/` or flattening `worker/` into root). Tracked as a possible follow-up; not in scope here.

## Architecture

SwimFrancisco runs as a single Cloudflare Worker in the unified Workers Builds model. The Worker serves the built Zola site as static assets (via `[assets]` in `wrangler.toml`) and handles `/api/*` requests in its `fetch` handler. There is no separate Pages project.

Three deploy paths converge on the same Worker:

1. **Push to `main`** — Cloudflare Workers Builds (dashboard-connected to the GitHub repo) runs `zola build && npx wrangler deploy --config worker/wrangler.toml` and deploys.
2. **PR opened** — same builder produces a preview deployment with a `*.workers.dev` URL.
3. **Daily cron at ~12:05 AM PT** — GitHub Actions workflow `curl`s a Workers Builds deploy hook, which triggers the same build path against the latest `main`.

Terraform manages the *infra around* the Worker: KV namespaces, DNS records, the apex custom-domain attachment, and the `www → apex` redirect rule. The Workers Builds project itself stays dashboard-managed because the Cloudflare Terraform provider does not yet have first-class coverage for Workers Builds project + git source configuration.

## Components

### Terraform configuration (`terraform/`)

```
terraform/
  versions.tf       # required_version + cloudflare provider pin
  backend.tf        # R2 (S3-compat) state backend, conditional-write locking
  main.tf           # provider config (reads CLOUDFLARE_API_TOKEN from env)
  variables.tf      # account_id, zone_id, domain, github_repo
  dns.tf            # www CNAME, www→apex redirect ruleset
  worker.tf         # KV namespaces (prod + preview), Workers Custom Domain
  outputs.tf        # KV ids
  README.md         # bootstrap and apply instructions
```

Resources managed by TF:

- `cloudflare_workers_kv_namespace.conditions` (production)
- `cloudflare_workers_kv_namespace.conditions_preview`
- `cloudflare_dns_record.www` (CNAME → apex, proxied)
- `cloudflare_ruleset.www_redirect` (zone-level dynamic redirect, 301 from `www.swimfrancisco.com` to `https://swimfrancisco.com/${path}`)
- `cloudflare_workers_custom_domain.apex` — binds the `swimfrancisco` Worker to `swimfrancisco.com`. The unified model has the Worker serving the entire apex (assets + API), so there is no separate `/api/*` route.

Resources NOT managed by TF (intentional):

- The Workers Builds project itself — provider coverage is incomplete; the project is created once via the dashboard with build/deploy commands hardcoded there. The KV bindings inside `wrangler.toml` are the only TF→runtime handoff.
- The deploy hook URL — created once in the dashboard, copied into a GitHub Actions secret.
- Worker code — `wrangler deploy` (run by Workers Builds) handles this.

### State backend — R2

Terraform's S3 backend is pointed at Cloudflare R2's S3-compatible endpoint. R2 supports conditional writes, so state locking works with `use_lockfile = true` (TF 1.10+). No DynamoDB needed.

Backend config:

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

R2 access keys are read by the S3 backend from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars (the names are an S3-backend quirk; they are R2 credentials).

### GitHub Actions

One workflow ships:

```
.github/workflows/daily-rebuild.yml
```

- **Trigger:** `schedule: cron: '5 8 * * *'` (08:05 UTC) plus `workflow_dispatch` for manual runs.
- **Job:** single `curl -fsS -X POST $WORKERS_BUILD_HOOK_URL`.
- **Secret:** `WORKERS_BUILD_HOOK_URL`, populated from the deploy hook URL after the project is created.

#### DST gap

`08:05 UTC` is `12:05 AM PST` and `1:05 AM PDT`. During PDT (March–November) the daily rebuild lands one hour late, so the date-sensitive UI is stale for up to one hour after midnight PT.

This is an explicit trade-off accepted at design time. The workflow YAML carries an inline comment documenting the gap and pointing to the strict-cron alternative (two cron entries at `5 7 * * *` and `5 8 * * *`, with a TZ-guard step that exits unless the current Pacific time is actually 12:05 AM). If the staleness window becomes painful, swap to the strict approach.

#### Push deploys

GitHub Actions does NOT deploy on push. Cloudflare Workers Builds (the dashboard git integration) handles push-to-main deploys and PR previews. Two deployers writing the same Worker is a foot-gun; one is enough.

### `devenv.nix` additions

```nix
pkgs.terraform   # local plan/apply
pkgs.act         # run GitHub Actions workflows locally against OrbStack
```

Plus convenience scripts:

- `act-daily` — runs the daily-rebuild workflow against `.env`.

`dotenv.filename` collapses to `[ ".env" ]` only — `.env.local` is dropped (see Cleanup section).

### Cleanup — `.env.local` removal

Both `.env` and `.env.local` are gitignored, so the dual-file convention here is decorative, not a security boundary. Collapse to `.env` only:

- `devenv.nix` — `dotenv.filename = [ ".env" ];`
- `.gitignore` — drop the `.env.local` line
- `README.md`, `docs/schedules.md`, `docs/plans/schedules.md`, `.env.example` — remove `or .env.local` phrasing

Migration step the operator runs once: append any existing `.env.local` contents into `.env`, then delete `.env.local`.

## Data flow

### Push to main

```
git push → GitHub → CF webhook → Workers Builds runs
  zola build
  npx wrangler deploy --config worker/wrangler.toml
→ swimfrancisco.com serves new bundle
```

### Daily rebuild

```
GitHub Actions cron (08:05 UTC, daily)
  → curl POST $WORKERS_BUILD_HOOK_URL
  → CF Workers Builds queues a fresh build of latest main
  → same build path as push deploy
  → swimfrancisco.com serves rebuilt bundle (today's date is now correct)
```

### Hourly conditions cron (unchanged)

The Worker's `[triggers] crons = ["0 * * * *"]` continues to populate KV with NOAA/NDBC data. Independent of the daily rebuild.

## Bootstrap (one-time human work)

1. **Create R2 bucket + token** for TF state (`swimfrancisco-tfstate`, scoped Object R/W token). Save keys to `.env` as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
2. **Create Cloudflare API token** for TF + wrangler:
   - Account permissions: `Workers Scripts:Edit`, `Workers KV Storage:Edit`, `Workers Routes:Edit`, `Account Settings:Read`
   - Zone permissions: `DNS:Edit`, `Page Rules:Edit`, `Zone:Read`
   - Scoped to `swimfrancisco.com` zone and the project's account.
   - Save to `.env` as `CLOUDFLARE_API_TOKEN`.
3. **Migrate `.env.local`** into `.env` and delete it.
4. **`terraform init && terraform apply`** — creates KV, DNS, redirect, custom domain attachment.
5. **Update `worker/wrangler.toml`** — set `name = "swimfrancisco"`, paste KV namespace IDs from `terraform output`, commit, push.
6. **Create the Workers Builds project** in the dashboard with:
   - Project name: `swimfrancisco`
   - Build command: `zola build`
   - Deploy command: `npx wrangler deploy --config worker/wrangler.toml`
   - Builds for non-production branches: enabled
   - Root directory: `/`
   - Build env var: `ZOLA_VERSION=0.22.1`
7. **Add a deploy hook** in Workers Builds → Settings → Triggers → Deploy hooks. Copy the URL into a GitHub repo secret named `WORKERS_BUILD_HOOK_URL`.
8. **Verify** by triggering `daily-rebuild` via `workflow_dispatch` and confirming a new build appears in the dashboard.

## Local development

`devenv shell` brings in `terraform` and `act`. To run workflows locally against OrbStack (Docker-compatible):

```sh
act workflow_dispatch -j rebuild --secret-file .env
```

`act` reads `.env` for both env vars and `secrets.X` references. OrbStack's Docker shim is picked up automatically.

## Error handling and rollback

- **Daily rebuild fails:** GitHub Actions surfaces the failure; the prior deployment continues serving. Re-run the workflow manually after fixing.
- **Workers Builds deploy fails:** Cloudflare keeps the previous Worker version live; the dashboard shows the failed build with logs.
- **TF apply fails mid-way:** R2 state is locked via conditional writes; rerun `terraform apply` after addressing the error. State is consistent because TF doesn't commit partial resource graphs.
- **Need to roll back the Worker:** dashboard → Deployments → Rollback to a prior version, OR `wrangler rollback` from `worker/`.
- **Need to roll back infra:** `terraform apply` against a prior commit of `terraform/`.

## Testing

- TF: `terraform validate` + `terraform plan` on each change. No automated apply in CI; humans do applies.
- Actions: `act workflow_dispatch -j rebuild --secret-file .env` to dry-run the cron locally before pushing the workflow file.
- Bootstrap: post-bootstrap verification commands (`curl` against the apex and `/api/conditions`) confirm the deploy reached production.

## Open questions / follow-ups

- **Layout cleanup:** consider flattening `worker/` into the repo root in a separate, focused PR after this work is shipped and validated. Would remove the `--config worker/wrangler.toml` flag and the `[assets] directory = "../public"` indirection.
- **Strict cron:** if the PDT 1-hour drift becomes painful, switch to the two-cron + TZ-guard approach.
- **Workers Builds in TF:** revisit whenever the Cloudflare provider gains first-class coverage; would let us drop the dashboard step from bootstrap.
