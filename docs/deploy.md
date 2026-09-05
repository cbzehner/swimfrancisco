# Swim Francisco Deploy Guide

Deploy is a single Cloudflare Worker (`swimfrancisco`) running in the
unified Workers Builds model: the same script serves the built Zola site
as static assets and handles `/api/*` requests. Terraform owns the durable
infrastructure around it (KV, DNS, the `www → apex` redirect, the apex
custom-domain binding).

Push to `main` auto-deploys via Workers Builds after GitHub CI passes for
the exact commit. The Worker's hourly
cron POSTs to a Workers Builds deploy hook on the tick that lands at
00:00 PT to daily-rebuild the site so date-tick-over fields in the
rendered HTML stay correct.

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

The `[[kv_namespaces]]` block in `worker/wrangler.toml` already has the
production and preview IDs from step 3. Rewrite `id` / `preview_id` only
if you recreate those namespaces, then commit and push to `main`.

### 5. Create the Workers Builds project

Dashboard → Workers & Pages → Create → Workers → Connect to Git. Select
`cbzehner/swimfrancisco`, branch `main`. Configure:

| Field | Value |
|---|---|
| Project name | `swimfrancisco` |
| Build command | `npm run build` |
| Deploy command | `npx wrangler deploy --config worker/wrangler.toml` |
| Root directory | `/` |
| Builds for non-production branches | Enabled (gives PR previews) |
| Build env var | optional: `ZOLA_VERSION=0.22.1` |

The build command must be `npm run build`, not a direct `zola build`.
The npm script regenerates translated strings, bulletin metadata, and
agent JSON before Zola packages the static assets. If Zola is not already
on the build image's `PATH`, the script downloads the pinned release.

The npm prebuild hook detects Workers Builds through `WORKERS_CI=1`.
For `WORKERS_CI_BRANCH=main`, it waits up to ten minutes for the successful
push run of `.github/workflows/ci.yml` at `WORKERS_CI_COMMIT_SHA`, which
must match the checked-out commit. GitHub CI and local builds skip this
gate, so CI can finish its own build. Non-production branch previews also
skip the gate. The existing dashboard build command needs no change.

The gate reads the public GitHub Actions API. A failed or cancelled run,
malformed response, permanent API error, or timeout stops the build before
deployment. It retries temporary network and timeout errors and HTTP 408,
429, and 5xx responses within the same ten-minute, 21-request limit. For a
rate limit it obeys `Retry-After` or the rate-limit reset time; an unknown
rate limit waits at least one minute and backs off. An optional build
`GITHUB_TOKEN` with Actions read access can avoid unauthenticated rate
limits. Daily rebuilds reuse the successful result for their commit; if that
run has expired from GitHub's retention, rerun CI before retrying the build.

The gate checks `git HEAD` again after every wait and immediately before it
accepts CI. The final build-metadata step also requires `git HEAD` to match
`WORKERS_CI_COMMIT_SHA` for a main Workers Build. This stops a checkout that
changes while the build waits from being marked as the CI-verified commit.

For a manual production deploy, use a clean, isolated checkout at the exact
commit to deploy. Do not edit, commit, or switch that checkout while the
build runs. These `HEAD` checks do not freeze files: uncommitted changes in
the checkout can still change generated output. They also cannot prove that
an external build system did not change files after the metadata check.

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

### CARTO basemap key

Set the map's browser-facing key as a Worker secret, not a build variable:

```sh
npx wrangler secret put CARTO_BASEMAP_API_KEY --config worker/wrangler.toml
# Paste the issued key at the hidden prompt.
```

`GET /api/map-config` exposes only this key to the map, with `no-store`.
The browser sends it directly to CARTO in tile requests; it is not a private
server credential. Keep it out of Git and logs, and register the domains
where it will be used. Replacing the Worker secret takes effect on the next
page load without rebuilding the site. Previews need their own configuration.

For local Worker development, put `CARTO_BASEMAP_API_KEY` in the ignored
`worker/.dev.vars` file. A plain Zola server does not serve this API route;
use Wrangler for a working basemap. Browser tests mock configuration and
tile requests, so they never need the issued key.

### 8. Publish cron triggers

```sh
cd worker
wrangler deploy
wrangler triggers deploy
```

`deploy` publishes Worker code; `triggers deploy` registers cron patterns.
In the dashboard: Worker → Settings → Triggers should show one cron
(`0 * * * *`).

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
just smoke-production                               # commit, content, and conditions freshness
```

The smoke check compares the deployed pool records with canonical content
from the expected Git commit, without fixed season dates. It defaults to
local `HEAD`; `--expected-commit=<ref>` selects another local commit.
`--skip-commit` accepts the deployed commit but still checks its content,
so that commit must exist in the local clone. Fetch it before checking an
older deployment if needed.

Within 24 hours, Workers Builds → Deployments should show exactly one
hook-triggered build at 00:00 PT in addition to any push-triggered builds.

---

## Daily rebuild cron

The Worker's `scheduled` handler runs both side-effects on every tick:

- Always calls `assembleAndPersist(env.CONDITIONS)` for the hourly
  NOAA/NDBC refresh.
- When `isPtMidnight(event.scheduledTime)` returns true, also calls
  `triggerRebuild(WORKERS_BUILDS_DEPLOY_HOOK, …)`. PT midnight maps to
  exactly one UTC hour per day (`07:00` during PDT, `08:00` during PST);
  `Intl.DateTimeFormat` handles the DST shift, so the cron config stays
  a single `0 * * * *` entry.

Tail the Worker to watch a firing:

```sh
cd worker
wrangler tail --format pretty
```

You should see one `daily-rebuild scheduledTime=...T07:00Z status=200`
line per day (or `T08:00Z` during PST).

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
