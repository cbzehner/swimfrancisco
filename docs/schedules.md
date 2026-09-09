# Pool Schedule Extraction

The schedule extractor is a local `uv`-managed Python CLI under `schedule-tools/`. It fetches direct sources once, asks an LLM provider to extract SF Rec & Park schedule PDFs, and writes review reports without changing `content/spots/*.md`.

## Closure coverage and Pomeroy automation

The September 7 approved extension adds explicit session-cell cancellations to
single-document schedules, inherited-month holiday syntax, and isolated
maintenance footers. Independent checks still reject ambiguous pool allocation,
unknown programs, missing clock markers, conflicting recurrence/date lists, and
unclear training duration. Resolving a closure parser error does not guarantee
that the entire document qualifies for publication.

Closure normalization derives a stable `reason_code` and original
`source_notices` from independently parsed source evidence. It retains the model's
`reason` separately. The renderer translates the code, so spelling differences
in model reasons cannot block an otherwise verified schedule. North Beach bundle
closures retain both original notice hashes and must agree on meaning and scope.
Forty-five existing reviewed snapshots received codes through a one-time exact
catalog migration. Removing those added codes reproduces their prior reviewed
facts; this migration does not claim new source verification. Historical paid
provider responses remain unchanged. Projection now requires codes; it does not
silently translate unknown raw reasons through a second publication path.

New direct-source artifacts store `details.direct_source`, copied into the
reviewed envelope as `direct_source`: full original-byte `sha256`, requested and
final URLs, Pacific `observed_on`, parser/schema and Python/library configuration, and the approved
14-day freshness lifetime. The existing envelope identity field `pdf_sha256`
also contains that exact byte hash for direct captures. Historical direct
payload/workbook-normalized hashes are retained as historical evidence, never
reinterpreted as byte hashes. No historical direct artifact qualifies for the
new automatic acceptance rule. Each new day's HTML observation retains its own
capture; same-day reuse requires matching bytes, configuration, and facts.

For an undated direct source, projected start/end dates mean observation validity,
not printed effective dates. They cover fourteen Pacific calendar dates,
inclusive. Failed fetching or parsing cannot renew that interval. The current
extraction report must identify the exact ready artifact before publication;
old pending candidates cannot substitute for a failed current extraction.
CI-reviewed city snapshots can refresh from a changed, current-configuration
production extraction only after that extraction succeeds in the current run.
Human and legacy reviews remain untouched. Carry-forward never overwrites an
existing review, and a failed multi-window update restores prior review bytes.

The registry explicitly opts in only Pomeroy's operator therapeutic-swim page.
Its independent inventory accounts for every table cell: the frozen original
contains sixteen lap/open sessions and six excluded Aquatic Exercise classes.
The verifier checks literal evidence, closures, and therapeutic restrictions.
Pomeroy remains limited-public, therapy-oriented, and slow-lap-only. Unfamiliar
source text holds the update. Other non-city sources remain manual, including
sources that only prove facility or pool-access hours.

HTTP handling now stops on permanent errors and retains bounded retries for
transient failures. Diagnostics include sanitized final URL/status and selected
headers; they exclude query strings, credentials, cookies, and response bodies.
The six hosted 403s have not yet been resolved. Local production-client HTTP 200
responses also exposed changed source semantics, so access recovery alone cannot
qualify those sources for publication.

Automation was paused after reading main `08e5c6c6231bf4b6945cac2be9f44bc0dac6209b`.
The cutover preserves the existing paid model and durable spending ledger. Shared
configuration changes invalidate extraction caches normally. Regression tests use
frozen originals and deterministic model mocks, never benchmark reference answers
as the production verifier. Hosted validation must use the existing accounted
workflow within $5/month and $1/run, followed by exact-commit CI, deployment, and
live browser verification before weekly operation resumes.

Local cutover validation passed `just check`: 1,154 Python tests (55 skips),
197 JavaScript tests, 35 WebKit/Chromium browser tests, localization, Worker type
checking, and the build. These checks made no model calls. The browser regressions
cover whole-session exclusions before/after narrower facility closures and
fourteen-day expiry at Pacific midnight in a Tokyo browser. Final publication
regressions also cover refreshing an existing verified window beside a future
window without treating it as a new, regressed schedule.

