# Pool Schedule Decision Log

This is an append-only historical record of dated evidence and decisions behind
the schedule extractor. It is not a runbook; current instructions live in
[`schedules.md`](schedules.md).

The evidence archives many of these entries cite (`benchmarks/pdf/*.zip`) and
the CLI commands that produced them (`schedules benchmark*`, `schedules debug
bakeoff`) have been deleted. Result tables that could no longer be reproduced
or replayed were removed; the conclusions they supported are kept below.

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
new automatic acceptance rule. Same-day reuse requires matching bytes,
configuration, and facts. Retention of capture directories is now governed by
the `## Retention` rule in `docs/schedules.md`; older captures are pruned.

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

## North Beach paired-PDF validation evidence

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

## Model selection, September 2026

Seven rounds of comparison chose the production extractor. Each round's raw
results lived in a portable ZIP under `benchmarks/pdf/`; those archives and the
`schedules benchmark*` commands that produced and replayed them no longer
exist, so only the conclusions remain.

### Checked PDF references

`tests/fixtures/schedule-benchmark.json` held source hashes and visual
transcriptions for North Beach summer, Hamilton fall, Balboa fall, and Balboa
interim: 97 weekly sessions and four effective windows. These were
agent-checked development references, **not human attestations**. They never
replaced `reviewed.json`, and no publication command read them. On 2026-09-06
the operator confirmed the North Beach summer sample and the separate Garfield
maintenance sample; the other transcriptions stayed agent-checked.

Method notes that outlived the harness: check documents as full pages with
Poppler, never macOS Quick Look thumbnails, which clipped the Balboa interim
text. Preserve source bytes and record renderer, resolution, and input hashes.
An expired printed window bounds a schedule; it does not mean the facility is
closed. Closure correctness stayed unscored where the source wording was
unresolved, rather than being assumed correct. Pool labels followed the prompt
literally, and pool identity was never normalized away to improve a score.

### Reference decisions, September 5

The operator approved four rules before the finalist round. Keep the literal
pool-label convention and keep standalone numeric lane counts out of pool
identity; do not split a shared slot into inferred pools. Mark Hamilton's
conflicting training hours (Thursday cells cancel 11:00-12:30 and 13:00-15:00
while the facility note gives 12:00-14:00) unresolved rather than picking one
reading. Leave Balboa's hourless training dates unscored rather than inventing
all-day closures. Preserve sessions and printed dates on expired sources and
derive expiry separately.

### CLI comparison, September 4

Twenty-four candidate routes ran across the four development documents: 128
cells, 124 extraction calls, and four cells blocked by expired Claude
authentication. Fifty-eight outputs were strict-schema-valid; a separate
offline diagnostic recovered 52 more complete objects from JSON framing without
changing any value.

Conclusion: Astra on images and Grok 4.6 through Cursor text matched all
checked fields on all four documents. GPT-5.5 text and Gemini 3.8 Flash text
were the speed comparators. The recurring failure across weaker candidates was
pool-label expansion, not lost sessions. The exact production Gemini model,
called through the Gemini CLI, had eight missing and five extra rows. That was
a CLI measurement, not a production API measurement. Harness limits mattered:
the Pi Cursor bridge dropped non-text content, so all Cursor candidates ran on
`pdftotext -layout` text. Subscription usage was never assumed free.

### Finalist comparison, September 5

Four finalists ran each of three reserved sources (Rossi spring, MLK fall,
Garfield maintenance) three times: 36 calls, no timeouts or execution errors.
All diagnostic-valid responses preserved session days, types, times, counts,
effective dates, and the closure-only classification. Every remaining scored
difference was MLK's composite pool labels shortened from `4 & shallow` to
`shallow`.

Conclusion: GPT-5.5 text was the first candidate for production API
confirmation, combining strict JSON reliability with the best literal accuracy
and lower grid latency. This was not a final choice; GPT-5.5 had missed a
Balboa interim session in the September 4 round.

### Production API confirmation, September 5

**Decision: do not switch production yet.** Twenty-one calls through the
OpenAI Responses API with native structured output on `gpt-5.5-2026-04-23`, all
valid, none retried. All 435 session rows had correct days, types, times, and
counts once pool labels were excluded, and every window and classification
matched. Fourteen of 21 runs matched every checked field. The 22 remaining
differences were all shortened pool labels. The references were not relaxed to
make the run pass. Estimated cost was $2.341085 against a $10 approval.

The conclusion was that the extraction contract, not the model, was at fault:
one field asked the model both to preserve and to interpret a printed label.

