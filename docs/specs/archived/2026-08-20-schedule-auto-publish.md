# End-to-end Auto-Publish of Pool Schedules

**Author:** TBD
**Date:** 2026-08-20
**Status:** Implemented
**Audience:** Operators of the schedule extract/review pipeline

---

## Approved hands-off publication contract (2026-09-05)

This section supersedes the PR-based publication design below. The remaining
sections record the original implementation and its rationale, not the target
workflow. Keep Python and GitHub Actions; do not add an agent framework, service,
or permanent alternative publication path.

On 2026-09-06 the operator approved draft PRs specifically for unclear closure
notices. This is an exception-review path, not a second automatic publisher.
Verified changes continue directly to main after exact-commit CI. Closure PRs
contain source evidence and a review checklist, never inferred hours; only a
human correction can supply a reviewed snapshot and content changes. Reuse the
same pool/source PR and preserve reviewer edits. Do not auto-merge these PRs.

### North Beach paired-source extension (approved September 6, 2026)

Support exactly one official Cool/Warm pair with matching printed windows.
Extract and independently verify each original, then atomically attest and
project one combined facility schedule. Preserve original bytes, URLs, full
hashes, source cells, literal allocation labels, and separate physical pool
identity. Cache each component by bytes and complete extraction configuration;
bundle identity includes both members. Missing or failed members, conflicting
windows or closures, unsupported formats, and stale source identities hold the
whole update. Never extend expired prior hours.

Pool-specific closures and explicit whole-session exclusion dates retain their
scope through review, projection, board status, and Pacific-time Today rows.
Ambiguous closure wording remains a draft review PR. Single-document behavior,
provider/model, spending limits, and checked direct-main publication remain in
place. See `docs/schedules.md` for artifact shapes, frozen sources, tests, and
rollout evidence. This extension does not reinstate the historical PR publisher.

### Closure coverage and direct-source pilot (approved September 7, 2026)

Support explicit inherited-month holiday lists/ranges, separate maintenance
footers, and clearly associated date/time clauses. A cancellation printed in a
session cell cancels the whole session; a separate facility notice retains its
own duration. Apply exclusions to single-document schedules as well as North
Beach. Uncertain scope, contradictory recurrences, and suspect dates remain on
the closure-review path. Other independent source failures still hold an update.

Derive closure display codes from independently parsed source notices, retaining
their identities/text and the separate model reason. Pool bundles must agree on
facility closure meaning and preserve both originals. Project only explicit
recognized codes. Migrate existing reviewed codes once through the exact label
catalog without claiming new source verification; preserve paid responses.

Direct captures now identify original bytes and the complete parser/schema
configuration. Keep observation dates separate in `direct_source` evidence.
For undated pages, the projected validity window runs from the observation date
through thirteen days later, inclusive, in Pacific time. This is an approved
freshness lifetime, not a printed effective window. Failed fetches cannot renew
it. Historical normalized hashes are not original-byte attestations and cannot
qualify for automatic publication.

Only `pomeroy-pool`, explicitly opted in at its approved operator URL, may enter
the direct-source pilot. Independently inventory every supported session and
excluded class, closure notice, and therapeutic restriction. Hold unfamiliar
content. Preserve limited-public/therapy access and slow-lap-only limits. Other
non-city sources remain manual; access or facility hours never establish swim
sessions. HTTP diagnostics retain sanitized status/URL/header evidence; permanent
HTTP failures do not retry. Do not bypass access controls.

Pause scheduled automation during the shared-format cutover. Run frozen-source
tests and `just check`, then exact-commit CI/deployment and accounted hosted
validation before restoring weekly operation. Keep the durable $5 monthly/$1
run budget, existing model, stale-main checks, publication allowlist, non-force
main promotion, and exact deployed-commit browser verification.

### Source-supported city hold resolution (approved September 7, 2026)

Resolve only facts established by the original sources: program-specific pool
labels within a shared-time cell; exact named registered lessons and school-group
bookings; an explicit afternoon start with an unlabeled ending clock that can
only fall later in the same afternoon; and recurrence lists whose omitted dates
are independently covered by explicit full-day facility closures. Preserve the
printed date list without inventing training sessions on a holiday. Partial-day,
pool-specific, circular, missing, or contradictory evidence cannot resolve a
recurrence conflict. A morning qualifier requires an explicit associated morning
time range; retain literal out-of-window dates without extending the schedule.

