# Pool Schedule Extraction

The schedule extractor is a local `uv`-managed Python CLI under `schedule-tools/`. It fetches SF Rec & Park schedule PDFs, asks an LLM provider to extract structured schedule data, merges the result into `content/spots/*.md`, and writes a review report to `tmp/extraction-report.md`.

## Setup

Use `uv` for package management in the extractor project:

```sh
just sync
```

Copy the root `.env.example` to root `.env`, then fill in one provider key:

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
just schedules-dry-run --only hamilton-pool
```

Run the full published registry:

```sh
just schedules-extract
```

Run a provider bakeoff on a flagged pool:

```sh
just schedules debug bakeoff --provider gemini --compare-with anthropic --only hamilton-pool --force
```

Useful flags on `extract`:

- `--provider anthropic|gemini`
- `--only slug1,slug2`
- `--force`
- `--dry-run` — skip content/state writes but still produce the report.

`schedules debug bakeoff` is always observational — it never writes to
`content/spots/` or any `data/` file.

**Exit codes:** the `extract` command exits non-zero when any pool failed
(hard-blocked or errored). Partial failure never exits 0; shell automation
can trust the exit code.

## Review Flow

The source of truth for a pool's schedule is `content/spots/<slug>.md`. The
extractor and reviewed-snapshot machinery are regeneration aids — they
help produce and verify that file, but they are not parallel authorities.

Everything for a given (slug, PDF) lives in one directory:

```
data/<slug>/<fetch-date>-<pdf-sha12>/
  source.pdf
  gemini-<model>.json          # self-describing provider output
  anthropic-<model>.json
  reviewed.json                # present ⇔ human-approved
```

Review status is a filesystem predicate: `reviewed.json` present ⇒ done;
absent ⇒ needs review. `--force` and `--compare-with` bypass this
fast-path.

1. Run `just schedules-extract`.
2. Read `tmp/extraction-report.md`.
3. Review `git diff content/spots/`.
4. For any pool with `review_note[...]` lines, inspect the provider
   outputs under `data/<slug>/<fetch-date>-<sha12>/`.
5. Run `just schedules-review` to approve the next pending pool. The
   CLI picks the oldest unreviewed directory, seeds `reviewed.json`, opens
   the PDF, and launches `$EDITOR`. On exit it validates, projects into
   `content/spots/<slug>.md`, and leaves `reviewed.json` on disk.
6. Spot-check flagged pools against the source PDF before accepting a
   content diff.
7. Commit `content/spots/` and the per-review directory (`source.pdf`,
   provider JSONs, `reviewed.json`) once the diff looks trustworthy.

Every new PDF requires a fresh human pass via `schedules review` — there
is no auto-ratification shortcut. If a re-exported PDF has identical
content to a prior review, approving it via the reviewer is cheap (few
seconds) and preserves the "human vouched for this hash" contract.

Each `<provider>-<model>.json` is self-describing: it carries
`prompt_sha256`, `schema_sha256`, `source_pdf_url`, `pdf_sha256`, and
`extracted_at`. Extraction skips when the cached file's hashes match the
current prompt and schema; an edit to either re-triggers the LLM.

`reviewed.json` payloads pass through the same validation and grounding
that provider output does — human review protects against
misinterpretation, not typos.

## Registry Maintenance

The source registry lives at `schedule-tools/src/schedules/registry.toml`.

When SF Rec moves a PDF URL:

1. Open the pool facility page on `sfrecpark.org`.
2. Copy the current schedule PDF `DocumentCenter/View/...` link into the matching registry entry.
3. Leave `official_page_url` pointed at the facility page.
4. If the facility page has no current PDF yet, keep the pool skipped and record the blocker in `source_status` and `notes`.

## Current Blockers

As of 2026-05-04:

- All 8 pools with current published PDFs have `reviewed.json` committed under `data/<slug>/<date>-<sha12>/`.
- `mission-community-pool` uses the Spring 2026 PDF (`DocumentCenter/View/28959`, effective 2026-05-12 through 2026-06-06), reviewed under `data/mission-community-pool/2026-05-03-6d12e60b17f1/`.
- `sava-pool` is skipped because the pool remains closed for repairs and the page only links an old Fall 2025 schedule.

## Closure Contract (v1)

Closures in the extractor schema are **facility-wide, all-day, and date-only**:

- Fields: `start`, `end`, `reason` — both dates are ISO (`YYYY-MM-DD`) and inclusive.
- There is no `pool` field and no time fields.
- SFUSD and other timed school-only bookings are **not** closures; they are omitted from the output entirely.

Timed or pool-scoped closures are a deliberate out-of-scope item; adding them is a schema migration, not a bug fix. See `docs/plans/review-followup.md` Step 1 for the rationale.

## Reviewing extracted schedules

Every extracted pool joins the review queue until a human approves it. Approve extractions by running:

```
just schedules-review
```

The CLI scans `data/<slug>/` for review dirs that have provider JSON but
no `reviewed.json`, picks the oldest-PDF-first, and:

1. Writes `reviewed.json` into the review dir (no separate draft tree).
2. Opens the PDF in Preview (macOS `open`).
3. Launches `$EDITOR` (or `hx`) on `reviewed.json`. Helix's JSON LSP picks up the `$schema` pointer and gives you autocomplete + inline validation.
4. On editor exit, validates (schema + `validate()` invariants) and projects into `content/spots/<slug>.md`.

To review a specific pool: `just schedules-review --slug hamilton-pool`.

If finalization fails after `reviewed.json` is written (rare; projection error), re-run `just schedules project <slug>` to finish.

To start over from raw extraction on a given pool, delete its `reviewed.json` and re-run `just schedules-review`.

## Future

The v3 path is still the same: a GitHub Action can wrap `just schedules-extract` and open a PR whenever the content diff is non-empty.