### Literal pool-label repeat, September 5

**Decision: retain the raw-label separation, but do not switch production
yet.** Splitting `pool_label_raw` (verbatim, model-supplied) from the derived
`pool` value (normalized in code) raised checked matches from 14/21 to 19/21
and the old shortening failures did not recur. Two differences remained on
Balboa interim, where the Poppler layout text contained `(s (small pool)` while
the rendered page showed `(small pool)`. That was a source-text quality problem,
not a model failure, and no case-specific replacement was added. Estimated cost
was $2.316806.

### Production source-inventory repeat, September 5

**Decision: do not enable publication yet.** Repeating the seven known
documents through the full production request (current prompt, coordinate-based
source inventory, pinned PDFium renderer, strict raw-label schema) matched
18/21. Rossi failed all three times by copying program names and numeric lane
counts into the pool-label field; the independent source check rejected every
incorrect candidate. Estimated cost was $2.023499, charged $2.240075 on the
conservative ledger.

### Physical pool labels and Mission holdout, September 5

**Decision: do not enable the new direct-main publisher.** Restricting the
label scope (program names, footnotes, and numeric-only lane assignments are
not physical pool labels) matched all checked fields in 19/21 runs and exact
session grids in 20/21. All three Rossi responses now matched. Two concrete
failures remained: one Balboa interim response wrote `small//main`, which the
source session check rejected, and one North Beach response omitted the July 4
closure while passing both the session and window checks. That second case is
the important one: session and window checks alone do not establish closure
completeness.

The separate Mission holdout (September 2 PDF, three runs) matched all 25
sessions, five facility closures, and its date window. Its untimed Thursday
cell and narrower facility closure notice still needed an approved
interpretation before publication.

Combined estimated cost across the five API comparisons was $8.913187 of the
original $10 approval, leaving $0.658269 after conservative accounting.

## Cost evidence and proposed allowance change (2026-09-06)

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

The archives these figures were computed from have since been deleted, so the
numbers above cannot be recomputed.

Recommendation, not implemented: replace the fixed $1 run allowance with the
sum of conservative request estimates for eligible uncached PDFs, including
the permitted transient retry, bounded by the remaining $5 monthly allowance.
Report expected cost separately from reserved cost, and release unused
reservations only after valid usage settlement. Keep holds, request limits,
and monthly accounting intact. The $1 cutover limit remains until this change
is approved and tested.

## Automation cutover trials, September 2026

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

### Free updates when paid extraction is unavailable

A missing API key or monthly approval, exhausted allowance, or unavailable or
invalid spending ledger disables new model calls without blocking browser
capture, deterministic extraction, cached PDF verification, or publication of
independently valid updates. The budget command records `status: unavailable`
and a zero-limit local ledger with no requests. Workflow summaries and retained
receipts expose that status. Sources that need a model call remain held.

Successful allowance checks still reserve at most $1 through the unchanged
durable `schedule-budget` branch and record `status: reserved`. The $5 monthly
ceiling and existing conservative settlement remain unchanged. Free-only
settlement requires a zero-limit ledger with no requests and makes no durable
ledger write. If a reservation may have reached GitHub before a connection
failure, its full charge remains reserved for later operator reconciliation;
free execution never clears or reinitializes it. Invalid local free-only
accounting fails settlement. PDF closure inspection runs before credential and
budget checks, so free-only runs can still produce review evidence. Paid-ready
sources must pass those checks before rendering or constructing a model request.
This ordering change and the Sava parsing fixes below change the full PDF
configuration and therefore invalidate affected model caches. The production
model and reasoning setting remain unchanged.

### UCSF facility calendar publication

