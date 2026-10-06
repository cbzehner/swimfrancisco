# Schedule reliability and simplification

Status: all local tasks complete; production delivery changes remain a separate authorized follow-up.
Prepared against `9ed5dd9e59b59b99328077bdf0906a8337992779` on September 12, 2026.
Intended driver: Luna, xhigh reasoning effort. This document does not change the session's model.

## Goal

Make trustworthy swimming information cheaper to maintain. Improve the checks that protect user answers, remove implicit dependencies between pipeline components, and reduce calendar-driven deployment work. Preserve useful automation and the original evidence that makes its behavior reproducible.

The four root analysis/synthesis files are background, not implementation requirements. They contain disputed claims; use the verified decisions below and inspect current code before each task.

## Decisions

- Keep Zola, vanilla JavaScript, Python extraction, the conditions Worker, and Git-backed source evidence. No framework migration, general parser framework, or new database.
- Keep independent publication checks, quarantine, atomic paired/sequential publication, source/configuration cache identity, and expiry behavior.
- Treat session F1 as a narrow diagnostic. It cannot certify closures, effective dates, physical pools, exclusions, access, or the final answer.
- Keep attestation provenance explicit. CI agreement is not independent truth; an agent transcription is not human approval; an omitted historical attestor is legacy, not newly verified human truth.
- Store machine state in structured fields. Notes are prose. Directory contents must not acquire meaning solely because every file ends in `.json`.
- Render dated schedules without consulting the build clock. With JavaScript, the existing availability engine selects the relevant window using an explicit Pacific clock. Without JavaScript, readers can inspect every included dated window and its notices.
- Keep hourly conditions refresh. Remove the midnight rebuild only after unchanged built assets remain correct across date changes.
- Preserve current schedule ownership until the ownership audit identifies a safe migration. Do not regenerate all Markdown schedules from the newest snapshot.
- Do not infer operating economics from line counts, one successful run, or absent analytics numbers in Markdown.

## Execution contract

This turn creates a plan only. When instructed to execute it, implement the ready local tasks in dependency order without another spec or approval step. Resolve routine details yourself.

1. Check host, branch, status, and applicable instructions. Preserve unrelated files and edits, including the root review documents. Stay on the current branch unless instructed otherwise. Commit/push only when requested.
2. Read the listed implementation, callers, and tests before editing. If the baseline has changed, update the task's evidence and scope rather than restoring old behavior.
3. Work on one task at a time. Use existing modules and test suites; add a new file only for a clear responsibility or necessary fixture. Do not create compatibility aliases or parallel implementations.
4. Run targeted checks after a change and the full gate at the stated checkpoints. Missing tools should be obtained through the existing devenv environment; do not alter global machine configuration to run a test.
5. Keep source bodies and historical provider responses immutable. Use temporary copies for mutation tests. Do not change published hours to satisfy a test or silently label an ambiguous source as resolved.
6. These implementation tasks require no paid extraction, live schedule publication, analytics writes, messages, PR creation, deployment, Terraform apply, or production setting changes. Read-only evidence queries are in scope. Any later explicitly granted authority still applies; do not ask for it twice.
7. A blocked evidence/design task does not block unrelated ready implementation. Record the missing fact and continue. Do not substitute guesses for analytics, human approval, source clarification, or deployment permissions.
8. Update the ledger below after each task with changed behavior, exact checks/results, remaining limitations, and any resulting commit. Avoid a running narrative of experiments.

For trade-off decisions, prefer the smallest change that protects the stated behavior. Preserve useful unknown/held states rather than inventing availability or closures. Count recurring operator work and failure paths, not just deleted lines. The task's acceptance criteria define completion; an implementation suggestion may change when inspected code gives a simpler way to satisfy them. Record that adjustment and its evidence without requesting approval for routine details. Reopen a design decision only when its stated assumptions fail or the alternative materially changes scope, published meaning, or operational authority.

Suggested checks, from the existing environment:

```sh
just test-python
just test-js
just test-browser
just check
```

For a Python subset use `TZ=America/Los_Angeles uv --project schedule-tools run pytest <files> -q`; for a JS subset use `TZ=America/Los_Angeles node --test <files>`. Run `just release` only when intentional generated-content changes need regeneration. Inspect generated diffs and retain only task-related changes.

## Task ledger and dependencies

| Task | Depends on | Work | Status |
|---|---|---|---|
| EVAL-ARTIFACTS | — | Make real-corpus evaluation run reliably | complete; no commit |
| EVAL-FACTS | EVAL-ARTIFACTS | Compare the facts that affect availability | complete; no commit |
| ANSWER-CHECKS | EVAL-FACTS | Verify user answers against independent expectations | complete; no commit |
| DISCOVERY-STATE | — | Replace machine tokens in notes | complete; no commit |
| EVIDENCE-RETENTION | — | Make historical retention pins explicit | complete; no commit |
| DATE-INDEPENDENT-PAGES | ANSWER-CHECKS | Remove build-clock-dependent schedule presentation | complete; no commit |
| REMOVE-DAILY-REBUILD | DATE-INDEPENDENT-PAGES | Remove the obsolete rebuild trigger | complete; no commit |
| OPERATING-EVIDENCE | — | Assess existing analytics and run outcomes | complete; no commit |
| SCHEDULE-OWNERSHIP | EVAL-FACTS | Audit and specify schedule authority | complete; no commit |
| RELEASE-DESIGN | REMOVE-DAILY-REBUILD | Specify a smaller release path without losing safeguards | complete; no commit |
| CURRENT-RUNBOOK | implementation tasks completed or blocked | Make current behavior and exceptions easy to find | complete; no commit |

