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
