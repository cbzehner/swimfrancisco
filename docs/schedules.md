# Pool Schedule Extraction

The schedule extractor is a local `uv`-managed Python CLI that fetches SF Rec & Park schedule PDFs, asks an LLM provider to extract structured schedule data, merges the result into `content/spots/*.md`, and writes a review report to `tmp/extraction-report.md`.

## Setup

Use `uv` for package management in this repo:

```sh
uv sync
```

Copy `.env.example` to `.env` or `.env.local`, then fill in one provider key:

```sh
cp .env.example .env
```

Example:

```sh
GOOGLE_API_KEY=...
# or
ANTHROPIC_API_KEY=...
```

The repo uses `devenv`'s built-in dotenv integration:

```nix
dotenv.enable = true;
dotenv.filename = [ ".env" ".env.local" ];
```

If you use `direnv`, run this once after pulling the `.envrc` change:

```sh
direnv allow
```

After editing `.env` or `.env.local`, reload your environment:

```sh
direnv reload
# or start a fresh `devenv shell`
```

Optional overrides:

```sh
SCHEDULES_PROVIDER=gemini
SCHEDULES_GEMINI_MODEL=gemini-3.1-flash-lite-preview
SCHEDULES_ANTHROPIC_MODEL=claude-sonnet-4-6
```

## Usage

Dry-run a single pool:

```sh
uv run schedules extract --only hamilton-pool --dry-run
```

Run the full published registry:

```sh
uv run schedules extract
```

Run a provider bakeoff on a flagged pool without touching content or state:

```sh
uv run schedules extract --provider gemini --compare-with anthropic --only hamilton-pool --dry-run --force
```

Useful flags:

- `--provider anthropic|gemini`
- `--compare-with anthropic|gemini`
- `--only slug1,slug2`
- `--force`
- `--dry-run`

## Review Flow

1. Run `uv run schedules extract`.
2. Read `tmp/extraction-report.md`.
3. Review `git diff content/spots/`.
4. For any pool with `review_flag[...]` lines, inspect the raw provider outputs under `data/artifacts/<slug>/<pdf_sha>/`.
5. If a pool needs a durable manual override, commit an adjudication file under `data/adjudications/<slug>/<pdf_sha256>.json`.
6. Spot-check flagged pools against the source PDF before accepting a content diff.
7. Commit `content/spots/`, `data/extraction-state.json`, and any new `data/adjudications/` files only after the diff looks trustworthy.

`data/artifacts/` is a local review cache. Keep it around when you are comparing providers or debugging a bad extraction, but do not commit it by default.

`data/adjudications/` is the opposite: it is committed source of truth for PDF hashes that have been manually reviewed. When the extractor sees the same `slug + pdf_sha256` again, it reuses that adjudicated payload instead of asking the provider to reinterpret the PDF.

## Registry Maintenance

The source registry lives at `src/schedules/registry.toml`.

When SF Rec moves a PDF URL:

1. Open the pool facility page on `sfrecpark.org`.
2. Copy the current schedule PDF `DocumentCenter/View/...` link into the matching registry entry.
3. Leave `official_page_url` pointed at the facility page.
4. If the facility page has no current PDF yet, keep the pool skipped and record the blocker in `source_status` and `notes`.

## Current Blockers

As of 2026-04-17:

- All 7 pools with current published PDFs have manually reviewed adjudications in `data/adjudications/`.
- `mission-community-pool` is skipped because the facility page announces the Summer 2026 opening date but exposes no current schedule PDF.
- `sava-pool` is skipped because the pool remains closed for repairs and the page only links an old Fall 2025 schedule.

## Future

The v3 path is still the same: a GitHub Action can wrap `uv run schedules extract` and open a PR whenever the content diff is non-empty.