### Completed task evidence

- **EVAL-ARTIFACTS:** `tests/test_eval.py` passes 26 tests. Both `just schedules-eval --stdout` and `just schedules-eval --all-dirs --stdout` process the tracked corpus, including North Beach's `source-bundle.json`, without writing tracked data. Malformed eligible artifacts now report their path and exit nonzero; recorded failures and unsupported history are listed as unscored. Astra review passed. The final Fable CLI review was unavailable after the client session limit; its prior findings were fixed and its retention of the remaining implementation was reviewed statically.
- **EVIDENCE-RETENTION:** `tests/test_prune.py` passes 23 tests; `tests/test_prune.py tests/test_signals.py tests/test_discover_backtest.py` passes 279 tests with 56 skips; `just schedules prune --dry-run` reports no obsolete captures. Nine non-PDF captures are explicit pins and the protected set remains 82 directories. Relative and absolute roots are covered. Astra review passed; Fable review passed before the final root-normalization fix, which was separately reviewed by Astra after the fix.
- **DISCOVERY-STATE:** `tests/test_discover.py tests/test_registry.py` passes 149 tests, with writer regressions covering multiline notes, escaped/commented text, trailing comments, and structured-field validation. The normalized MLK and Sava candidate identities and decisions match before and after migration, and the retired machine-note parser/writer is gone. Astra review passed after the TOML writer fix. The Fable CLI was unavailable after its session limit.
- **EVAL-FACTS:** `tests/test_eval.py tests/test_envelope.py` passes 68 tests; the full `just test-python` suite passes 1,518 tests with 56 skips. The evaluator now reports duplicate multiplicity, explicit physical-pool and exclusion coverage, effective windows, schedule basis, closure boundaries and scope, access hours and exceptions, and legacy/human/agent-reference/CI provenance. Seasonal semantic rows remain outside quality aggregates and preserve both reference and snapshot origins. Forty-four malformed-field probes, both real-corpus report modes, and `git diff --check` pass. Astra medium review passed after two finding/fix cycles; the Fable CLI review was unavailable because its session limit had been reached.
- **OPERATING-EVIDENCE:** Added a dated runbook section based on 82 committed capture directories from 2026-04-19 through 2026-09-09, the decision log through 2026-09-09, local event definitions, and receipt-schema inspection. It records named extraction-only, hosted capture, and deterministic publication outcomes from the decision log, including holds, browser budgets, model charges, capture-only changes, and published swimming facts; it keeps operator minutes and unattended effort unknown. It recommends retaining weekly detection and hourly conditions refresh while simplifying cache/deterministic work, and defers cadence changes until date-independent pages and missing measurements are addressed. No external data, telemetry, production setting, issue, or message was created. Astra review passed after one correction cycle; the Fable CLI review was unavailable after the session limit.
- **SCHEDULE-OWNERSHIP:** Added a fixed-date decision record mapping all 25 canonical pools and 26 current/upcoming windows to specific accepted evidence paths. Temporary reconstruction found zero operational fact mismatches; 24 pools and 25 windows matched full canonical fields, with North Beach retaining a metadata/provenance gap. Latest-only projection loses MLK’s second live window, so Markdown remains authoritative. The record preserves paired/sequential identity and defines a bounded read-only verifier plus retention requirements. The audit ran the relevant merge/project/review/publish suites: 342 passed, with no real schedule files edited. Astra review passed after the inventory-path and count corrections; the Fable CLI review was unavailable because its session limit had been reached.
- **ANSWER-CHECKS:** Added independent literal expected-answer cases for the September 14, 2026 Pacific closure/open pair, Pacific midnight, spring-forward and fall-back boundaries, and visible board/detail answers in both Los Angeles and Tokyo browser contexts. Existing assertions cover session boundaries, partial/facility/physical-pool closures, cancellations, simultaneous pools, season gaps, expiry, upcoming windows, facility access, and exceptions. Focused Node tests pass 82, the full JavaScript suite passes 228, the full browser suite passes 39 across WebKit and Chromium, and `just check` passes with 1,518 Python tests and 56 skips. Astra medium review passed; the Fable CLI review was unavailable because its session limit had been reached.
- **DATE-INDEPENDENT-PAGES:** Removed Tera's build-clock window and notice selection. Each dated window now renders as ordinary dated HTML with a keyboard-accessible disclosure button; JavaScript selects the active window and applies the two-week notice view, while print expands all windows and notices and restores the screen state. Static pages start with `—` and remain readable with JavaScript disabled. Focused site-render tests pass 43, focused and full JavaScript tests pass 228, the full browser suite passes 41 across WebKit and Chromium, and `just check` passes with 1,519 Python tests, 56 skips, typecheck, browser tests, and build. Astra medium review found and the follow-up fix covered collapsed-window print and beyond-horizon closure/access notices; the final Fable CLI review was unavailable because its session limit had been reached.
- **REMOVE-DAILY-REBUILD:** Removed the Worker midnight rebuild request, hook binding, `triggerRebuild`, and `isPtMidnight`; the hourly cron now only refreshes conditions, including standard/DST midnight cases and with or without the stale binding present. Production smoke no longer imposes static build/index age limits, but still rejects malformed or future timestamps, wrong commits, mismatched content, and stale conditions. Active Worker, deploy, spec, Terraform, and environment instructions describe the conditions-only cron; historical rebuild material remains archived, and the unused production hook/secret is listed for separately authorized cleanup. Targeted Worker/smoke tests pass 22, typecheck and syntax checks pass, and `just check` passes with 1,519 Python tests, 56 skips, 224 JavaScript tests, 41 browser tests, and build. Astra medium review passed; the final Fable CLI review was unavailable because its session limit had been reached.
- **RELEASE-DESIGN:** Added an implementation-ready dated release design in `docs/deploy.md`: GitHub `workflow_run` becomes the staged production owner only after Workers Builds admission is drained; exact SHA/main-head guards, candidate staging, atomic schedule promotion, live smoke/evidence, protected credentials, config-trigger ownership, staging rehearsal, cutover, rollback, and the deletion set remain explicit. Production upload uses a pinned non-retrying helper because stock Wrangler retries API failures; promotion and non-versioned settings are separate terminal operations, each retained in the receipt and admission hold. Explicit GitHub admission records are distinct from automatic environment records, and superseded non-promoting uploads can close as reconciled-not-deployed while unknown writes remain held. `git diff --check` passes; no production setting or deployment changed. Astra medium final gate passed after three correction cycles. The installed Claude CLI rejected the requested Fable 5.1 model identifiers, so the Fable gate was unavailable.
- **CURRENT-RUNBOOK:** Added an operator entry point to `README.md` and dated current-state guidance to `docs/schedules.md`; clarified canonical Markdown authority, carried-forward attestations, current holds, correction recovery, explicit retention pins, weekly direct-to-main automation, structured `discovery.documents` retirement, quarantine format, conditions-only runtime behavior, and the pending Workers Builds release design. Reconciled `docs/deploy.md` with the current owner and removed stale daily-rebuild wording from active instructions while preserving historical and separately authorized cleanup notes. `just schedules prune --dry-run`, `just schedules pending-reviews`, `just schedules-eval --stdout`, CLI help, local Markdown-link validation, and `git diff --check` pass. `just schedules discover-blocking` correctly fails closed when no discovery report exists; the runbook now documents that prerequisite. Astra medium final gate passed after three correction cycles. The installed Claude CLI rejected the requested Fable 5.1 model identifier, so the Fable gate was unavailable.