Keep genuinely ambiguous notices and malformed sources held. Drop-in source
sessions longer than twelve hours remain unsupported; never correct a printed
midnight to noon. Investigate hosted
403s through operator-linked alternatives and supported public access only;
access success does not authorize publication or prove source completeness.
Other non-city publication remains manual. Preserve the existing model, budget,
ledger, independent verification, atomic publication, CI and deployment gates.

### Terms

- **Source facts:** what an official document explicitly states, including its
  dates, pool labels, sessions, and closures. An expired document remains evidence
  of a historical schedule, not evidence that the facility has closed.
- **Raw pool label:** the complete printed allocation for a session, stored as
  `pool_label_raw`, or null if absent or only a numeric lane count. The model
  copies it without shortening qualifiers or expanding source codes.
- **Normalized pool label:** `pool`, derived in code by removing enclosing
  parentheses and the standalone word `pool`, lowercasing, and collapsing
  whitespace. Counts attached to named sections, qualifiers, punctuation, and
  codes remain intact. This is not a resolved facility identity.
- **Candidate:** extracted facts that have not passed the publication rules.
- **Source cell:** a program block located by PDF coordinates under a weekday
  header, or one time entry in a program-oriented table row. It exists before
  model extraction and retains its page, bounds, weekday, and printed text.
- **Source coverage:** exact agreement between the supported source cells and
  candidate sessions, including programs, times, and pool allocations. Unknown
  layouts or program blocks cannot establish coverage.
- **Accepted snapshot:** a candidate that passed those rules. Acceptance by CI is
  not a claim that a human checked the document.
- **Published schedule:** accepted data that the live site serves and that the
  deployment check has verified. Writing local content or pushing a commit does
  not establish publication.
- **Held update:** a candidate that the pipeline does not publish because the
  source or extraction is unclear or invalid. Other pools can still update.

### Source and publication rules

| Source or result | Required action |
| --- | --- |
| Same source and extraction configuration | Reuse extraction; still evaluate date validity. |
| Valid, supported new schedule | Accept and publish the applicable dated window. |
| Transient network or model failure | Retry a bounded number of times; record every attempt. |
| Conflicting documents or unsupported extraction | Hold this pool's update and report the reason. |
| Prior schedule still valid | Retain it when a replacement fails. |
| Prior schedule expired | Show schedule unavailable; never extend old hours. |
| Explicit closure-only notice | Require a dated closure and no sessions or access windows. |
| Expected reopening date without a new grid | Do not invent weekly hours or claim confirmed reopening. |

Keep direct parsing for structured sources. PDF extraction must preserve literal
pool labels and supporting source locations. Code, not the model, selects the
applicable window and applies publication rules. Reject duplicate session tuples
without collapsing distinct pools, programs, or time ranges. Reject malformed
rows without crashing validation. A schema-valid response is not proof of
factual accuracy, and matching extracted evidence does not prove that no rows
were omitted. Missing-session coverage remains a required cutover check.

### Checked direct-main publication

The production API adapter now uses the pinned GPT-5.5 snapshot, medium reasoning,
native strict output, and at most two attempts. Only timeouts and selected
transient HTTP errors retry. Authentication and quota failures do not retry.
A local locked ledger reserves the maximum request cost before sending it.
Missing usage keeps that reservation; reported usage settles at the full input
rate, without relying on cache discounts. A pricing or accounting mismatch
blocks later calls. The workflow connects this request ledger to durable monthly
accounting across Actions runs. Enabled recurring automation requires an
operator-approved limit and the completed enablement checklist.

The durable accounting implementation stores one `budget.json` on the separate
`schedule-budget` branch. That branch stores accounting only; it cannot publish
site content and does not match the CI publication-branch pattern. An operator
must initialize it once, after approving `SCHEDULES_MONTHLY_BUDGET_USD`. A missing
branch blocks later reservations rather than creating a fresh allowance.
Each UTC calendar month records its approved limit. Each Actions run/attempt
reserves at most $1, or the smaller remaining allowance, before model calls.
The request ledger enforces that run allowance. Settlement releases only the
unused amount established by a valid ledger. Interrupted runs retain their
reservation; invalid accounting blocks subsequent paid runs. A changed monthly
limit cannot silently reset the current month's ledger.

All accounting updates use ordinary fast-forward Git pushes. Competing writers
cannot both reserve the same remaining funds. Local tests exercise that race,
process restart, missing accounting, month rollover, and malformed run ledgers.
The remote accounting branch was initialized on 2026-09-06 after the operator
approved $20/month. The later cutover lowers the ceiling to $5/month based on
measured per-document cost and expected source changes. GitHub configuration
and September's ledger use $5; the existing settled runs and charges remain
intact. The $1 run limit is unchanged. The workflow calls reserve and settle;
do not repeat initialization:

