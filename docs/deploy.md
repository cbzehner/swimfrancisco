# Swim Francisco Deploy Guide

Deploy is a single Cloudflare Worker (`swimfrancisco`) running in the
unified Workers Builds model: the same script serves the built Zola site
as static assets and handles `/api/*` requests. Terraform owns the durable
infrastructure around it (KV, DNS, the `www → apex` redirect, the apex
custom-domain binding).

Push to `main` auto-deploys via Workers Builds after GitHub CI passes for
the exact commit. The Worker's hourly cron refreshes environmental
conditions; schedule pages remain correct across date changes without a
calendar-driven rebuild.

## Current production path

Until the staged release design below is implemented and cut over, a push to
`main` runs the required GitHub `check`, then Workers Builds runs `npm run
build` and `npx wrangler deploy --config worker/wrangler.toml` for that exact
commit. The Worker independently refreshes conditions on its hourly cron.
No GitHub deploy workflow or production ownership change is active yet.

---

## Release design (2026-09-12)

This is an implementation-ready design record. It does not change the
Cloudflare dashboard, production credentials, or deployment owner.

### Decision

Move production deployment ownership to one separate GitHub Actions workflow,
triggered by successful completion of the existing CI workflow and serialized
by the `production` environment/concurrency group. Keep Workers Builds as the
owner until that cutover is staged and verified. The current Workers Builds
path remains the rollback path during the transition.