Default order: evaluator tasks, answer checks, discovery, retention, date-independent pages, rebuild removal, evidence/audits, current runbook. Evidence queries may be brought forward when access is available. Dependencies are correctness requirements, not an instruction to launch parallel agents.

## EVAL-ARTIFACTS — evaluate the committed corpus

**Why this task exists:** the documented evaluation command crashes because North Beach's `source-bundle.json` is an array and `_evals_for_dir` treats almost every JSON file as a provider object. Thirteen evaluator unit tests passed despite this real-corpus failure. Existing discovery backtests already read the committed PDFs in CI; this task repairs an additional evidence consumer, not an unused archive.

**Files:** `schedule-tools/src/schedules/eval.py`, `cli.py`, `review.py` and `artifacts.py` for existing artifact conventions; `tests/test_eval.py`; `justfile` and `docs/schedules.md` only as needed.

**Trade-off guidance:** prefer a narrow artifact reader over a new registry of plugin types. Ignoring a known evidence file is correct; silently ignoring a malformed successful extraction hides lost coverage. An explicit failed provider response is evidence of failure, not a zero-session prediction. Preserve the distinction between report execution failure, an unscored historical input, and a scored disagreement. Do not require every historic format to satisfy today's publication schema just to read it.

**Implement:**

- Inventory the JSON artifact shapes actually present in tracked capture directories. Reuse existing artifact conventions where they fit; distinguish provider results from `reviewed.json`, `source-bundle.json`, and other evidence.
- Fix the North Beach array crash. Explicitly recognized auxiliary files are not provider predictions. Eligible successful provider artifacts must have an object payload. Report malformed artifacts with their path and reason; do not silently discard them or turn them into empty predictions.
- Distinguish recorded provider failures/unsupported historical artifacts from malformed successful results. List unscored inputs and reasons so the report does not hide corpus gaps. Historical failures must not be rewritten into successes.
- Preserve latest/all-directories behavior and the separation of same-source reference comparisons from seasonal changes. Never score CI against itself as independent quality.
- Add a test that invokes the evaluation path on the actual tracked corpus, including the North Beach bundle. Run it through the existing Python suite. Report-only execution must not write reviewed payloads or content.

