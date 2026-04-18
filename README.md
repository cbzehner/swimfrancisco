# SwimFrancisco

A "departure board" for San Francisco swim spots — 9 city pools and 5 open-water locations — with live open/closed status, water temperatures, and tide predictions.

## Architecture

A [Zola](https://www.getzola.org/) static site deployed on Cloudflare Pages. A companion Cloudflare Worker fetches NOAA and NDBC conditions on an hourly cron, caches them in KV, and exposes them at `/api/conditions`. The frontend is plain vanilla JS (no bundler, no framework). The UI uses an amber-on-navy departure-board aesthetic with split-flap row animations on load. Leaflet is lazy-loaded only when the user opens the map view.

## Repo layout

```
content/spots/   one .md per spot (TOML frontmatter)
templates/       Zola/Tera templates (base, index, spots/page)
static/          plain JS (conditions, filters, map, status, expand), _redirects
sass/            main.scss (compiled to /main.css)
worker/          Cloudflare Worker source (TypeScript)
docs/            spec.md, plan.md, deploy.md, design-concepts.md
```

## Local development

```sh
devenv shell          # enter the Nix-managed dev environment
zola serve            # run the site with live reload at http://127.0.0.1:1111
zola build            # produce public/
zola check            # validate links and content
```

Worker development (separate process):

```sh
cd worker
npm install
npm run dev           # wrangler dev
npm run typecheck     # tsc --noEmit
```

## Tests

```sh
uv run pytest                     # Python pipeline + site-render tests
node --test tests/js/*.test.mjs   # pure JS helpers (node:test)
```

## Deploy

Cloudflare Pages builds the site from `main` (build command `zola build`, output `public/`). The Worker is deployed separately with `wrangler deploy` and bound to `swimfrancisco.com/api/*` via a Workers route. After the first deploy, `/api/conditions` returns 503 until the first hourly cron fires; see `docs/deploy.md` for the full runbook including manual cron trigger and KV setup.

## Adding or updating spots

Create a new file at `content/spots/<slug>.md` with TOML frontmatter. See `docs/spec.md` for the full schema (fields differ between `type = "pool"` and `type = "open_water"`). Rebuild with `zola build`.

For new **open-water** spots, also edit `worker/src/spots.ts` to map the slug to its NOAA temperature station and tide station. Pools do not need worker changes.

For pool schedule refreshes, use the local extractor in `docs/schedules.md`. It is `uv`-managed, reads provider credentials from a gitignored `.env` or `.env.local` loaded by `devenv`'s built-in dotenv integration, can run a `--compare-with` provider pass that saves raw local review artifacts under `data/artifacts/`, and can lock manually reviewed payloads to a specific PDF hash via committed files in `data/adjudications/`.

## Tech stack

Zola, plain JS (no build step for frontend), Leaflet (lazy-loaded for map view), Cloudflare Pages + Workers + KV, devenv/Nix for the dev shell.

## Known gaps

- All 7 pools with current published schedule PDFs now have manually adjudicated `sessions[]` data. `mission-community-pool` and `sava-pool` still depend on upstream publishing a current schedule PDF.
- Lat/lng for all spots are best-estimate geocodes; re-verify before any distance-critical UX work.
- Worker bootstrap: after first deploy `/api/conditions` returns 503 until the first hourly cron fires — see `docs/deploy.md` for the manual trigger command.

## License

TBD.

## Links

- [`docs/spec.md`](docs/spec.md) — product spec and content schema
- [`docs/schedules.md`](docs/schedules.md) — pool schedule extraction workflow
- [`docs/deploy.md`](docs/deploy.md) — deploy runbook
- [`worker/README.md`](worker/README.md) — Worker-specific notes
