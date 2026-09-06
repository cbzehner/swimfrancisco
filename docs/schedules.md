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
`reviewed.json`, and no publication command reads them. Human sign-off is pending.

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
both windows or `--force` re-extract; North Beach stays until a combined
PDF. A kept sequential window that has already ended counts as covered,
so a late re-export of a past window does not refuse forever.

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