**Acceptance criteria:**

- Both `schedules eval --stdout` and `schedules eval --all-dirs --stdout` process the tracked corpus without the array crash. A genuinely malformed eligible artifact yields a path-specific error and nonzero exit, not an empty successful score; document such a baseline blocker without changing historical responses.
- A recognized auxiliary array adds no provider comparison. Recorded failures/unsupported history appear as unscored with reasons. Tests separately exercise all three cases.
- Same-source, seasonal, and CI-origin handling remain correct; report execution leaves tracked files unchanged.
- The real-corpus evaluation regression runs through the existing test command, and evaluator/discovery backtests pass. No existing corpus check is removed.

**Stop:** do not establish a minimum model F1 or fail CI on historical extraction disagreement. This task protects the tool's ability to read evidence, not historical model accuracy.

## EVAL-FACTS — expose semantic disagreements

**Why this task exists:** a reproduced candidate missing a closure and using the wrong season scored F1 = 1.0. A second candidate missing one physical pool also scored 1.0. The comparator only sees a subset of session fields. Independent publication gates check more than this, so the diagnosis is an incomplete quality measure, not proof those bad candidates can publish.

**Files:** `eval.py`, `envelope.py`, `reviewed_snapshots.py`, `schemas/reviewed-snapshot.json` for contract reading; `tests/test_eval.py`; current evaluation runbook.

**Trade-off guidance:** prefer explicit per-dimension comparisons to a universal scoring framework. Normalize list order and genuinely nonsemantic presentation differences, but never normalize away physical scope, time boundaries, missing dates, or duplicates. An explicitly empty reference closure list and a reference with no closure coverage are different. Use the applicable artifact contract/provenance to distinguish them; do not infer completeness from a missing key. A migration of old source data is outside this task.

**Implement:**

- Keep session precision/recall labeled as session-only. Include physical-pool identity and excluded dates in session comparison, in addition to the current day/program/start/end/allocation fields. Surface duplicate rows rather than allowing set conversion to conceal them.
- Add separate comparisons for effective windows, schedule basis, closures (inclusive dates, optional half-open time interval, physical scope), access hours, and access exceptions. Compare semantic facts, not extraction timestamps, source-cell coordinates, JSON ordering, or cosmetic prose.
- Report per-dimension matches/mismatches and missing reference coverage. Do not claim complete correctness when historical truth lacks a dimension. Keep legacy, human, agent-reference, and CI origins distinguishable; do not relabel stored artifacts.
- Update callers of `RowKey`, especially `tests/conftest.py`, deliberately. Do not inadvertently weaken duplicate/reference validation while extending its identity.
- Add direct regressions for a missing holiday closure, wrong season, one missing physical pool, a session cancellation, partial versus all-day closure, facility versus pool scope, and an access-hours-only source.

**Acceptance criteria:**

- Missing closure/wrong-season and missing-physical-pool candidates produce explicit mismatches in the appropriate dimensions, regardless of session-only F1.
- Duplicate rows, exclusions, partial-day boundaries, and physical scope cannot disappear through normalization; benign ordering changes do not create mismatches.
- Missing reference coverage is reported as unknown/unmeasured, not a match; historical seasonal changes remain outside quality aggregates.
- The real-corpus report identifies the reference origin and evaluated dimensions. No composite score is described as complete correctness, trust, or confidence.

**Verification:** `tests/test_eval.py`, reference/provider tests affected by row identity, then `just test-python`. Run both real-corpus report modes. Keep historic discrepancies visible rather than editing evidence to erase them.

## ANSWER-CHECKS — test what a swimmer is told

**Why this task exists:** feeding the perfect-F1 missing-closure example to the existing display code produced `OPEN` where the reference produced `CLOSED_TODAY`. Field comparisons and deployment equality are useful but cannot alone protect the user's decision. Independent expected answers are also necessary before changing how pages choose windows.

**Files:** `static/js/helpers/board.mjs`, `pacific.mjs`, `tests/js/board-status.test.mjs`, `pacific.test.mjs`, `tests/browser/smoke.test.mjs`, `tests/fixtures/source-references.json`; `scripts/smoke-production.mjs` for existing integration assertions.

**Trade-off guidance:** first map the cases below to existing tests and reuse adequate coverage. Add tests for actual gaps, not a duplicate test framework. Pure tests should cover the combinatorics; browser tests should cover DOM behavior and timezone/engine integration. A few carefully chosen cases beat the full cross-product of every pool, date, locale, and browser. Synthetic expectations establish logic; source-derived expectations establish transcription fidelity only to the extent their provenance supports it.

**Implement:**

- Add a compact table of independently specified input/time/expected-answer cases to the existing tests. Reuse verified source fixtures where their meaning is established; synthetic fixtures are appropriate for logical boundary cases. Label provenance honestly. Do not generate expected answers by calling the same function being tested.
- Cover ordinary open and closed sessions; exact opening/closing boundaries; partial/facility/physical-pool closures; cancellations; simultaneous Cool/Warm sessions; gaps between seasons; expiry; upcoming windows; facility access without a swim claim; and access exceptions.
- Include Pacific midnight and daylight-saving transitions, exercised in both Pacific and a non-Pacific visitor timezone. Preserve the existing clock interface unless a failing case warrants a focused fix.
- Include the concrete case: Monday September 14, 2026 at 07:30 Pacific, a 07:00–08:00 lap session with a September 14 full-day closure must not produce `OPEN`. Removing the closure must change the result.
- Keep deployed-data equality smoke checks, but distinguish them from independent correctness expectations. Matching generated content proves delivery fidelity, not source truth.

