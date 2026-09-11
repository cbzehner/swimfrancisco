# Pool Schedule Extraction

The schedule extractor is a local `uv`-managed Python CLI under
`schedule-tools/`. It fetches direct sources once, asks OpenAI to extract SF
Rec & Park schedule PDFs, and writes review reports without changing
`content/spots/*.md`.

Dated evidence and past decisions live in
[`schedules-decision-log.md`](schedules-decision-log.md). This file is the
runbook.

## Setup

Use `uv` for package management in the extractor project:

```sh
just sync
```

Copy the root `.env.example` to root `.env`, then fill in the provider key:

```sh
cp .env.example .env
```

```sh
OPENAI_API_KEY=...
```

OpenAI is the only provider. CI stores `OPENAI_API_KEY` as an Actions secret.
Local extract is optional and is not required for sequential FLAG ingest. Do
not commit the key.

The repo uses `devenv`'s built-in dotenv integration, so a `devenv shell`
autoloads root `.env`:

```nix
dotenv.enable = true;
dotenv.filename = [ ".env" ];
```

If you use `direnv`, run `direnv allow` once after pulling the `.envrc` change.
After editing `.env`, run `direnv reload` or start a fresh `devenv shell`.

## Usage

Run all provider-independent direct sources once:

```sh
just schedules-extract --direct
```

Run the PDF sources through the provider:

```sh
just schedules-extract --provider openai
```

Use `--only slug1,slug2` with either mode. A slug outside the selected source
group is rejected rather than silently skipped. `--force` re-fetches sources
and bypasses the unchanged shortcut.

Useful flags on `extract`:

- exactly one of `--direct` or `--provider openai`
- `--only slug1,slug2`
- `--force`
- `--no-discover` to reuse the last discovery decisions instead of rediscovering
- `--url` to fetch one PDF URL for a single `--only` slug without rewriting the
  registry

`extract` never writes `content/spots/*.md` or `reviewed.json` — those
only change through `schedules review`. The pipeline produces direct or
provider artifacts under `data/<slug>/<date>-<sha12>/` and writes one fixed
report per pass: `tmp/extraction-report-direct.md` or
`tmp/extraction-report-openai.md`. Each report labels the run `success` or
`partial success`, includes the failure count, and retains failed pool
identities and complete errors. The operator approves changes by hand.

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
  source.pdf                   # original bytes; committed
  source.sha256                # hash of the snapshot
  openai-<model>.json          # self-describing provider output; dots in the
                               # model ID become dashes in the filename
  reviewed.json                # present ⇔ attested (`human`, `ci`, or omitted)
