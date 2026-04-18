---
status: in_progress
progress:
  - section: "Step 1: Wire Python toolchain into devenv"
    status: complete
    notes:
      - "pyproject.toml added with uv-managed dependencies and a `schedules` console script"
      - "src/schedules/cli.py added with `extract` command; `uv run schedules --help` verified"
      - ".gitignore updated for data/pdfs/ and tmp/; README now points to docs/schedules.md and API key env vars"
  - section: "Step 2: Build the pool registry"
    status: partial
    notes:
      - "src/schedules/registry.toml + registry.py added; loader validates slugs against content/spots/*.md"
      - "Current published PDF URLs captured for Balboa, Coffman, Garfield, Hamilton, MLK, North Beach, and Rossi"
      - "blocker: Mission Community Pool facility page announced Summer 2026 opening but exposed no current 2026 schedule PDF as of 2026-04-17; registry marks it `missing_current_schedule` and skips it"
      - "blocker: Sava Pool facility page still points at an old Fall 2025 PDF while the pool remains closed for repairs; registry marks it `closed_without_current_schedule` and skips it"
  - section: "Step 3: Fetch + cache PDFs"
    status: complete
    notes:
      - "src/schedules/fetch.py added with httpx retries, sha-addressed cache files, local cache index, and pypdf page-count sanity check"
      - "unit test covers fetch, sha naming, and second-run cache hit without a second HTTP request"
  - section: "Step 4: Provider abstraction"
    status: complete
    notes:
      - "Anthropic and Gemini provider adapters added behind src/schedules/providers/"
      - "Anthropic path uses document base64 + tool schema; Gemini path uses Part.from_bytes + JSON response schema"
      - "real extraction verified after `.env` setup; default model is `gemini-3.1-flash-lite-preview` and Anthropic remains available for manual adjudication"
  - section: "Step 5: Schema + prompt"
    status: complete
    notes:
      - "Shared JSON schema added in src/schedules/schema.py"
      - "Extraction prompt added at src/schedules/prompts/extract.txt"
  - section: "Step 6: Syntactic validation"
    status: complete
    notes:
      - "src/schedules/validate.py added with session-count, time-range, closure-range, and ISO-date checks"
      - "unit tests cover valid and invalid payloads"
  - section: "Step 7: Semantic delta validation"
    status: complete
    notes:
      - "src/schedules/delta.py added with session-count delta, disappearing session-type, schedule regression, and zero-session hard-block rules"
      - "unit tests cover both soft flags and hard-block behavior"
  - section: "Step 8: Merge into pool .md"
    status: complete
    notes:
      - "src/schedules/merge.py added with targeted frontmatter updates only"
      - "merge preserves non-schedule fields and body text; it is a no-op when extracted schedule fields already match"
      - "unit tests verify both no-op behavior and scoped writes"
  - section: "Step 9: State file"
    status: complete
    notes:
      - "data/extraction-state.json added"
      - "src/schedules/state.py added with load/save helpers and state entry builder"
      - "state format now supports structured review flags, artifact paths, PDF page counts, PDF text hashes, and adjudication fingerprints for future accepted runs"
  - section: "Step 10: Report writer"
    status: complete
    notes:
      - "src/schedules/report.py added and writes tmp/extraction-report.md"
      - "report now surfaces `review_flag[...]`, `pdf_text_sha256`, and artifact paths under `data/artifacts/`"
  - section: "Step 11: Pipeline orchestrator + CLI"
    status: complete
    notes:
      - "src/schedules/pipeline.py wires registry, fetch, provider, validation, delta, merge, state, and reporting together"
      - "`--compare-with` runs a second provider on the same PDF, saves both raw payloads, and raises disagreement flags without merging the secondary result"
      - "PDF signal heuristics now flag repeated day-grid pages and likely under-extracted timed lesson blocks"
      - "Committed `data/adjudications/<slug>/<pdf_sha256>.json` files now let the extractor reuse manually reviewed payloads on later runs"
  - section: "Step 12: End-to-end run"
    status: complete
    notes:
      - "Verification complete: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests` passed (12 tests)"
      - "Verification complete: `UV_CACHE_DIR=/tmp/uv-cache uv run schedules --help` passed"
      - "Verification complete: `set -a; source .env; set +a; UV_CACHE_DIR=/tmp/uv-cache uv run schedules extract` returned `7 succeeded, 2 skipped, 0 failed`"
      - "Verification complete: `set -a; source .env; set +a; UV_CACHE_DIR=/tmp/uv-cache uv run schedules extract --provider gemini --compare-with anthropic --only hamilton-pool,north-beach-pool --dry-run --force` returned `2 succeeded, 2 flagged for manual review` and wrote artifact bundles"
      - "Verification complete: `zola build` passed"
  - section: "Step 13: Re-run idempotence"
    status: complete
    notes:
      - "Verification complete: second full run returned `7 unchanged, 2 skipped, 0 failed` when upstream PDF bytes were unchanged"
      - "Manual-review compare runs are intentionally executed with `--dry-run --force` because provider outputs are nondeterministic enough that flagged pools should not auto-update state"
  - section: "Step 14: Document + hand off"
    status: complete
    notes:
      - "docs/schedules.md updated with `--compare-with`, local artifact review, adjudication files, and commit guidance"
      - "README.md updated to point maintainers at the extractor workflow, raw artifact cache, and committed adjudications"
