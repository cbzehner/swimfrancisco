# Swim Francisco

A "departure board" for San Francisco swim spots — 9 city pools and 5 open-water locations — with live open/closed status, water temperatures, and tide predictions.

## Architecture

A [Zola](https://www.getzola.org/) static site served by a single Cloudflare Worker in the Workers Builds model. The Worker serves the built Zola assets, handles `/api/*`, fetches NOAA and NDBC conditions on an hourly cron, and caches them in KV. The frontend is plain vanilla JS (no bundler, no framework). The UI uses an amber-on-navy departure-board aesthetic with split-flap row animations on load. Leaflet is lazy-loaded only when the user opens the map view.

## Repo layout

```
content/spots/   one .md per spot (TOML frontmatter)
i18n/            source translation catalogs and locale registry
data/i18n/       generated runtime/Zola localization artifacts
templates/       Zola/Tera templates (base, index, spots/page)
static/          plain JS (conditions, detail, filters, map, status), main.css, _redirects
worker/          Cloudflare Worker source (TypeScript)
schedule-tools/  uv-managed Python pool schedule extractor
docs/            spec.md, deploy.md, design-concepts.md, testing-webkit.md, …
```

## Local development

```sh
devenv shell          # enter the Nix-managed dev environment
just serve            # run the site with live reload at http://127.0.0.1:1111
just build            # refresh bulletin fingerprint/count and produce public/
just test-i18n        # verify translation catalogs and generated artifacts
zola check            # validate links and content
```

Production-parity local preview:

```sh
just dev              # Zola build watcher + wrangler dev at http://localhost:8787
just refresh-conditions # trigger /__scheduled to populate local KV
```

Worker development:

```sh
cd worker
npm install
npm run dev           # wrangler dev
npm run typecheck     # tsc --noEmit
```

## Tests

```sh
just test-python      # Python pipeline + site-render tests
just test-js          # pure JS helpers (node:test)
just typecheck-worker # Worker TypeScript
just check            # full local verification: tests + zola build
```

## Deploy

Pushes to `main` auto-deploy through Cloudflare Workers Builds. The build command runs `npm run build`; the deploy command runs `npx wrangler deploy --config worker/wrangler.toml`. The hourly Worker cron also triggers a rebuild on the tick that lands at 00:00 PT so date-sensitive rendered HTML stays current. After a fresh KV bootstrap, `/api/conditions` returns 503 until the hourly cron populates conditions; see `docs/deploy.md` for the full runbook.

## Adding or updating spots

Create a new file at `content/spots/<slug>.md` with TOML frontmatter. See `docs/spec.md` for the full schema (fields differ between `type = "pool"` and `type = "open_water"`). Rebuild with `zola build`.

For new **open-water** spots, the Worker's station mapping is regenerated from the markdown frontmatter automatically — `wrangler dev` and `wrangler deploy` invoke `scripts/generate-worker-spots.mjs` via the `[build]` hook. Pools do not need worker changes.

For pool schedule refreshes, use the local extractor in `docs/schedules.md`. It lives in `schedule-tools/`, is `uv`-managed, reads provider credentials from a gitignored root `.env` loaded by `devenv`'s built-in dotenv integration, has a `schedules debug bakeoff` subcommand that runs two providers and saves raw review artifacts alongside the PDF under `data/<slug>/<date>-<sha12>/`, and locks manually reviewed payloads via a committed `reviewed.json` in the same directory. `npm run build` and `just build` refresh `data/bulletin.json`; when the reviewed schedule fingerprint changes, the visible bulletin number bumps automatically.

## Adding or updating translations

Localization is catalog-driven. Edit the source catalogs under `i18n/`, then regenerate artifacts:

```sh
npm run generate-i18n
npm run check-i18n
```

Source of truth:

- `i18n/locales.toml` defines supported locales, labels, OG locale codes, titles, and descriptions.
- `i18n/ui/<locale>.toml` defines UI, status, SEO, and runtime JS strings.
- `i18n/spots/<locale>.toml` defines translated spot metadata and body copy.
- `i18n/sections/<locale>.toml` defines translated section page frontmatter.
- `i18n/dynamic-labels.toml` maps stable display codes and canonical labels to UI translation keys.

Generated artifacts:

- `config.toml` Zola language and translation blocks.
- `data/locales.toml` and `data/i18n/*` runtime/Zola lookup data.
- localized section pages and spot pages under `content/`.

Do not hand-edit generated localized pages for translation changes. Run `npm run generate-i18n` after catalog edits, and keep `npm run check-i18n` green so locale lists, keys, placeholders, dynamic labels, and generated files do not drift.

## Tech stack

Zola, plain JS (no build step for frontend), Leaflet (lazy-loaded for map view), Cloudflare Workers Builds + KV, devenv/Nix for the dev shell, uv/Python for the local schedule extractor.

## Known gaps

- All 8 pools with current published schedule PDFs have manually reviewed `sessions[]` data. `sava-pool` still depends on upstream publishing a reopening schedule PDF.
- Lat/lng for all spots are best-estimate geocodes; re-verify before any distance-critical UX work.
- Worker bootstrap: after first deploy `/api/conditions` returns 503 until the first hourly cron fires or the dashboard cron trigger is run manually — see `docs/deploy.md`.

## License

GPL-3.0-only. See [`LICENSE`](LICENSE).

## Links

- [`docs/spec.md`](docs/spec.md) — product spec and content schema
- [`docs/schedules.md`](docs/schedules.md) — pool schedule extraction workflow
- [`docs/deploy.md`](docs/deploy.md) — deploy runbook
- [`worker/README.md`](worker/README.md) — Worker-specific notes
