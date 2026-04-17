# SwimFrancisco Deploy Guide

This guide walks through the first deploy of SwimFrancisco v1 to Cloudflare. There are two moving parts:

1. **Static site** — built by Zola, served by Cloudflare Pages.
2. **Conditions API** — a Cloudflare Worker (under `worker/`) that fetches NOAA / NDBC data on a cron and serves JSON.

The custom domain `swimfrancisco.com` ties them together.

All steps below are performed manually (dashboard + `wrangler` CLI). v1 has no CI; pushes to `main` trigger Pages builds automatically once the project is wired up.

---

## 1. Cloudflare Pages — static site

### Create the Pages project

In the Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git, select this repo and branch `main`.

### Build settings

| Field | Value |
|---|---|
| Framework preset | None |
| Build command | `zola build` |
| Build output directory | `public` |
| Root directory | `/` (repo root) |
| Environment variables | `ZOLA_VERSION=0.22.1` |

Notes:

- Cloudflare Pages' build image ships a recent Zola, but pinning `ZOLA_VERSION` matches the devenv pin (`zola 0.22.1`) and avoids surprise upgrades.
- Leave Node and Rust versions on their defaults; the build does not use them.
- `static/_redirects` is copied to `public/_redirects` by Zola and consumed by Pages at deploy time.

### First deploy

Trigger a deploy (dashboard → Deployments → Retry or push a commit). The first deploy will be reachable at `https://<project>.pages.dev`.

---

## 2. Conditions Worker

See `worker/README.md` for the short version; the full flow is:

```sh
cd worker
wrangler login

# Create KV namespaces (one real, one for preview/dev).
wrangler kv:namespace create CONDITIONS
wrangler kv:namespace create CONDITIONS --preview
```

Copy the `id` and `preview_id` wrangler prints into `worker/wrangler.toml` under `[[kv_namespaces]]` (replace the `REPLACE_ME` placeholders).

```sh
wrangler deploy            # ships the Worker
wrangler triggers deploy   # registers the hourly cron
```

### Bootstrap KV immediately

Fresh Workers have empty KV, so `/api/conditions` returns `503 conditions not yet available` until the first scheduled tick (up to an hour later). Force a populate:

```sh
wrangler cron trigger --env production
# or click "Trigger" on the cron in the dashboard.
```

Re-run this any time you want to refetch upstream data on demand.

---

## 3. Custom domain — swimfrancisco.com

### Add the zone

If `swimfrancisco.com` is not already in this Cloudflare account, add it via dashboard → Websites → Add a site and follow the registrar instructions to move nameservers (or use Cloudflare Registrar).

### Attach the apex to Pages

Pages project → Custom domains → Set up a custom domain → `swimfrancisco.com`. Cloudflare creates the CNAME flattening record and provisions TLS automatically.

### Redirect `www` to apex

Rules → Redirect Rules → Create:

- When incoming requests match: `hostname equals www.swimfrancisco.com`
- Then: `Static → 301 → https://swimfrancisco.com/${uri.path}`

### Wire the Worker to the zone

Pick **one** of the two options below (both are already stubbed as commented `[[routes]]` blocks in `worker/wrangler.toml` — uncomment the one you choose, then `wrangler deploy`).

#### Option C — single origin (recommended)

Bind the Worker to `swimfrancisco.com/api/*`:

```toml
[[routes]]
pattern = "swimfrancisco.com/api/*"
zone_name = "swimfrancisco.com"
```

The browser calls `/api/conditions` (same origin), so no CORS handshake is needed in production. Preview Pages deploys (`*.pages.dev`) fall through to `static/_redirects`, or you can add a second route to the preview hostname if you want live data in previews.

#### Option B — dedicated API subdomain

Bind the Worker to `api.swimfrancisco.com/*`:

```toml
[[routes]]
pattern = "api.swimfrancisco.com/*"
zone_name = "swimfrancisco.com"
```

Then either:

- uncomment the `/api/*` rule in `static/_redirects` so Pages rewrites same-origin `/api/*` to the subdomain, or
- set `window.SWIMFRANCISCO_API = "https://api.swimfrancisco.com/api/conditions"` at runtime (already supported by `static/js/conditions.js`).

If you pick Option B, confirm the Worker's CORS allow-list still covers `https://swimfrancisco.com` (it does — see `worker/src/` for the CORS handler added in Step 15).

---

## 4. Verify

After both services are live:

```sh
curl -sSf https://swimfrancisco.com/ | head -5
curl -sSf https://swimfrancisco.com/api/conditions | head -c 400   # Option C
curl -sSf https://api.swimfrancisco.com/api/conditions | head -c 400  # Option B
```

The API response should include a `generated_at` ISO timestamp and a `spots` array with current NOAA bay + NDBC ocean readings.

Then load `https://swimfrancisco.com/` in a browser and confirm the departure-board populates within a few seconds (the JS fetches `/api/conditions` on page load).

---

## 5. Rollback

- Pages: Deployments → pick a previous successful deploy → Rollback.
- Worker: `wrangler rollback` from `worker/`, or redeploy a previous commit.
- KV: the cron will re-populate on the next tick; if upstream is broken, stale records stay served until they're overwritten.