last_review: 2026-04-17T15:46:00-07:00
iterations: 2
no_progress_count: 0
started_at: 2026-04-17T01:25:21-07:00
work_unit_granularity: step
---

# SwimFrancisco Pool Schedule Extraction Plan

Reference: [docs/spec.md](../spec.md) ("Scraping Pipeline v2"), [docs/plans/archived/plan-v1.md](archived/plan-v1.md)

## Context

v1 shipped with 8 of 9 pools carrying empty `[[extra.sessions]]` arrays. SF Rec
& Parks publishes schedules as PDFs on sfrecpark.org (linked from each pool's
facility page). This plan builds a local Python CLI that extracts schedule data
from those PDFs into the pool `.md` frontmatter, along with a review report the
user scans before committing.

**Scope of this plan (v2):** local CLI that populates `sessions[]`, `closures[]`,
and `schedule_effective` for all 9 pools. Not in scope: GitHub Action wrapping,
automated PRs, open-water spots, address/lat/lng/website/cost/description (those
stay hand-curated). The CLI's interfaces are designed so a weekly Action can
wrap it later (v3) without refactoring.

**Strategy:** LLM-only extraction via Python SDKs with native PDF input and
structured output (JSON schema). Two provider backends — `anthropic` and
`google-genai` — selectable via `--provider` / env. Output is hand-reviewed via
`git diff content/spots/` plus a per-run report. No structured PDF parser
(pdfplumber): at 9 PDFs × quarterly, the maintenance cost exceeds the benefit,
and municipal PDF layouts drift with every republish.

## Post-review notes (magi, 2026-04-17)

Design revised in response to magi review findings:
- Dropped subprocess-to-CLI boundary (claude CLI has no file-input flag; stdout
  contamination + auth state was fragile). Replaced with Python SDKs.
- Dropped structured pdfplumber phase + `tests/golden/` + `bakeoff` subcommand.
  LLM is primary and permanent. `--provider` flag allows manual A/B.
- Fixed day enum in prompt spec: full lowercase `monday..sunday` (not abbreviated) —
  `static/js/status.js` `DAY_KEYS` requires full names.
- Added semantic delta validation (session count Δ threshold, disappearing
  session types, `schedule_effective` regression).
- `closures = []` is always written, never omitted.
- `24:00` end-of-day disallowed (breaks `parseHHMM`); use `23:59` or split across
  days. Enforced by schema.
- Closure dates strict `YYYY-MM-DD` ISO (status.js does lexicographic compare).
- Second TOML consumer named: `templates/spots/page.html` (renders weekly table).
- Timezone: all times are America/Los_Angeles implicit; frontend uses client
  `Date.getDay()`. Documented, not fixed.

## Success criteria

- `uv run schedules extract` populates sessions/closures/schedule_effective on
  all 9 pools.
- `tmp/extraction-report.md` summarizes per pool: provider, model, sessions
  count, invariants, semantic delta vs last run, cost estimate, any error.