```

Source bodies (`source.pdf`, `source.html`, `source.xlsx`, `source.csv`) are
committed with the extraction artifacts. They are the backtest corpus: a
fresh clone can re-run extraction and compare against the original bytes.
`source.sha256` is the integrity check. For HTML, the hash may be a
semantic fingerprint of extracted hours rather than the raw file; for Koret
workbooks it is the zip-content hash of `source.xlsx`.

Koret is workbook-backed: `source.xlsx` is the canonical hashed source and
`source.pdf` is the full-workbook visual export used by the reviewer. The XLSX
preserves visible sheet names, merged ranges, and cell values; every visible
sheet must be classified by the extractor or extraction fails.

Review status is a filesystem predicate: `reviewed.json` present ⇒ attested;
absent ⇒ not published. `--force` bypasses this fast-path.

When a new capture extracts a payload identical to the pool's most recent
attested one, the pipeline carries the attestation forward: it writes
`reviewed.json` into the new capture dir with the original `reviewed_at`
and a `carried_from` field pointing at the prior snapshot. A prior attestor
already signed this exact payload; only the source bytes churned.
Direct extractors stamp `payload.effective_start` with the fetch date, so
that one clock-derived field is ignored in the comparison; for PDF pools
the whole payload must match. A new Rec & Park unique-grid SHA, and a
date-disjoint sequential sitting, is attested by `schedules publish-pending`
(`attested_by: ci`) when the auto-publish gates pass. FLAG URL choice
(Garfield band-only), sequential grounding repair, and a re-queued bad
auto-publish still use `just schedules-review`.

1. Run `just schedules-extract --direct` and, when needed, the PDF provider mode.
2. Read the report for the selected pass under `tmp/extraction-report-<mode>.md`.
3. Review `git diff content/spots/`.
4. For any pool with `review_note[...]` lines, inspect the provider
   output under `data/<slug>/<fetch-date>-<sha12>/`.
5. Run `just schedules-review` to open the local review site. Select each
   pending pool, compare its source with the structured rows, then choose
   **Save & next pool**. The site validates the result, projects it into
   `content/spots/<slug>.md`, and leaves `reviewed.json` on disk.
6. Spot-check flagged pools against the source PDF before accepting a
   content diff.
7. Run `just release`. If the reviewed schedule fingerprint changed, the
   visible bulletin number bumps automatically.
8. Commit `content/spots/`, `data/bulletin.json`, the registry change if
   the PDF URL moved, and the per-review directory (`source.pdf` /
   `source.html` / `source.xlsx` / `source.csv`, `source.sha256`, provider
   JSON, `reviewed.json`) once the diff looks trustworthy.

A new unique Rec & Park session-grid PDF auto-publishes when
`publish-pending` gates pass. Date-disjoint sequential windows
(Sava, MLK, Balboa) ingest in the same CI sitting. Identical payloads
still carry the prior attestation. FLAG URL choice (unsupported splits,
band-only grids) stays operator work. Do not `--adopt` one sequential
window; that is the 10-day trap.

Each `openai-<model>.json` is self-describing: it carries `prompt_sha256`,
`schema_sha256`, `source_pdf_url`, `pdf_sha256`, and `extracted_at`.
Extraction skips when the cached file's hashes match the current prompt and
schema; an edit to either re-triggers the model.

`reviewed.json` payloads pass through the same validation and grounding
that provider output does. Grounding and schema are filters, not proof a
cell was read correctly.

## Retention

Per slug, keep a snapshot dir if ANY of: (a) it is the newest dir containing
`reviewed.json`; (b) it contains provider or direct JSON but no `reviewed.json`
(pending review); (c) another dir's `reviewed.json` names it in `carried_from`;
(d) its source is a PDF (Rec & Park corpus used by backtests); (e) a file under
`tests/` or `docs/` names the dir. Everything else is deleted by
`schedules prune`, which `schedules automate` runs before every commit.

Run it by hand with `just schedules prune`.

## Registry Maintenance

The source registry lives at `schedule-tools/src/schedules/registry.toml`.

CI discovers Rec & Park `DocumentCenter` IDs daily from each pool's
`official_page_url`. `schedules discover` rewrites `pdf_url` to the
table-linked current `session_grid` (a unique table grid, or the current
window of a date-disjoint sequential set). Extract then fetches one href
per collapsed window. Discover never writes `content/spots/`.
`publish-pending` writes eligible unique grids, sequential sittings, and
unique table closure flyers. The live site updates when that PR merges.

Happy path is cron. `--adopt` remains Garfield band-only URL confirmation.
North Beach uses complete-pair discovery. Unique-grid and sequential payload
change does not:

- **Unique table `session_grid`.** CI auto-publishes after extract when
  gates pass. No `just schedules-review` on the happy path. Rossi
  `RossiPool_Fall*.pdf` is a session grid, not a closure flyer.
- **Sequential windows** (Sava Fall 1 + Fall 2, MLK `pt.1` / `pt.2`,
  Balboa interim + fall). Date-disjoint replacements, not Cool/Warm. CI
  extracts one href per window. `publish-pending` projects every
  unpublished window in one sitting, or none. `pdf_url` tracks the
  table-linked current file. Sibling IDs persist across `--adopt` and
  `max_id` jumps. Do **not** `--adopt` Fall 1 then extract that pointer
  locally. That ships one window and is the 10-day trap.
- **North Beach Cool/Warm pair.** Discover requires exactly one table-linked
  original for each physical pool, matching printed effective windows and
  weekday grids. It stores `pool_sources` instead of `pdf_url`. Missing,
  duplicate, conflicting, expired, or unsupported pairs remain blocked.
  Other split formats remain unsupported. A single part cannot be adopted
  as a complete facility schedule.
- **Band-only grid** (Garfield flyer + unlinked fall grid 29799).
  Discover never puts a flyer on `pdf_url`. CI `publish-pending`
  projects a unique table `closure_notice` as `temporarily_closed`. A
  lone off-table grid **auto-adopts** when it proves itself: its
  filename or page 1 names this pool and no other, page 1 carries a
  weekday grid header, its window parsed, it has not ended, and it starts
  after the pinned PDF's window. Extract and the unique-grid
  `publish-pending` gates then run as for a table grid. Anything weaker
  (no grid header, unparsed or overlapping window, two off-table grids)
  stays a blocking FLAG for:

  ```
  just schedules discover --adopt garfield-pool=29799
  ```

- **Facility page fetch failure.** A `fetch_error` decision writes
  nothing to `registry.toml`; persisted band IDs and sequential siblings
  survive the outage. The report says `registry: unchanged`.

`--adopt` of a `session_grid` writes `pdf_url` and sets
`source_status = published`. It persists remaining sibling `session_grid`
IDs. `--adopt` of a `split_part` writes `pdf_url` but does not publish.
`--url` fetches without rewriting the registry. CI never passes `--url`
or `--adopt`.

Leave `official_page_url` pointed at the facility page.

`just schedules discover-blocking` reports the FLAG decisions that currently
block auto-publish, and `just schedules pending-reviews` lists the capture
directories waiting on a human review.

## North Beach paired original PDFs

North Beach's supported pair contains one Cool and one Warm PDF, each linked
from the official facility page. Printed titles establish physical identity;
printed windows must match exactly. Discovery alone does not approve hours.
Each original independently passes the production extraction, schema,
source-cell completeness, dates, and closure checks. The fixed model remains
`gpt-5.5-2026-04-23`, medium reasoning.

Original captures retain `source.pdf`, `source.sha256`, and the configured
OpenAI artifact under their own full-byte identity. A separate capture contains
`source-bundle.json`, `openai-pool-bundle.json`, and, only after acceptance,
`reviewed.json`. Its `bundle_sha256` covers the ordered physical identities,
original URLs, full byte hashes, and full extraction configurations. Bundle
envelopes use `bundle_sha256` and `source_bundle`; single-document envelopes
retain their actual `pdf_sha256` and `source_pdf_url`.

The publisher reopens and verifies both originals and compares the bundle with
fresh discovery and registry membership. It writes one combined dated schedule
and one attestation, or restores both on failure. Component captures cannot
publish individually or carry forward a facility attestation. Review shows both
original PDFs beside one combined candidate. Unresolved closure notices remain
on the draft review-PR path.

Sessions retain `physical_pool` separately from the literal `pool_label_raw`
and normalized cell allocation `pool`, plus `source_sha256` and `source_cell`.
Thus identical times in Cool and Warm remain distinct. An explicit cell
cancellation supplies `excluded_dates` for that session; it does not broaden a
facility closure. Pool-specific closures affect only matching physical pools.
The board and Today list apply exclusions and partial closures in Pacific time;
weekly rows show the physical pool and excluded dates. Expired windows show CHECK.

Unchanged originals with matching configurations reuse their extraction without
model calls. One changed member reuses the other; the bundle is rebuilt and
reverified. A changed prompt, schema, implementation, model configuration, or
rendering dependency invalidates the relevant cache. Exclusion-date uniqueness
is enforced locally; the API transport uses the
[documented Structured Outputs subset](https://developers.openai.com/api/docs/guides/structured-outputs).

## Closure Contract (v2)

Closures without `physical_pool` in the extractor schema are **facility-wide**,
and all-day by default. Single-day closures may carry a partial-day time window
so recurring sub-day events (Aquatics Division Training on the 3rd Thursday of
each month, etc.) need not round up to a whole-day cancellation.

- Fields: `start`, `end`, `reason` (required); `start_time`, `end_time` (optional, both required together).
- Dates are ISO (`YYYY-MM-DD`) and inclusive. Times are 24-hour `HH:MM` and the window is half-open: `[start_time, end_time)`.
- Partial-day windows are only valid on single-day entries (`start == end`). For recurring patterns, expand to one entry per occurrence within the schedule's effective window.
- There is no `pool` field. North Beach paired documents may use `physical_pool` (`cool` or `warm`) for an explicitly scoped closure. Omitted means facility-wide.
- SFUSD and other timed school-only bookings are **not** closures; they are omitted from the output entirely.

The pre-v2 contract was all-day-only, which over-reported "Closed for staff training 11–2" cells as full-day closures. v2 was added in 2026-05; existing all-day closures keep working unchanged (the time fields are additive).

## Reviewing extracted schedules

FLAG URL adopt, sequential grounding repair, and a re-queued bad
auto-publish still use the local reviewer. Eligible unique grids and
successful sequential sittings do not join that queue. Start the local
reviewer with:

```
just schedules-review
```

The command binds to `127.0.0.1` on an available port and opens a browser. The
site scans `data/<slug>/` for review directories with provider JSON but no
`reviewed.json`, including FLAG captures that sit on `main`. Leftovers older
than a later reviewed capture stay hidden, as do band-only extracts whose View
ID is not the current `pdf_url` (Garfield 29799 until `--adopt`). Sequential
slugs list every unpublished kept window. The site then provides:

1. A pending-pool queue and source schedule beside the seeded structured data.
2. Add, edit, and remove controls for sessions, access hours, exceptions, and closures.
3. PDF page and zoom controls, a full-screen source view, and a persistent weekday review cursor.
4. A live source-identity check before editing; changed sources must be refreshed and re-extracted first.
5. An explicit source-cell attestation before save, followed by a second source check.
6. Schema and schedule validation followed by projection into `content/spots/<slug>.md`.

Sequential human repair is **Save-all**, not per-card Save. Confirm every
unpublished kept-window card, then one Save-all writes the edited
envelopes and projects both windows or none (`attested_by: human`; no
0.9 grounding floor). Per-card sequential confirm does not write
`reviewed.json` or `project()`. Saving one sequential window is the
10-day trap. Ordinary Save+project stays for Hamilton-class unique-grid
repair.

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

The eval reads existing per-review artifacts — no API calls. Quality baseline
is same-dir provider JSON vs a human Save or omitted `attested_by` (legacy).
CI-attested dirs, including carried CI attestations, are not same-dir truth
and are never scored CI vs CI. Copying an approval does not change its origin.
When the latest dir is `attested_by: ci`, eval may look
back to an older human envelope and list that pair in a **seasonal-delta**
table only. Seasonal-delta F1 is not the quality aggregate.

Run before and after any prompt or schema tweak as an observational check.
Do not gate on "require improvement" against a CI-attested fall grid.

## Autonomous extraction and publication

`schedules automate` runs the weekly hosted pipeline. It replaces the earlier
rolling-PR workflow: verified updates go straight to `main`, and unclear
closure notices get a separate draft review PR.

The schedule is Monday at 16:00 UTC (09:00 Pacific daylight time, 08:00 standard
time). Weekly discovery checks for upcoming schedules before the current window
ends. A late change can take up to seven days to appear; manual runs remain
available. Manual runs default to `extract-only`. Both modes require
`SCHEDULES_AUTOMATION_ENABLED=true`; unset means disabled.

Keep the $1 per-run limit within the $5 monthly ceiling. Scheduled runs, trials,
and manual reruns share the same monthly allowance; a new run does not reset it.
Unchanged source/configuration pairs reuse cached extraction
without model calls. Failed or interrupted requests can retain their maximum
reservation, so the accounting total can exceed the eventual API invoice.

### Run contract

1. Reserve at most $1 from the approved UTC calendar-month allowance on the
   separate `schedule-budget` accounting branch. Missing accounting stops the
   run. The local request ledger reserves worst-case cost before each API call.
2. Fetch current main into an isolated worktree. Discover once, run structured
   sources, then run the pinned OpenAI provider without a second discovery.
   Cache reuse requires matching source bytes and the full extraction configuration.
3. In `extract-only` mode, retain evidence and stop without projecting content,
   committing, or pushing a candidate. Accounting updates still occur.
4. In `publish` mode, independently verify source sessions, dates, and closures.
   Hold unclear pools and retain prior valid data; never extend expired hours.
   Non-production PDF artifacts cannot use the old percentage-based grounding
   check to obtain automatic approval. Human review remains an explicit repair path.
5. Validate the generated-file allowlist before staging and committing. Direct
   source changes to capture time and clock-derived start alone do not create
   content commits. PDF dates remain substantive facts.
6. Push one generated commit to `auto/schedules/<run>-<attempt>-<build>`, wait for
   its exact successful CI run, and fast-forward main only if its head still
   matches the recorded base. No PR and no force push. If main moves, rebuild
   once in a new worktree. Reuse only source/extraction cache files, not previous
   publication decisions or concurrently edited files.
7. Verify the deployed commit, all canonical spot records, live conditions, and
   all pool pages in WebKit and Chromium. The browser checks use a non-Pacific
   visitor timezone, check Today rows and weekly windows, and require map tiles
   to load. A watermark does not fail the map check. Stop after twenty minutes
   if deployment cannot be verified. Only then report a live publication.
8. Settle valid request charges. Canceled runs and missing usage retain their
   reservations; malformed accounting blocks further paid execution.

The content-writing job cannot write issues. A separate read-only-evidence job
updates one operator issue when failures or held pools change. It closes that
issue after a clean run. Repeated identical failures do not create new issues
or comments. A pushed commit without a verified deployment is not a success.

### Closure review PRs

An unclear PDF closure stops that pool before a paid model call when possible.
The extraction report preserves the source hash, notice text, and unresolved
checks even when no model artifact exists. Closure-flyer source mismatches also
enter the review queue. Verified updates for other pools still use checked
direct-main publication.

A separate job (`schedules closure-prs --evidence <dir>`) opens a draft PR on
`review/closures/<pool>-<PDF hash prefix>`. Its generated diff contains only the
source PDF and `closure-review.md`, never guessed closure hours, a CI
attestation, or projected content. The PR includes the source evidence and a
checklist for a human correction. It never auto-merges. Merging the evidence
note alone does not resolve a closure or approve hours.

The full PDF hash is checked before any write. An existing open, closed, or
merged PR for the same pool/source is reused rather than reopened. New PDF bytes
create a new review. Existing review branches without a PR are preserved for
operator recovery; automation does not force-push over reviewer edits. Close an
unresolvable PR with a reason, or add a corrected human-reviewed snapshot and
content changes before merging. Other failures remain in the operator issue.

Extraction-only trials do not open PRs. The PR job has no OpenAI key and cannot
make extraction calls. Its separate GitHub token needs Pull requests read/write
as well as Contents read/write. PR receipts are retained with the run evidence.

### Enablement checklist

Budget approval and accounting setup are complete. Keep these requirements
in place for enabled runs:

- `SCHEDULES_MONTHLY_BUDGET_USD=5` is configured in GitHub, matching the
  recurring ceiling. `SCHEDULES_MONTHLY_BUDGET_OVERRIDES` carries explicit
  single-month approvals; an operator applies the matching durable amendment
  with `schedules budget increase`. A changed variable alone never changes the
  ledger.
- Store `OPENAI_API_KEY` and a repository-scoped `SCHEDULES_BOT_TOKEN` as Actions
  secrets. The publication token needs Contents read/write and must trigger CI;
  the built-in Actions token is not its publication fallback. The workflow uses
  the built-in token only for read-only CI lookups.
- Store `CLOUDFLARE_BROWSER_API_TOKEN` as a secret and `CLOUDFLARE_ACCOUNT_ID`
  as a repository variable for the blocked-HTML browser captures.
- Keep main's required `check` status, strict updates, administrator enforcement,
  and no force pushes. Permit the publication token to create closure-review PRs;
  auto-merge is not used.
- Accounting was initialized on 2026-09-06 with `schedules budget initialize`.
  Do not initialize it again. Missing accounting in later runs must be repaired,
  not reset.
- Set `SCHEDULES_AUTOMATION_ENABLED=true`, dispatch an `extract-only` trial, inspect
  its evidence and charges, then run a checked publication trial. Confirm hosted
  CI, main promotion, and the exact live deployment before declaring autonomy.

### Evidence and recovery

Each run retains `tmp/automation/result.json`, per-build discovery and publication
reports, source PDFs, provider artifacts, accepted snapshots, request/response
files under `api-budget/api-attempts/`, browser-capture evidence, and sanitized
budget ledgers as a GitHub artifact for 90 days. The receipt records base and
candidate commits, changed paths, CI URL, outcomes, and confirmed live updates.
Run artifacts exclude credentials and raw transport logs.

Set `SCHEDULES_AUTOMATION_ENABLED=false` to stop future runs. This does not cancel
a run already started: cancel that run separately when needed. Its full spend
reservation remains conservative. `SCHEDULES_AUTO_PROJECT=false` also rejects
local publication mode.

For incorrect published data, keep automation disabled, inspect the retained
source and receipt, and prepare a scoped corrective commit. Quarantine each
incorrect PDF SHA so a later run cannot automatically accept it again. Use
`just schedules-review` for explicit human correction; save all related
sequential windows together. Test and verify the corrective deployment before
enabling automation again. Do not reset main or erase accounting to recover.

Past trial runs, their spend, and the source exceptions they exposed are in
[`schedules-decision-log.md`](schedules-decision-log.md).

## Future

Semantic XLSX fingerprinting remains separate work. This workflow uses existing
source-byte identity and does not introduce semantic identity or canonicalization.

Open source follow-ups (Chinatown, Stonestown, Koret, 24 Hour Fitness, and the
reuse rule for the approved Sava and Balboa reviews) are tracked under
**Deferred schedule work** in
[`schedules-decision-log.md`](schedules-decision-log.md).