**Acceptance criteria:**

- Every listed behavioral category has an identified existing or new assertion with an independently stated expected result.
- The September 14 example is closed with its closure and open without it. Boundary tests distinguish a known closure from an expired/unknown schedule.
- Pacific and non-Pacific visitor contexts agree on the same real instant, including midnight and DST cases; browser checks cover the visible answer as well as embedded data.
- All checks are deterministic and offline with respect to source/model services. Ground-truth labels do not overstate how fixtures were reviewed.

**Verification:** affected JS tests and a small browser subset for timezones, followed by `just check`. This is the first full checkpoint before presentation changes.

## DISCOVERY-STATE — replace machine notes atomically

**Why this task exists:** persisted sibling documents are recovered from a miniature token language inside `notes`. Recovery instructions require editing that prose precisely, and fetch-failure handling must preserve it to avoid forgetting schedules. This couples human documentation to publication state. Existing atomic multi-window handling is valuable and must survive the representation change.

**Files:** `schedule-tools/src/schedules/models.py`, `registry.py`, `registry.toml`, `discover.py`; callers in `review.py`, `pipeline.py`, `publish.py`; discovery/registry/review/publish tests; `docs/schedules.md`.

**Trade-off guidance:** choose a small typed representation of facts existing callers consume. Do not reproduce the entire discovery report inside the registry. TOML inline records or tables are routine implementation choices; semantic stability and preserved comments matter more than formatting. Reuse `tomlkit` where it eliminates hand-written editing rules. This is a migration of known current state, not authority to discover or select a new source.

**Design:** keep registry TOML and use a structured `discovery` value on the relevant pool entries. Represent persisted documents as records with validated integer IDs, kind, and origin (`table`, `band`, `persisted` as applicable). Store other machine decision fields only when an existing consumer or unchanged-write rule needs them. Keep human `notes` unchanged except removal of the old machine line.

**Implement:** enumerate every reader/writer of the old tokens first. Migrate the tracked registry and fixtures in the same slice as the runtime cutover. Preserve the exact persisted candidate set and discovery decisions; do not fetch/adopt new URLs during migration. Use the TOML library already present. Remove the legacy token parser/writer after updating callers; do not retain a dual-format compatibility path.

**Acceptance criteria:**

- Before/after normalized candidate identities and decisions match for the tracked registry and frozen fixtures, including MLK and Sava siblings.
- Adoption retains needed siblings; transient fetch failures preserve prior state; paired and sequential publication safeguards still pass.
- Changing only human notes cannot change candidates. Repeating an equivalent decision produces no registry diff.
- Invalid structured IDs/kinds/origins fail at the registry boundary. No runtime reader or writer depends on the retired machine-note syntax after migration.

**Verification:** registry/discovery/backtest/review/publish suites, then `just test-python`. Compare normalized registry facts before and after. Inspect the exact migration diff for lost notes or IDs.

## EVIDENCE-RETENTION — decouple evidence pins from prose

**Why this task exists:** `_names_in_tests_and_docs` makes a narrative citation an implicit retention pin. Removing obsolete prose can therefore change what a future prune deletes. Source bytes are already used by backtests and audits; hashes alone cannot replace them. The desired simplification is explicit retention intent, not a smaller archive at any cost.

**Files:** `schedule-tools/src/schedules/prune.py`, `tests/test_prune.py`, `tests/fixtures/source-references.json`, existing source fixtures, and `docs/schedules.md`. Add `tests/fixtures/corpus-retention.toml` only for explicit pins not already represented by a structured reference.

**Trade-off guidance:** a small explicit pin list is justified by a current retention consumer. Avoid listing every file already protected by the PDF rule or another structured reference. Temporary over-retention is safer than losing reproducible evidence, but it should be explained rather than hidden. Preserve all members of source bundles and any referenced attestation chain; test those references independently of the prose being migrated.

**Design:** preserve all existing retention rules other than replacing regex searches through arbitrary test/doc text with explicit corpus references. Pins identify a repository-relative capture directory and why it is retained. Validate path containment and targets. Reuse structured source-reference paths directly rather than duplicating them unnecessarily.

**Implement:** inventory the currently protected set before editing; convert protections previously supplied only by prose into explicit pins. Remove `_names_in_tests_and_docs` after migration. Preserve PDF corpus protection, latest accepted capture, pending review, fresh incomplete captures, and live carry dependencies. Validate broken explicit references loudly.

**Acceptance criteria:**

- A recorded before/after dry-run comparison shows no loss from the starting protected set; any extra retention is identified and explained.
- Editing a document citation no longer changes the plan, while adding/removing an explicit test pin changes only the intended target's protection.
- Missing/escaping pins fail clearly. Carry, pending-review, bundle-member, and latest-capture protections pass their behavioral tests.
- Source backtests still work from committed files alone. No real capture is deleted or relocated during this task.