```sh
just schedules budget initialize
just schedules budget reserve --run-id ACTIONS_RUN_ID-ACTIONS_RUN_ATTEMPT --output tmp/api-budget
just schedules budget settle --directory tmp/api-budget
```

`scripts/check-build-ci.mjs` now shares its exact-commit CI lookup between the
main deployment gate and temporary branches named
`auto/schedules/<run>-<attempt>-<build>`. CI accepts that branch prefix. Its
`promote BASE BRANCH` command requires one generated commit above the recorded
main head, an explicit file allowlist, regular files, and a clean tracked tree.
It pushes the temporary branch, waits for that branch's successful CI run, and
fast-forwards main only if main still equals the recorded base. Stale heads
return exit code 2 so the workflow can rebuild and recheck. Failed checks,
unexpected paths, symlinks, and concurrent main updates never authorize a main
push. Tests use local bare repositories; they do not replace a hosted CI and
deployment trial. The integrated runner validates paths before commit, limits
rebuilds to two checked candidates, and reports success only after live verification.

The API adapter and the benchmark share the same transport and pricing code.
Historical CLI/API comparisons use their archived prompts so a production
prompt change cannot silently change an earlier experiment's contract. New
production-request comparisons must freeze the current source inventory and
conditional image inputs separately.

Cached production extraction requires the source hash and the exact model,
prompt, schema, parser, normalization, renderer, and output-limit configuration.
Publication rechecks the source facts, PDF hash, and rendered evidence. The
printed window must match both extracted dates; a missing year cannot borrow
the current year or a year from a holiday note. The closure inventory below adds
a separate check; session and window coverage do not establish closure completeness.

Run source discovery weekly on Monday at 16:00 UTC, as approved on 2026-09-06.
Keep the $1 per-run allowance inside the approved $5/calendar-month API ceiling;
the ceiling is not a spending target. Keep unchanged runs free of model calls and content
commits unless a configuration or publication-state change requires work.

1. Build accepted changes against the current `main` commit. Keep source evidence
   and failure records for held pools, but do not overwrite their accepted hours.
2. Enforce an explicit generated-file allowlist. Reject unexpected staged paths.
3. Commit to a run-specific automation branch and run the full `check` workflow on
   that exact commit. Do not open a PR for verified updates. Unclear closure
   sources instead get a separate evidence-only draft PR for human review.
4. After checks pass, fast-forward `main` to that commit. Never force-push `main`.
   If its head changed, rebuild and recheck against the new head, with a bounded
   retry count. Serialize publication attempts.
5. Wait for deployment, verify the exact commit and changed pools' served data,
   and run the live browser checks. Only then report publication success.
6. Retain source hashes, model and extraction configuration, raw results,
   validation decisions, check/deploy URLs, and the published commit ID. Keep
   credentials and account metadata out of those records.

The repository settings checked on 2026-09-05 require the GitHub Actions `check`
status, apply that rule to administrators, and disallow force pushes. They do not
require PR review. Preserve those protections. The temporary branch exists only
to obtain checks before promotion; it is not a review queue. Use the existing
CI-capable bot token initially. A default `GITHUB_TOKEN` push does not trigger the
normal push CI workflow. Token replacement is a separate operational decision.

Keep a kill switch and a deduplicated failure report. A failed deployment must
not report success or automatically restore expired hours. Check the deployed
revision before attempting any recovery; do not revert unrelated commits.

### Implementation order and acceptance

- **Publication rules:** implement contradiction and duplicate checks with
  regression tests; preserve inclusive expiry dates and pool-level isolation.
- **Production API confirmation:** use the preserved benchmark methodology in
  `docs/schedules.md`. Confirm GPT-5.5 through the real API before changing the
  production provider. CLI results do not establish API behavior or billing.
- **Extraction simplification:** separate source facts from publication policy;
  keep source/configuration caching and bounded failure handling.
- **Direct-main promotion:** replace rolling PR creation and auto-merge completely
  after API confirmation. Test stale heads, failed checks, and unexpected paths.
- **Live verification:** test expiry, explicit closure, held updates, partial
  success, failed deployments, and the success report on the deployed revision.

Initial rule changes are not a claim that the whole cutover is ready. API access,
missing-session checks, workflow replacement, and live verification remain gates.

### Extraction integration checks

Read-only checks during the literal-label repeat confirmed two remaining gaps:

- Removing one session from the first Hamilton result changes 23 rows to 22.
  `validate(..., prior_sessions_count=23)` still passes, and the existing
  grounding ratio stays at 1.0. Grounding means that returned evidence appears
  in the source; it does not establish that extraction included every session.
  The cutover must include a missing-row test that does not use benchmark
  reference answers as a production check.
- The first North Beach result matches all scored reference fields, but its
  existing grounding ratio is 0.8. Five failures involve printed ranges such
  as `7-8 AM` and `12-1 PM`; `_start_variants` does not recognize the omitted
  start meridiem. Another evidence line differs between Poppler layout text
  and production's pypdf text order. Extraction and evidence checks must share
  the same source representation. Do not lower the grounding threshold to
  conceal these differences.

Production also needs the benchmark's request contract and raw facts preserved
in provider artifacts. Cache identity must cover the model, prompt, transport
schema, text extraction settings, and normalization rules. An accepted snapshot
can remain the publication baseline without hiding a requested configuration
re-evaluation. Finish these checks before replacing the provider and workflow.

### Source-cell implementation

The implementation uses PDF coordinates to separate weekday columns and program
blocks. Program-oriented tables supply one cell per printed time range. This
inventory does not use model output or reference answers. It checks the complete
session multiset, not just returned evidence lines. Supported time syntax includes
shared meridiems (`7-8 AM`), noon, midnight, and an explicit lap-only end time.
Named pool labels retain qualifiers; standalone lane counts are not pool labels.

Unknown grids, unknown programs, ambiguous allocations or times, and duplicate
source slots hold the update. Unbalanced source text requires a rendered-page
input; the response still must agree with the independently parsed source slots.
Images do not waive coverage. Scanned documents without a supported text
inventory remain held, even if a model could guess their sessions.

The regression corpus contains 145 sessions. Mutation tests remove every row
and alter its day, program, start, end, and pool; all must fail coverage. These
tests establish behavior on the known corpus, not universal PDF support. Fresh
documents and a human reference check remain release checks.

### Closure inventory and source limits

The clarified-label repeat omitted North Beach's July 4 closure in one response.
Its sessions and window still matched. The new publication check rejects that
unchanged archived response and catches removed, duplicated, shifted, or
incorrectly timed closure entries.

The parser separates the right-hand Notes column by PDF coordinates and retains
closure-related notices. Closure words elsewhere in a grid hold the source:
the pipeline does not yet have an approved rule for resolving a session-cell
cancellation against a narrower facility-wide closure. A closure-only page must
establish its own dates; a link title alone cannot authorize publication.

Supported facility notices include explicit numeric or named dates, inclusive
date ranges, one shared time range, and numbered weekday recurrences within the
printed schedule window. Unparsed numbers, conflicting dates, uncertain scope,
multiple time ranges, and bare training mentions hold the update. This is a
bounded parser, not universal natural-language support. It compares closure
dates and hours; it does not claim to verify free-text reason paraphrases.
Production rejects unresolved notices before spending on an extraction call.
Benchmark runs still measure their candidates and preserve the closure check
separately; a scored benchmark result does not authorize publication.

Mission's fresh holdout matched all reference fields three times. Its cell
caveat still holds production until the operator decides how to resolve it.
Other unresolved benchmark references remain unchanged and unapproved. No model
response, successful test, or CI attestation replaces that domain decision or a
human reference check.

PDF input is limited to 25 MiB, 12 pages, and 2,000 points per page dimension.
Rendered evidence is limited to 20 million pixels per batch. Downloads request
identity encoding, reject other encodings, enforce actual streamed bytes, and
allow at most five redirects. Permanent HTTP failures and invalid PDFs do not
retry. The fetch path uses [HTTPX streaming](https://www.python-httpx.org/quickstart/#streaming-responses)
to enforce the byte limit before buffering the complete response.

The weekly OpenAI/direct-main workflow replaces the Gemini/PR workflow.
Automatic PDF session publication now requires the production artifact and
independent source verification; the legacy grounding percentage cannot approve
an update. Manual human repair remains explicit. The runner, durable accounting,
checked promotion, and live browser verification are connected.
Production credentials are configured with a $5/month ceiling and $1 run cap.
The operator confirmed the North Beach summer and Garfield maintenance samples
on 2026-09-06; other reference transcriptions remain agent-checked. See the
hosted trial receipts and enablement checklist in `docs/schedules.md`. Successful
workflow runs do not approve held closure notices, unsupported split PDFs, or
non-city/direct candidates that remain outside automatic publication scope.

References: [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
[workflow triggers](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
