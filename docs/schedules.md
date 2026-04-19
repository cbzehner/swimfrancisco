# Pool Schedule Extraction

The schedule extractor is a local `uv`-managed Python CLI that fetches SF Rec & Park schedule PDFs, asks an LLM provider to extract structured schedule data, merges the result into `content/spots/*.md`, and writes a review report to `tmp/extraction-report.md`.

## Setup

Use `uv` for package management in this repo:

```sh
uv sync
```

Copy `.env.example` to `.env`, then fill in one provider key:

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
dotenv.filename = [ ".env" ];
```

If you use `direnv`, run this once after pulling the `.envrc` change:

```sh
direnv allow
```

After editing `.env`, reload your environment:

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

Run a provider bakeoff on a flagged pool:

```sh
uv run schedules debug bakeoff --provider gemini --compare-with anthropic --only hamilton-pool --force
```

Useful flags on `extract`:

- `--provider anthropic|gemini`
- `--only slug1,slug2`
- `--force`
- `--dry-run` — skip content/state writes but still produce the report.

`schedules debug bakeoff` is always observational — it never writes to
`content/spots/` or `data/extraction-state.json`.

**Exit codes:** the `extract` command exits non-zero when any pool failed
(hard-blocked or errored). Partial failure never exits 0; shell automation
can trust the exit code.

## Review Flow

The source of truth for a pool's schedule is `content/spots/<slug>.md`. The
extractor and reviewed-snapshot machinery are regeneration aids — they
help produce and verify that file, but they are not parallel authorities.

1. Run `uv run schedules extract`.
2. Read `tmp/extraction-report.md`.
3. Review `git diff content/spots/`.
4. For any pool with `review_note[...]` lines, inspect the raw provider
   outputs under `data/artifacts/<slug>/<pdf_sha>/`.
5. If a pool needs a durable manual override, commit a reviewed snapshot
   under `data/reviewed-snapshots/<slug>/<pdf_sha256>.json`. The envelope
   schema is enforced on load — see `src/schedules/reviewed_snapshots.py`
   for the required fields.
6. If the provider catches up to the reviewed payload on a future PDF
   (same schedule, re-exported PDF), ratification fires automatically and
   writes a new snapshot at the new hash — no re-review needed.
7. Spot-check flagged pools against the source PDF before accepting a
   content diff.
8. Commit `content/spots/`, `data/extraction-state.json`, and any new
   `data/reviewed-snapshots/` files only after the diff looks trustworthy.

`data/artifacts/` is a local review cache. Keep it around when comparing
providers or debugging a bad extraction, but do not commit it by default.

`data/reviewed-snapshots/` is the opposite: committed, schema-enforced,
and used by the pipeline to skip re-extraction when the same
`slug + pdf_sha256` is seen again. Its payloads pass through the same
validation and grounding that provider output does — human review
protects against misinterpretation, not typos.

## Registry Maintenance

The source registry lives at `src/schedules/registry.toml`.

When SF Rec moves a PDF URL:

1. Open the pool facility page on `sfrecpark.org`.
2. Copy the current schedule PDF `DocumentCenter/View/...` link into the matching registry entry.
3. Leave `official_page_url` pointed at the facility page.
4. If the facility page has no current PDF yet, keep the pool skipped and record the blocker in `source_status` and `notes`.

## Current Blockers

As of 2026-04-17:

- All 7 pools with current published PDFs have manually reviewed snapshots in `data/reviewed-snapshots/`.
- `mission-community-pool` is skipped because the facility page announces the Summer 2026 opening date but exposes no current schedule PDF.
- `sava-pool` is skipped because the pool remains closed for repairs and the page only links an old Fall 2025 schedule.

## Closure Contract (v1)

Closures in the extractor schema are **facility-wide, all-day, and date-only**:

- Fields: `start`, `end`, `reason` — both dates are ISO (`YYYY-MM-DD`) and inclusive.
- There is no `pool` field and no time fields.
- SFUSD and other timed school-only bookings are **not** closures; they are omitted from the output entirely.

Timed or pool-scoped closures are a deliberate out-of-scope item; adding them is a schema migration, not a bug fix. See `docs/plans/review-followup.md` Step 1 for the rationale.

## Future

The v3 path is still the same: a GitHub Action can wrap `uv run schedules extract` and open a PR whenever the content diff is non-empty.