**Verification:** prune tests and corpus tests; compare before/after dry-run plans. Do not run destructive prune on the real repository or remove committed evidence as part of this task.

## DATE-INDEPENDENT-PAGES — build once, read on different dates

**Why this task exists:** Tera, Python, and JavaScript each choose schedule windows. Tera additionally filters notices relative to build time, so removing only the active-window block would leave stale closure/exception lists. Daily rebuilding compensates for those time dependencies. This task removes that operational requirement while retaining useful static HTML and current browser behavior.

**Files:** `templates/spots/page.html`, `templates/macros/schedule.html`, other templates found by a `now(` search, `static/js/detail.js`, `status.js`, `helpers/board.mjs`, relevant CSS, site-render/browser tests, and production smoke expectations.

**Trade-off guidance:** accept a somewhat longer no-JavaScript page in exchange for honest, fully dated information. Semantic collapsible sections are an option if necessary; every window must remain accessible. With JS, preserve the compact current experience. Avoid a client-only schedule renderer, edge transforms, a new endpoint, or a new framework. Distinguish stable printed dates from transient labels such as Today. If a design makes print, accessibility, or localization materially worse, revise its markup before removing the rebuild safety net.

**Design:** render every included schedule window as accessible dated HTML, with its applicable closures and access exceptions. Do not hide the only copy of a future window in an inert template for readers without JavaScript. Use progressive enhancement to select the relevant window and show Today/upcoming/expired state. Existing embedded schedule data already contains all windows; do not introduce a second data feed.

**Implement:** remove Tera's active-window selection and every build-relative filter affecting schedule correctness, including the current two-week closure/exception lists. Preserve window-scoped notices in static HTML; JS may filter the visible upcoming list at view time. Avoid briefly claiming `OPEN` before enhancement. Keep localized headings, physical-pool labels, print layout, and keyboard accessibility. Reuse the existing availability functions.

Python's active-schedule selector also supplies extraction/review baselines; do not delete it as though it were only pruning code. The goal is removing the Tera copy, not forcing the publishing and browser runtimes into one language.

**Acceptance criteria:**

- One build is reused for clock-advanced browser cases at Pacific midnight, season rollover, beyond fourteen days, and DST. Rebuilding between cases does not satisfy this criterion.
- Window selection, Today rows, expiry, closures, and access exceptions remain correct in WebKit and Chromium. No unsafe transient `OPEN` appears before enhancement.
- With JS disabled, each included window and its applicable notices are accessible, clearly dated, and readable in print; no current-state claim depends on when the build ran.
- Representative paired, sequential, access-only, and closure-only pages retain their meaning. Check localization structure in every locale and focused behavioral cases rather than an unnecessary full cross-product.
- No schedule-correctness output depends on template `now()`; Python extraction/review baselines and existing publication guards are unchanged.

**Verification:** answer checks, site-render tests, real-browser tests, `just check`. Keep daily rebuilding until this task passes; removing the hook is the next task.

## REMOVE-DAILY-REBUILD — delete only the obsolete trigger

**Why this task exists:** once a fixed build survives calendar changes, the midnight hook, its secret, and its failure mode no longer serve schedule correctness. The existing smoke check also limits static artifact age to 36 hours, so deleting the trigger without revisiting that assertion would create false production failures. Hourly environmental observations have a genuinely different freshness requirement.

**Files:** `worker/src/index.ts`, `deploy.ts`, `schedule.ts`, Worker types/config, affected JS tests, `.env.example`, `docs/deploy.md`, Worker README and any active references found by searching for the hook and midnight helper.

**Trade-off guidance:** remove the unsupported build-age requirement, not freshness validation in general. Old static data can still be wrong if it differs from the expected commit; expired observations remain stale regardless of a recent build. Separate these checks explicitly. Delete helpers only after checking all callers, and avoid unrelated Worker refactoring. Production removal of an unused secret can wait; local runtime correctness must not depend on it being present or absent.

**Implement:** remove the midnight rebuild call, hook binding requirement, and helpers/tests with no remaining caller. Keep hourly conditions refresh and its failure visibility unchanged. Remove daily-build instructions from active docs. Inspect build-age assertions in `scripts/smoke-production.mjs`: an old static build is valid after DATE-INDEPENDENT-PAGES, whereas conditions still require freshness. Preserve exact-commit/content equality checks and timestamp validity; do not refresh build metadata just to fake freshness.

**Acceptance criteria:**

- Hourly scheduled execution refreshes conditions and makes no rebuild request in standard or daylight time, with or without the obsolete binding.
- A test with old but otherwise valid static build metadata and fresh matching data passes. Stale conditions, wrong commits, or mismatched deployed content still fail their respective checks.
- No active code requires the midnight hook/helper, and active instructions describe the new behavior. `just check` passes.
- Obsolete production resources are listed for later authorized cleanup; no Cloudflare setting is changed in this task.

## OPERATING-EVIDENCE — use existing signals before adding machinery

