---
status: in_progress
progress:
  - step: 1
    status: done
    date: 2026-04-17
  - step: 2
    status: done
    date: 2026-04-17
last_review: null
iterations: 2
no_progress_count: 0
started_at: 2026-04-17
work_unit_granularity: step
---

# SwimFrancisco Review Follow-up Plan

Reference: review performed on 2026-04-17 across source, `zola build`,
`worker/npm run typecheck`, `devenv up`, local `/__scheduled`, and live UI
inspection in headless Chrome. Magi synthesis on 2026-04-17 reshaped the
plan from 10 loose steps into 7 grouped steps; see
`~/.claude/magi/sessions/2026-04-17-swimfrancisco-review-followup-plan-rewrite.md`.

Product ideas (Swim Windows, Time Scrubber, Trust Layer) live in
`docs/ideas/product-directions.md` and are intentionally out of scope here.

## Scope

- Fixes + hardening only.
- No paid extractor rerun inside this plan. A one-pool canary on
  `balboa-pool` is a post-plan activity once Steps 1-3 land.
- TDD for every step: failing test first, then implementation, then
  hardening that removes the class of bug rather than just this instance.

## Policy Decisions

- **Closure contract v1**: closures stay facility-wide, all-day, date-only.
  Timed/pool-scoped closures are a future schema migration and are
  explicitly out of scope. `closures[].pool` is removed from schema to make
  the invalid state unrepresentable.
- **Prompt versioning**: any edit to `src/schedules/prompts/extract.txt`
  bumps a prompt version and adds a short note to existing adjudication
  files so reproducibility is traceable.

## Test Runners

- `uv run pytest` — Python pipeline + site-render tests
- `node --test tests/js/*.test.mjs` — JS pure helpers (introduced in Step 5)
- `zola build` — static site build
- `cd worker && npm run typecheck` — Worker TS

## Validated Findings

Severity and file references for each finding. Execution groups them;
this section is the source of truth for the 10 bugs themselves.

### 1. Near Me sort does not restore baseline order

Severity: medium. Files: `static/js/filters.js`, `static/js/status.js`.

`applyFilters` reads current (mutated) DOM order instead of a stable
baseline captured after `status.js` dispatches `sf:status-applied`.
Executed in Step 5.

### 2. Pool closures render as `[OBJECT]` on detail pages

Severity: medium (regression from `b940196`). Files:
`templates/spots/page.html:57-59`.

Template iterates closure dicts with `{{ c }}`. Confirmed live on
`/spots/balboa-pool/`. Executed in Step 4.

### 3. Open-water tide data missing in UI

Severity: medium. Files: `templates/spots/page.html:79-81`,
`static/js/conditions.js`.

Template reserves `<dd data-field="tide">` but `conditions.js` has no tide
code path. Executed in Step 6.

### 4. Closure phrasing wrong for inclusive end dates

Severity: low. Files: `static/js/status.js:71`.

`Closed until <end>` contradicts inclusive semantics. All current closures
are single-day so it reads as "Closed until today" on closure day. Prefer
`Closed through YYYY-MM-DD`. Executed in Step 5.

### 5. Detail schedule table renders legacy schema

Severity: medium. Files: `templates/spots/page.html:30,41`.

Dead `LANES` column (schema has no `lanes`), raw enum `FAMILY_SWIM`,
`pool`/`notes` never rendered. Executed in Step 4.

### 6. Grounding accepts fabricated evidence

Severity: medium. Files: `src/schedules/grounding.py:61`,
`tests/test_grounding.py`.

Success condition omits `evidence_in_pdf`. Paraphrased evidence with the
right time+type tokens passes. Executed in Step 3.

### 7. SFUSD closure instructions do not match schema or runtime

Severity: high. Files: `src/schedules/prompts/extract.txt:15`,
`src/schedules/schema.py`, `static/js/status.js`.

Prompt instructs providers to encode SFUSD slots as timed closures, but
schema is date-only and runtime treats closures as facility-wide.
Executed in Step 1 (gating item).

### 8. Compare mode overwrites adjudicated data

Severity: medium. Files: `src/schedules/pipeline.py:145,228`,
`src/schedules/cli.py`, `docs/schedules.md`.

`--compare-with` disables adjudication bypass and merges unless
`--dry-run` is set. Executed in Step 2.

### 9. Provider disagreement checks ignore `pool` and `notes`

Severity: medium. Files: `src/schedules/review.py:127-133`,
`tests/test_review.py`.

Diff key is `(day, type, start, end)`. Multi-zone disagreement invisible.
Executed in Step 3.

### 10. Partial extraction failure exits zero

