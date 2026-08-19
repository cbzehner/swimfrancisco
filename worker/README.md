# Swim Francisco Conditions Worker

Cloudflare Worker that fetches water conditions from NOAA CO-OPS and NDBC, assembles per-spot records, and serves them as JSON.

## Routes

- `GET /api/conditions` — slug-keyed record for every spot

Responses are JSON with `cache-control: public, max-age=900` (15 min at both client and edge). CORS allows `swimfrancisco.com`, `*.swimfrancisco.pages.dev`, and `localhost`.

## Scheduled trigger

A cron trigger runs hourly (`0 * * * *`, see `wrangler.toml`). The scheduled handler calls `assembleAndPersist`, which fetches upstream data and writes the single `conditions` key to KV.

## Deploy prereqs

KV namespace IDs are already in `wrangler.toml`. Recreate them only if you rebuild the Terraform-managed namespaces; then paste the new `id` / `preview_id` into `[[kv_namespaces]]`.

See [`../docs/deploy.md`](../docs/deploy.md) for the end-to-end Workers Builds + Terraform runbook.

## First-deploy bootstrap

After the initial deploy, KV is empty and `/api/conditions` returns `503 conditions not yet available` until the first cron tick (up to an hour later).

To populate immediately:

```sh
wrangler triggers deploy         # register the cron
```

Then run the cron from the dashboard: Workers & Pages → `swimfrancisco` → Triggers → Cron Triggers → **Run**. Wrangler 4 has no `wrangler cron trigger` command.

## Local dev

```sh
npm run dev        # wrangler dev
npm run typecheck  # tsc --noEmit
```