**Why this task exists:** the reviews inferred both low automation value and absent product measurement from incomplete evidence. Source-specific automation now publishes useful changes; analytics capture calls already exist. We have not measured recurring operator effort or queried product usage. Those unknowns should guide investment decisions rather than trigger speculative instrumentation or removal of functioning parsers.

**Files/sources:** existing analytics events in `static/js`, connected read-only analytics if available, GitHub automation receipts/operator issue, current runbook. Write a concise dated section in `docs/schedules.md` or link one small evidence report if necessary.

**Trade-off guidance:** prefer existing aggregate queries and receipts over a dashboard or telemetry subsystem. Inspect the longest useful available period, identify manual rollout trials, and do not extrapolate from a single successful week. Low usage may reflect missing awareness or coverage; outbound clicks are intent proxies, not completed swims. Separate elapsed CI time, money, recurring human attention, and user benefit. Missing analytics access means unknown, not zero demand.

**Work:** inspect available visitors, pools, locales, planning/filter usage and outbound clicks. Check event availability before proposing instrumentation. Summarize retained runs by changed source, cached extraction, accepted changes, holds, corrected publication, and elapsed delivery. Keep actual operator minutes separate from workflow runtime; mark missing data unknown. A successful run is not proof of positive economics.

**Decision:** recommend retain/simplify/defer per expensive source family, and whether detection cadence deserves a change. Factor in browser capture costs, discovery of new document URLs, configuration invalidation, and existing cache reuse. Do not add another scheduler or change extraction cadence in this task. If access or historical evidence is missing, document the smallest missing measurement and continue other work.

**Acceptance criteria:**

- Findings identify time range, sample size, source, and caveats, including whether runs were unattended or manual trials. Missing information is explicitly unknown.
- Each proposed source/cadence change states expected benefit, maintenance cost, evidence strength, and the observation that would cause reconsideration. Recommendations may reasonably be “retain” or “insufficient evidence.”
- No private user-level analytics or secrets enter the public repo. No new telemetry, schedule change, external issue, or message is created.

**Verification:** reconcile reported publication counts with retained receipts and sampled content changes; distinguish capture-only commits from changed swimming facts. Verify analytics event definitions before interpreting counts. If evidence is unavailable, deliver the bounded gap report and mark the recommendation blocked, not the whole plan.

## SCHEDULE-OWNERSHIP — decide authority from a complete inventory

**Why this task exists:** Markdown is documented as authoritative, yet accepted snapshots can project into its schedule fields. The risk is conditional: unchanged candidates are skipped, and human reviews are protected; not every publish overwrites every hand edit. Changing authority without an inventory could discard corrections or one of several valid seasonal windows. This task establishes the real reconstruction contract before proposing a migration.

**Files:** `project.py`, `merge.py`, `review.py`, `reviewed_snapshots.py`, `publish.py`, `prune.py`, canonical Markdown and accepted snapshots; relevant runbook sections.

**Trade-off guidance:** choose authority based on lossless reconstruction and an understandable correction path, not a preference for JSON versus Markdown. One canonical write path is valuable only if it preserves current accepted facts and all live/future windows. Test reprojection in temporary copies with a fixed date because merge prunes expired windows. Missing evidence requires an explicit exception; do not manufacture an attestation to complete the map.

**Work:** inventory which accepted snapshots support each current/upcoming Markdown window, including manual corrections, paired bundles, and sequential seasons. Distinguish explicit reprojection from automatic candidate selection. Identify projected facts that cannot be reconstructed from retained accepted evidence without loss.

**Deliverable:** a short decision record with current ownership, correction workflow, options, trade-offs, and a concrete migration slice if structured accepted data should become authoritative. State which evidence must be retained for every live/future window. Default to the existing ownership contract until reconstruction and correction behavior are proven. Do not overwrite schedules, auto-approve sources, or choose the latest capture as the complete facility schedule.

**Acceptance criteria:**

- Every canonical pool's current/upcoming windows map to accepted evidence or an explicitly described gap; paired and sequential sources retain their complete identity.
- Temporary reconstruction comparisons distinguish semantic differences from formatting and clock-driven pruning. No real schedule file is rewritten.
- The decision explains manual edits, explicit reprojection, automatic candidate acceptance, unchanged human decisions, changed bytes, and expiry.
- Any proposed migration includes preservation tests, retention consequences, and a bounded next implementation task. The current ownership rule remains in force until that migration is implemented.

**Verification:** record normalized before/reconstructed comparisons at one fixed Pacific date and run existing merge/project/review tests relevant to any behavioral claim. A documentation-only recommendation does not require inventing new tests.

## RELEASE-DESIGN — prepare a smaller, reviewable delivery change

**Why this task exists:** GitHub/Cloudflare coordination has caused real deployment failures and accumulated authentication/polling code. However, candidate staging, main-head checks, and publication receipts also protect concurrent human changes and correct deployment ordering. Using a different deploy command does not remove those responsibilities. This task makes the proposed deletion concrete without pretending a CI edit alone proves production correctness.

