# Pool Schedule Extraction

The schedule extractor is a local `uv`-managed Python CLI under `schedule-tools/`. It fetches direct sources once, asks an LLM provider to extract SF Rec & Park schedule PDFs, and writes review reports without changing `content/spots/*.md`.

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

CI already has `GOOGLE_API_KEY`. Local extract is optional and is not
required for sequential FLAG ingest. For a local Gemini pass, copy the
1Password item "Gemini API Key" into root `.env`. Do not commit it.

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

Run all provider-independent direct sources once:

```sh
just schedules-extract --direct
```

Run the PDF sources with one provider:

```sh
just schedules-extract --provider gemini
just schedules-extract --provider anthropic
```

Use `--only slug1,slug2` with either mode. A slug outside the selected source
group is rejected rather than silently skipped. `--force` re-fetches sources
and bypasses the unchanged shortcut.

Run a provider bakeoff on a flagged pool:

```sh
just schedules debug bakeoff --provider gemini --compare-with anthropic --only hamilton-pool --force
```

Useful flags on `extract`:

- exactly one of `--direct` or `--provider anthropic|gemini`
- `--only slug1,slug2`
- `--force`

`extract` never writes `content/spots/*.md` or `reviewed.json` — those
only change through `schedules review`. The pipeline produces direct or
provider artifacts under `data/<slug>/<date>-<sha12>/` and writes one fixed
report per pass: `tmp/extraction-report-direct.md`,
`tmp/extraction-report-gemini.md`, or `tmp/extraction-report-anthropic.md`.
Each report labels the run `success` or `partial success`, includes the failure
count, and retains failed pool identities and complete errors. The operator
approves changes by hand. `schedules debug bakeoff` is observational only.

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
  gemini-<model>.json          # self-describing provider output
  anthropic-<model>.json
  reviewed.json                # present ⇔ attested (`human`, `ci`, or omitted)