- `git diff content/spots/` is scannable and trustworthy enough to commit.
- Hand-curated fields (`title`, `lat`, `lng`, `address`, `website`, `cost`,
  `description` body) are never touched.
- Per-pool failures do not block other pools.
- Re-running with no PDF byte changes is a no-op (report shows "unchanged",
  exit 0, zero file writes).

## Phase 1: Scaffold & registry

### Step 1: Wire Python toolchain into devenv
- `devenv.nix` already exposes Python + uv; no changes expected.
- Create `pyproject.toml` at repo root with uv-managed deps:
  `anthropic`, `google-genai`, `tomlkit`, `httpx`, `click`, `pytest`, `pypdf` (for
  page-count sanity check only, not extraction).
- Create `src/schedules/__init__.py` + `src/schedules/cli.py` with a `click`
  group. Single subcommand for now: `extract`.
- Entry point: `uv run schedules --help` lists `extract`.
- `.gitignore`: `data/pdfs/`, `tmp/`, `.venv/` (if not already present).
  - API key bootstrap: README section documents `ANTHROPIC_API_KEY` and
  `GOOGLE_API_KEY`; neither is committed. `devenv` users put them in `.env`
  or `.env.local`, loaded via `dotenv.enable`.

### Step 2: Build the pool registry
- `src/schedules/registry.toml`, one entry per pool:
  - `slug` — matches `content/spots/<slug>.md`
  - `pdf_url` — current SF Rec & Parks DocumentCenter URL for the schedule
  - `official_page_url` — sfrecpark.org facility page (for report links)
- Source `pdf_url` by opening each facility page and grabbing the "Schedule"
  PDF link. 9 entries. Commit.
- `src/schedules/registry.py`: `load_registry() -> list[PoolEntry]`. Validates
  every entry has all three fields and that each `slug` corresponds to an
  existing `content/spots/<slug>.md`.

### Step 3: Fetch + cache PDFs
- `src/schedules/fetch.py`: `fetch_pdf(slug, url) -> FetchResult`.
- Writes to `data/pdfs/<slug>-<sha256[:12]>.pdf`. Returns
  `{path, sha256, bytes, from_cache}`.
- Skips download if a file with the expected hash exists.
- `httpx` with 30s timeout, retries 2× on network errors.
- Unit test: fetch from a local HTTP fixture, verify hash + cache hit on
  second call.

## Phase 2: LLM extraction

### Step 4: Provider abstraction
- `src/schedules/providers/__init__.py` — exports `extract(pdf_bytes, prompt, schema) -> ExtractedPayload`.
- `src/schedules/providers/anthropic_provider.py`:
  - Uses `anthropic.Anthropic().messages.create(...)` with model
    `claude-sonnet-4-6` (override via env `SCHEDULES_ANTHROPIC_MODEL`).
  - Passes PDF via document content block: `{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": <base64>}}`.
  - Uses tool-use with a single tool whose `input_schema` is the extraction
    JSON schema. Parses `tool_use.input` directly as `ExtractedPayload`.
  - Returns cost estimate from response usage.
- `src/schedules/providers/gemini_provider.py`:
  - Uses `google.genai.Client().models.generate_content(...)` with model
    `gemini-3.1-flash-lite-preview` (override via env `SCHEDULES_GEMINI_MODEL`).
  - Passes PDF via `types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")`.
  - Uses `response_schema` + `response_mime_type="application/json"` for
    structured JSON output.
  - Returns cost estimate from usage metadata.
- Provider selection: `--provider anthropic|gemini` CLI flag, default read from
  env `SCHEDULES_PROVIDER` (default: `gemini` — magi-preferred for PDF/tabular).

### Step 5: Schema + prompt
- `src/schedules/schema.py`: JSON schema (dict literal) shared by both providers.
  Encodes enums directly so the model is constrained server-side:
  - `day`: `["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]` (full lowercase — matches `static/js/status.js` `DAY_KEYS`)
  - `session.type`: `["lap_swim", "open_swim", "family_swim", "senior_swim", "lessons"]`
  - `start` / `end`: pattern `^([01]\d|2[0-3]):[0-5]\d$` — `24:00` forbidden.
  - `closures[].start` / `closures[].end`: pattern `^\d{4}-\d{2}-\d{2}$`.
  - `schedule_effective`: `^\d{4}-\d{2}-\d{2}$`.
  - `schedule_effective_end`: same pattern, nullable (optional field).
