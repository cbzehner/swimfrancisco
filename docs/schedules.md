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

Run a single pool:

```sh
just schedules-extract --only hamilton-pool
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

`extract` never writes `content/spots/*.md` or `reviewed.json` — those
only change through `schedules review`. The pipeline produces provider
artifacts under `data/<slug>/<date>-<sha12>/` and a review report; the
operator approves changes by hand. `schedules debug bakeoff` is the
same: observational only.

**Exit codes:** the `extract` command exits non-zero when any pool failed
(hard-blocked or errored). Partial failure never exits 0; shell automation
can trust the exit code.

## Review Flow

The source of truth for a pool's schedule is `content/spots/<slug>.md`. The
extractor and reviewed-snapshot machinery are regeneration aids — they
help produce and verify that file, but they are not parallel authorities.

Localized spot pages are intentionally separate from the schedule source of
truth. When adding a new canonical `content/spots/<slug>.md`, also add sibling
localized pages for every configured language (`<slug>.es.md`,
`<slug>.zh-Hant.md`, `<slug>.fil.md`, `<slug>.vi.md`) with
`extra.localized_from = "<slug>"`. The templates call `get_page(..., lang=...)`
for each configured language so missing localized siblings should fail the
build instead of silently publishing an English fallback.

Everything for a given (slug, PDF) lives in one directory:

```
data/<slug>/<fetch-date>-<pdf-sha12>/
  source.pdf
  gemini-<model>.json          # self-describing provider output
  anthropic-<model>.json
  reviewed.json                # present ⇔ human-approved
```

Koret is workbook-backed: `source.xlsx` is the canonical hashed source and
`source.pdf` is the full-workbook visual export used by the reviewer. The XLSX
preserves visible sheet names, merged ranges, and cell values; every visible
sheet must be classified by the extractor or extraction fails.

Review status is a filesystem predicate: `reviewed.json` present ⇒ done;
absent ⇒ needs review. `--force` and `--compare-with` bypass this
fast-path.

1. Run `just schedules-extract`.
2. Read `tmp/extraction-report.md`.
3. Review `git diff content/spots/`.
4. For any pool with `review_note[...]` lines, inspect the provider
   outputs under `data/<slug>/<fetch-date>-<sha12>/`.
5. Run `just schedules-review` to open the local review site. Select each
   pending pool, compare its source with the structured rows, then choose
   **Save & next pool**. The site validates the result, projects it into
   `content/spots/<slug>.md`, and leaves `reviewed.json` on disk.
6. Spot-check flagged pools against the source PDF before accepting a
   content diff.
7. Run `just release`. If the reviewed schedule fingerprint changed, the
   visible bulletin number bumps automatically.
8. Commit `content/spots/`, `data/bulletin.json`, the registry change if
   the PDF URL moved, and the per-review directory (`source.pdf`, provider
   JSONs, `reviewed.json`) once the diff looks trustworthy.

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

## Closure Contract (v2)

Closures in the extractor schema are **facility-wide**. By default they are
all-day. Single-day closures may carry a partial-day time window so common
recurring sub-day events (Aquatics Division Training on the 3rd Thursday of
each month, etc.) don't have to round up to a whole-day cancellation.

- Fields: `start`, `end`, `reason` (required); `start_time`, `end_time` (optional, both required together).
- Dates are ISO (`YYYY-MM-DD`) and inclusive. Times are 24-hour `HH:MM` and the window is half-open: `[start_time, end_time)`.
- Partial-day windows are only valid on single-day entries (`start == end`). For recurring patterns, expand to one entry per occurrence within the schedule's effective window.
- There is no `pool` field. Pool-scoped closures remain out of scope.
- SFUSD and other timed school-only bookings are **not** closures; they are omitted from the output entirely.

The pre-v2 contract was all-day-only, which over-reported "Closed for staff training 11–2" cells as full-day closures. v2 was added in 2026-05; existing all-day closures keep working unchanged (the time fields are additive).

## Reviewing extracted schedules

Every extracted pool joins the review queue until a human approves it. Start the local reviewer with:

```
just schedules-review
```

The command binds to `127.0.0.1` on an available port and opens a browser. The
site scans `data/<slug>/` for review directories with provider JSON but no
`reviewed.json`, then provides:

1. A pending-pool queue and source schedule beside the seeded structured data.
2. Add, edit, and remove controls for sessions, access hours, exceptions, and closures.
3. PDF page and zoom controls, a full-screen source view, and a persistent weekday review cursor.
4. A live source-identity check before editing; changed sources must be refreshed and re-extracted first.
5. An explicit source-cell attestation before save, followed by a second source check.
6. Schema and schedule validation followed by projection into `content/spots/<slug>.md`.

Use `just schedules-review --no-open` to print the URL without opening a browser,
or `just schedules-review --port 4317` to choose a fixed local port.

If projection fails after a manual `reviewed.json` edit, run `just schedules project <slug>` to finish.

If you edit an already-reviewed `reviewed.json` by hand, re-run
`just schedules project <slug>`, then `just release`.

To start over from raw extraction on a given pool, delete its `reviewed.json` and re-run `just schedules-review`.

## Eval

```sh
just schedules-eval               # writes tmp/eval-<timestamp>.md
just schedules-eval --stdout      # prints the same report
just schedules-eval --all-dirs    # include historical review dirs (default: latest only)
```

The eval reads existing per-review artifacts — no API calls. For each pool with a
committed `reviewed.json`, it diffs every same-dir provider artifact against the
human-reviewed payload using `(day, type, start, end, pool)` as the row identity.
Output is per-provider aggregate plus per-pool/per-artifact precision/recall/F1,
plus a sample of disagreements (extra rows the model emitted, missing rows it
dropped).

Run before and after any prompt or schema tweak; require improvement, not regression.

## Auto-extract workflow

The `.github/workflows/schedules-extract.yml` action runs every Monday at
09:00 PT and on `workflow_dispatch`. It re-runs extraction with both Gemini
and Anthropic — provider artifacts under `data/<slug>/<date>-<sha12>/`
get written, while `content/spots/` and `reviewed.json` stay untouched
(the pipeline never writes those). If anything changed under `data/`, the
action commits to an `auto/schedules-extract-YYYY-MM-DD` branch and opens
or updates a PR with the extraction report and eval scorecard in the body.

Reviewer flow on an auto-PR:

1. Pull the branch locally.
2. Run `just schedules-review` for any pool the report flags.
3. Verify each row against the source PDF in `$EDITOR`.
4. Save `reviewed.json`; the projection writes `content/spots/<slug>.md`.
5. Run `just release`.
6. Commit the reviewed files to the PR branch and merge.

Public-repo safety: the workflow has no `pull_request` or
`pull_request_target` triggers, only `schedule` and `workflow_dispatch`.
Forks cannot run it. `concurrency.cancel-in-progress` caps cost at one
extraction at a time. Set monthly budget caps on `GOOGLE_API_KEY` and
`ANTHROPIC_API_KEY` in their respective dashboards as belt-and-suspenders.

Required repo secrets: `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`. The default
`GITHUB_TOKEN` (auto-provisioned with `contents: write` and
`pull-requests: write`) is enough to push the branch and open the PR.

Required repo settings: Settings → Actions → General →
- Workflow permissions: **Read and write permissions**
- **Allow GitHub Actions to create and approve pull requests: ENABLED**

GitHub bundles create + approve into a single toggle. The defense against
the bot self-approving its own PRs is branch protection: Settings →
Branches → main → require pull request review before merging, with at
least 1 approval. The bot can open a PR but cannot merge it.

## Future

The v4 path is auto-merge for trivially-confident updates: when an
auto-PR's eval F1 is at or above the prior baseline AND the row diff vs
prior `reviewed.json` is below a threshold, allow the bot to mark itself
mergeable after a quiet period. Out of scope today; humans always review.