**Files:** `.github/workflows/ci.yml`, `schedules-extract.yml`, `scripts/check-build-ci.mjs`, `smoke-production.mjs`, `schedule-tools/src/schedules/automation.py`, Worker package/config, and `docs/deploy.md`.

**Trade-off guidance:** prefer platform-owned dependency ordering where it truly replaces custom coordination. Compare the existing design with one explicit alternative by failure paths, credentials, operator actions, and deletable code. A smaller script that loses atomicity or allows an older deployment to win is worse. Do not assume previews are unused or that a cancelled process cancelled an external request. If the replacement cannot simplify the total workflow while preserving guarantees, recommending retention with a smaller targeted fix is a valid outcome.

**Deliverable:** a concrete replacement design and separately executable tasks, preferably one CI-owned production delivery path. Check current official deployment documentation before depending on platform-specific behavior. Do not migrate deployment merely because two scripts can be combined.

The design must show:

- How both human and generated changes reach the authoritative branch without overwriting concurrent work or bypassing required checks.
- How verification, built artifact, source commit, and deployed version stay associated; what happens if main moves during validation.
- How production writes are serialized and an older job cannot deploy after a newer one. Cancelling a CI job is not proof its external deploy stopped.
- Which credentials the trusted deploy job needs; untrusted PR checks remain unprivileged. Inspect whether previews are actually used and describe their replacement or retention.
- Which polling/authentication helpers can be deleted, which safeguards remain, and the exact files affected. Preserve artifact staging scope, atomic schedule acceptance, and actual deployment verification.
- A test matrix for concurrent main movement, candidate CI failure, deployment failure, stale deployment, retries, and corrective rollback with preserved evidence.
- A staged cutover, one production deployment owner at every point, and a concrete rollback procedure. Prepare all safe local changes/tests before any permission request for production settings or deployment.

**Acceptance criteria:**

- Every existing safeguard has an identified replacement/retention point, or an evidence-backed explanation that it became unnecessary.
- The proposed sequence handles concurrent main movement, failed validation/deploy, stale external requests, retries, and rollback; the test matrix states observable expected outcomes.
- File changes, credential placement, preview behavior, deletion set, cutover order, and rollback steps are concrete enough for separate implementation tasks. External unknowns are explicitly unresolved.
- The recommendation explains why it reduces total operational work. Retaining the current design is acceptable if the alternative fails that comparison.

**Verification and stop:** trace at least a normal publication, concurrent human edit, and out-of-order deployment through the proposed sequence; validate platform claims with current official sources. An implementation-ready design or justified retention decision is success. Production migration is a subsequent action requiring authority beyond this planning/local-task packet.

## CURRENT-RUNBOOK — make resumption cheap

**Why this task exists:** the append-only decision log preserves useful evidence, but historical holds and old implementation details were mistaken for current behavior in these reviews. The cost is reader ambiguity, not merely word count. Current commands, actual authority, and unresolved exceptions need a short entry point while historical evidence remains available.

**Files:** `docs/schedules.md`, `docs/deploy.md`, `README.md`, `NAPKIN.md` only where current behavior changes; `docs/schedules-decision-log.md` for links/corrections, not wholesale rewriting.

**Trade-off guidance:** edit the existing runbook rather than adding a competing current-state document. Link details and histories instead of repeating them. Do not rewrite old dated statements as though later facts were known then; label superseded conclusions and point to the current rule. Keep a decision's reason and revisit condition when they prevent repeated debate. Brevity is useful only if a new operator can still recover correctly.

**Implement:** ensure a reader can quickly find the canonical data contract, normal commands, actual checks, current exception locations, failure recovery, and outstanding decisions. Keep historical trials labeled historical. Link a short current-state summary to evidence rather than copying run narratives. Replace stale claims such as generic F1 implying complete quality. Do not create external issues or delete historical source evidence/history.

**Acceptance criteria:**

- Starting at README, an unfamiliar driver can locate the canonical data rule, normal verification command, current holds, correction procedure, and deployment boundary without reconstructing the trial history.
- Current instructions match code and completed tasks; pending proposals remain visibly pending. Historical evidence is labeled and linked rather than presented as current capability.
- The ledger records completed acceptance criteria, exact check outcomes, and concrete blockers. No task is marked complete merely because code was written.
- Changed links/commands are checked, unrelated docs are preserved, and no external issue or historical evidence deletion is performed.

**Verification:** search active docs for retired hook/ownership/evaluator claims, inspect every changed command against its CLI or script definition, and check local link targets. Do not run publishing commands merely to validate documentation.

## Driver prompt

Use this prompt in a session configured for Luna with xhigh effort:

> Execute `docs/plans/2026-09-12-schedule-reliability-and-simplification.md`. Begin with the first pending ready task, verify current code, and implement tasks one at a time. Follow the execution contract and update its ledger with concrete results. Preserve unrelated changes and remain on the current branch. Do not commit or push unless I ask. Continue through ready local tasks; complete evidence/design deliverables at their stated stopping points and record missing external evidence without blocking unrelated work. Do not deploy, change production configuration, make paid model calls, delete source evidence, or send messages. Ask only about a material unresolved choice or newly required authority. Report what changed, what passed, and exactly what remains.