- `src/schedules/prompts/extract.txt`: the extraction prompt. Explicit rules:
  - "Emit sessions exactly as the PDF shows; do not infer."
  - "If the PDF lists any program not in the type enum, map to the nearest
    value or omit; never invent a new type."
  - "If a session ends at midnight, use 23:59."
  - "If a holiday/maintenance closure is listed, include it in closures[].
    Otherwise closures is an empty array."
  - "schedule_effective is the schedule's start-of-validity date. If the PDF
    names a quarter (e.g., 'Spring 2026 — Mar 17 to Jun 6'), set
    `schedule_effective_end` to the end date."

### Step 6: Syntactic validation
- `src/schedules/validate.py`: `validate(payload) -> ValidationResult`.
- Schema-level enums are enforced by the provider; `validate` catches edge
  cases JSON schema can't:
  1. `len(sessions) >= 5` (a pool with fewer than 5 weekly sessions is suspect)
  2. `start < end` per session (string compare on HH:MM works)
  3. `closure.start <= closure.end` per closure
  4. `schedule_effective` parses as ISO date
- Returns `{ok: bool, violations: [str], stats: {sessions, closures}}`.

### Step 7: Semantic delta validation
- `src/schedules/delta.py`: `check_delta(extracted, prior_state_entry) -> DeltaResult`.
- Flags but does NOT hard-fail; the report surfaces flags for human decision.
- Rules:
  - `session_count_delta_pct` > 20 → flag.
  - Any `session.type` present in prior run but absent in new run → flag
    (e.g., `lap_swim` disappearing).
  - `schedule_effective` regresses (new < prior) → flag.
  - `sessions_count` drops to 0 while prior > 0 → hard flag (block merge).
- Returns `{flags: [str], hard_block: bool}`.

### Step 8: Merge into pool .md
- `src/schedules/merge.py`: `merge(pool_md_path, extracted) -> MergeResult`.
- Uses `tomlkit` to parse frontmatter. Replaces only:
  - `extra.sessions` (always writes, even if empty — unexpected but allowed)
  - `extra.closures` (always writes, `[]` if no closures extracted — prevents
    stale closures surviving a re-run)
  - `extra.schedule_effective`
  - `extra.schedule_effective_end` (only if present in extracted)
- `extra.last_verified_at` is **not** touched by the merge. It is reserved for
  the human reviewer to bump after comparing the diff against the PDF.
- Preserves everything else (`title`, `slug`, `extra.type/subtype/address/
  lat/lng/website/cost`) and the entire post-`+++` description body byte-exact
  where tomlkit round-trip allows.
- Skipped if `delta.hard_block` is true.
- Returns `{prior_sessions_count, new_sessions_count, prior_closures_count, new_closures_count, written: bool}`.

### Step 9: State file
- `src/schedules/state.py`: `data/extraction-state.json` (committed).
- Schema: `{<slug>: {pdf_url, pdf_sha256, sessions_count, session_types: [str], schedule_effective, extracted_at, provider, model, invariants_passed: bool, flags: [str]}}`.
- `session_types` list is what powers delta-rule "type disappeared" check.
- Helpers: `load_state()`, `save_state()`, `entry_for(slug)`.
- Initial file is `{}`; Step 11 populates it.

### Step 10: Report writer
- `src/schedules/report.py`: `write_report(results) -> Path` at `tmp/extraction-report.md`.
- Summary header: `N/9 pools processed, X succeeded, Y skipped (unchanged), Z failed, W flagged for manual review`.
- Per-pool block:
  - slug + link to `official_page_url` + pdf_url
  - provider + model + pdf_sha256 short form
  - `sessions: 12 (+2 vs last run)`, `closures: 1`, `schedule_effective: 2026-03-17`
  - invariants: ✓ or list violations
  - delta flags: list or "none"
  - cost estimate (from provider usage)
  - error (if any)