Severity: medium. Files: `src/schedules/pipeline.py:298`.

`any(success/unchanged)` gate masks partial failure. Executed in Step 2.

## Execution Plan

### Step 0: Move product ideas out of the fix plan

- Move Swim Windows, Time Scrubber, Trust Layer to
  `docs/ideas/product-directions.md`.
- Leave this plan focused on fixes + hardening.

Definition of done:

- `docs/ideas/product-directions.md` contains all three ideas.
- This plan no longer contains "Saved Ideas".

### Step 1: Freeze the closure contract (finding 7) — DONE 2026-04-17

Why first: only finding that causes actively wrong content. Must land
before any extractor rerun.

Files:

- `src/schedules/prompts/extract.txt` — remove the timed-SFUSD-as-closure
  rule
- `src/schedules/schema.py` — freeze closures to `{start, end, reason}`;
  remove `pool`
- `docs/schedules.md` — document the closure contract
- `static/js/status.js` — one-line comment linking to the contract

TDD:

- `tests/test_extraction_contract.py::test_prompt_forbids_timed_sfusd_rows_in_closures`
  - `assert "Record these as a closure entry for that day and time" not in prompt`
  - `assert "Do not encode timed school-only bookings in closures[]" in prompt`
- `tests/test_extraction_contract.py::test_closures_are_date_only_and_facility_wide`
  - `assert "start_time" not in closures_props`
  - `assert "end_time" not in closures_props`
  - `assert "pool" not in closures_props`

Hardening beyond tests:

- Remove `closures[].pool` from schema and any fixtures.
- Bump prompt version; annotate existing adjudications with previous
  version.

Definition of done:

- Prompt no longer instructs providers to encode SFUSD slots as closures.
- Schema forbids timed or pool-scoped closures.
- Tests above pass.

### Step 2: Make compare mode observational and exit codes honest (findings 8 + 10) — DONE 2026-04-17

Why together: both land in `src/schedules/pipeline.py`; both are operator
trust; precondition for trusting any later re-run.

Files:

- `src/schedules/pipeline.py`
- `src/schedules/cli.py`
- `src/schedules/models.py` (if `PoolResult.status` gets a `Literal`)
- `docs/schedules.md`

TDD:

- `tests/test_pipeline.py::test_compare_mode_never_calls_merge_or_save_state`
  - `assert merge_calls == []`
  - `assert save_state_calls == []`
  - `assert results[0].written is False`
- `tests/test_pipeline.py::test_exit_code_is_nonzero_when_any_pool_failed`
  - `assert compute_exit_code([success, failed]) == 1`
  - `assert compute_exit_code([unchanged, skipped]) == 0`

Hardening beyond tests:

- Extract `compute_exit_code(results) -> int` pure helper.
- `read_only = dry_run or compare_with is not None` routes all writes.
- `PoolResult.status` becomes
  `Literal["success","unchanged","failed","skipped"]`.

Definition of done:

- `--compare-with` never writes unless an explicit `--write` opt-in.
- Partial failures exit non-zero.
- `docs/schedules.md` documents the behavior.

### Step 3: Tighten extraction-review correctness (findings 6 + 9)

Why now: honest exit codes + safe compare are worth less if grounding
rubber-stamps fabricated evidence and diffs miss multi-zone disagreement.
Same phase, separate test modules (different algorithms).

Files:

- `src/schedules/grounding.py`
- `tests/test_grounding.py`
- `src/schedules/review.py`
- `tests/test_review.py`

TDD (grounding):

- `tests/test_grounding.py::test_paraphrased_evidence_with_matching_type_and_time_is_not_grounded_without_verbatim_pdf_match`
  - `assert entry.evidence_in_pdf is False`
  - `assert entry.start_in_evidence is True`
  - `assert entry.type_in_evidence is True`
  - `assert entry.grounded is False`

TDD (review):

- `tests/test_review.py::test_compare_payloads_flags_pool_or_notes_only_session_disagreement`
  - Two providers agree on `(day, type, start, end)` but disagree on
    `pool`.
  - Diff flag evidence reflects the pool difference.

Hardening beyond tests:

- `grounding.py:61` changes to
  `ok = all((evidence_in_pdf, type_in_evidence, start_in_evidence, type_in_pdf_text))`.
- Session-diff key becomes a typed 6-tuple
  `(day, type, start, end, pool, notes)`.

Definition of done:

- Paraphrased evidence no longer passes grounding.
- Multi-zone-only disagreement surfaces in provider diff reports.

### Step 4: Rewrite pool detail template in one pass (findings 2 + 5)

Why together: both edits live in `templates/spots/page.html`; both driven
by the schedule schema as it exists today.