```

Source bodies (`source.pdf`, `source.html`, `source.xlsx`, `source.csv`) are
committed with the extraction artifacts. They are the backtest corpus: a
fresh clone can re-run extractors and compare models against the original
bytes. `source.sha256` is the integrity check. For HTML, the hash may be a
semantic fingerprint of extracted hours rather than the raw file; for Koret
workbooks it is the zip-content hash of `source.xlsx`.

Koret is workbook-backed: `source.xlsx` is the canonical hashed source and
`source.pdf` is the full-workbook visual export used by the reviewer. The XLSX
preserves visible sheet names, merged ranges, and cell values; every visible
sheet must be classified by the extractor or extraction fails.

Review status is a filesystem predicate: `reviewed.json` present ⇒ attested;
absent ⇒ not published. `--force` and `--compare-with` bypass this
fast-path.

When a new capture extracts a payload identical to the pool's most recent
attested one, the pipeline carries the attestation forward: it writes
`reviewed.json` into the new capture dir with the original `reviewed_at`
and a `carried_from` field pointing at the prior snapshot. A prior attestor
already signed this exact payload; only the source bytes churned.
Direct extractors stamp `payload.effective_start` with the fetch date, so
that one clock-derived field is ignored in the comparison; for PDF pools
the whole payload must match. A new Rec & Park unique-grid SHA, and a date-disjoint sequential
sitting, is attested by `schedules publish-pending` (`attested_by: ci`)
when the auto-publish gates pass. FLAG URL choice (Garfield band-only,
North Beach Cool/Warm), sequential grounding repair, and a re-queued
bad auto-publish still use `just schedules-review`.

1. Run `just schedules-extract --direct` and, when needed, one or both PDF provider modes.
2. Read the report for the selected pass under `tmp/extraction-report-<mode>.md`.
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
   the PDF URL moved, and the per-review directory (`source.pdf` /
   `source.html` / `source.xlsx` / `source.csv`, `source.sha256`, provider
   JSONs, `reviewed.json`) once the diff looks trustworthy.

A new unique Rec & Park session-grid PDF auto-publishes when
`publish-pending` gates pass. Date-disjoint sequential windows
(Sava, MLK, Balboa) ingest in the same CI sitting. Identical payloads
still carry the prior attestation. FLAG URL choice (Cool/Warm splits,
band-only grids) stays operator work. Do not `--adopt` one sequential
window; that is the 10-day trap.

Each `<provider>-<model>.json` is self-describing: it carries
`prompt_sha256`, `schema_sha256`, `source_pdf_url`, `pdf_sha256`, and
`extracted_at`. Extraction skips when the cached file's hashes match the
current prompt and schema; an edit to either re-triggers the LLM.

`reviewed.json` payloads pass through the same validation and grounding
that provider output does. Grounding and schema are filters, not proof a
cell was read correctly.

## Registry Maintenance

The source registry lives at `schedule-tools/src/schedules/registry.toml`.

CI discovers Rec & Park `DocumentCenter` IDs daily from each pool's
`official_page_url`. `schedules discover` rewrites `pdf_url` to the
table-linked current `session_grid` (a unique table grid, or the current
window of a date-disjoint sequential set). Extract then fetches one href
per collapsed window. Discover never writes `content/spots/`.
`publish-pending` writes eligible unique grids, sequential sittings, and
unique table closure flyers. The live site updates when that PR merges.

Happy path is cron. `--adopt` remains Garfield band-only URL confirmation
and North Beach split confirmation. Unique-grid and sequential payload
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
- **Split PDFs** (North Beach Cool + Warm only). Discover flags and sets
  `missing_current_schedule`. Do not pick a part. Extract stays skipped.
  Discover never auto-promotes `missing_current_schedule` to `published`.
  Only an operator `--adopt` of a classified `session_grid` (a later
  combined whole-pool PDF) publishes. `--adopt` of a `split_part` writes
  `pdf_url` but does not publish.
- **Band-only grid** (Garfield flyer + unlinked fall grid 29799).
  Discover never puts a flyer on `pdf_url`. CI `publish-pending`
  projects a unique table `closure_notice` as `temporarily_closed`. CI
  may extract 29799 while FLAG so the operator does not need a Gemini
  laptop after `--adopt`. Human Save of 29799 is **not** URL
  confirmation. `--adopt` is:

  ```
  just schedules discover --adopt garfield-pool=29799
  ```

  Commit `registry.toml` on the rolling PR, or wait for the next cron.
  Next CI: unchanged on 29799; unique-grid publishes the fall window
  beside the closure.

`--adopt` of a `session_grid` writes `pdf_url` and sets
`source_status = published`. It persists remaining sibling `session_grid`
IDs. `--adopt` of a `split_part` writes `pdf_url` but does not publish.
`--url` fetches without rewriting the registry. CI never passes `--url`
or `--adopt`.

Leave `official_page_url` pointed at the facility page.

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

FLAG URL adopt, sequential grounding repair, and a re-queued bad
auto-publish still use the local reviewer. Eligible unique grids and
successful sequential sittings do not join that queue. Start the local
reviewer with:

```
just schedules-review
```

The command binds to `127.0.0.1` on an available port and opens a browser. The
site scans `data/<slug>/` for review directories with provider JSON but no
`reviewed.json`. After the review-queue cut-over, FLAG captures that sit
on `main` appear without a git-changed-dir gate. May leftovers older than
a later reviewed capture stay hidden. Band-only extracts whose View ID is
not the current `pdf_url` (Garfield 29799 until `--adopt`) stay hidden.
Sequential slugs list every unpublished kept window. The site then
provides:

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
CI-attested dirs are not same-dir truth and are never scored CI vs CI. When
the latest dir is `attested_by: ci` with no `carried_from`, eval may look
back to an older human envelope and list that pair in a **seasonal-delta**
table only. Seasonal-delta F1 is not the quality aggregate.

Run before and after any prompt or schema tweak as an observational check.
Do not gate on "require improvement" against a CI-attested fall grid.

## Auto-extract workflow

The `.github/workflows/schedules-extract.yml` action runs weekly on
Mondays at 09:00 PT and on `workflow_dispatch`. It discovers Rec & Park PDF URLs
first (`schedules discover` writes `registry.toml`), then runs direct
extraction once, then processes the PDF sources once with Gemini
(`extract --provider gemini --no-discover`). There is no weekly Anthropic
step; bakeoff stays local (`schedules debug bakeoff`). Each pass has a
distinct report; the run summary and uploaded
`schedule-extraction-reports` artifact retain all reports that were produced,
including `tmp/discovery-report.md` and partial-success failure details.
Provider artifacts under `data/<slug>/<date>-<sha12>/` get written, and
the pipeline carries attestation forward (writes `reviewed.json` with
`carried_from`) for pools whose payload matches the last attested one.
`schedules publish-pending` then attests eligible unique Rec & Park grids
and date-disjoint sequential sittings (`attested_by: ci`) and projects
`content/spots/`. Sequential extract fetches one href per collapsed
window; the workflow does not pass `--url` or `--adopt`. The live site
updates when that PR merges.

If `data/`, `registry.toml`, `content/spots/`, or `quarantine.toml`
changed, the action commits to the rolling `auto/schedules-extract`
branch and opens or refreshes its PR. Scheduled extract refreshes that PR;
closing it without merging reopens on the next run that still sees a
diff against `main`. Auto-merge keys on `publish-pending` exit 0. FLAG
notes do not hostage unique-grid pools. Kill switch:
`SCHEDULES_AUTO_PROJECT=false` (or `workflow_dispatch` `auto_project=false`)
skips publish-pending and leaves the PR open with `needs-schedule-review`.

Operator signal for FLAG and unique-grid/closure/sequential refuses is
the rolling GitHub issue `schedules flagged`, not a merge veto.
Successful auto-publish comments `schedules published`. After this slice
the `schedules flagged` set is: Rossi leaves on unique-grid publish;
Sava leaves if both windows pass; MLK and Balboa stay on
`sequential_partial` (`grounding_coverage_low`) until human Save-all of
both windows or `--force` re-extract; Garfield stays until `--adopt`
29799 then unique-grid; North Beach stays until a combined PDF.

Before checkout, the workflow requires `SCHEDULES_BOT_TOKEN`. Provision a
repository-scoped fine-grained PAT limited to `cbzehner/swimfrancisco` with
Contents read/write and Pull requests read/write permissions, then store it as
that exact Actions secret. The workflow fails with guidance and does not
publish when it is absent; it never falls back to `github.token`,
`GITHUB_TOKEN`, or another credential. The PAT should expire within 90 days
and be rotated through the same Operator-supervised account-settings flow.
The other prerequisites are the repo setting "Allow auto-merge" and a branch
protection rule on `main` requiring the `check` status.

To provision `SCHEDULES_BOT_TOKEN`:

1. In GitHub account settings, create a fine-grained PAT owned by `cbzehner`,
   limited to `cbzehner/swimfrancisco`, with only Contents and Pull requests
   read/write permissions and an expiration no later than 90 days.
2. Store it as the repository Actions secret named `SCHEDULES_BOT_TOKEN`.
   Do not paste the token into chat, commit it, or put it in shell history.
3. Confirm the secret exists by name and update time. GitHub does not expose
   the stored value. Do not reuse a broad GitHub CLI OAuth token for Actions
   publication.

Happy-path unique grids and sequential windows auto-merge. Reviewer flow
is debug / FLAG / sequential grounding repair:

```
git fetch origin && git checkout auto/schedules-extract
just schedules-review          # Save-all sequential cards, or FLAG adopt
just release                   # bulletin only if reviewed payloads changed
git add content/spots data schedule-tools/src/schedules/registry.toml
git commit -m "review Rec & Park schedules"
# merge this PR; do not open a second one
```

If the queue is empty, `schedules-review` prints `nothing to review`.
That is expected after CI attested unique-grid or sequential dirs. Do
not `--adopt` a sequential Fall 1 to fill the queue. Garfield 29799 stays
hidden until `--adopt`. After the review-queue cut-over, FLAG captures
on `main` (Balboa / MLK `sequential_partial`) appear without a
git-changed-dir gate.

### Repair sitting

The review UI will not open an already-attested dir.

1. Kill switch: `SCHEDULES_AUTO_PROJECT=false`.
2. Dashboard tourniquet if the live board is wrong right now.
3. Prefer a per-pool content revert (delete that `[[extra.schedules]]`
   table; leave `reviewed.json`) so the next cron does not republish.
   A squash revert of `data/` requires a `[[quarantine]]` row for that
   `pdf_sha256` in the same sitting. A sequential sitting needs a row
   for **each** shipped SHA.
4. Confirm candidate state: `schedules pending-reviews` lists the slug
   **only if** `reviewed.json` is gone.
5. Human Save of a corrected payload (`attested_by: human`) overrides
   quarantine. Sequential repair is Save-all of every unpublished kept
   window, minus the 0.9 grounding floor (Balboa 0.61 / MLK 0.11). Do
   not Save one sequential window. `publish-pending` still refuses the
   sha until the row is deleted.
6. Clear the kill switch after `main` has the revert (and quarantine
   row, if required).

Public-repo safety: the workflow has no `pull_request` or
`pull_request_target` triggers, only `schedule` and `workflow_dispatch`.
Forks cannot run it. `concurrency.cancel-in-progress` caps cost at one
extraction at a time.

Required repo secrets: `GOOGLE_API_KEY` and the CI-capable
`SCHEDULES_BOT_TOKEN` described above. `ANTHROPIC_API_KEY` is a local
bakeoff secret, not a CI requirement. Set monthly budget caps on
`GOOGLE_API_KEY` and, when used locally, `ANTHROPIC_API_KEY`.

Required repo settings: Settings → Actions → General →
- Workflow permissions: **Read and write permissions**
- **Allow GitHub Actions to create and approve pull requests: ENABLED**

GitHub bundles create + approve into a single toggle. Do not require
reviews on `main`: the publication token opens PRs as the Operator, so a
required approval would deadlock quiet-week auto-merge. The merge gate is
the required `check` status, enforced for administrators. The bot can
open a PR; it cannot land on `main` until CI is green.

## Future

Semantic XLSX fingerprinting remains a separate provenance-design follow-up.
This workflow continues to use the existing source-byte identity and does not
implement canonicalization or semantic identity.

Unique Rec & Park table grids and date-disjoint sequential windows
already auto-publish via `publish-pending`. Remaining later work is
split-PDF extract (North Beach Cool/Warm), not a second human gate on
unique grids or sequential sittings.