The first hosted cutover trial ([34189395735](https://github.com/cbzehner/swimfrancisco/actions/runs/34189395735))
completed five paid requests under the unchanged production configuration, costing
$0.553410. The durable September ledger settled that amount: $0.998910 total,
$4.001090 remaining. The run retained original PDFs, model responses, independent
verification results, candidate outputs, and request receipts in its workflow
artifact. Hamilton, current MLK, Mission, both North Beach components, and Pomeroy
passed candidate acceptance. Candidate `69431b7b26d96fecb799c00ec64eb733581a9269`
failed CI because a site-render test still required literal closure reasons in the
translation catalog. Main did not advance. The test now checks verified closure
codes and translations in every locale, including the trial's previously unseen
literal wording. Five paid provider artifacts were independently reverified and
retained in their original source directories for a cache-only retry; candidate
reviews and projected hours were not manually copied into main. Deployment of
code commit `e9fb9b5ae76f331ac86cc50accb326567fa28574` passed exact-commit browser
smoke checks for all thirty spots. Weekly automation stayed paused through the
publication retry and live schedule checks.

A detached replay of the actual candidate with the corrected translation test
passed `just check`: 1,168 Python tests (55 skips), 197 JavaScript tests,
35 browser tests, localization, Worker types, and build. It made no model calls.

The follow-up main checkout passed `just check`: 1,162 Python tests (55 skips),
197 JavaScript tests, 35 browser tests, localization, Worker types, and build.
Independent re-verification of all five retained provider artifacts passed
source coverage, date-window, closure, and exclusion checks without model calls.

The trial charged Hamilton $0.130305, current MLK $0.108015, Mission $0.099710,
North Beach Cool $0.099795, and North Beach Warm $0.115585. Original full byte
hashes and extraction configurations remain in the corresponding source and
provider artifacts listed by the run's `ready_openai` receipt.

Remaining trial holds were four ambiguous closure inputs (Balboa, Coffman, and
two Sava windows), plus Garfield pool allocation, Rossi's missing end meridiem,
and unknown programs in MLK's later window. Five hosted HTTP 403s carried
Cloudflare challenge headers (JCCSF and four YMCA sources); SFSU returned a
Pantheon 403. Equinox fetched successfully but its changed “Indoor Saline Lap
Pool” wording failed the existing parser. These sources did not gain automatic
publication authority. Pomeroy's stale pending-artifact refusal was corrected:
a valid current artifact supersedes an older pending artifact, while missing
current readiness still holds publication.

The accounted retry ([34191084886](https://github.com/cbzehner/swimfrancisco/actions/runs/34191084886))
published Hamilton, current MLK, Mission, North Beach, and Pomeroy at commit
`66890c8ebe738f71be48a4a3d95f455adb92f13b`. Its request receipt is empty: zero model
calls and $0 charged, settled on the existing ledger. Candidate CI
[34191245437](https://github.com/cbzehner/swimfrancisco/actions/runs/34191245437)
and main CI [34191540855](https://github.com/cbzehner/swimfrancisco/actions/runs/34191540855)
passed; final CI ran 1,174 Python tests (55 skips), 197 JavaScript tests, and
35 browser tests. Cloudflare deployed that exact commit. The required
`smoke-production.mjs --expected-commit=66890c8ebe738f71be48a4a3d95f455adb92f13b --browser`
passed all thirty spots, both in the hosted workflow and locally.

An additional 52 live WebKit/Chromium scenarios used Tokyo visitor clocks and
expectations transcribed from original sources: twenty North Beach cases covered
both pools, September 1–December 12 dates, simultaneous sessions, exclusions,
maintenance, partial closures, expiry, Pacific midnight and standard time; eight
Pomeroy cases covered therapy restrictions, excluded classes, and September 7–20
observation validity; twenty-four Hamilton/Mission/MLK cases checked session
cancellations separately from narrower facility closures and ordinary-day
controls. All passed. The workflow artifact retains original source/configuration
identities, publication decisions, live verification, and spend receipts. The
closure-review job also succeeded. Equinox parsed on the retry but remains manual;
six hosted 403s and the seven city input holds above remain. Weekly Monday
16:00 UTC automation was restored only after these checks. The $5 monthly limit,
$1 run reservation, unchanged production model, and durable ledger remain intact.

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
when the auto-publish gates pass. FLAG URL choice (Garfield band-only), sequential grounding repair, and a re-queued
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
still carry the prior attestation. FLAG URL choice (unsupported splits,
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

## North Beach paired original PDFs

North Beach's supported pair contains one Cool and one Warm PDF, each linked
from the official facility page. Printed titles establish physical identity;
printed windows must match exactly. Discovery alone does not approve hours.
Each original independently passes the production extraction, schema, source-cell
completeness, dates, and closure checks. The fixed model remains
`gpt-5.5-2026-04-23`, medium reasoning.

Original captures retain `source.pdf`, `source.sha256`, and the configured OpenAI
artifact under their own full-byte identity. A separate capture contains
`source-bundle.json`, `openai-pool-bundle.json`, and, only after acceptance,
`reviewed.json`. Its `bundle_sha256` covers the ordered physical identities,
original URLs, full byte hashes, and full extraction configurations. Capture
paths locate evidence but do not change identity. Bundle envelopes use
`bundle_sha256` and `source_bundle`; single-document envelopes retain their
actual `pdf_sha256` and `source_pdf_url`. The bundle is never presented as a PDF.

The publisher reopens and verifies both originals and compares the bundle with
fresh discovery and registry membership. It writes one combined dated schedule
and one attestation, or restores both on failure. Component captures cannot
publish individually or carry forward a facility attestation. Review shows both
original PDFs beside one combined candidate and checks both current sources
before saving. Unresolved closure notices remain on the draft review-PR path.

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
rendering dependency invalidates the relevant cache. The prompt is trimmed
consistently when computing extraction configuration in both extraction and
publication. Exclusion-date uniqueness is enforced locally; the API transport
uses the [documented Structured Outputs subset](https://developers.openai.com/api/docs/guides/structured-outputs).
No benchmark answer is read by production verification.

### Paired-PDF validation evidence

The frozen fall originals are committed under `data/north-beach-pool/`:

- Cool, View 29953: `6c2b2e77fb2370a1aee52203c9d8672fc5e55ab398875a72f83156ac3b23397c`.
- Warm, View 29954: `ac196df42a14a71cd86fbb13972706e22b5e5cf8dcc5820f660d57882bfd25c8`.

Both one-page PDFs print September 1–December 12, 2026. Full-page Poppler
renders were visually checked. Separate deterministic test transcriptions
contain 15 Cool and 20 Warm allowed drop-in sessions. These are development
references, not attestations. Both documents cancel their respective Thursday
late-morning sessions on September 24 and October 22, in addition to the stated
facility-wide training window. Maintenance is October 13–31; holidays are
November 11 and November 26–27; December 12 training is 09:00–12:00.

Regression tests use mocked model results and the frozen original bytes. They
exercise independent omissions, identity/configuration changes, duplicate
sessions, simultaneous physical pools, exclusions, closures, cache reuse,
atomic publication failures, and date boundaries. Local `just check` passed:
1,073 Python tests (55 skipped), 194 JavaScript tests, 31 browser tests across
WebKit and Chromium, Worker type checking, localization checks, and the site
build. The final publication/cache/review-refresh checks passed all 96 tests.
These tests made zero model calls and spent $0.

After API authentication was restored, scheduled automation was paused. Exact
commit [CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34089753760)
passed with 1,074 Python tests, 55 skips, and the browser/build gates. Commit
`70fa4a71a87f7a80ce9965a022e3e5c42ed48db1` then reached main through a non-force
push, passed [main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34090150621),
and appeared in live build metadata.

The first [accounted trial](https://github.com/cbzehner/swimfrancisco/actions/runs/34090185656)
made two model requests, charged $0.113035 and $0.116405, and settled at
**$0.229440**. Both independent extractions and combined candidate publication
passed: 15 Cool and 20 Warm sessions, September 1–December 12, seven facility
closures, and both cell-specific exclusions. Bundle identity was
`e494dea3b5f825d3d9b27e2a24720ffa80971ba0c7bb0ea655f7221ccb7ee869`.

The run stopped before staging or main publication. Investigation exposed an
allowlist mismatch: it expected `openai-gpt-5.5-2026-04-23.json`, while the path
function writes `openai-gpt-5-5-2026-04-23.json`. That mismatch also excluded
component artifacts from retained evidence and stale-main cache reuse. The
rules now use the actual filename; a regression creates it through the
production path function and checks all three consumers. The failed run's
bundle and settled spend receipt are retained in its hosted artifact, but its
missing component artifacts must not be reconstructed or accepted as a cache.
The second [accounted trial](https://github.com/cbzehner/swimfrancisco/actions/runs/34091343343)
charged $0.099475 and $0.116585, settling at **$0.216060**. Total spend is
**$0.445500**. Both extractions and the combined candidate again passed. Its
complete component artifacts are retained and committed under the original
captures above, without a facility attestation or manual hours patch.

Local replay identified the generation failure: the localization catalog lacked
the returned maintenance, Veterans Day, and in-service training label variants.
The catalog now maps those literal strings to existing translations; unknown
labels still block publication. The generated-label allowlist also now matches
the actual `data/i18n/dynamic-labels.json` path. Replay uses the retained paid
artifacts, rechecks both original PDFs independently, then generates and stages
the full candidate without model calls. The next hosted trial can reuse these
unchanged, configuration-matched components. North Beach's live CHECK remains
until that trial publishes and deploys.

The full retained-data replay also exercises committed bundle byte integrity
and rendered pages. It exposed an unescaped apostrophe in the shared
`data-schedule` attribute. The template now HTML-escapes the JSON, preserving
literal source punctuation after the browser decodes the attribute. A render
regression checks apostrophes, quotes, ampersands, and angle brackets; the
browser verifier checks both original pools in the complete candidate.

The [cached publication trial](https://github.com/cbzehner/swimfrancisco/actions/runs/34092991204)
then passed all three jobs. It made **zero model requests**, reused both committed
component artifacts with matching full configurations, and published only
North Beach's swimming hours. The combined candidate
`1bbc755a54340eb82c3baf6083652bc02931150f` passed
[candidate CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34093141191),
reached main through non-force promotion, passed
[main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34093491591),
and deployed. The hosted receipt records `status=published` and
`published_slugs=["north-beach-pool"]`. Its budget receipt has an empty request
list and settled at $0. The full source/configuration identities, bundle,
attestation, and original component artifacts are committed under the captures
above. Other generated changes contain source captures and bulletin metadata,
not non-city schedule acceptance.

An additional local `node scripts/smoke-production.mjs
--expected-commit=1bbc755a54340eb82c3baf6083652bc02931150f --browser` passed all
30 canonical locations. Twenty live date scenarios (ten in each of WebKit and
Chromium, with the browser timezone set to Tokyo) checked both the board and
North Beach detail page: September 1 opening, September 24 cell exclusions and
simultaneous Cool/Warm sessions, October maintenance, November Pacific standard
time, Thanksgiving, December 12 reopening after the partial closure, December
13 expiry, and Pacific midnight rollover. Expiry shows CHECK on the board and
an unverified schedule on the detail page; it does not extend prior hours.
The independent visual transcription agrees with all 15 Cool and 20 Warm
program/day/time entries, exclusions, and seven closure entries. This comparison
is development evidence and is never an input to the production verifier.

Final candidate checks passed 1,079 Python tests (55 skipped), 195 JavaScript
tests, 31 browser tests, type checking, localization checks, and the build.
The durable ledger records **$0.445500 total** for the two paid trials and the
zero-call publication, leaving **$4.554500** of the approved $5 monthly ceiling.
The $1 per-run reservation remains unchanged. After verified success,
`SCHEDULES_AUTOMATION_ENABLED=true` was restored for Monday 16:00 UTC checks.
Ten unresolved city closure inputs remain on their existing review-PR path;
six direct sources still return hosted HTTP 403, and non-city publication
remains manual. New unsupported formats or unknown display labels still hold
publication; this result does not certify every pool as fully automated.

The cutover pauses scheduled automation before the shared-format commit reaches
main. Preserve the durable budget branch, $5 monthly/$1 run limits, generated
allowlist, stale-main protection, non-force promotion, and exact-commit CI.
Use controlled accounted hosted validation and restore weekly operation after
verified deployment and browser checks. A successful push is not live evidence.

## Closure Contract (v2)

Closures without `physical_pool` in the extractor schema are **facility-wide**. By default they are
all-day. Single-day closures may carry a partial-day time window so common
recurring sub-day events (Aquatics Division Training on the 3rd Thursday of
each month, etc.) don't have to round up to a whole-day cancellation.

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
CI-attested dirs, including carried CI attestations, are not same-dir truth
and are never scored CI vs CI. Copying an approval does not change its origin.
When the latest dir is `attested_by: ci`, eval may look
back to an older human envelope and list that pair in a **seasonal-delta**
table only. Seasonal-delta F1 is not the quality aggregate.

Run before and after any prompt or schema tweak as an observational check.
Do not gate on "require improvement" against a CI-attested fall grid.

### Checked PDF benchmark

`tests/fixtures/schedule-benchmark.json` holds source hashes and visual
transcriptions for North Beach summer, Hamilton fall, Balboa fall, and Balboa interim. These are
agent-checked development references, **not human attestations**. They contain
97 weekly sessions and four effective windows. They never replace
`reviewed.json`, and no publication command reads them. On 2026-09-06 the operator
confirmed the North Beach summer sample and the separate Garfield maintenance
sample. Other reference transcriptions remain agent-checked, not human-approved.

The four documents were checked as full pages with Poppler. Do not use macOS
Quick Look thumbnails as reference images: the previous Balboa interim thumbnail
omitted early sessions and clipped text. Preserve the PDF bytes; models that
need images must receive every page rendered consistently, with renderer,
resolution, and input hashes recorded for the run.

North Beach's June 9-August 15, 2026 schedule is an expired-source case, with a
fixed evaluation date of September 4. Keep all 30 historical sessions and the
printed end date; do not extend the window or claim that the facility is closed.
Its two holiday closures are scored. The benchmark preserves its printed pool
codes (`c`, `w`, `w/t`, `c/w/t`) in lowercase, without splitting shared slots.
The benchmark-only prompt states this rule; production extraction is unchanged.
The scorer also derives `window_status` from extracted dates. This is a
deterministic check, not an extra model-generated field or a live-site test.

The other PDFs contain unresolved closure wording. Hamilton's cell cancellations
conflict with its facility-wide training hours. Balboa lists training without
closure hours and dates outside the interim window. The manifest records these
questions. Closure correctness is **unscored**, not assumed correct. Pool labels
follow the current prompt literally; lane counts alone are not pool sections.
Do not normalize away pool identity to improve scores.

Rossi spring, MLK fall, and Garfield maintenance are reserved for the next
comparison. They have no benchmark labels yet. Do not use them for prompt
tuning; check and freeze their references before the final comparison. This is
a prospective split for this work, not a claim that these historical files
have never appeared in older experiments. Koret's canonical XLSX source stays
in its direct-extraction tests, outside the Rec & Park PDF model comparison.

Score one recorded attempt without API calls or writes:

```sh
uv --project schedule-tools run schedules benchmark tmp/attempt.json --reference hamilton-fall
```

The attempt is a JSON object with `model` (exact requested ID), `transport`
(for example `openai-api` or `cursor-cli`), `source_sha256`, `exit_code`,
`timed_out` (boolean), and `payload` (decoded final extraction object).
A timeout can have a null exit code. Other completed attempts require an
integer exit code. Missing transport, missing identity, and mismatched source
hashes are errors. Record failed attempts too; do not omit them from a matrix.

The scorer reports execution errors and timeouts without quality scores. Only
successful attempts with schema-valid payloads get field scores. Session
identity includes day, type, start, end, and pool; duplicates count as extras.
Dates are checked separately. Closure scoring, once references are resolved,
compares dates and partial-day times, not the wording of `reason`. It compares
literal entries, not merged date intervals. `checked_fields_match` only covers
the named checks; it is not a publication approval or an overall quality score.
The command exits zero after reporting a scored mismatch or failed attempt;
read `status` and the scores, not just the command exit code.

The old ignored `tmp/research-eval/run.py` and its report are historical evidence,
not the supported benchmark. Its six Codex runs exited before extraction with
`No prompt provided via stdin.`; they are execution failures, not schema failures.
Its Hamilton reference was CI-attested and encoded numeric lane counts as pool
sections. Preserve those raw records, but do not use that report to select a model.
Any future CLI runner must test argument construction without model calls first.
For Codex, pass the prompt through stdin with the explicit `-` positional argument
after `--`, so the variadic `--image` option cannot consume it; capture the final
answer separately from event logs. Check the installed executable and its help
before invoking it. On the reviewed host, `agent` resolves to Grok, not Cursor.

Offline replay on 2026-09-04, using the saved final payloads and exit codes
(no new model calls):

| Historical cell | Hamilton session F1 | Balboa fall session F1 | Balboa interim session F1 |
| --- | --- | --- | --- |
| `gemini-37flash-low` | 0.9565 | 1.0000 | 1.0000 |
| `claude-sonnet-med` | 1.0000 | 1.0000 | 1.0000 |
| `codex-sol-high` | Execution failure | Execution failure | Execution failure |

These cell labels describe the old CLI experiment, not current model snapshots
or new API measurements. Hamilton's Gemini error moves Wednesday's 06:30 swim
to Tuesday. These are session-only scores on agent-checked development labels;
unresolved closures and independent human review still prevent a model decision.

### CLI model comparison (2026-09-04)

Keep production unchanged until reference review and scored trials are complete.
The `models` array in `tests/fixtures/schedule-benchmark.json` records 22 primary
candidates, the exact production baseline, Codex Spark, and two named
cross-harness comparisons. The `comparisons` map selects their tracks and cases.
Use existing CLI authentication first; new API keys are not required for preparation.

| Candidates | Primary route | Initial effort |
| --- | --- | --- |
| GPT-6 Astra; GPT-5.6 Sol, Terra, Luna; GPT-5.5; GPT-5.4 Mini | Codex | Medium |
| GPT-5.4 Nano | Pi / Cursor | Medium |
| Claude Opus 5, Sonnet 5, Fable 5, Fable 5.1 | Pi / Cursor | Medium |
| Claude Haiku 4.5 | Pi / Anthropic OAuth | Default; login refresh needed |
| Gemini 3.8 Flash, 3.7 Flash | Pi / Cursor | Low |
| Gemini 3.1 Pro | Pi / Cursor | Default |
| Gemini 3.1 Flash-Lite, 3.5 Flash-Lite | Gemini CLI | Default |
| Kimi K3 | Pi / Cursor | Low; High in the effort comparison |
| GLM 5.2 | Pi / Cursor | High |
| Grok 4.5, 4.6 | Grok CLI | Medium |
| Composer 2.5 | Pi / Cursor | Default |
| Production `gemini-3.1-flash-lite-preview` | Gemini CLI | Default; API baseline configuration remains separate |
| GPT-5.3 Codex Spark | Codex, text track only | Medium |

Authenticated catalogs list seven selectable Codex models, 211 Cursor variants,
and two native Grok models. Pi's offline list is not the live catalog. Cursor's
raw IDs encode effort: use `kimi-k3-low`, `glm-5.2-high`, and the other exact IDs
in the manifest, with Pi thinking set to `off` to prevent a second suffix. This
does not turn off the reasoning selected by the raw Cursor ID. Bare family IDs
can fail at cold startup before asynchronous catalog discovery finishes.

Text/JSON readiness checks succeeded for all candidates except Haiku. Both the
native Claude access token and Pi's Anthropic refresh token expired. Haiku needs
a new sign-in, not an API key. Native Grok reported `grok-4.5-build` and
`grok-4.6-build`; these are not silently equated with a production xAI endpoint.
Readiness means a tiny JSON response succeeded, not that schedule extraction is
accurate. Backend identity remains unknown when the transport does not expose it.
All six image-capable Codex models also read North Beach's pool name and year
correctly from the rendered page, using medium effort and no shell tools. This
establishes image access, not full-grid accuracy.
The Luna/Pi-Codex and Grok-4.6/Pi-Cursor comparison routes also passed the tiny
text/JSON check. Their extraction comparisons are separate matrix entries.

The installed Pi Cursor bridge drops non-text content in `textContent()`;
reading an image through a tool does not avoid that conversion. All Cursor
candidates therefore use the common `pdftotext -layout` track for this harness.
This is a transport limit, not a claim that Kimi or Claude lack native vision.
GLM's documented native input is also text-only. Do not modify the installed
provider or add an image-reading model as an implicit benchmark fallback.

Prepare frozen, label-free development inputs without model calls:

```sh
uv --project schedule-tools run schedules benchmark-prepare --poppler /path/to/poppler/bin
```

This creates a fresh temporary directory outside the repository. It contains
the four PDFs, layout text, every page rendered at 150 DPI, a shared prompt and
schema, file hashes, renderer version, and model matrix. Paths use source hashes,
not labels such as "expired". It contains no expected answers, old extractions,
review envelopes, or reserved PDFs. Preparation never overwrites an existing run.

Check one candidate (one real CLI request; uses account quota):

```sh
uv --project schedule-tools run schedules benchmark-check \
  --candidate kimi --output /path/to/fresh-check-directory \
  --pi-extension /path/to/installed/pi-multi-account/index.ts
```

`--pi-extension` is required only for Pi routes. Checks disable model tools,
except Gemini which uses a deny-all admin tool policy with read-only plan mode.
Keep Gemini's ambient credentials available: do not add `--sandbox`. Pi loads
only the specified provider extension with `PI_SUBAGENT_CHILD=1`, which disables
its model switching and automatic continuation. Checks have a 60-second default
deadline and terminate their process group on timeout. They save local logs and
exit nonzero on failure, including provider errors hidden behind CLI exit zero.
Costs and resolved model IDs remain null when not verified; adapter estimates
are not billing records. These commands prepare inputs and test access; they do
not execute or score the extraction matrix.

Scored run specification:

```sh
uv --project schedule-tools run schedules benchmark-run \
  --inputs /path/to/prepared-inputs --output /path/to/new-results \
  --pi-extension /path/to/installed/pi-multi-account/index.ts \
  --blocked-candidate haiku --timeout 180
```

Omit `--blocked-candidate haiku` after its login is restored. The runner refuses
an existing output directory, changed input hashes, extra input files, changed
model entries, or reserved documents. It uses four execution lanes: two Codex
lanes, one serial Pi lane, and one for the other CLIs. Only the runner reads the
reference labels. Each model receives the fixed prompt, schema and source text
or page images, with no model tools enabled (Gemini uses a deny-all tool policy).

All scored routes receive the schema in the prompt; native schema-constrained
output is not enabled for this comparison. JSON fences or explanatory prose
fail the strict output contract and remain visible as failures. Any later
format-unwrapped diagnostic must remain separate from these strict results.
`write_benchmark_diagnostics` performs that offline diagnostic after a run. It
accepts only one complete extraction object, validates it against the unchanged
schema, and never repairs values or rescues execution failures. Its separate
report categorizes pool-label-only differences without removing pool identity
from F1. Strict attempt files and the strict report remain unchanged.

The runner makes no retries or model substitutions. A deadline ends the child
process group. CLI-internal retries may still occur and are not claimed to be
zero. Every finished attempt saves its request, raw logs, final payload, usage
reports, hashes, execution status, and score. Pi usage is marked as an adapter
estimate, not billing data. `report.md` and `results.json` collect all cells,
including authentication-blocked entries. A complete run exits zero even when
cells fail; inspect the report, not just the process exit code.

1. Run every text-ready entry on all four development documents: 96 cells when
   all 24 entries are ready. Keep blocked cells in the report. Use identical
   text, prompt, and schema. Models must not read references or repository files.
2. Keep direct image runs separate from text runs. The six image-capable Codex
   entries add 24 cells; Spark and this Cursor adapter are not image candidates.
   Freeze input hashes before a run; do not change the prompt between models.
3. Compare a shared OpenAI model through Codex and Pi, and Grok 4.6 through native
   Grok and Cursor. Record harness differences rather than treating routes as
   duplicate measurements. Check higher efforts only after the broad comparison.
4. Freeze finalists before reserved-document tests. Review reference labels and
   unresolved closures, then repeat finalist runs to measure variability. Confirm
   the chosen production API model and cost separately before any model change.

Subscription usage is not assumed free. CLI checks report unknown actual cost as
unknown. Scored runs must retain failures, requested/reported model identity,
effort, input type, elapsed time, retries, usage, and available billing data.

### Development comparison results (2026-09-04)

The local run recorded all 128 planned cells: 124 extraction calls and four
Haiku cells blocked by expired authentication. Strict results contain 58
schema-valid outputs, 54 schema-invalid outputs, eight execution failures,
and four timeouts. The separate diagnostic recovered 52 complete, schema-valid
objects from wrapped responses without changing any values or strict scores.

| Candidate and input | Observed result across four documents | Mean seconds per call |
| --- | --- | --- |
| Astra medium, Codex images | All checked fields matched on 4/4 documents; all 97 sessions exact | 62.2 |
| Grok 4.6 medium, Pi / Cursor text | All checked fields matched on 4/4 documents; all 97 sessions exact | 97.5 |
| GPT-5.5 medium, Codex text | 3/4 checked matches; one omitted Balboa interim session | 41.3 |
| GPT-5.5 medium, Codex images | 3/4 checked matches; one incorrect pool label | 43.3 |
| Gemini 3.8 Flash low, Pi / Cursor text | Diagnostic: six pool-label differences; no other missing or extra session rows | 14.0 |
| Gemini 3.1 Pro, Pi / Cursor text | Diagnostic: one pool-label difference; no other missing or extra session rows | 72.6 |
| Kimi K3 low, Pi / Cursor text | Diagnostic: 36 pool-label differences and one omitted Hamilton session | 14.6 |
| GLM 5.2 high, Pi / Cursor text | Diagnostic: 3/4 schema-valid objects; six pool-label differences and two extra rows in those three | 39.6 |

All four outputs from each diagnostic-only candidate above failed the strict
JSON contract. Kimi preserved North Beach's 30 sessions and dates but expanded
all printed pool codes. Its zero literal session score on that document does
not mean it lost the schedule. GLM's Balboa fall object added an unsupported
`evidence` field to closures and remained schema-invalid. The earlier summary
incorrectly blamed its `start` and `end` field names; those names are valid.

Opus 5, Fable 5, and Gemini 3.7 Flash also preserved all session days, types, and
times after unwrapping; each had five pool-label differences. Spark, Nano,
Composer, and the Flash-Lite routes had errors beyond pool labels. The exact
production model ID, called through Gemini CLI, had eight missing and five
extra rows beyond six pool-label pairs. This is not a production API measurement.

Two Mini text cases and two Sonnet cases timed out at 180 seconds. All eight
native Grok calls stopped at the CLI turn limit, so they have no extraction
quality score. One additional Grok 4.6 North Beach control with native JSON
schema enabled also stopped at that limit; it is separate from the matrix.
That control used the same frozen text request, medium effort, plan mode,
disabled tools, and `--max-turns 1`, adding `--json-schema` with the frozen
schema. It exited 1 after 8.769 seconds with `max turns reached`; no extraction
quality score was assigned.
Luna's text session F1 was 0.8958 through Codex and 0.9231 through Pi. One sample
per document cannot establish that the harness caused this difference.

The portable evidence archive is
[`benchmarks/pdf/development-2026-09-04.zip`](../benchmarks/pdf/development-2026-09-04.zip).
It contains all 128 cells, final response text, frozen inputs, the reference
manifest, and both reports. Raw CLI events, stderr, local paths, and account
configuration are not committed. The larger git-ignored working copy remains
at `tmp/pdf-benchmark-2026-09-04/`, including the separate Grok control. Original
Pi attempt usage lists include repeated streaming snapshots; the portable
archive recomputes usage from final events only. Usage remains an estimate,
not an invoice. The extra Grok control has no quality score and is not one of
the 128 archived matrix cells.

Next comparison: review the pool-label convention and unresolved closures with
a human, freeze finalists, then test reserved documents and repeat runs.
Astra images and Grok / Cursor text are the observed accuracy finalists;
GPT-5.5 text and Gemini 3.8 Flash text merit the speed comparison. Kimi's higher
effort remains untested. Confirm API behavior, native output constraints, and
cost before selecting a production model. This run changed no production
configuration or published schedules, and it did not use reserved documents.

### Preserve, replay, and rerun a benchmark

Offline replay means reproducing the saved scores exactly, without model calls.
A rerun means sending the same inputs through the same specified method again.
It can produce different answers: CLI model aliases, services, account access,
and tool behavior can change. Requested IDs are not proof of immutable backend
snapshots. This distinction follows the [evaluation guidance on fixed criteria,
datasets, and repeated evaluation](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

The ZIP contains:

- The exact four PDFs, layout text, 150-DPI page images, shared prompt, schema,
  renderer version, input hashes, and fixed evaluation date.
- The unchanged reference manifest, all requested models and efforts, transport,
  failure status, final response text including JSON framing, parsed payloads,
  strict scores, separate diagnostic scores, timing, and available usage reports.
- A checksum for each file and archive-time hashes of the Python implementation,
  schemas, package definition, and `uv.lock`. The containing Git commit preserves
  that implementation. Replay does not execute code from inside the ZIP.

The historical run did not capture a full runtime environment or a source
revision before execution. Its archived `environment` is explicitly null;
archive-time source hashes are not presented as run-time provenance. The
preflight recorded Codex 0.153.2, Pi 0.84.4, Gemini 0.46.0, and Grok 1.0.13
(build `5e9a58528b76`). New runs capture Python, system and machine type,
CLI versions, the Pi extension entry-file hash, and implementation hashes
before extraction. This does not snapshot provider services or all CLI
dependencies. No credentials or account settings belong in an archive.

From the Git revision that contains this archive, install the locked Python
dependencies and replay it into a **new** output directory:

```sh
uv --project schedule-tools sync --locked
uv --project schedule-tools run --locked schedules benchmark-replay \
  benchmarks/pdf/development-2026-09-04.zip --output tmp/pdf-benchmark-replay
```

Replay validates checksums, exact case coverage, requested identity and effort,
source and request hashes, the schema, and implementation hashes. It reconstructs
the strict payload from final response text and compares every score and both
reports. Failures stay failures; wrapped JSON stays a strict failure. No login,
model CLI, Poppler installation, or original temporary directory is needed for
replay. Dependency installation may need network access; replay itself does not.

If the implementation has changed, replay stops. Use the commit that introduced
the immutable archive, not an edited reference or a silently updated scorer:

```sh
git log --diff-filter=A --format=%H -- benchmarks/pdf/development-2026-09-04.zip
```

Check out that revision in a separate checkout if the current worktree is dirty.
Do not replace this historical archive when changing labels or methodology.
Create a separately named run and state its changes before comparing results.

For a new paid run of the historical development matrix, use the restored
inputs. Authenticate the same CLI routes first and check their current access.
Record blocked candidates explicitly; do not substitute model IDs:

```sh
uv --project schedule-tools run --locked schedules benchmark-run \
  --inputs tmp/pdf-benchmark-replay/inputs --output tmp/pdf-benchmark-rerun \
  --pi-extension /path/to/installed/pi-multi-account/index.ts \
  --blocked-candidate haiku --timeout 180
```

The command writes both reports after all calls finish. It does not retry or
resume an interrupted run; partial raw attempts remain available locally.
Archive a complete run into a new, descriptive filename:

```sh
uv --project schedule-tools run --locked schedules benchmark-archive \
  --inputs tmp/pdf-benchmark-replay/inputs --results tmp/pdf-benchmark-rerun \
  --output benchmarks/pdf/development-YYYY-MM-DD.zip
```

Archival checks every raw attempt against the result list, verifies an offline
replay, and refuses to overwrite an existing ZIP. Review the exported final
responses for sensitive content before committing them; excluding CLI metadata
cannot guarantee that a model never put sensitive text in its answer. Commit
the ZIP, methodology changes, references, implementation and lockfile together.
A local commit is not a remote backup until pushed. Automated tests replay the
historical archive with process execution forbidden and test damaged evidence,
missing/duplicate cells, changed identities, score drift and unsafe ZIP paths.

### Reference decisions before the finalist comparison

The September 4 archive is frozen. The following are proposed rules for the
next comparison, not edits to historical labels or human sign-off:

| Decision | Source evidence | Proposed rule |
| --- | --- | --- |
| Pool labels | Hamilton uses `2 lanes + small pool` and `waterslide`; Balboa uses `main pool only` and `small/main`. | Keep the documented literal-label convention for this comparison. Keep standalone numeric lane counts out of pool identity. Do not split a shared slot into inferred pools. |
| Hamilton training closures | Thursday cells cancel sessions spanning 11:00–12:30 and 13:00–15:00 on 8/27, 9/24 and 10/22. The facility note gives 12:00–14:00. | Mark the conflicting hours as unresolved. Do not select one interpretation as ground truth without source confirmation. |
| Balboa training closures | Saturday training dates have no hours. The interim PDF also lists holidays outside its August window. | Do not invent all-day closures or remove printed facts silently. Keep these closure checks unscored until their scope is agreed. |
| Expired sources | A printed end date bounds a schedule, not the facility's operating status. | Preserve sessions and dates; derive expiry separately. |

Source pages: [Hamilton fall](../data/hamilton-pool/2026-08-20-c8e193806d9e/source.pdf),
[Balboa fall](../data/balboa-pool/2026-08-20-d6f218710372/source.pdf), and
[Balboa interim](../data/balboa-pool/2026-08-20-d20965597a7a/source.pdf), page 1 of each.
Full-page visual review on September 5 confirmed these unresolved questions;
it did not create a human attestation.

The user approved these rules on September 5. The reference transcriptions
remain agent-checked rather than human-attested.

### Finalist comparison specification (2026-09-05)

Candidate selection preceded inspection of the three reserved sources. Their
full pages were then reviewed and references frozen before any finalist calls:

| Source | Checked sessions | Effective window | Closure scoring |
| --- | --- | --- | --- |
| Rossi spring | 21 | March 15–June 4, 2026 | Unscored: cell cancellations conflict with the facility training hours; one listed holiday falls outside the window. |
| MLK fall | 27 | August 18–September 26, 2026 | Unscored: training hours and the scope of selected-cell cancellations are not fully specified. |
| Garfield maintenance | 0 | August 14–September 7, 2026 | One all-day maintenance interval. Expected reopening September 8 does not prove a weekly schedule or actual reopening. |

The literal-label rule keeps MLK's composite `4 & shallow` and `shallow` labels,
but omits purely numeric lane counts. Rossi has no pool labels under that rule.
The evaluation date remains September 4, as in the development comparison.
Session notes and evidence text are not quality-scored. No publication reads
these benchmark references.

The manifest now explicitly defines `development` and `finalists` comparisons,
including source IDs, input tracks and repetitions. The historical development
ZIP remains unchanged and must be replayed from commit `d14a21d`; current code
does not silently migrate its old case layout.

Finalists: Astra medium on images; Grok 4.6 medium through Pi / Cursor on text;
GPT-5.5 medium on text; Gemini 3.8 Flash low through Pi / Cursor on text. Each
receives each source three times in fresh CLI sessions: 36 calls total, nine
per candidate. Repetition is part of case identity and its output path. Calls
are ordered by repetition, document and candidate before assignment to the
existing lanes. There are no additional preflight inference calls, retries or
model substitutions. The timeout stays 180 seconds per call. CLI-internal
retries and server caching remain outside the runner's control.

One generic prompt correction was necessary before freezing inputs: the old
prompt unconditionally demanded `swim_schedule`, even for a closure-only
notice. The finalist addendum instead requires `temporarily_closed`, no
invented sessions, and the explicit closure period for that source type. This
addendum applies to every finalist and contains no source-specific facts.
Because source inspection informed this change, this is a prospective
finalist test, not an untouched holdout test of the September 4 prompt. Do not
tune the prompt or references after observing finalist responses.

The schema and strict-versus-unwrapped diagnostic remain unchanged. Native
schema enforcement stays disabled. Check each repetition separately; do not
count three repetitions as three independent documents. An empty-session
closure notice must not hide grid errors in pooled session metrics.

```sh
# Historical API-confirmation commands: use source revision d52e022.
uv --project schedule-tools run --locked schedules benchmark-prepare \
  --comparison finalists --poppler /path/to/poppler/bin
uv --project schedule-tools run --locked schedules benchmark-run \
  --inputs /path/to/prepared-inputs --output tmp/pdf-finalists-results \
  --pi-extension /path/to/installed/pi-multi-account/index.ts --timeout 180
```

Archive the complete run with `benchmark-archive` under a separately named
`benchmarks/pdf/finalists-2026-09-05.zip`; never replace the development archive.

### Finalist comparison results (2026-09-05)

All 36 CLI calls completed without timeouts or execution errors. Twenty-six
returned schema-valid strict JSON. Ten failed the strict contract because of
framing; each contained one complete schema-valid object in the separate
diagnostic. No output values were repaired. The runner, references and prompt
hashes remained unchanged from launch through archival.

| Candidate | Strict JSON | Checked matches after diagnostic | Rossi matches | MLK matches | Garfield matches | Mean grid seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GPT-5.5 text | 9/9 | 8/9 | 3/3 | 2/3 | 3/3 | 41.5 |
| Grok 4.6 / Cursor text | 8/9 | 8/9 | 3/3 | 2/3 | 3/3 | 85.2 |
| Astra images | 9/9 | 6/9 | 3/3 | 0/3 | 3/3 | 64.7 |
| Gemini 3.8 Flash / Cursor text | 0/9 | 7/9 | 3/3 | 1/3 | 3/3 | 12.6 |

Grid timing covers Rossi and MLK only, six calls per candidate. The much simpler
closure notice took 2.9–9.2 seconds and would make pooled latency look better.
Mean times across all nine calls were 30.0, 59.6, 46.0 and 9.5 seconds respectively.
These are wall-clock CLI measurements under the recorded concurrency, not API
latency or verified billing data. Codex was 0.153.4 in this run versus 0.153.2 in
the September 4 preflight; Pi remained 0.84.4. The archive records this run's
Python, machine, CLI versions and extension entry-file hash.

All diagnostic-valid responses preserved session days, types, times and counts,
all effective dates, and the closure-only source classification. The remaining
scored differences were MLK's four composite pool labels: `shallow` instead of
the frozen `4 & shallow`. Astra shortened them in all three repetitions; GPT-5.5
in repetition 2; Grok in repetition 1; Flash in repetitions 1 and 2. These are
literal-label failures, not missing whole sessions, and were not normalized
away. Grok's repetition 3 on MLK matched the checked data but wrapped its JSON;
all nine Flash responses had framing. Three repeated calls are not three new
source documents, and unresolved Rossi/MLK closures remain unscored.

GPT-5.5 text is the first candidate for production API confirmation: it combined
strict JSON reliability with the best observed literal accuracy and lower grid
latency than Astra or Grok here. Flash remains the fast comparator if its API
offers the exact model and an enforceable output schema. This is not a final
production choice: GPT-5.5 missed a Balboa interim session in the development
run, and the new source-kind prompt differs from that run. Do not discard that
earlier failure. Confirm API behavior and cost before changing production.

Portable results: [finalists-2026-09-05.zip](../benchmarks/pdf/finalists-2026-09-05.zip).
Replay the archive from its containing commit:

```sh
uv --project schedule-tools run --locked schedules benchmark-replay \
  benchmarks/pdf/finalists-2026-09-05.zip --output tmp/pdf-finalists-replay
```

The ZIP contains all 36 final responses, strict and diagnostic reports,
repetitions, frozen inputs and references. Raw events stay in the ignored
`tmp/pdf-finalists-results/` working copy. The September 4 archive remains
byte-identical and replays from `d14a21d`, with no compatibility conversion.

### Production API confirmation method

Keep production on its current provider until this check completes. The initial
candidate is `gpt-5.5`, text input, medium reasoning, through the OpenAI Responses
API with native strict structured output. Do not substitute a newer model or
assume that a CLI alias identifies the same backend snapshot. Record the requested
model and the model reported by the API separately.

Use all seven checked documents: North Beach expired summer, Hamilton fall,
Balboa fall, Balboa interim, Rossi spring, MLK fall, and Garfield maintenance.
Make three independent calls per document (21 extraction calls), plus one small
readiness call. Reuse the frozen reference date, literal-label rules, and generic
closure-only instruction from the finalist comparison for every document. The
earlier Balboa omission remains a regression case. These are known regression
documents, not a new holdout set. Keep unresolved closures unscored; report that
limitation, and do not treat it as publication approval for those closures.

Before paid calls:

- Set `OPENAI_API_KEY` in the ignored root `.env` or the shell, never in a prompt,
  committed file, or benchmark artifact. Do not use CLI subscription credentials
  as a production API key.
- Confirm a user-approved spend limit. Freeze token limits and reserve a
  conservative maximum cost before each request. Count a timed-out request as
  potentially billed; do not retry paid benchmark cells silently.
- Preserve the API request body, source text, source hashes, prompt, schema,
  normalization rules, reference labels, dependency versions, and code revision.
- Use a separate API comparison, not a replacement for either CLI archive.

The current extraction schema has optional fields. OpenAI strict output requires
every property to be required, with nullable values to represent absence. Freeze
an explicit transport schema and null-to-absence mapping before the run. Preserve
the untouched API response, validate its strict contract first, then score the
mapped payload against the existing reference schema. Do not repair labels,
times, dates, missing rows, or JSON framing. This is a declared transport change,
not a claim that the API used an identical CLI request.

Record each response's completion status, refusal/incomplete result, usage,
latency, reported model, and estimated cost from the dated official pricing.
Keep billing estimates distinct from an invoice. Run sequentially for a simple
cost limit and report grid latency separately from closure-notice latency.
Confirm the exact Flash API model and access before adding it as a comparator;
do not silently substitute another Flash model.

Production selection requires correct session counts, days, types, times, dates,
source classification, and literal pool labels across all scored repetitions.
No refusal or incomplete response may become a publishable payload. Archive and
replay the results offline before selection. Any mismatch needs a recorded
decision and another frozen run; do not tune references after seeing results.
Passing this small regression set still does not prove completeness on unseen
documents, so publication checks remain mandatory.

The API runner is available as `benchmark-api-run`. The frozen comparison uses
the documented snapshot `gpt-5.5-2026-04-23`, medium reasoning, no tools, no stored
Responses state, and the standard service tier. Extraction requests allow 8,192
output tokens, including reasoning; the readiness request allows 1,024. Each
request has a 240-second network timeout and no automatic retries.

Before the first call, the runner reserves the entire matrix at $5 per million
input tokens and $30 per million output tokens. The input reservation counts every
UTF-8 byte of the complete request as a token and adds 4,096 framing tokens. It
rejects large inputs that could use long-context pricing. For these seven sources,
the full reservation is $7.393455. Timeouts never release their reservation.
Reported usage estimates account for the $0.50 cached-input rate; the reservation
does not rely on cache savings. Recheck official prices before a future paid run.

The native schema also omits unsupported `dependentRequired` constraints. The
original schema checks paired closure-time fields after null-to-absence mapping.
Raw successful API bodies stay in ignored logs; the portable archive retains
output, completion status, model, usage, and incomplete details without account
metadata. Invalid native responses are not rescued by the CLI framing diagnostic.

```sh
uv --project schedule-tools run --locked schedules benchmark-prepare \
  --comparison api-confirmation --poppler /path/to/poppler/bin
just schedules benchmark-api-run --inputs /path/printed/by/prepare \
  --output tmp/pdf-api-results --budget-usd 10
uv --project schedule-tools run --locked schedules benchmark-archive \
  --inputs /path/printed/by/prepare --results tmp/pdf-api-results \
  --output benchmarks/pdf/api-confirmation-2026-09-05.zip
uv --project schedule-tools run --locked schedules benchmark-replay \
  benchmarks/pdf/api-confirmation-2026-09-05.zip --output tmp/pdf-api-replay
```

Use new output directories and archive names on later runs. Never overwrite an
earlier comparison. A failed readiness call stops before extraction and leaves
its result in the output directory. The base Git commit and runtime source hashes
are recorded; exact replay requires the source revision containing those hashes,
not merely the base commit if the run used local changes.

The first paid run is recorded below. The publication contract and
remaining cutover gates are in
[the auto-publish spec](specs/2026-08-20-schedule-auto-publish.md#approved-hands-off-publication-contract-2026-09-05).

Official references, checked 2026-09-05:
[GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5),
[structured output requirements and limitations](https://developers.openai.com/api/docs/guides/structured-outputs).

### Production API confirmation results (2026-09-05)

**Decision: do not switch production yet.** The API works with the pinned model
and native structured output, but the candidate does not pass the frozen
literal-label acceptance rule. Do not relax the references to make this run pass.

All 21 extraction calls completed with valid native output and valid mapped
payloads. No request timed out, failed, or retried. Every response reported
`gpt-5.5-2026-04-23`. All 435 session rows across the repetitions had correct days,
types, times, and counts when pool labels were excluded. Every effective date
window and source classification matched. North Beach's expired schedule remained
historical, and Garfield remained a closure notice with no invented weekly hours.
The nine scored closure entries across those two sources also matched. Closures
on the other five sources remain unscored, not confirmed correct.

| Source | Checked matches | Mean seconds | Remaining difference |
| --- | --- | --- | --- |
| North Beach expired summer | 3/3 | 37.7 | None |
| Hamilton fall | 1/3 | 37.3 | Four labels shortened from `2 lanes + small` to `small` in repetitions 2 and 3. |
| Balboa fall | 3/3 | 38.2 | None |
| Balboa interim | 1/3 | 31.1 | One label shortened from `main only` to `main` in repetitions 1 and 3. |
| Rossi spring | 3/3 | 25.4 | None |
| MLK fall | 0/3 | 48.5 | Four labels shortened from `4 & shallow` to `shallow` in every repetition. |
| Garfield maintenance | 3/3 | 3.1 | None |

Total checked matches: **14/21**. Literal session F1: **0.9494**, with 22
pool-label differences and no other missing or extra rows. Mean grid latency was
36.4 seconds across 18 calls; including the closure notice lowers the mean to
31.6 seconds. The earlier CLI omission on Balboa interim did not recur here, but
this small, known regression corpus does not establish reliability on new PDFs.
The references are agent-checked, not human-attested.

Reported extraction usage was 70,665 input tokens (42,240 cached) and 72,564 output
tokens, including reasoning. Estimated extraction cost was **$2.340165**. The
readiness call added **$0.000920**, for **$2.341085 total**, below the approved $10
limit and the $7.393455 full-run reservation. These are estimates from reported
usage and the frozen price table, not an invoice. API calls took about 11.1
minutes in total, including readiness.

Portable evidence: [api-confirmation-2026-09-05.zip](../benchmarks/pdf/api-confirmation-2026-09-05.zip)
(4,084,036 bytes; 33 members).
SHA-256: `67767c80b0afe9908ae527b51ad59889ef2bba0bd4d610b84507f462151c78da`.
Offline replay reproduced both reports and every score. The archive contains the
request bodies, transport schemas, final responses, usage, budget reservation,
source files, references, and runtime/archive-time implementation hashes. The
local raw logs remain in ignored `tmp/pdf-api-results/`.

After the calls finished, the export filter was tightened to remove opaque
encrypted reasoning and API output item IDs from the portable response copies.
No request, final answer, normalization rule, reference, or score changed. This
explains the difference between runtime and archive-time source hashes. The raw
responses remain local. Credential and local-path scans of the portable ZIP
passed. Both earlier CLI archives remain byte-identical.

The next extraction change should separate verbatim pool labels from derived pool
identity. The current field asks the model to both preserve and interpret labels.
That is a proposed cause of these differences, not a demonstrated fix. Preserve
raw labels, apply explicit source-backed normalization in code, then repeat a
new frozen comparison. Keep the current production provider and PR publication
workflow until the remaining acceptance checks pass.

### Literal pool-label comparison

The approved repeat changes only the pool-label extraction contract. The model
returns required `pool_label_raw` (a complete printed label or null) instead of
`pool`. Code strips enclosing parentheses, lowercases text, removes the standalone
word `pool`, and collapses whitespace. It preserves qualifiers, combined lane and
section labels, punctuation, and unexpanded codes. It does not use case-specific
aliases or the expected answers. Raw facts and the derived payload both remain
in the evidence archive, and replay checks both.

Keep the same model snapshot, reasoning effort, token limit, seven documents,
three repetitions, date rules, references, and exact-match acceptance rule. This
is a targeted regression comparison after observing failures, not a new holdout.
The earlier API archive requires source revision `d52e022` for exact replay;
current code fully uses the raw-label contract for API benchmarking.

The repeat reserves at most $7.65 before making any request. Together with the
initial run's estimated $2.341085, that stays below the original approved $10.
Use fresh output paths; preserve earlier evidence unchanged.

```sh
uv --project schedule-tools run --locked schedules benchmark-prepare \
  --comparison literal-pool-labels --poppler /path/to/poppler/bin
just schedules benchmark-api-run --inputs /path/printed/by/prepare \
  --output tmp/pdf-literal-label-results --budget-usd 7.65
uv --project schedule-tools run --locked schedules benchmark-archive \
  --inputs /path/printed/by/prepare --results tmp/pdf-literal-label-results \
  --output benchmarks/pdf/literal-pool-labels-2026-09-05.zip
uv --project schedule-tools run --locked schedules benchmark-replay \
  benchmarks/pdf/literal-pool-labels-2026-09-05.zip --output tmp/pdf-literal-label-replay
```

### Literal pool-label results (2026-09-05)

**Decision: retain the raw-label separation, but do not switch production yet.**
Checked matches increased from 14/21 to 19/21. The old label-shortening failures
did not recur. Two new literal-label differences remain on Balboa interim's
overlapping text, so the unchanged all-repetitions acceptance rule is not met.

| Source | Checked matches | Mean seconds |
| --- | --- | --- |
| North Beach expired summer | 3/3 | 32.7 |
| Hamilton fall | 3/3 | 28.4 |
| Balboa fall | 3/3 | 33.7 |
| Balboa interim | 1/3 | 31.1 |
| Rossi spring | 3/3 | 27.3 |
| MLK fall | 3/3 | 34.1 |
| Garfield maintenance | 3/3 | 2.8 |

All 21 calls completed without errors, timeouts, or retries and reported the
pinned model. Native responses and derived payloads were schema-valid. All 435
session rows had correct days, types, times, and counts when pool labels were
excluded. All date windows, source classifications, and nine scored closure
entries matched. Closures on the other five sources remain unscored. Literal
session F1 was 0.9954, with two label differences and no other missing or extra
rows. Mean grid latency was 31.2 seconds; all-call mean was 27.2 seconds.

In repetitions 2 and 3, Balboa interim's Wednesday 15:30–17:30 family session
returned `pool_label_raw: "s (small pool"`, derived as `pool: "s (small"` instead
of `small`. The frozen Poppler layout text contains `(s (small pool)`; the
rendered page shows `(small pool)`. A read-only check after the calls also found
the extra fragment in pypdf layout output, but not in pypdf plain or Poppler raw
output. Those representations were not substituted into this run. The evidence
supports a source-text problem, not another shortened qualifier. Do not add a
case-specific replacement or change the reference. The next extraction design
needs a source-quality check and visual verification or a held update when text
and layout are unclear. That fallback has not yet been benchmarked.

Extraction used 73,794 input tokens (45,312 cached) and 71,694 output tokens,
including reasoning. Estimated extraction cost was $2.315886; readiness added
$0.000920, totaling **$2.316806**. The full reservation was $7.480710 against a
$7.65 cap. Combined estimated cost for both API comparisons is **$4.657891** of
the approved $10. These estimates use reported usage, not invoice data. Calls
took 572.7 seconds in total, including readiness.

Portable evidence: [literal-pool-labels-2026-09-05.zip](../benchmarks/pdf/literal-pool-labels-2026-09-05.zip)
(4,099,124 bytes; 33 members).
SHA-256: `1358cde019fcfb23cc9b76e70f724c80e82fc2276de8c416e676f6ba842bb07c`.
Exact replay source: `c143d64a623f8d93ed3ce58491469edfbe089d87`.
Runtime and archive-time implementation hashes match. Offline replay reproduced
every score and both reports. The archive preserves raw facts, derived payloads,
request schemas, final responses, usage, budget, sources, and unchanged
references. Credential, local-path, and opaque-reasoning scans passed. Earlier
archives remain unchanged. Local raw logs are in ignored
`tmp/pdf-literal-label-results/`.

This known regression set remains agent-checked, not human-attested. Passing its
labels would not establish source completeness. The production integration gaps,
including a demonstrated undetected missing row, are recorded in
[the publication spec](specs/2026-08-20-schedule-auto-publish.md#extraction-integration-checks).

### Production source-inventory comparison

The current API runner tests the production request, not the historical Poppler
text request. It freezes the current prompt, coordinate-based source inventory,
pinned PDFium renderer, strict raw-label schema, model snapshot, medium effort,
and 8,192-token output limit. It attaches only pages flagged for broken text;
the other rendered pages remain in the archive for inspection, not model input.
Each response records independent session coverage and printed-window checks in
addition to the unchanged reference scores. Replay rebuilds the request and
source checks and verifies image bytes, raw facts, scores, and spending records.

`source-inventory` repeats the same seven known documents three times. It is a
regression set, not a holdout. `source-holdout` tests Mission's September 2 PDF
three times. Its 25 sessions and five facility closures were transcribed from
the rendered page before model calls. Neither set has human attestation.
Coffman's fall PDF is a separate preflight refusal test: an ambiguous closure
block stops extraction before a model call. Do not weaken that refusal to make
the benchmark look complete, or turn its session caveat into an all-day closure.

The spending policy now uses the production ledger: reserve each request's
maximum cost before sending it, then settle trustworthy reported usage at full
input rates. Missing usage keeps the maximum reservation. Calls run sequentially
with no benchmark retries. The command stops before a request that cannot fit
the remaining limit, preserving partial local results. This is a budget-policy
change, not a change to reference answers or exact-match acceptance.

The two earlier API runs used an estimated $4.657891 of the approved $10. The
source-inventory repeat may use at most the remaining $5.342109. Any later
holdout run must subtract this repeat's ledger charges first; it does not get
a second $5.342109 allowance. Recurring automation has no approved monthly
allowance yet.

```sh
uv --project schedule-tools run --locked schedules benchmark-prepare \
  --comparison source-inventory
just schedules benchmark-api-run --inputs /path/printed/by/prepare \
  --output tmp/pdf-source-inventory-results --budget-usd 5.342109
uv --project schedule-tools run --locked schedules benchmark-archive \
  --inputs /path/printed/by/prepare --results tmp/pdf-source-inventory-results \
  --output benchmarks/pdf/source-inventory-2026-09-05.zip
uv --project schedule-tools run --locked schedules benchmark-replay \
  benchmarks/pdf/source-inventory-2026-09-05.zip --output tmp/pdf-source-inventory-replay
```

Run historical API comparisons from their recorded source revision. Their
archives and reference results remain unchanged; the current API command fully
uses the production request contract.

### Source-inventory results (2026-09-05)

**Decision: do not enable publication yet.** The production-request repeat
matched 18/21 references. Balboa interim passed all three times with its rendered
page, but Rossi failed all three. Six shared-program sessions per Rossi response
copied program names and numeric lane counts into the pool-label field. All
other session fields and all printed windows matched. The independent source
check rejected every incorrect candidate; it accepted the other 18 results.
No requests failed, timed out, or retried.

Estimated API cost was $2.023499 including readiness, from reported usage rather
than invoices. The conservative ledger charged $2.240075, leaving $3.102034 of
the original approval available for further checks. Total call latency was
472.191 seconds. The next repeat clarifies the existing distinction between
physical pool labels and program names with lane counts. It must not alter
reference answers, normalization, or exact-match acceptance.

Portable evidence: [source-inventory-2026-09-05.zip](../benchmarks/pdf/source-inventory-2026-09-05.zip).
SHA-256: `daa9543d0511a940cbb52c7627ba37c9b92567443b950c31a2c8be53d2b3a3e9`.
Exact replay source: `4ea39ba`. Runtime and archive-time implementation hashes
match. Offline replay reproduced the requests, source checks, scores, reports,
and per-request budget accounting. The failed Rossi responses remain unchanged.

The physical-pool-label repeat changes only the prompt's label-scope rule:
program names, footnotes, and numeric-only lane assignments are not physical
pool labels. It keeps the same seven documents, three repetitions, model,
renderer, normalization, source checks, and reference answers. Prepare a new
`source-inventory` input directory and use `tmp/pdf-physical-label-results` with
`--budget-usd 3.102034`. Preserve it as a separate
`physical-pool-labels-2026-09-05.zip` archive. This allowance is the remainder of
the original $10, not new spending permission.

### Physical pool labels and Mission holdout results (2026-09-05)

**Decision: do not enable the new direct-main publisher.** The clarified-label repeat
matched all checked fields in 19/21 runs and exact session grids in 20/21.
One Balboa interim response wrote `small//main` instead of `small/main` for
two shared-program rows. The source session check rejected it. One North Beach
response omitted the July 4 closure while passing both session and window
checks. This is a concrete false acceptance: those checks alone do not establish
closure completeness. Do not repair either response or weaken exact matching.
All three Rossi responses now matched. No request failed or retried.

The separate Mission holdout matched all 25 sessions, five facility closures,
and its date window in all three runs. The reference was frozen before calls;
it is agent-checked, not human-approved. The untimed Thursday cell caveat and
the narrower facility closure notice still need an approved interpretation
before publication. Passing this holdout does not resolve that policy question.

Both runs used source revision `1ecf4a1`, unchanged model configuration, and
the production request. Archive replay verified input hashes, requests,
source checks, scores, and conservative budget accounting offline.

| Run | Estimated API cost, including readiness | Conservative ledger charge | Call seconds, including readiness |
| --- | --- | --- | --- |
| Physical pool labels, 21 calls | $2.010941 | $2.197565 | 449.539 |
| Mission holdout, three calls | $0.220856 | $0.246200 | 49.742 |

The original $10 approval has $0.658269 left after conservative accounting.
Total estimated API cost across the five API comparisons is $8.913187, not an
invoice total. No recurring monthly allowance had been approved at the time of
these benchmark runs; the later automation allowance is recorded below.

Portable evidence:

- [physical-pool-labels-2026-09-05.zip](../benchmarks/pdf/physical-pool-labels-2026-09-05.zip),
  SHA-256 `58bb90ccbd6f8f278744f6d6c919f7ceba6e85690a0f97c64a2b4a9b31b0090b`.
- [mission-holdout-2026-09-05.zip](../benchmarks/pdf/mission-holdout-2026-09-05.zip),
  SHA-256 `8656d13e551772e03ea601a992b427f9ea44f7b2de76e24573f25ffa0e992178`.

## Autonomous extraction and publication

The operator confirmed the North Beach summer and Garfield maintenance reference
samples on 2026-09-06 and approved the hosted cutover trials. The recovered
publication trial passed after the Cloudflare build secret was configured;
the fresh unattended confirmation passed and weekly runs are enabled. Evidence
and remaining source exceptions are recorded under Evidence and recovery.
The operator initially approved a $20/month API ceiling on 2026-09-06;
the cutover uses the lower $5/month ceiling discussed that evening. This is
a limit, not a spending target. It replaces the Gemini/PR workflow;
verified updates do not use a rolling publication PR. Unclear closure notices
use a separate draft review PR, as approved on 2026-09-06.

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

### Cost evidence and proposed allowance change (2026-09-06)

The extraction-only hosted trial `34049718694` made no API requests and settled
at $0. All ten PDF inputs were held by source closure checks; this is not a
measurement of successful extraction cost or proof of hosted API access.

The pinned-model physical-pool-label benchmark contains 18 schedule calls and
three closure-flyer calls. Schedule calls cost $0.067072–$0.161904 each from
reported usage, including reasoning and cached-input discounts. Their
conservative pre-request reservations were $0.330165–$0.397480. The three
closure-flyer calls cost $0.013755–$0.014835 each. These are API estimates, not
invoice totals. The stored $5/million input, $0.50/million cached input, and
$30/million output rates still match [official standard pricing](https://developers.openai.com/api/docs/pricing)
checked on 2026-09-06. No model or request limit changed for cutover.

Ten similar newly changed schedules would therefore cost roughly $0.67–$1.62
without retries, while two attempts per document would reserve roughly
$6.60–$7.95 in total. These are planning examples, not measured production
workloads. Unchanged cached inputs and sources held before extraction cost $0
in model calls. Four or five weeks of checks do not imply four or five complete
re-extractions.

Recompute the per-document benchmark estimates without model calls:

```sh
unzip -p benchmarks/pdf/physical-pool-labels-2026-09-05.zip results.json |
  jq 'group_by(.reference) | map({reference: .[0].reference,
    calls: length, min_usd: (map(.cost_usd) | min),
    max_usd: (map(.cost_usd) | max),
    reserve_usd: ((map(.reserved_microusd) | max) / 1000000)})'
```

Recommendation, not implemented: replace the fixed $1 run allowance with the
sum of conservative request estimates for eligible uncached PDFs, including
the permitted transient retry, bounded by the remaining $5 monthly allowance.
Report expected cost separately from reserved cost, and release unused
reservations only after valid usage settlement. Keep holds, request limits,
and monthly accounting intact. The $1 cutover limit remains until this change
is approved and tested.

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

A separate job opens a draft PR on `review/closures/<pool>-<PDF hash prefix>`.
Its generated diff contains only the source PDF and `closure-review.md`, never
guessed closure hours, a CI attestation, or projected content. The PR includes
the source evidence and a checklist for a human correction. It never auto-merges.
Merging the evidence note alone does not resolve a closure or approve hours.

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

- `SCHEDULES_MONTHLY_BUDGET_USD=5` is configured in GitHub, matching the recurring ceiling.
  September's recorded ceiling was lowered from $20 to $5 with automation
  paused and no active reservations. Both prior settled runs and all charges
  were preserved in an ordinary fast-forward accounting commit; the ledger
  was not reinitialized.
  The original $10 benchmark trial remains a separate historical allowance.
- The operator confirmed a limited human reference spot-check on 2026-09-06:
  North Beach summer (June 9–August 15, 30 weekly sessions, June 19 and July 4
  closures) and Garfield maintenance (August 14–September 7, no sessions).
  This does not attest the other reference answers or the Garfield fall grid.
  Ambiguous closure scope remains a hold and produces a draft review PR.
- Store `OPENAI_API_KEY` and a repository-scoped `SCHEDULES_BOT_TOKEN` as Actions
  secrets. The publication token needs Contents read/write and must trigger CI;
  the built-in Actions token is not its publication fallback. The workflow uses
  the built-in token only for read-only CI lookups.
- Keep main's required `check` status, strict updates, administrator enforcement,
  and no force pushes. Permit the publication token to create closure-review PRs;
  auto-merge is not used.
- Accounting was initialized on 2026-09-06. Do not initialize it again.
  Missing accounting in later runs must be repaired, not reset.
- Set `SCHEDULES_AUTOMATION_ENABLED=true`, dispatch an `extract-only` trial, inspect
  its evidence and charges, then run a checked publication trial. Confirm hosted
  CI, main promotion, and the exact live deployment before declaring autonomy.

### Evidence and recovery

The [extraction-only cutover trial](https://github.com/cbzehner/swimfrancisco/actions/runs/34049718694)
completed on 2026-09-06 with no API requests and a settled $0 charge. It held
ten PDF inputs for closure review and skipped North Beach's split PDFs. Direct
sources returned one successful extraction, seven unchanged results, and seven
failures (six HTTP 403 responses and one missing expected page marker).

The [publication cutover trial](https://github.com/cbzehner/swimfrancisco/actions/runs/34059756714)
passed [candidate CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34059851327)
and pushed `3dcd27bbaecf72081b1fb976cf43c53d11975af3` directly to main.
[Main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34060044948) also
passed. Its generated changes updated source captures and registry metadata,
not published swimming hours. Cloudflare build
`df74342f-f9f0-4edc-b255-03b765b98050` failed; production still served `8ba8e46`
when the failure was checked. This is not a successful autonomous publication.
`SCHEDULES_AUTOMATION_ENABLED` was set back to `false`. The available local
Cloudflare OAuth credential could not read build logs (HTTP 403). Later logs
supplied by the operator confirmed that the GitHub CI lookup was unauthenticated
and an HTTP 403 retry delay consumed the remaining deployment-gate deadline.

The publication runner reached its bounded live-verification timeout and
recorded `status=failed`, with no confirmed live updates. It made no model
requests and settled at $0, leaving the full $20 monthly allowance available.
The separate closure-review and operator-report jobs both succeeded. Draft PRs
#95–#104 contain only `closure-review.md`; their source PDFs were already in
the repository. A local replay against the retained publication evidence reused
all ten PRs without changing any PR head or main. The current failure is tracked
in [operator issue #94](https://github.com/cbzehner/swimfrancisco/issues/94).
The [recovered publication trial](https://github.com/cbzehner/swimfrancisco/actions/runs/34082697652)
passed [candidate CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34082900294),
pushed `723ab1d0103402b3ae00120f8251ccd20ffee895` directly to main, and passed
[main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34083089300).
Its first Cloudflare build failed because `GITHUB_TOKEN` existed only as a
Worker runtime secret. The operator added the token to **Builds → Variables
and secrets** and retried the same commit. Cloudflare build
`7faf256f-b6db-4a58-807b-f7c781c27342` succeeded, and the running publication
trial verified that exact deployment before its deadline and recorded
`status=published`. All three workflow jobs succeeded. No swimming hours
changed: only source captures changed. There were no API requests and the
monthly ledger settled the run at $0. Closure review reused PRs #95–#104.

The [fresh unattended confirmation](https://github.com/cbzehner/swimfrancisco/actions/runs/34084043126)
then completed without a manual deployment retry. It passed
[candidate CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34084164907),
pushed `9cf591194aedf4a08d897359b0cc7dce4043f4f0` to main, passed
[main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34084392269), and
deployed through Cloudflare build `879239d4-3dc4-4a24-b2bd-3a06ead8a39c`.
The hosted live checks verified the exact commit, all 30 canonical locations,
pool pages, conditions freshness, and map loading in WebKit and Chromium.
All three workflow jobs succeeded and the receipt recorded `status=published`.
Again, source captures changed but swimming hours did not. There were no model
requests, the run settled at $0, and its closure-PR receipt exactly matched the
recovered trial's receipt. All ten PR heads remained unchanged. All four
cutover runs are settled at $0; the full $5 monthly allowance is available.
`SCHEDULES_AUTOMATION_ENABLED=true` is confirmed. The next weekly check is
Monday, September 7, 2026 at 16:00 UTC (09:00 Pacific daylight time).

These trials are not evidence that every source can update without review.
Ten city PDF inputs are held for unresolved closure checks, and North Beach's
split PDFs were unsupported during these historical trials. Discovery found the fall Cool Pool PDF (29953)
and Warm Pool PDF (29954), both listed for September 1–December 12, but held
them as `split_part`; the missing live North Beach schedule is a pipeline
capability gap, not an absent official schedule. Six direct sources returned HTTP 403 in the
recovered trial. Non-city candidates are outside the publisher's current
automatic-acceptance scope (`not_rec_park`) and need explicit human review.
These exceptions retain prior valid data without extending expired hours.
The operator issue and closure PRs remain open; successful workflow execution
does not certify those held sources or demonstrate a hosted paid API call.

Each run retains `tmp/automation/result.json`, per-build discovery and publication
reports, source PDFs, provider artifacts, accepted snapshots, and sanitized
budget ledgers as a GitHub artifact for 90 days. The receipt records base and
candidate commits, changed paths, CI URL, outcomes, and confirmed live updates.
Historical benchmark ZIPs remain committed with hashes and pinned replay
instructions above. Run artifacts exclude credentials and raw transport logs.

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

## Future

Semantic XLSX fingerprinting remains separate work. This workflow uses existing
source-byte identity and does not introduce semantic identity or canonicalization.

## Hosted direct-source access investigation

The follow-up inspection of [run 34191084886](https://github.com/cbzehner/swimfrancisco/actions/runs/34191084886)
used its saved `extraction-report-direct.md` and bounded read-only requests.
JCCSF and all four YMCA location pages returned hosted HTTP 403 with
`server=cloudflare` and `cf-mitigated=challenge`. SFSU returned hosted HTTP 403
with `server=Pantheon`. These are access failures, not evidence that their
schedules are absent. All six exact URLs returned local HTTP 200 using the
production httpx client and identifying schedule-bot User-Agent. Local success
is not hosted access proof. No challenge bypass, provider call, or publication
change formed part of this investigation.

The [official YMCA aquatics page](https://www.ymcasf.org/aquatics/)
embeds `https://embed.upace.app/equipment/103/schedule?facility_id=all&equipment_type_id=13`.
The public embed loaded locally without login and requested the public GET
endpoint `https://upace.app/api/equipment/schedules/unauth`. Its observed query
used `facility_id=`, `equipment_type_id=13`, `university_id=103`,
`start_date=2026-09-06`, `end_date=2026-09-12`,
`exclude_if_closed_or_cancelled=true`, and `exclude_past_classes=true`.
The screen displayed September 7–13, 2026. The date offset and filtering require
explanation before these rows can establish a complete dated schedule.

The returned all-location schedule included Chinatown (`gym_id=733`, room
`Pool`) and Embarcadero (`gym_id=732`, rooms `Pool` and `Activity Pool`). It
contained four Chinatown Lap Swim slots and three Pool Closed slots, plus six
Embarcadero Lap Swim and six Rec Swim slots. Embarcadero also had a separate
hot-tub closure. Stonestown and Letterman/Presidio had no returned schedule
rows. Absence must not become a closed-pool assertion. Individual slots exposed
weekday/time values rather than explicit occurrence dates. A cutover therefore
needs confirmed coverage for all four facilities, complete cancellation and
closure semantics, pool identity, and the exact timezone/date-window contract.
The existing access-hours parsers and manual publication policy remain in place.

[JCCSF's official aquatics page](https://www.jccsf.org/fitness/aquatics/) now
links a [first-party seven-page pool PDF](https://www.jccsf.org/wp-content/uploads/2026/08/260814_AQU_PoolSchedules-Aug-Oct_v2dm.pdf),
not the historical SharePoint source described in the registry note. The PDF
returned local HTTP 200 and has SHA-256
`39d3939ee434f0a3db93cb7d0de04a286a8f774bca881e17073c565c06b9e92e`.
It matches the previously rendered inspection copy and prints “Updated 8/14/26”.
The filename's August–October wording is not a printed effective-date window.
The HTML and Monday PDF page agree on the changed 13:30 family-swim reopening.
The HTML also contains third-Sunday early closing and Swim School closures;
those notices must retain their own scope. No hosted PDF fetch or complete
seven-page extraction acceptance is claimed.

[SFSU's current aquatics URL](https://campusrec.sfsu.edu/Aquatics) remains
locally valid. Its linked `/aquatic` alternative returned local HTTP 404, so it
is not a replacement. The current page uses Monday–Thursday and Friday–Saturday
natatorium-hours groups, which the older parser rejects. These are pool access
hours, not proof of lap-lane availability. No verified supported alternate feed
was found.

Next access decisions require operator-supported bot access or an explicitly
supported complete schedule feed. For YMCA, confirm whether the public embed
covers Stonestown and Letterman, how to include cancelled/closed occurrences,
and which timezone and inclusive dates define the requested week. For JCCSF,
confirm an accessible authoritative PDF link and effective-date policy. For
SFSU, confirm permitted hosted access or an official published equivalent.
These are questions to resolve; no external messages were sent. Do not replace
these holds with client impersonation, proxies, or inferred hours.

## Source-supported city hold resolution

The approved follow-up resolves only facts established by frozen original PDFs.
Coffman's August 18–December 12 schedule lists August 27, September 24, and
October 22 training exclusions. Its only omitted fourth Thursday is November 26,
which a separate notice explicitly closes for Thanksgiving. Sava's current
August 29–December 12 schedule has the same holiday-covered omission. The
verifier preserves the listed training dates and the separate holiday closure;
it does not create a training event on Thanksgiving. Only an independent,
explicit full-day facility notice can justify such an omission. Pool-specific,
partial-day, conditional, reopening, and circular recurrence evidence cannot.

Sava's “morning of December 22” notice explicitly gives 09:00–11:00. Those literal
dates and times remain source evidence; the schedule still ends December 12.
Balboa's December 12 in-service notice gives no duration and remains held.
Sava's fall Thursday Senior/Therapy cell prints 10:00 a.m.–12:00 a.m.; this
unsupported session duration holds the current document before paid extraction.
Do not silently correct midnight to noon. The expired Sava interim PDF also
remains held for unclear recurrence and duplicate source sessions. These sources
cannot establish replacement hours without clarification.

Garfield explicitly assigns Main Pool to lap swim and Small Pool to family swim
within shared-time cells. Each program retains its own allocation. Column
character ownership prevents a clipped neighboring glyph from becoming another
weekday's text. Unknown allocation wording must still hold the source. The
Wednesday Rec/Family Swim School Groups entry is a school booking. MLK's exact
Bayview Safety Swim & Splash program is a registered youth lesson, as confirmed
by its [official program page](https://www.sfrecpark.org/1613/Bayview-Safety-Swim-Splash).
Both remain in original source evidence and do not become public drop-in sessions;
changed or combined program names must pass the independent inventory anew.

Rossi prints both clocks in `2:00pm–3:30`; only the ending suffix is absent. The
parser accepts an unlabeled ending clock only when an explicit PM start and
same-day ordering establish a later afternoon end. It does not supply missing
clock values or resolve ambiguous morning, overnight, or fully unlabeled ranges.

The shared verifier and prompt changes invalidate component extraction caches
through the existing full configuration identity. Frozen-source tests and mocked
responses precede any hosted API validation. Each hosted run retains the $1
reservation and the unchanged $5 monthly durable ledger; no benchmark allowance
or local paid extraction applies. Non-city publication authority is unchanged.

Local validation passed `just check`: 1,226 Python tests (55 skips), 197
JavaScript tests, 35 browser tests, localization, Worker types, and build. The
final unsupported-duration guard then passed 264 focused source, grounding, and
extraction-contract tests. These checks made no model calls. Automation was
paused for the controlled rollout; hosted validation and live verification must
succeed before weekly operation resumes.

A final prompt/verifier consistency check found Coffman's “4 lanes; may vary”
count. It has no named pool or section, so its pool label remains null while the
literal caveat stays in source evidence. Named physical allocations retain their
qualifiers. The correction passed 259 focused source/extraction tests, including
the frozen original and seven numeric-versus-named allocation cases, without
model calls.

The first hosted follow-up [34195357373](https://github.com/cbzehner/swimfrancisco/actions/runs/34195357373)
completed six paid requests for $0.739270 and published independently accepted
Coffman, MLK, Mission, and Pomeroy updates at
`194c8cc1426b650dbed7648a537e1cc9db5615e0`. Candidate CI, main CI, Cloudflare,
and the exact-commit browser smoke passed. September spending settled at
$1.738180. North Beach and Rossi made no requests after the run could no longer
reserve another request within $1. Balboa and both Sava sources held before
model calls. Garfield's model response had all 33 sessions and six closures but
incorrectly copied facility closure dates into 22 session exclusions; independent
verification rejected it. Hamilton's response omitted source closures and failed
before a provider artifact was written. Its $0.140025 charge is known, but the
exact omitted closure cannot be recovered from that run's retained files.

The trial exposed two bounded automation corrections. A current-configuration
model artifact with failed independent coverage cannot remain a reusable cache
entry forever: retry it through the accounted provider while retaining prior
reviews until acceptance. Valid caches still make no calls; malformed or
identity-mismatched artifacts still hold. The prompt now explicitly separates
session-cell cancellations from facility closures and separate recurrence
notices. This changes configuration identity normally, without relabeling old
responses. The existing workflow now retains `api-budget/api-attempts/` request
and response files as well as budget receipts, including responses that fail
before provider artifact creation. Those files contain public source/request
bodies and model output, not authorization headers or keys. The earlier missing
Hamilton response is not claimed as retroactively retained.

The cache/exclusion/evidence follow-up passed `just check`: 1,250 Python tests
(55 skips), 197 JavaScript tests, 35 browser tests, localization, Worker types,
and build. Its pipeline regressions use independent cached-artifact verification
and mocked paid-provider calls, including failed retries that preserve the prior
review and malformed-cache cases that never call the provider.

The next accounted runs charged $0.461875
([34196672255](https://github.com/cbzehner/swimfrancisco/actions/runs/34196672255))
and $0.716080
([34197948665](https://github.com/cbzehner/swimfrancisco/actions/runs/34197948665)).
September's durable ledger settled at $2.916135, with $2.083865 remaining.
The latter run accepted Hamilton with the clarified prompt. Its retained
Garfield response contains all 33 source sessions and no false session
exclusions, but represents the same Thanksgiving notice as November 26–27
instead of two singleton dates. The strict interval comparison held Garfield.

Grouped all-day closure dates can match independent singleton source entries
only when they cover exactly the same consecutive dates, physical pool scope,
reason code, and original notice. Canonical closures retain the independent
source entries; raw model facts remain unchanged. Gaps, extra dates, partial
days, duplicate model intervals, and mixed notices still fail. Existing exact
interval matches retain their behavior. This provider change invalidates caches
through the full configuration identity; it does not relabel prior responses.

The completed grouped-closure rollout used two accounted runs:

- [34200692356](https://github.com/cbzehner/swimfrancisco/actions/runs/34200692356)
  made seven completed requests for $0.741500. Garfield passed with 33 sessions,
  five untouched raw model closures, and six canonical source closures. North
  Beach Cool passed and was cached, but the run could not reserve Warm within
  $1. Publication held the whole pair. The accepted city updates deployed at
  `12dd5cd55d43ad3f53ae9c7d26a452238b5e6fd5` after candidate and main CI.
- [34202066893](https://github.com/cbzehner/swimfrancisco/actions/runs/34202066893)
  reused the seven accepted component artifacts and made only two requests:
  North Beach Warm ($0.109970) and Rossi ($0.101485). Both passed. The complete
  North Beach pair and Rossi deployed at
  `dab82ff1847263d3d2964cb695adab44856ab767`, with successful
  [candidate CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34202363924),
  [main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34202859195),
  exact-commit deployment, and hosted live checks.

All nine current city component artifacts also passed a separate local
`verify_artifact` replay against original PDF bytes and the current prompt and
configuration, without network or model calls. It checked payload reconstruction,
source evidence, sessions, effective dates, closures, and cell exclusions. The
North Beach bundle retains the original Cool/Warm URLs and full byte hashes,
15 Cool sessions, 20 Warm sessions, and September 1–December 12 dates.

Final schedule CI passed 1,287 Python tests (55 skips), 197 JavaScript tests,
35 browser tests, localization, Worker types, and build. Local `just check`
passed before publication; the final duplicate guard additionally passed all
91 extraction-contract tests and independent review. Tests used frozen original
PDFs and deterministic responses, without paid calls or benchmark answers as a
verifier.

The required `node scripts/smoke-production.mjs
--expected-commit=dab82ff1847263d3d2964cb695adab44856ab767 --browser` passed
for all 30 canonical spots. Additional WebKit and Chromium checks passed 80
source-based scenarios on the board and individual pages: 28 for Coffman,
Garfield, Rossi, and future MLK; 24 for Hamilton, Mission, and current MLK;
eight for Pomeroy; and 20 for North Beach. Checks covered simultaneous physical
pools, excluded school bookings, source-cell cancellations, full and partial
closures, effective windows, expiry, Pacific midnight, and daylight saving time
with a Tokyo visitor timezone. Pomeroy's September 8 observation expires after
September 21; no prior observation window was extended.

The durable September ledger settled at $3.869090, leaving $1.130910 of $5.
This city-source follow-up spent $2.870180, including rejected responses; no
usage reservation remains unresolved. Request/response evidence and spend
receipts use the existing workflow artifact retention. Weekly Monday 16:00 UTC
automation was restored only after live verification, with the unchanged $1
per-run reservation and model configuration.

Remaining city holds are Balboa's unspecified December 12 closure duration and
the two Sava inputs: the current grid's literal Thursday 10am–12am session and
the expired interim grid's unresolved recurrence. Do not infer corrected hours.
Ambiguous closure notices remain on the existing review-PR path. Six hosted
direct-source HTTP 403 failures remain unresolved; local HTTP 200 responses and
the official alternatives described above do not establish hosted ingestion.
Other non-city publication remains manual, with only the existing Pomeroy
exception. A successful workflow does not mean every pool is automated.

## Cloudflare primary capture for blocked HTML sources

The registry selects exactly one `capture_method` for each source. JCCSF,
Chinatown YMCA, Embarcadero YMCA, Stonestown YMCA, Presidio/Letterman YMCA, and
SFSU use `cloudflare_browser`. Other sources use `http`, including city PDFs.
There is no fallback chain. A failed browser capture holds that source.

The existing schedule workflow captures these six pages through
`scripts/capture-schedules.mjs` before direct extraction. One Cloudflare Browser
Run session visits the six approved URLs sequentially. Each source retains its
original main-document HTML bytes, rendered HTML, screenshot, exact URLs,
response status, timestamp, browser version, and capture configuration and
hashes. Parsing uses original HTML, never silently substitutes rendered DOM.
These are HTML sources; this change does not claim original JCCSF PDF capture or
YMCA calendar-feed acceptance.

The Python consumer requires a completed capture with confirmed browser closure,
matching source/configuration/evidence identities, and a capture no older than
15 minutes. It holds changed redirects, failed responses, missing or mismatched
files, and stale receipts. Browser evidence remains in each build's retained
workflow artifact even when parsing fails. It is not added to the generated-file
publication allowlist. Accepted direct artifacts bind capture provenance inside
their configuration; reviewed envelope fields retain their existing contract.

Stale-main rebuilding performs a fresh capture against that checkout's registry
and implementation. Browser captures are not copied as extraction caches.
Each workflow run has a separate 300-second browser allowance. Before session
creation a batch reserves 150 seconds; an 80-second active deadline plus the
60-second idle expiry bounds abandoned sessions. Confirmed closure settles
elapsed time conservatively; uncertain closure retains the reservation and
blocks another browser. The run budget uses an exclusive lock. No capture
retries or concurrent browser sessions are used. This accounting is separate
from the unchanged durable $5 model ledger and $1 model reservation.

GitHub Actions needs `CLOUDFLARE_BROWSER_API_TOKEN` as a repository secret, with
Account / Browser Rendering / Edit restricted to the intended account, and
`CLOUDFLARE_ACCOUNT_ID` as a repository variable. The token does not need Workers
deployment, DNS, or token-administration permissions. Local Wrangler OAuth is
not copied into GitHub. Missing credentials fail workflow setup before spending.
The browser budget and source receipts use the existing 90-day artifact retention.

Local deterministic checks mock browser and API responses; ordinary tests make
no network or model calls. Local capture requires the same two Cloudflare
environment variables and an absolute `SCHEDULES_BROWSER_BUDGET_FILE` pointing
to a fresh JSON run receipt with `limit_seconds: 300`, `used_seconds: 0`, and
`blocked: false`. Run `node scripts/capture-schedules.mjs` before
`just schedules extract --direct`. A completed capture directory is not reused
for another batch; preserve its evidence before starting a separate run.

Capture success does not authorize schedule publication. These six sources
remain manual, and their existing parser guards continue to hold changed or
unsupported source wording. Pomeroy remains the only approved direct automatic
publisher. The exact-commit CI/deployment gate and live verification remain in
force.

Local integration validation used the approved Cloudflare account and one
shared 300-second browser receipt. The first two batches exposed screenshot
readiness timeouts; both closed their sessions and retained conservative charges
(49 and 81 seconds). The final implementation uses Chrome's direct screenshot
command as its sole screenshot path, with an explicit timeout and size bound.
Its third batch captured all six sources, closed successfully, and settled 71
seconds. Total local browser accounting was 201 seconds; model calls and spend
were zero. Cloudflare's subsequent active-session list was empty. This is local
orchestration of real Cloudflare browsers, not yet proof of a GitHub-hosted run.

All six final original HTML captures, rendered documents, PNGs, configuration
identities, hashes, and timestamps passed the Python consumer. Stonestown and
Embarcadero produced manual access-hours candidates with zero swim sessions.
JCCSF held changed afternoon hours, Letterman and Chinatown held explicit
maintenance-closure wording, and SFSU held its changed weekday-hours format.
Those parser limitations are not capture failures and were not relaxed here.
The nine existing city PDF artifacts still passed current independent
verification; this capture integration did not invalidate their model caches.

Hosted validation completed in [run 34310713112](https://github.com/cbzehner/swimfrancisco/actions/runs/34310713112)
on September 8, 2026 Pacific time. The permanent account-scoped Actions token
captured all six sources with HTTP 200 in one batch, confirmed browser closure,
and settled 33 of 300 browser seconds. The retained artifact
`schedule-automation-34310713112-1` contains `browser-budget.json`, model budget
receipts, and `automation/build-1/browser-capture/` with all original HTML,
rendered HTML, screenshots, and full source/configuration hashes. Downloaded
receipts matched the committed capture script and all three evidence hashes for
each source; all six PNGs validated. Capture dates correctly remained September
8 in Pacific time despite September 9 UTC timestamps.

The hosted parser outcomes matched local validation: two manual access-hours
candidates and four holds. Only Pomeroy appeared in `published_slugs`; none of
the six gained automatic publication. Existing city closure holds and an
unrelated Equinox parser hold remained visible. The model receipt had no
requests, and durable ledger entry `34310713112-1` settled at $0. September
model charges remained $3.869090 of $5, leaving $1.130910. Browser seconds are
conservative run accounting, not an invoice-dollar estimate.

The run promoted `f1cb4fc53b219a97f0854e1e83e0b57bcc825796` after exact-commit
[candidate CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34310871671).
[Main CI](https://github.com/cbzehner/swimfrancisco/actions/runs/34311192730),
deployment, and hosted live verification passed. A separate local invocation of
`node scripts/smoke-production.mjs --expected-commit=f1cb4fc53b219a97f0854e1e83e0b57bcc825796 --browser`
also passed all 30 canonical spots. Implementation validation passed `just check`:
1,325 Python tests, 214 JavaScript tests, and 35 browser tests; 55 Python tests
were skipped. Automation remains enabled for Monday 16:00 UTC, with the existing
$1 model reservation, $5 monthly ceiling, and exact-commit deployment gate.

## Deterministic extraction for the six browser sources

The approved implementation publishes supported JCCSF, Letterman, Stonestown,
Embarcadero, Chinatown, and SFSU captures through deterministic extraction.
Cloudflare remains their primary capture method, with no HTTP fallback. There
is no paid HTML model path, model-facts cache, or model scheduling queue.
Pomeroy retains its existing extractor; unrelated non-city sources remain
outside this publication scope. Hosted publication is verified by run `34413507767`, recorded below. The earlier
capture-only run does not establish publication.

Each capture retains original HTML, a full byte hash, the Pacific observation
date, browser receipt, rendered HTML, and screenshot. A source inventory keeps
hours, closed days, exceptions, notices, and their scope. Code derives supported
facts and reconstructs the payload from the original source before publication.
Unknown wording, omitted inventory rows, ambiguous dates, contradictory notices,
and unsupported closure scope hold the source. Printed years remain explicit;
supported relative dates and freshness windows resolve in code. Expired prior
hours never extend because a new source fails.

The frozen captures support four sources: JCCSF's swim hours with its
third-Sunday exception; Letterman's dated maintenance closure; and Embarcadero
and SFSU access hours. Access hours do not establish lap-swim availability.
Chinatown and Stonestown contain conflicting closure notices and remain held.
These fixture results do not establish that all future captures will publish.
Each update must pass source identity, extraction, and publication checks.

Ambiguous HTML closures use the existing evidence-only draft review PR path.
The original HTML and hash remain attached; only the six approved browser
sources may use HTML attachments. A new capture reuses an existing open closure
review for the same source, so harmless HTML changes do not create weekly review
PRs. New captures still remain in workflow evidence. The system does not change
an existing review's contents, and merging a note does not approve changed hours.

Automation retains discovery, browser capture, direct extraction, and city PDF
extraction in that order. Direct extraction consumes no model budget. A
stale-main rebuild captures fresh browser evidence and recomputes publication
decisions; it preserves the existing PDF/model cache reuse and concurrent main
changes. It does not reuse old browser receipts or reviewed decisions.

The city PDF model remains `gpt-5.5-2026-04-23` with medium reasoning. Its durable
`schedule-budget` branch, $5 monthly ceiling, and $1 run reservation remain
unchanged, as does the separate 300-second browser allowance. Source failures
hold that source while independent sources continue. Exact-commit CI, non-force
main promotion, publication file allowlists, evidence retention, and live browser
verification remain required. Ordinary tests use frozen captures and make no
paid calls. Any real city model validation uses the existing accounted workflow.

Fable 5.1 reviewed the model-based proposal and the implementation through Pi.
The user approved removing the redundant HTML model path after the deterministic
verifier already derived the supported facts. The resulting design keeps source
provenance, explicit closure scope and exceptions, deterministic date handling,
and deletion of replaced extractors. It removes paid HTML requests, their cache
and rotation logic, and the duplicate model-facts representation. Model pricing
estimates from the review are not spend receipts. Hosted results and exact live
commit checks must establish deployment success before this rollout is reported
as verified.

Review adjudication retains exact, full PDF extraction configuration identities,
all historical receipts, and the existing live smoke checks. Removing the HTML
model does not justify weakening any of those contracts. Broader core-review
recommendations remain outside this change and require separate review.

Local deterministic validation passed `just check`: 1,435 Python tests (55
skipped), 214 JavaScript tests, and 35 browser tests, plus worker type checks
and the production build. Tests forbid paid HTML calls and cover actual source
extraction through readiness reporting and publication verification.

The first hosted deterministic trial, run `34410514298`, captured all six
original sources and closed the browser session (56/300 seconds). Four browser
sources passed extraction; Chinatown and Stonestown retained their closure
holds. Publication stopped before main promotion because Letterman's closure
lacked the reason category required by content projection. No schedule changes
reached main. The model receipt contained zero requests and $0 charges. The
retained artifact `schedule-automation-34410514298-1` preserves the original
captures, hashes/configuration, extraction reports, and spend receipts.

The correction assigns source-supported closure categories and treats projection
errors as candidate refusals with rollback. The regression now runs all four
supported frozen captures through full publication and content projection.
`just check` passed 1,445 Python tests (55 skipped), 214 JavaScript tests, 35
browser tests, worker type checks, and the production build.

Hosted run `34412111592` passed extraction and content projection for JCCSF,
Letterman, Embarcadero, SFSU, and Pomeroy. Exact-commit CI blocked generated
commit `4dce34e64fce83d30127d41b13d9756a62be6897`: the new integration test
incorrectly used changing live content as the baseline for an older frozen
capture. No changes reached main. Spend was zero model calls/$0 and 55 browser
seconds. Its retained workflow artifact preserves all source and spend evidence.
The test now uses a fixed baseline and checks unchanged and next-day refreshes.

The trial also exposed missing `source.sha256` files in new closure-review PRs.
Review creation now includes the verified digest and rejects conflicting existing
sidecars. The three affected PRs (#105, #106, #107) received only their missing
hash files; all passed CI. No closure decision or published hours changed.

With these fixes overlaid on the actual generated schedule tree, `just check`
passed 1,470 Python tests (55 skipped), 214 JavaScript tests, 35 browser tests,
worker type checks, and the production build. This checks the tests against
updated schedule data, not only the prior checked-in baseline.

Hosted run [34413507767](https://github.com/cbzehner/swimfrancisco/actions/runs/34413507767)
completed with `status=published`. It published JCCSF, Letterman, Embarcadero,
SFSU, and the existing Pomeroy source at exact commit
`1eff139b502acec8f8ceed55a2c8586a5783087f`. Generated-commit CI, non-force main
promotion, main CI, Cloudflare deployment, and hosted browser checks passed. A
separate local `smoke-production.mjs --expected-commit=1eff139b502acec8f8ceed55a2c8586a5783087f --browser`
also passed all 30 canonical spots. The artifact
`schedule-automation-34413507767-1` preserves original captures, full hashes,
configuration, extraction/publication reports, and budget/deployment receipts.

All six Cloudflare captures completed and the browser closed. Browser spend was
52/300 seconds. The model receipt contained zero requests and $0 charges; this
is proof of hosted deterministic HTML publication, not hosted paid extraction.
September model charges remain $3.869090 of $5, with $1.130910 remaining and no
unsettled reservations. The earlier two failed trials also charged $0 and used
56 and 55 browser seconds; the cancelled stale-commit dispatch never reserved
model funds. The spending ledger was not reset.

JCCSF's 23 swim sessions and third-Sunday exception cover the observed September
9–22 window. Embarcadero and SFSU each expose six days of pool access over that
window, not confirmed lap-swim hours. Letterman's explicit maintenance closure
ends September 13. Chinatown and Stonestown remain held for conflicting notices,
using their existing open review PRs. Other city closure holds and unrelated
manual non-city sources remain outside this change. Monday 16:00 UTC automation,
the $1 run limit, and the $5 monthly ceiling remain enabled.

The board now routes verified `temporarily_closed` schedules through the existing
status calculator even when no weekly sessions or access hours are present.
Browser tests cover CLOSED through September 13, CHECK after Pacific midnight,
and current/future horizon selection for a Tokyo visitor. Final local
`just check` with the published schedules passed 1,470 Python tests (55 skipped),
214 JavaScript tests, 37 browser tests, worker type checks, and the build.