- Footer: suggested commit commands (`git add content/spots data/extraction-state.json`).

### Step 11: Pipeline orchestrator + CLI
- `src/schedules/pipeline.py`: `run_pipeline(slugs, provider) -> list[PoolResult]`.
- Per slug: fetch → (if sha256 matches state and not `--force` → record "unchanged", skip) → provider.extract → validate → check_delta → merge (unless hard_block) → update state → record result.
- Per-pool failures are caught and recorded; pipeline exits 0 if ≥1 pool
  succeeded or was unchanged, 1 if all failed.
- `cli.py` `extract` flags:
  - `--only slug1,slug2` (subset)
  - `--provider anthropic|gemini` (override default)
  - `--force` (re-fetch even if sha256 matches)
  - `--dry-run` (skip merge and state write; still produce report)
- After Step 11 ships, user runs `uv run schedules extract`, reviews the
  report, inspects `git diff`, and commits when satisfied.

## Phase 3: Verification & handoff

### Step 12: End-to-end run
- `uv run schedules extract` on all 9 pools from a clean checkout (provider =
  default).
- Verify:
  - `content/spots/*.md` frontmatter populated for all 9 pools.
  - `zola build` passes; pool detail pages (`templates/spots/page.html`) render
    weekly schedule tables.
  - Homepage status columns (`static/js/status.js`) compute OPEN/CLOSED and
    NEXT for all pools — no pool shows em-dash STATUS.
  - `tmp/extraction-report.md` is present and readable.
  - `data/extraction-state.json` is populated with 9 entries.
- Any pool with `delta.flags` or validation failures gets a manual spot-check
  against the source PDF before commit.
- Commit in logically separate commits: code changes, registry, `content/spots/`
  bulk, `data/extraction-state.json`.

### Step 13: Re-run idempotence
- `uv run schedules extract` a second time with no upstream PDF changes.
- Expected: report shows 9/9 "unchanged" (pdf_sha256 matched state), no
  files modified, exit 0.

### Step 14: Document + hand off
- Add `docs/schedules.md`: CLI usage, quarterly re-verification flow, how to
  read the report, how to update the registry when SF Rec moves a PDF URL,
  how to provide API keys.
- Update root `README.md` under "Adding/updating spots" to point at
  `docs/schedules.md`.
- Leave a "Future (v3)" note: GitHub Action wraps `uv run schedules extract`,
  opens a PR on non-empty `content/spots/` diff.

## Critical files

- `devenv.nix` — Python + uv already enabled
- `pyproject.toml` — new
- `src/schedules/` — new package
- `src/schedules/registry.toml` — new, 9 entries
- `src/schedules/schema.py` — new, JSON schema shared by both providers
- `src/schedules/prompts/extract.txt` — new extraction prompt
- `data/extraction-state.json` — new, committed
- `content/spots/*.md` — merged into, never wholesale rewritten
- `.env` / `.env.local` — hold `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` locally

## Downstream consumers of the TOML

The extractor output must conform to what these already expect:
- `static/js/status.js` — consumes `sessions[]` + `closures[]`. Day enum is
  full lowercase (`DAY_KEYS = ['sunday', 'monday', ...]`). Time is `HH:MM`
  24h; `24:00` breaks `parseHHMM`.
- `static/js/filters.js` — type-pill filter matches `session.type` values
  `lap_swim | open_swim | family_swim` (and `open_water` for open-water rows).
  `senior_swim` + `lessons` are allowed in data but don't get filter pills.
- `templates/spots/page.html` — renders weekly schedule table + closures list
  on each detail page.

## Verification

- Unit: `pytest tests/` — validate invariants, delta rules, merge round-trip
  (Hamilton's committed file → no-op when extracted matches current), registry
  loader, state read/write.
- Integration: `uv run schedules extract --only hamilton-pool --dry-run`
  against the real PDF; assert extracted JSON schema-conforms and invariants
  pass. No assertion on exact session values (Hamilton is partially-verified
  ground truth, not gold).
- End-to-end: full `schedules extract`, then `zola build`, then manual browser
  check on `localhost:8787` that status columns populate for all 9 pools.
- Re-run idempotence: second run shows all "unchanged", no file writes.
