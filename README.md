# Swim Francisco

A "departure board" for San Francisco swim spots — 9 public city pools, 5 open-water locations, and membership or limited-access pools behind a toggle — with live open/closed status, water temperatures, and tide predictions.

Pool hours are derived from official facility sources and may be wrong. The board marks unverified rows; treat it as a starting point, not a guarantee.

## Architecture

A [Zola](https://www.getzola.org/) static site served by a single Cloudflare Worker in the Workers Builds model. The Worker serves the built Zola assets, handles `/api/*`, reverse-proxies PostHog analytics at `/ingest/*` so the same origin serves both, fetches NOAA and NDBC conditions on an hourly cron, and caches them in KV. The frontend is plain vanilla JS (no bundler, no framework). The UI uses an amber-on-navy departure-board aesthetic with split-flap row animations on load. Only map pages load Leaflet.

## Repo layout

```
content/spots/   one .md per spot (TOML frontmatter)
i18n/            source translation catalogs and locale registry
data/i18n/       generated runtime/Zola localization artifacts
templates/       Zola/Tera templates (base, index, spots/page)
static/          plain JS (conditions, detail, filters, map, status), main.css, _redirects
worker/          Cloudflare Worker source (TypeScript)
schedule-tools/  uv-managed Python pool schedule extractor
scripts/         generators and smoke checks run by just/npm
terraform/       Cloudflare KV, DNS, and custom-domain state
tests/           Python, node:test, and real-browser suites
docs/            spec.md, deploy.md, schedules.md, testing-webkit.md, …
```

## Local development

Requires [Nix](https://nixos.org/download/) and [devenv](https://devenv.sh/). After a clone:

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
just test-browser     # WebKit + Chromium integration smoke tests (~20s)
just check            # full local verification: tests + browser smoke + build
```

`just test-browser` drives a freshly built site in real browser engines —
the WebKit-only regressions nothing else can catch (see
`docs/testing-webkit.md`). One-time setup per machine: `just browsers`.
A devenv-managed pre-push hook runs `just test test-browser`; bypass
deliberately with `git push --no-verify`.

## Deploy

Pushes to `main` auto-deploy through Cloudflare Workers Builds after CI passes for that exact commit; [`docs/deploy.md`](docs/deploy.md) is the full runbook.

## Adding or updating spots

Create a new file at `content/spots/<slug>.md` with TOML frontmatter. See `docs/spec.md` for the full schema (fields differ between `type = "pool"` and `type = "open_water"`). Rebuild with `zola build`.

For new **open-water** spots, regenerate the committed Worker station mapping with `node scripts/generate-worker-spots.mjs` (also run by `just typecheck-worker`); `tests/test_worker_spots.py` fails if it drifts. Pools do not need worker changes.

For pool schedule refreshes, use the local extractor in `docs/schedules.md`. It lives in `schedule-tools/`, is `uv`-managed, reads its credentials from a gitignored root `.env` loaded by `devenv`'s built-in dotenv integration, saves raw review artifacts under `data/<slug>/<date>-<sha12>/`, and locks reviewed payloads via a committed `reviewed.json` in the same directory. Git keeps the source snapshot (`source.pdf` / `source.html` / `source.xlsx` / `source.csv`), `source.sha256`, provider JSON, and `reviewed.json`. `npm run build` and `just build` refresh `data/bulletin.json`; when the reviewed schedule fingerprint changes, the visible bulletin number bumps automatically.

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
- `data/i18n/*` runtime/Zola lookup data.
- localized section pages and spot pages under `content/`.

Do not hand-edit generated localized pages for translation changes. Run `npm run generate-i18n` after catalog edits, and keep `npm run check-i18n` green so locale lists, keys, placeholders, dynamic labels, and generated files do not drift.

## Tech stack

Zola, plain JS (no build step for frontend), Leaflet (map pages only), Cloudflare Workers Builds + KV, devenv/Nix for the dev shell, uv/Python for the local schedule extractor.

## Known gaps

- Lat/lng for all spots are best-estimate geocodes; re-verify before any distance-critical UX work.
- Worker bootstrap: after first deploy `/api/conditions` returns 503 until the first hourly cron fires or the dashboard cron trigger is run manually — see `docs/deploy.md`.

Issues and pull requests are welcome.

## License

Copyright (C) 2026 Chris Zehner.

GPL-3.0-only. See [`LICENSE`](LICENSE). Leaflet and the bundled fonts keep their own licenses; see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

## Links

- [`docs/spec.md`](docs/spec.md) — product spec and content schema
- [`docs/schedules.md`](docs/schedules.md) — pool schedule extraction workflow
- [`docs/schedules-decision-log.md`](docs/schedules-decision-log.md) — dated evidence behind that workflow
- [`docs/deploy.md`](docs/deploy.md) — deploy runbook
- [`worker/README.md`](worker/README.md) — Worker-specific notes
