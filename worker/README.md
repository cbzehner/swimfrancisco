# Swim Francisco Conditions Worker

Cloudflare Worker that fetches water conditions from NOAA CO-OPS and NDBC, assembles per-spot records, and serves them as JSON.

## Routes

- `GET /api/conditions` — bulk record for all spots
- `GET /api/conditions/:slug` — single spot (e.g. `/api/conditions/aquatic-park`)

Responses are JSON with `cache-control: public, max-age=60, s-maxage=300`. CORS allows `swimfrancisco.com`, `*.swimfrancisco.pages.dev`, and `localhost`.

## Scheduled trigger

A cron trigger runs hourly (`0 * * * *`, see `wrangler.toml`). The scheduled handler calls `assembleAndPersist`, which fetches upstream data and writes per-slug + `all` keys to KV.

## Deploy prereqs

1. Create a KV namespace: `wrangler kv:namespace create CONDITIONS`
2. Paste the returned `id` (and optionally `preview_id`) into `wrangler.toml` under `[[kv_namespaces]]`.
3. `wrangler deploy`

See [`../docs/deploy.md`](../docs/deploy.md) for the end-to-end flow (Pages + Worker + custom domain).

## First-deploy bootstrap

After the initial deploy, KV is empty and `/api/conditions` returns `503 conditions not yet available` until the first cron tick (up to an hour later).

To populate immediately:

```sh
wrangler triggers deploy         # register the cron
wrangler cron trigger --env production   # or click "Trigger" in the dashboard
```

Re-run either command any time you want to force a fresh assemble.

## Local dev

```sh
npm run dev        # wrangler dev
npm run typecheck  # tsc --noEmit
```