Bakar and Millberry use the same [official 2026 facility and holiday calendar](https://campuslifeserviceshome.ucsf.edu/fitness-and-recreation/news/2026-fitness-and-recreation-holiday-schedule).
Their registry entries permit automatic publication of facility access hours,
not swim sessions or lap-lane availability. The original HTML is frozen at
`tests/fixtures/html-facts/ucsf-holiday-2026.html` for deterministic tests.

The parser validates the calendar identity, all three regular-hours groups,
both facility names, and all 17 holiday rows. It preserves their different
weekend closing times, all-day holidays, and dated partial-day hours. Unsupported
rows, missing rows, conflicting scope, duplicate dates, or unexpected ordering
hold the update. Explicit printed years establish January 1, 2026 through
January 1, 2027 coverage. Each observation lasts at most 14 days and cannot
extend past that printed endpoint. The system does not infer a new year's
schedule from an expired calendar.

Publication checks the exact approved URL and facility/parser identity, original
byte hash, current full extraction configuration, Pacific observation date,
and freshness. It reconstructs the whole payload from retained original HTML
and rejects any changed hours, omitted closures or exceptions, or extended
window. This is deterministic HTTP extraction and uses no model calls. These
sources do not use Cloudflare unless separately approved. Unsupported UCSF
source wording holds publication. Ambiguous closure notices retain their original
HTML and full hash on the existing evidence-only review PR path, including
notices outside the accepted calendar body. Hosted publication must pass the
required commit-specific CI, deployment, and production checks.

### Current-source holds and source corrections

Sava's current original is PDF 30037, printed August 29–December 12, 2026,
SHA-256 `4b1055669e1df46512c16b051b02b8de52d1b935f7cbfde2f27bfe38ff03009c`.
The frozen `tests/fixtures/sava-fall-30037.pdf` covers the exact training-cell
wording and overlapping Notes heading. Source checks preserve the full
September 24 and October 22 12:30–15:00 lap cancellations separately from the
12:00–14:00 facility closures. An expired discovery grid is excluded only when
its full hash and printed window agree with a retained original. Discovery
metadata alone cannot exclude it, and current or future grids remain required.

The printed Thursday therapy end still says 12 a.m. On September 9, the user
reviewed and approved the complete source-specific draft through the human
review path, including the noon correction. Its other changes include Wednesday 14:30–15:30 lap swim,
Friday lap ending at 15:30, and both full Thursday session cancellations.
December 1–19 maintenance does not extend the schedule's December 12 expiry.
The human attestation records that explicit full-draft approval; the original
PDF and literal midnight evidence remain unchanged.

Chinatown's newer original provides separate complete facility and pool hours.
January 1, 2027 lists facility opening at 10:00 and pool opening at 08:00.
The user approved publishing verified dates before this conflict. Chinatown's
pool-access window lasts at most 14 days and stops before the first future
holiday with conflicting facility and pool hours. The conflicting date itself
holds publication; a later observation can publish dates after it. This does
not guess holiday hours, publish lap-swim sessions, or extend an expired window.
Unknown date/scope, conflicting duplicate statements, incomplete weekly hours,
and unsupported closure notices retain the existing review hold. The original
HTML and full source inventory preserve the withheld holiday evidence.
Publication reconstructs the shortened window and rejects any extension into
the conflicting date, even when the capture is otherwise still fresh.

Koret's original workbook, frozen as `tests/fixtures/koret-september.xlsx`,
prints Monday hours as 7 a.m.–7 a.m. Invalid headlines now hold extraction
instead of silently dropping a day. Sunday’s “Deep End Closed” notice does not
close the entire pool. Automatic publication remains disabled until Monday's
closing time is confirmed and lane-level completeness checks cover bookings
and restrictions.

Remaining operator questions include Stonestown's conflicting “Thursday, 09/22/2026” closure end date, and current
2026 holiday hours for both 24 Hour Fitness locations. September 22 is Tuesday.
The linked 24 Hour Fitness holiday page still identifies 2025; the pipeline
must not advance that year by assumption. No operator messages were sent.

Publication reports distinguish the number of pools with refusals from the
number of refused retained candidates. Markdown groups reasons by pool; JSON
keeps every refusal for audit. These counts are not a count of current source
outages. The operator issue reports publication status separately from extraction
commands with held or failed sources: a per-source hold can produce a nonzero
command result while other verified sources publish successfully.

Fitness SF Fillmore and City Sports 20th Avenue also permit automatic facility
access publication. Fitness SF must expose agreeing repeated weekly hours and
empty holiday content fields. City Sports must expose agreeing main and repeated
hours; its maintenance footnote must remain bound to the named non-aquatic
class cancellation. New pool, facility, holiday, or unsupported cancellation
notices hold and retain original HTML on the review-PR path. Frozen original
HTML and source receipts live in `tests/fixtures/html-facts`. Publication repeats
the source checks and rejects changes to identity, original bytes, configuration,
hours, closure coverage, or observation lifetime. Facility hours do not establish
pool lane availability. The existing minute-based midnight representation ends
at 23:59; it does not claim the final minute before midnight.

Equinox verifies its canonical club identity and requires complete agreement
between its structured club hours and every visible club hours group. A visible
“Today” row must identify the sole missing weekday in a complete, ordered week;
the parser does not guess a date. Spa hours remain a separate scope. Populated
holiday fields, unknown service scopes, and unsupported visible or structured
notices hold publication. Both retained page layouts exercise this same source
contract, including the September 9 redesigned original. Gateway uses the individual
`https://www.bayclubs.com/clubs/thegateway` page, with its exact name, address,
pool amenities, seven-day hours, and dedicated notice field. It does not choose
among the four campus cards. Both publish facility access only and use the same
original-byte, identity, configuration, observation, and publication checks as
the other approved HTTP access sources. They use no model calls.

Local release validation on September 9 passed `just check`: 1,642 Python tests
(55 skipped), 214 JavaScript tests, 37 browser tests, worker type checks, and the
build. Ordinary tests made no model calls. They include zero-allowance cached
PDF reuse, free closure-review evidence, unchanged durable accounting, complete
original-source publication and tamper rejection, expired-grid exclusion,
Sava session cancellations, and non-aquatic City Sports class replacements.
Automation remains enabled; these changes do not require pausing it because
source formats remain valid for existing readers and stale-main/commit-specific
CI protections remain in place. Hosted results and spend receipts must be read
from the subsequent accounted Actions run, not inferred from local tests.

### Approved Sava and Balboa source reviews — September 9, 2026

The user explicitly approved both complete review drafts. Both snapshots were
finalized through `finalize_draft` and projected into their individual pool
content. No model request was made for either review.

Sava uses official PDF [30037](https://sfrecpark.org/DocumentCenter/View/30037),
SHA-256 `4b1055669e1df46512c16b051b02b8de52d1b935f7cbfde2f27bfe38ff03009c`.
Its 20 public-swim rows include Wednesday 14:30–15:30 lap swim and Friday lap
until 15:30. Thursday therapy is approved as 10:00–12:00, with the original
`10:00 a.m. -12:00 a.m.` retained as evidence. Thursday 12:30–15:00 lap swim
is fully excluded on September 24 and October 22. Nine closure rows retain
printed maintenance through December 19 and the December 22 training notice;
the operating schedule still expires December 12. No general meridiem
correction or extension of expired hours was introduced.

Balboa retains all 22 swim rows and six other closures from official PDF
[29796](https://sfrecpark.org/DocumentCenter/View/29796), SHA-256
`d6f21871037274cc7b8817ab17a92eb7fec8b8d9dfa915d1cb72182b9526dda9`.
The approved December 12 closure is 09:00–12:00, replacing the prior all-day
interpretation. Balboa's in-service note does not give times, but both official
North Beach schedules explicitly say all city pools close December 12 from
09:00 to noon. Supplemental originals and literal page-one Saturday notices
are retained with the closure:

- [Cool 29953](https://sfrecpark.org/DocumentCenter/View/29953), SHA-256
  `6c2b2e77fb2370a1aee52203c9d8672fc5e55ab398875a72f83156ac3b23397c`,
  notice `p1-c5-b20-notice`.
- [Warm 29954](https://sfrecpark.org/DocumentCenter/View/29954), SHA-256
  `ac196df42a14a71cd86fbb13972706e22b5e5cf8dcc5820f660d57882bfd25c8`,
  notice `p1-c5-b28-notice`.

Balboa's afternoon December 12 sessions therefore remain available. Its
September 24 and October 22 training still starts at its explicitly printed
11:30. The fourth-Thursday November 26 cancellation is covered by Thanksgiving.
August 22 and August 27 precede this fall window; no historical closure time
was inferred. Existing session notes about Tuesday lap until 16:00 and
Thursday recurrence are restored in projected content. These approved reviews
do not enable automatic cross-source closure propagation.

### September-only spending approval

The user approved an additional $1 for September 2026, raising that month's
ceiling from $5 to $6. The default monthly ceiling remains $5, and each run
still reserves at most $1. This approval does not resolve ambiguous source
notices or permit new calls outside the accounted workflow.

`SCHEDULES_MONTHLY_BUDGET_OVERRIDES` accepts explicit calendar-month approvals,
for this authorization `{"2026-09":6}`. The workflow passes this variable to
the existing budget commands. October 2026 and every other month continue to
use `SCHEDULES_MONTHLY_BUDGET_USD=5`; no scheduled reset is needed. Missing or
empty overrides retain the default. Invalid overrides disable paid extraction
through the existing free-only receipt path.

A changed variable alone cannot change the durable ledger. After checks and
explicit approval, the operator applies the matching amendment with:

```sh
SCHEDULES_MONTHLY_BUDGET_USD=5 \
SCHEDULES_MONTHLY_BUDGET_OVERRIDES='{"2026-09":6}' \
uv --project schedule-tools run --locked schedules budget increase \
  --month 2026-09 --from-usd 5 --to-usd 6
```

The command requires the current month, the exact prior cap, a greater approved
cap, an existing month, and an unblocked ledger. It changes only that month's
limit. Existing charges, active reservations, other months, and commit history
remain intact. Its non-force append fails on concurrent ledger changes; reruns
cannot reset or reapply the prior cap. The workflow never runs this amendment
automatically. PDF provider code and extraction configuration remain unchanged
by this budget approval mechanism.

### Deferred schedule work

These work items remain open after the September 9 source reviews. They do not
authorize operator messages, guessed corrections, or additional model spending.
Keep source evidence and existing review holds until each item's checks pass.

- [ ] **Confirm Chinatown's January 1 pool and facility hours.** The
  [official location page](https://www.ymcasf.org/location/chinatown-ymca/)
  lists January 1, 2027 facility hours as 10:00–16:00 and pool hours as
  08:00–13:30. The repeated pool statement agrees with the pool statement,
  but the facility and pool opening times conflict. Retain the original in
  `tests/fixtures/html-facts/chinatown-ymca-reopened.html`. Obtain a corrected
  official statement or an explicit source-specific review before publishing
  that date. The separately approved date-limited publication policy may
  publish an earlier verified window; it does not resolve January 1. Done when
  both scopes agree, the source checks pass, and January 1's individual-page
  and board behavior is verified in Pacific time.

- [ ] **Confirm Stonestown's last closed date and reopening time.** The
  [official notice](https://www.ymcasf.org/location/stonestown-family-ymca/)
  gives a pool, sauna, and spa closure from August 21 through “Thursday,
  09/22/2026.” September 22 is Tuesday. Ask which date is the last closed day
  and when the pool first reopens; the printed range end is not itself a
  reopening announcement. Preserve pool-specific scope and do not infer
  September 22 or September 24. Member Services lists
  `memberservices@ymcasf.org` and (415) 242-7100. Ask for both dates and the
  reopening time in Pacific time, whether the pool, sauna, and spa reopen
  together, and a corrected notice or current pool schedule.
  Done when the corrected source dates and
  weekdays agree and publication cannot extend closure or prior hours beyond
  their verified window. The retained original is
  `tests/fixtures/html-facts/stonestown-ymca.html`.

- [ ] **Confirm Koret's Monday closing time and validate lane coverage.**
  The [official workbook](https://docs.google.com/spreadsheets/d/1PcFSl3ndScM2-SZnubwDvBlbhpmbFsVjEPK-yGilZU0/edit?gid=1958899859&pli=1)
  prints `Hours: 7am-7am` in Monday cell A2. Obtain the corrected closing time;
  evening bookings alone do not establish it. Then independently account for
  all lane cells, bookings, closures, shallow-lane restrictions, and the
  Sunday deep-end closure before enabling automatic publication. Preserve
  `tests/fixtures/koret-september.xlsx` as the regression source. Done when
  missing days, unaccounted bookings, and wrongly broadened lane closures
  reject publication, while complete supported schedules pass.

- [ ] **Obtain current 24 Hour Fitness holiday coverage for both clubs.**
  [Potrero](https://www.24hourfitness.com/gyms/san-francisco-ca/potrero-sport)
  and [Ocean](https://www.24hourfitness.com/gyms/san-francisco-ca/ocean-sport)
  link a [holiday page](https://www.24hourfitness.com/locations/holiday-hours)
  that still identifies 2025 and allows club-specific differences. Monitor
  for an explicit 2026 update or obtain an official confirmation for both
  clubs, including Thanksgiving, Christmas, and New Year reopening hours.
  Do not advance a printed year. Done when originals for the relevant year
  and both club identities support all exceptions, with tested December–January
  rollover and no extension of expired hours.

- [ ] **Define reuse and renewal of approved Sava and Balboa reviews.**
  The [September 9 full-source approvals](#approved-sava-and-balboa-source-reviews--september-9-2026)
  resolve the current Sava noon correction and Balboa December 12 09:00–12:00
  closure. They are not outstanding requests for the same answers. Specify
  how unchanged approved source bytes reuse those reviews without repeated
  work, and how changed primary or supplemental documents require a fresh
  comparison and review. Keep the literal source text, full hashes, reviewer
  decision, and effective dates; never turn these approvals into a general
  meridiem correction or automatic cross-source closure propagation. Done
  when unchanged reviews remain usable, changed evidence cannot silently
  inherit an attestation, and expired schedules remain expired.