The current design has two coordinators: GitHub CI verifies an exact commit,
then Workers Builds polls GitHub before building and deploying it. That keeps
the commit association explicit, but Workers Builds does not provide the
repository-level production queue or the out-of-order protection needed by
the release plan. GitHub documents deployment concurrency groups, but they do
not promise commit ordering, so the workflow must reject stale SHAs itself.
Current
[Workers Builds configuration](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/)
documents a production deploy command plus a separate non-production version
upload command. The proposed job uses the former responsibility in GitHub and
leaves preview behavior as an explicit cutover choice. The version upload and
promotion commands are documented in [Cloudflare version and deployment
management](https://developers.cloudflare.com/workers/versions-and-deployments/deployment-management/),
and emergency rollback behavior in [Cloudflare rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/).

The schedule automation path remains candidate-based: it builds in an
isolated worktree, stages only the generated allowlist, keeps paired and
sequential acceptance atomic, waits for CI on the exact automation branch,
and fast-forwards `main` only when the recorded base is still current. A
normal human change still reaches `main` through the existing required `check`
status. A main push, regardless of origin, is the only production trigger.

### Production workflow

Add `.github/workflows/deploy.yml` with a `workflow_run` trigger for the
successful `ci` workflow. The current workflow-level `ci-${{ github.ref }}`
concurrency with `cancel-in-progress: true` may remain: it cancels only an
unfinished verification run, while the separate deploy workflow is already
running under its own production group. The deploy workflow must require all
of these before it admits a write: `workflow_run.name == ci`,
`workflow_run.event == push`, `workflow_run.head_branch == main`, and
`workflow_run.conclusion == success`.

Use a protected `production` environment and
`concurrency: { group: production, cancel-in-progress: false }`. GitHub may
replace a pending job or start a later queued run first, so commit order is
not a safety property. The workflow enforces this sequence for the exact
`workflow_run.head_sha`:

1. Fetch `refs/heads/main` and require it to equal the CI-verified SHA. If it
   differs, record `superseded-before-upload` and exit without Cloudflare
   credentials or a write. A failed main-push CI run is handled separately:
   `main` has already advanced, the previous version remains active, and the
   next successful CI completion is the only candidate admitted.
2. Check out that SHA, build it, write metadata with the same full SHA, and
   submit the non-promoting version upload through a pinned production helper
   that makes one Cloudflare request and does not retry it. Do not use the
   stock `npx wrangler versions upload --config worker/wrangler.toml
   --tag <sha>-<run-attempt>` as an opaque admission write: the installed
   Wrangler implementation retries retryable API failures. The helper must
   record the request start, response or unknown outcome, returned version ID,
   and tag. Upload is deliberately non-promoting.
3. Fetch `main` again. If it moved, record
   `superseded-after-upload`, leave the uploaded version undeployed, and do
   not run a promotion or smoke claim. The uploaded version is retained as
   evidence and can be deleted during later authorized cleanup.
4. Promote only that returned version through a pinned helper that records the
   deployment request separately from every non-versioned settings request,
   then run `node scripts/smoke-production.mjs
   --expected-commit=<sha> --browser`. The current Wrangler
   `versions deploy` implementation performs a later settings PATCH when the
   config contains settings such as observability, so a returned deployment ID
   does not close the whole attempt. The helper must make each write explicit,
   avoid implicit retries, and wait for every write to be terminal before
   smoke verification. Recheck `main` after promotion. A changed head records
   `superseded-after-promotion`; it does not relabel the deployed version as
   the latest source.
5. Report `published` only when the exact SHA, every canonical spot record,
   live browser pages, and fresh conditions pass. A failed upload has no
   active write. A failed smoke after promotion is an explicit failed deploy,
   not a successful publication.

Before sending any Cloudflare request, the workflow creates an explicit GitHub
deployment record marked `swimfrancisco-production-admission` for the exact
SHA, workflow run/attempt, and version tag with status `in_progress`. This is
separate from the automatic deployment record GitHub creates for a protected
environment. Its token needs `deployments: write` and `actions: read` in
addition to contents read; it does not need permission to mutate GitHub
environment variables. The production preflight lists only the explicit
admission records, fails closed if it cannot create the current record, and
fails closed if any earlier explicit record is still `in_progress` or
unknown. A record from the current workflow is not ignored merely because it
has the same SHA. This record is the durable admission hold, rather than an
environment variable that a failed runner might never update.

If any upload, deployment, or settings request times out after it was sent,
the individual operation is `unknown-write`, never automatically retried, and
its admission record stays `in_progress`. A response that Cloudflare
explicitly rejects before accepting an individual request is terminal
`reconciled-not-deployed` evidence. A missing version, an inactive version
observed immediately, a passing smoke check for another version, or a
rollback is not terminal evidence for a request that may still arrive. The
reconciler queries the exact tag/version, active deployment, live build
metadata, every submitted operation, and the non-versioned settings state; if
it cannot establish a terminal outcome for every write and the exact accepted
deployment, it leaves the hold in place indefinitely for operator resolution.
An admission record may close as `reconciled-deployed` only with the exact
version/deployment ID, matching SHA, and terminal settings result recorded. It
may close as `reconciled-not-deployed` when the upload is terminal and
non-promoting, promotion was provably never submitted or was terminally
rejected, and every other submitted operation is terminal, with an evidence
link. A successful upload followed by `superseded-after-upload` therefore
releases admission while retaining the uploaded version as evidence; an
unknown upload, promotion, or settings write keeps the hold in place.
Completing or rolling back a version does not clear an outstanding record by
itself. This covers a delayed promotion arriving after an initially negative
query and a delayed settings PATCH after deployment success.

Runner loss before the record is created causes no Cloudflare write. Runner
loss after the record is created leaves the record in progress and blocks the
next job. A failure to update the record after a Cloudflare operation also
leaves it in progress; the operator reconciles the exact operation before
closing it. The next job never blindly deploys “newest main.”

Automatic retries are allowed only for a known non-write failure and reuse the
same CI run SHA and attempt identity under the same production group. A
superseded or unknown attempt requires reconciliation first. Each receipt
contains the CI workflow run ID and attempt, source SHA, main SHA at each
guard, version tag and ID, an operation list covering the upload, deployment,
and settings requests with their request IDs and terminal states, Cloudflare
deployment ID when available, smoke result, outcome (`published`,
`superseded`, `failed`, `cancelled`, or `unknown-write`), and links to the
retained workflow artifact.

Schedule automation consumes this receipt by exact main SHA. After its
compare-and-promote succeeds, `automation.py` waits only for the deploy
workflow and smoke receipt for that SHA; a missing, pending, cancelled,
superseded, or twenty-minute timeout is recorded as an unsuccessful outcome,
never as `published`. The automation result keeps the candidate base, main
promotion SHA, deploy workflow run/attempt, Cloudflare version/deployment IDs,
and live verification URL together. Queue delay is therefore visible rather
than misreported as a deployment failure of the schedule extraction itself.

### Safeguard mapping

| Existing safeguard | Cutover location | Required behavior |
|---|---|---|
| Human changes and required full checks | GitHub branch protection and `check` | No production job without the exact successful check run. |
| Candidate worktree and generated-path allowlist | `schedules-extract.yml`, `automation.py`, `check-build-ci.mjs` promotion path | Keep temporary staging, whole-snapshot deletion rules, atomic publication, and compare-and-promote when `main` moves. |
| Exact source/content association | Deploy checkout, build metadata, `--expected-commit` smoke check | The SHA checked out, built, deployed, and verified must be identical. |
| Conditions freshness | `smoke-production.mjs` | Keep the three-hour conditions checks and observation-age limits; static build age is not a correctness check after date-independent pages. |
| Out-of-order production writes | Separate deploy workflow, non-cancelling `production` concurrency, two main-head guards, and version upload/promotion split | Never promote a stale SHA; an unknown external write blocks the next promotion until its exact version is reconciled. |
| Unclear extraction or closure | Existing hold, evidence, and draft closure-review paths | No guessed hours reach the candidate or production job. |
| Rollback evidence | Deployment receipt artifact and live smoke output | Keep the failed SHA, active SHA, smoke result, and source evidence together. |

### Configuration and trigger ownership

Version upload and version promotion own the Worker code, assets, bindings,
and compatibility settings for an already-created Worker. They do not apply
changes to cron triggers, routes, or custom domains. Terraform remains the
owner of KV namespaces, DNS, redirects, and the custom domain. A separately
reviewed configuration release owns changes to `worker/wrangler.toml` and
must run under the same production admission record and serialization lock.
Cloudflare documents this as the separate `wrangler triggers deploy` operation:
[command reference](https://developers.cloudflare.com/workers/wrangler/commands/workers/#triggers-deploy).

1. Run `npx wrangler triggers deploy --config worker/wrangler.toml` for a
   cron/route change only after the exact config commit passes CI and the
   active production version is recorded.
2. Record the trigger operation, resulting cron/route configuration, config
   SHA, and verification result in the same deployment receipt. A failed or
   unknown trigger request leaves the record in progress and blocks version
   promotion until reconciled.
3. Roll back a bad trigger/config change with the prior exact config commit,
   rerun the trigger operation, and verify the scheduled invocation and live
   API. Do not silently bundle a trigger change into a code-only version
   receipt.

The initial Worker creation, Terraform resource changes, and custom-domain
changes remain separately authorized infrastructure work. The normal code
workflow refuses to claim that it delivered those changes.

### Credentials and previews

The trusted production workflow receives only a protected-environment
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Cloudflare's [external
GitHub setup](https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/)
uses the `Edit Cloudflare Workers` policy and account/zone resource scopes;
the repository
has not verified a narrower one-Worker token scope, so the cutover must record
the actual token permissions and keep the token environment-protected.
`SCHEDULES_BOT_TOKEN` remains limited to the schedule automation workflow;
`OPENAI_API_KEY` and browser-capture credentials remain in that workflow.
Pull requests and all untrusted checks receive none of these secrets. The
deploy token must not be copied into repository variables or build artifacts.

The repository does not contain evidence that anyone uses the current
Workers Builds preview URLs. Before cutover, inspect the dashboard and recent
workflow receipts. If previews are used, retain the non-production
`versions upload` path while making the main production trigger inert. If
they are unused, disable non-production builds in a separately authorized
dashboard change. Do not assume a preview is a production canary.

The current Workers Builds production build must be disabled or changed to a
non-promoting version upload before the GitHub job is enabled. First close
GitHub production admission, disable new Workers Builds production admission,
and wait for every existing Workers Build, deploy hook request, and submitted
deployment to finish or be reconciled. Record the active Workers version and
exact source SHA, then confirm no old build remains in progress. Only after
that drain does the GitHub workflow open production admission. Otherwise both
systems can write production. The official [Deploy Hooks documentation](https://developers.cloudflare.com/workers/ci-cd/builds/deploy-hooks/)
and [Workers Builds overview](https://developers.cloudflare.com/workers/ci-cd/builds/)
describe the current dashboard controls; verifying the actual trigger state
is a cutover prerequisite.

### Separate implementation tasks

1. Add and test `.github/workflows/deploy.yml` with the exact
   `workflow_run` admission predicates, main-head guards, protected
   environment, non-cancelling concurrency, pre-write GitHub deployment
   record, version upload/promotion split, receipt artifact, and exact live
   smoke step. Make build metadata accept the GitHub checkout SHA while
   retaining full-SHA and `HEAD` checks. Test record-creation failure and
   record-update failure as fail-closed cases.
2. Define a staging Worker configuration, for example
   `swimfrancisco-staging`, with its own `worker/wrangler.staging.toml`, KV
   namespace, `CARTO_BASEMAP_API_KEY`, `workers.dev` or custom smoke base URL,
   and no production custom domain. Bootstrap it with
   `npx wrangler deploy --config worker/wrangler.staging.toml`, then register
   its hourly trigger with `npx wrangler triggers deploy --config
   worker/wrangler.staging.toml` and run that trigger once through the
   dashboard so its isolated KV has fresh conditions. Subsequent version
   tests must use explicit `--config worker/wrangler.staging.toml` and
   `--base-url=$STAGING_BASE_URL`; their receipts must name the staging
   Worker, KV namespace, map domain/key, config SHA, version ID, and smoke
   URL. Exercise successful upload and promotion, failed build, failed smoke,
   reversed CI completion, three pushes, an older-run retry,
   upload/promotion timeout, runner loss, delayed promotion after a negative
   query, an old Workers Build in flight during cutover, a cron/config change,
   and rollback without changing the public Worker.
3. Confirm branch protection, the production environment reviewers, actual
   token permissions, Cloudflare trigger settings, preview usage, and active
   Worker name/account. Change the Workers Builds production command or
   disconnect it only after the new workflow passes the staging matrix.
4. After cutover, remove only the Workers Builds main-build gate:
   `buildCommit`, `checkBuildCI`, their command-line default, and their
   main-build tests/package hook. Keep `waitForCommitCI` and its
   authentication/retry helpers for schedule-branch promotion, as well as
   `generatedSchedulePath`, `stageScheduleChanges`, and
   `promoteScheduleCommit`. Keep `scripts/smoke-production.mjs`,
   exact-content checks, and schedule evidence retention.

### Release test matrix

| Scenario | Expected result |
|---|---|
| Normal human push to `main` | `check` passes, one production job runs for that SHA, live smoke passes, receipt is retained. |
| Generated candidate | Candidate CI passes first; main promotion occurs only if its base is current; main then gets the same production path. |
| Main advances during candidate validation | Promotion reports `stale`; no candidate reaches main; a fresh isolated attempt reuses captures but not publication decisions. |
| Candidate CI failure | No main push and no production credentials are used. Candidate evidence remains available for recovery. |
| Main-push CI failure | `main` has advanced but no production write occurs; the previous verified deployment remains active until the next successful `ci` completion. |
| Cloudflare deploy failure | Job fails, no success receipt is reported, and the prior active version is checked before retry. |
| Smoke failure after upload | Job fails with the live SHA and mismatch recorded; operator rolls back or prepares a corrective commit, then reruns the verified path. |
| Reversed CI completion for two pushes | Each workflow carries its own SHA; the pre-upload and pre-promotion main guards reject a stale run, even if the older CI completes later. |
| Three pushes and a pending replacement | The concurrency group may retain only the latest pending run; each admitted run rechecks `main`, and skipped SHAs are recorded as superseded rather than reported as deployed. |
| Retry of an older successful run | The workflow rejects it when `main` differs; only a new successful CI run for the current SHA can deploy. |
| Delayed or stale external request | The affected upload, deployment, or settings operation is `unknown-write`; the production hold reconciles its exact tag/version and every submitted operation and blocks the next promotion until the operator records deployed or not deployed. |
| Runner loss or deployment-record failure | Loss before record creation sends no Cloudflare request; loss after creation leaves `in_progress`; inability to create or close the record fails closed and blocks later promotion. |
| Delayed promotion after an initially negative query | The record stays `in_progress`; absence or current inactivity is not treated as terminal, and a later promotion cannot be cleared by another version's smoke result. |
| Upload timeout followed by a client retry or delayed success | The production helper uses one submission; any retry or later success is reconciled by exact tag and operation evidence before admission can close. |
| Deployment success followed by a delayed settings PATCH | Deployment and settings have separate operation receipts; the admission hold stays open until both are terminal and the live settings match the exact config SHA. |
| Successful upload superseded before promotion | The upload is recorded as terminal non-promoting, the main-head guard proves promotion was never submitted, and `reconciled-not-deployed` releases admission while retaining the version evidence. |
| Old Workers Build during forward cutover | GitHub admission stays closed until the old build/request is drained or reconciled and its active SHA/version is recorded. |
| Cron, route, or custom-domain change | Code promotion does not claim the change; the serialized config-release path or Terraform applies it, records the exact config operation, and verifies or rolls back it separately. |
| Retry and rollback | Known non-write retries use the same SHA and attempt receipt; rollback first disables admission, settles unknown writes, records the target version, runs exact-SHA smoke, then requires a corrective main commit before normal delivery resumes. |

### Rollback and unresolved facts

For an emergency, first disable admission: stop schedule automation, pause
the protected production environment, and disable the Workers Builds
production trigger. Wait for active CI/deploy jobs and any Cloudflare upload
or promotion requests to settle. Record the active version, its exact source
SHA, the intended rollback version, and every unresolved receipt. Resolve an
unknown write through the exact version tag/API result before continuing.
Then use the Workers deployment history or
`npx wrangler rollback <version-id> --config worker/wrangler.toml` to roll
back, immediately run
`node scripts/smoke-production.mjs --expected-commit=<target-sha> --browser`,
and retain the rollback receipt. Staging rehearsals use the corresponding
`worker/wrangler.staging.toml` and
`--base-url="$STAGING_BASE_URL"`. Only after the public Worker is verified
should the environment admit a corrective `main` commit. Do not reset `main`
or edit published schedules by hand to hide a deployment failure.

Restoring Workers Builds ownership is the reverse exclusive procedure: pause
the GitHub production environment, settle or reconcile every GitHub version
attempt, verify the active version, restore the Workers Builds production
deploy command and its exact-CI prebuild gate, disable the GitHub deploy
workflow, and test one exact main push before resuming schedule automation.

The dashboard's actual Workers Builds trigger state, preview usage, protected
environment rules, token scopes, and whether the account plan permits the
desired concurrency are external facts. They must be recorded during the
staged cutover. No production migration or Cloudflare setting change is part
of this task. The design trades Workers Builds' managed deploy credential for
one protected GitHub token, a staging Worker, receipts, and reconciliation
holds; it reduces split-owner race debugging only if preview usage and token
rotation remain manageable. Current evidence cannot establish that net
operator-work reduction, so the cutover remains conditional on the staging
measurements rather than an assumed saving.

---

## One-time bootstrap

Follow in this order. Each step depends on the previous.

### 1. `.env` setup

Create the root `.env` file from `.env.example`. Fill in:

- `CLOUDFLARE_API_TOKEN` — token with the scopes listed in `terraform/README.md`.
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — R2 credentials for the
  Terraform state bucket. (These ARE R2 credentials; the `AWS_` naming is a
  Terraform S3 backend quirk.)
- `OPENAI_API_KEY` — for the schedule extractor. Unrelated to deploy, but
  `.env` is the one file that holds both.

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
rate limit waits at least one minute and backs off. Retry logs include the
HTTP status and wait duration, and identify delays that reach the build
deadline. Network failures log no underlying error details or credentials.

Configure a build-only `GITHUB_TOKEN` to avoid GitHub's unauthenticated,
shared-IP rate limit:

1. Create a fine-grained GitHub personal access token restricted to
   `cbzehner/swimfrancisco`, with **Actions: Read-only** repository permission.
   Do not reuse a publication token with write access. Track the token's expiry
   and replace it before it expires.
2. In Cloudflare, open `swimfrancisco` → **Settings → Build → Build variables
   and secrets**. Add `GITHUB_TOKEN` as a **secret** for the production build.
   This is not a Worker runtime secret; `wrangler secret put` will not make it
   available to the build. Do not expose it to untrusted preview builds.
3. Retry the failed production build. Confirm `CI passed for <commit>` in its
   logs, then verify the live build metadata matches that commit.

The script permits unauthenticated requests but warns when the build token
is missing. A retry delay can consume the entire ten-minute deadline even
when CI has already passed; waiting longer is not a reliable substitute for
authenticated requests. See [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
and [Cloudflare build configuration](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/).

There is no daily rebuild. The hourly Worker refresh is independent of the
static build; if a Workers Build needs to be retried, use the exact commit and
rerun CI when its retained check is unavailable.

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

### 7. Publish cron triggers

```sh
cd worker
wrangler deploy
wrangler triggers deploy
```

`deploy` publishes Worker code; `triggers deploy` registers cron patterns.
In the dashboard: Worker → Settings → Triggers should show one cron
(`0 * * * *`).

### 8. Bootstrap KV immediately

Fresh KV returns `503 conditions not yet available` until the first hourly
cron tick. Force a populate via the dashboard: Workers & Pages →
`swimfrancisco` → Triggers → Cron Triggers → next to `0 * * * *`, click
**Run**. (Wrangler 4 has no standalone `cron trigger` subcommand; the
dashboard invoker is the official production path.)

### 9. Verify end-to-end

```sh
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

Workers Builds should show push-triggered builds for the exact commits
accepted by CI. The hourly Worker invocation refreshes conditions separately.

---

## Hourly conditions cron

The Worker's `scheduled` handler runs one side effect on every tick:

- Calls `assembleAndPersist(env.CONDITIONS)` for the hourly NOAA/NDBC
  refresh. This remains true at Pacific midnight and across daylight saving
  transitions.

Tail the Worker to watch a firing:

```sh
cd worker
wrangler tail --format pretty
```

### Rollback

- **Bad deploy.** Workers Builds → Deployments → pick a prior successful
  deploy → Rollback. Instant; no rebuild.
- **Bad Worker code.** Use Workers deployment history or
  `npx wrangler rollback <version-id> --config worker/wrangler.toml`, then run
  `just smoke-production --expected-commit=<target-sha> --browser`.
- **Bad infra.** `git revert` the relevant commit in `terraform/` and
  `terraform apply`.

### Cron health

`assembleAndPersist` logs source and KV failures, and a rejected refresh
remains a failed scheduled task. If the cron stops firing, the `scheduled`
invocation list in the dashboard shows gaps — check before assuming KV data
is stale.

## Deferred production cleanup

The old Workers Builds `daily-rebuild` deploy hook and its
`WORKERS_BUILDS_DEPLOY_HOOK` Worker secret are unused by the current code.
Remove them in a separately authorized Cloudflare cleanup; this task does
not change production settings.
