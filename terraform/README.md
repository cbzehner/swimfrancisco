# Swim Francisco Terraform

Manages the Cloudflare infrastructure around the `swimfrancisco` Worker:
KV namespaces, the `www` CNAME + redirect, and the apex→Worker custom-domain
binding. State lives in a Cloudflare R2 bucket (`swimfrancisco-tfstate`).

## One-time bootstrap

1. **Create the R2 state bucket.** Dashboard → R2 → Create bucket:
   `swimfrancisco-tfstate`, automatic location, no public access.
2. **Create an R2 API token** scoped to that bucket, permissions "Object
   Read & Write". Store `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the SecretSpec
   `infrastructure` profile; see [Task credentials](../docs/secrets.md).
3. **Create a Cloudflare API token** with:
   - Account: `Workers Scripts:Edit`, `Workers KV Storage:Edit`,
     `Workers Routes:Edit`, `Account Settings:Read`
   - Zone: `DNS:Edit`, `Single Redirect:Edit`, `Zone:Read`, scoped to
     `swimfrancisco.com`

   Store it as `CLOUDFLARE_API_TOKEN` in that same profile.
4. **Create a project sandbox** using [the sandbox workflow](../docs/sandboxes.md).
   Run Terraform through `just sandbox-terraform <name> <command>` on the host.
   Credentials reach only that guest Terraform process; ordinary shells do not
   load them. Use `just sandbox-terraform <name> version` to test transport
   without making infrastructure changes.

## First apply (two phases)

`cloudflare_workers_custom_domain.apex` requires the Worker script to exist
before it can bind the apex. The Worker is created by the first Workers
Builds deploy (dashboard-connected to the GitHub repo). Apply in two phases:

```sh
just sandbox-terraform swimfrancisco init

# Phase 1 — create infra the Worker does NOT depend on.
just sandbox-terraform swimfrancisco plan -out=bootstrap.tfplan \
  -target=cloudflare_workers_kv_namespace.conditions \
  -target=cloudflare_workers_kv_namespace.conditions_preview \
  -target=cloudflare_dns_record.www \
  -target=cloudflare_ruleset.www_redirect
# Review the saved plan before applying.
just sandbox-terraform swimfrancisco apply bootstrap.tfplan
just sandbox-terraform swimfrancisco output
```

Paste the KV IDs into `worker/wrangler.toml`, commit, push. The push
triggers the first Workers Builds deploy.

```sh
# Phase 2 — attach the apex now that the Worker exists.
just sandbox-terraform swimfrancisco plan -out=reviewed.tfplan
# Review the saved plan before applying.
just sandbox-terraform swimfrancisco apply reviewed.tfplan
```

Subsequent changes use `just sandbox-terraform swimfrancisco plan -out=reviewed.tfplan`,
review the plan, then `just sandbox-terraform swimfrancisco apply reviewed.tfplan`.
The wrapper disables interactive input; a saved plan is the preferred apply path.

## Outputs

- `kv_namespace_id` — production KV binding id for `worker/wrangler.toml`.
- `kv_preview_namespace_id` — preview KV binding id for
  `worker/wrangler.toml` (used by `wrangler dev`).

## Not managed here

- **Workers Builds project + git integration.** The Cloudflare provider does
  not yet expose Workers Builds git source (see
  [cloudflare/terraform-provider-cloudflare#6924]). Created once in the
  dashboard; see `docs/deploy.md` for the field values.
- **Worker code, cron triggers.** `wrangler deploy` and
  `wrangler triggers deploy` own these.

[cloudflare/terraform-provider-cloudflare#6924]: https://github.com/cloudflare/terraform-provider-cloudflare/issues/6924