Files:

- `templates/spots/page.html`

TDD (Python-driven render test via `zola build` + HTML inspection):

- `tests/test_site_render.py::test_pool_detail_never_renders_object_literal_for_closures`
  - Build site; load `/spots/balboa-pool/index.html`.
  - `assert "[object Object]" not in html and "[object]" not in html`
  - Closure's actual date + reason are visible in the rendered HTML.
- `tests/test_site_render.py::test_schedule_table_uses_current_schema_fields`
  - `assert "<th>LANES</th>" not in html`
  - `assert "FAMILY_SWIM" not in html`
  - Human-readable program label ("Family Swim") present.
  - Pool zone label + notes render when present in content.

Hardening beyond tests:

- Tera macro or small mapping for program-label rendering; raw enum IDs
  never reach the DOM again.
- Closures rendered as `{{ c.start }}`, `{{ c.end }}`, `{{ c.reason }}` —
  never `{{ c }}`.
- Same audit done for `hazards`, `clubs`, `common_distances` so the same
  pattern cannot reintroduce.

Definition of done:

- No pool detail page renders `[object]`.
- Schedule table reflects current schema.
- `zola build` passes.

### Step 5: Extract JS helpers + fix board semantics (findings 1 + 4)

Why together: both land in `status.js`/`filters.js`. Right moment to
introduce the minimal JS test layer since fixes require pulling pure
logic out of DOM code anyway.

JS harness: Node's built-in `node:test`. No Vitest, no Jest, no jsdom.

Files:

- `static/js/status.js`
- `static/js/filters.js`
- `static/js/helpers/board.mjs` (new) — pure baseline-rank capture,
  sort-from-rank, closure copy
- `tests/js/board-status.test.mjs` (new)
- top-level npm script or Makefile target:
  `node --test tests/js/*.test.mjs`

TDD:

- `tests/js/board-status.test.mjs::restores_baseline_order_after_near_me_turns_off`
  - Baseline-sort → Near Me on → Near Me off → deep-equal to baseline.
- `tests/js/board-status.test.mjs::computeStatus_uses_closed_through_for_inclusive_end_dates`
  - Expects `Closed through 2026-04-17`, not `Closed until 2026-04-17`.

Hardening beyond tests:

- `data-baseline-rank` on each row after `status.js` sort; dispatched via
  `sf:status-applied`.
- `applyFilters` always sorts from rank when `nearMe` is false.
- `closureCopy(closure)` pure helper — no inline string templates.

Definition of done:

- Near Me on/off restores exact baseline ordering.
- Active closure copy says `Closed through YYYY-MM-DD`.
- `node --test tests/js/*.test.mjs` green in CI-friendly form.

### Step 6: Surface tide data on open-water detail pages (finding 3)

Why last: isolated, additive, benefits from the JS helpers added in
Step 5.

Files:

- `static/js/conditions.js`
- `static/js/helpers/tide.mjs` (new, pure)
- `tests/js/conditions.test.mjs` (new)
- existing tide slot in `templates/spots/page.html:79-81`

TDD:

- `tests/js/conditions.test.mjs::formatTideSummary_uses_next_upcoming_predictions`
- `tests/js/conditions.test.mjs::formatTideSummary_returns_null_for_missing_predictions`

Hardening beyond tests:

- `formatTideSummary(record, now)` pure and deterministic; DOM glue in
  `conditions.js` stays thin.
- Manually verify on `/spots/ocean-beach/` and `/spots/aquatic-park/`.

Definition of done:

- Open-water detail pages show a readable tide summary locally.
- Homepage temperature injection still works.

## Verification

- `uv run pytest`
- `node --test tests/js/*.test.mjs`
- `zola build`
- `cd worker && npm run typecheck`
- `devenv up` and visit:
  - `/`
  - `/map/`
  - `/spots/aquatic-park/`
  - `/spots/balboa-pool/`
  - `/spots/sava-pool/`
- Specifically verify:
  - No `[object]` anywhere.
  - Near Me toggles reversibly.
  - Closure copy says `Closed through ...`, not `Closed until ...`.
  - Tide rendered on open-water detail pages.
  - `--compare-with` is observational without explicit write opt-in.
  - Pipeline exits non-zero when any pool fails.

## Post-Plan (not part of this plan)

- Single-pool canary: rerun extractor on `balboa-pool` only, with the new
  prompt, and confirm the 2026-04-17 adjudication reproduces without
  SFUSD rows leaking into closures.
- Only after that, consider a fuller rerun.
- Post-fix product direction sequence lives in
  `docs/ideas/product-directions.md`.
