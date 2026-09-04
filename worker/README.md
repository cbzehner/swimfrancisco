# Swim Francisco Conditions Worker

Cloudflare Worker that fetches water conditions (USGS, NOAA CO-OPS, NDBC, ERDDAP, MUR SST), assembles per-spot records, and serves them as JSON. It also serves the built site from `../public` and reverse-proxies PostHog at `/ingest/*`.

## Routes

- `GET /api/conditions` — slug-keyed record for every spot

Responses are JSON with `cache-control: public, max-age=900, s-maxage=3600` (15 min in the browser, 1 h at the edge). CORS allows `swimfrancisco.com`, `*.swimfrancisco.pages.dev`, and `localhost`.

## Scheduled trigger

A cron trigger runs hourly (`0 * * * *`, see `wrangler.toml`). The scheduled handler calls `assembleAndPersist`, which fetches upstream data and writes the single `conditions` key to KV. The tick that lands at 00:00 PT also fires the Workers Builds deploy hook so date-sensitive rendered HTML turns over.

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
