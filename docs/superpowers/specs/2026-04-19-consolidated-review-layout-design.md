# Consolidated Review Layout & Extract-Skip — Design

Date: 2026-04-19
Status: Draft for review

## Purpose

Collapse the current three-tree data layout (`data/pdfs/`, `data/artifacts/`, `data/reviewed-snapshots/`) into a single per-review directory and commit artifacts alongside the reviewed snapshot. This closes the "where does reviewer intent live?" gap left by removing the `summary` field: the reviewed envelope and the raw LLM extractions it was reviewed against are now co-located and permanently diffable in git.

Bundled simplifications (see "Complexity to cut" below): delete `extraction-state.json`, unify envelope validation, de-dupe artifact metadata, eliminate the drafts directory.

Teach `schedules extract` to skip extraction work when a PDF's artifacts already exist with a matching prompt hash.

## Non-goals

- No changes to envelope payload shape (`schedule_effective`, `sessions`, `closures`).
- No changes to the content projection (`content/spots/<slug>.md`).
- No changes to the CLI surface (`schedules extract`, `schedules review`, `schedules project`, `schedules debug bakeoff`). Flags and output semantics are preserved.
- No concurrency story. Solo maintainer, linear workflow.

## Architecture

### One directory per review

```
data/<slug>/<date>-<pdf-sha12>/
├── source.pdf                           # committed, immutable
├── <provider>-<model-slug>.json         # committed; one per provider; self-describing
└── reviewed.json                        # exists ⇔ reviewed

data/extraction-state.json               # DELETED
data/pdfs/                               # DELETED (content moves into per-review dirs)
data/artifacts/                          # DELETED (ditto)
data/reviewed-snapshots/                 # DELETED (ditto); schema moves to src/schedules/schemas/
data/reviewed-snapshot-drafts/           # DELETED (no draft concept)
```

The review-unit directory is the state. The filesystem is the source of truth. Each `<provider>-<model-slug>.json` is self-describing: it carries its own `prompt_sha256`, `schema_sha256`, `extracted_at`, `provider`, `model`, `usage`, `cost_estimate`, `payload`, and optional `grounding`. No shared `meta.json`.

### Date semantics

`<date>` in the directory name is the PDF's **first-seen fetch date** — the date `fetch.py` wrote `source.pdf`. It never changes for a given `<pdf-sha12>`. Re-downloading the same hash short-circuits before rename.

This matches the existing convention in `data/pdfs/<slug>/<date>-<sha>.pdf` and is preserved across the migration.

### `reviewed.json` — the filesystem IS the state machine

One predicate: **`reviewed.json` exists ⇔ reviewed.** That's it.

- File present → the pool has been reviewed. Pipeline emits `Unchanged` (unless `--force` or `--compare-with`).
- File absent → needs work. Pipeline will seed it; queue scan surfaces the dir.

No git invocations on the hot path. No tracked/dirty/staged distinctions. No `is_approved` helper. No draft concept. Git's role is its normal one — recording history of files the user commits — not adjudicating review state.

Re-review: `rm data/<slug>/<dir>/reviewed.json` (or `--force`) and re-run. Abandon in-flight edits: `git restore` or `git checkout`. These are user-workflow concerns, not pipeline concerns.

`seed_draft` = **write if missing, never overwrite.** Finalize rewrites are atomic via `os.replace` on `reviewed.json.tmp` within the same dir.

### Extract-skip logic

For each selected registry entry, the pipeline:

1. Fetch the PDF. Compute sha256.
2. Resolve the target directory: `data/<slug>/<first-seen-date>-<sha12>/`.
3. If `source.pdf` and `<provider>-<model-slug>.json` already exist and the provider file's embedded `prompt_sha256` + `schema_sha256` match current, skip extraction. Emit `Unchanged` with the cached payload.
4. Otherwise, run extraction and overwrite the provider file.

Per-provider skip: `--compare-with anthropic` runs anthropic even if gemini is already cached.

`--force` ignores the skip and re-extracts.

Invalidation knob: `prompt_sha256` + `schema_sha256` embedded in each provider JSON. Bumping the prompt or extraction schema invalidates all cached extractions on the next run.

### `reviewed.json` skip (unchanged semantics, new home)

The existing "reviewed-snapshot seen for this hash → skip LLM" path keeps working. Now it's: if `reviewed.json` exists in the target dir AND the run isn't `--force`/`--compare-with`, the pipeline uses its payload verbatim instead of invoking a provider. The artifacts may or may not be present — an existing `reviewed.json` is authoritative on its own.

## Envelope trim

Collapsing everything that isn't pulling its weight:

- **Drop `$schema`** — no published URL, solo project, no editors need the pointer. If IDE hinting ever becomes valuable, that's a local config, not a per-file field.
- **Drop `version`** — one shape at a time. A shape change is a migration, not a runtime predicate.
- **Drop `reviewed_by`** — git commit authorship already answers "who reviewed this."
- **Drop `reviewed_against`** — the sibling `<provider>-*.json` files in the review dir already enumerate what was considered. A separate field that restates them is just drift-bait.

Envelope shrinks to:

```json
{
  "slug": "rossi-pool",
  "pdf_sha256": "f580...f",
  "reviewed_at": "2026-04-17",
  "source_pdf_url": "https://sfrecpark.org/...",
  "payload": { "schedule_effective": "...", "sessions": [...], "closures": [...] }
}
```

- `reviewed_at`: useful standalone (reports, display).
- `source_pdf_url`: immutable provenance; `registry.toml` URLs drift.
- `pdf_sha256` + `slug`: lock the envelope to a specific PDF and pool; cross-checked at load against the directory.
- `payload`: the canonicalized schedule data.

### Unify validation

Delete `reviewed_snapshots.py::_validate_envelope` (hand-rolled, lenient). All load paths go through `envelope.py::validate_envelope` (jsonschema, strict — enforces `additionalProperties: false`).

Old snapshots carrying a `summary` field would now fail to load. That's fine: the migration script strips `summary` (already done as of the prior refactor) and all on-disk snapshots are clean.

## Pipeline-state deletion

`data/extraction-state.json` goes away. What it used to hold, and where it goes now:

| Former state field | Replacement |
|---|---|
| `pdf_sha256` | Directory name |
| `extracted_at` | `meta.json::extracted_at` (already there) |
| `provider` / `model` | Filename `<provider>-<model>.json` |
| `artifact_paths` | The directory IS the artifact path |
| `pdf_page_count` | `meta.json` (already there) |
| `pdf_text_sha256` | `meta.json` (already there); dropped from pipeline report |
| `reviewed_snapshot_sha256` | Recomputable from `reviewed.json` content |
| `notes` / `note_details` | Regenerated each run; not persisted across runs |

The `Unchanged` path no longer replays prior-run notes. If nothing changed, the previous commit's `tmp/extraction-report.md` already captured them.

## Provider JSON is self-describing

No sibling `meta.json`. Each `<provider>-<model-slug>.json` carries everything it needs, including the two fields that review seeding depends on and that can't be reconstructed later:

```json
{
  "provider": "gemini",
  "model": "gemini-3.1-flash-lite-preview",
  "extracted_at": "2026-04-17T10:30:00-07:00",
  "prompt_sha256": "...",
  "schema_sha256": "...",
  "source_pdf_url": "https://sfrecpark.org/...",
  "pdf_sha256": "f580...f",
  "usage": {...},
  "cost_estimate": "...",
  "payload": {...},
  "grounding": {...}
}
```

- `source_pdf_url` and `pdf_sha256` stay because `review.py` seeds the envelope from a provider artifact and `registry.toml` URLs can drift. They're the immutable provenance record tied to this specific extraction.
- Dropped (derivable from the containing directory or the PDF itself): `slug`, `pdf_page_count`, `pdf_text_sha256`.

Why fold `meta.json` away: the only values it held that weren't already in each provider JSON were `prompt_sha256` + `schema_sha256`, and duplicating two 64-char strings per provider file is cheaper than maintaining "one shared file + N per-provider files." Each file is now complete on its own.

## Migration

One-shot script `scripts/migrate_consolidated_layout.py`:

1. For each existing `data/reviewed-snapshots/<slug>/<date>-<sha12>.json`:
   - Read envelope to get `pdf_sha256` and `reviewed_at`.
   - The PDF's first-seen date may differ from `reviewed_at`. Resolve via `data/pdfs/<slug>/*-<sha12>.pdf`; use the date prefix from that filename. If no PDF exists, fall back to `reviewed_at`.
   - Create `data/<slug>/<date>-<sha12>/`.
   - Move `data/pdfs/<slug>/<date>-<sha12>.pdf` → `.../source.pdf`.
   - If `data/artifacts/<slug>/<sha12>/` exists:
     - Read the existing `meta.json` (for `prompt_sha256` + `schema_sha256` + `source_pdf_url`; compute/fall back from current prompt/schema/envelope if missing — worst case triggers one re-extraction).
     - For each `<provider>-<model>.json`: drop `slug`/`pdf_page_count`/`pdf_text_sha256`; keep (or inject from meta.json / the envelope) `source_pdf_url` + `pdf_sha256`; inject `prompt_sha256` + `schema_sha256` + `extracted_at`; write to the new dir.
     - Do NOT carry `meta.json` forward — it's folded away.
   - Move the snapshot file → `.../reviewed.json`. Strip `version`, `$schema`, `reviewed_by`, `reviewed_against`. Keep `slug`, `pdf_sha256`, `reviewed_at`, `source_pdf_url`, `payload`.
2. Delete `data/pdfs/`, `data/artifacts/`, `data/reviewed-snapshots/` (now empty).
3. Delete `data/extraction-state.json`.
4. Move `data/reviewed-snapshots/schema.json` → `src/schedules/schemas/reviewed-snapshot.json` (schema is code).
5. Print summary: N review dirs created, M snapshots migrated, P extractions will re-run on next `schedules extract`.

The script is idempotent — re-running after partial success continues where it left off.

### `.gitignore` delta

```diff
-data/artifacts/
-data/reviewed-snapshot-drafts/
```

Nothing new gitignored. `reviewed.json` WIP is untracked-because-new-file, not because of gitignore.

### PR heads-up for developers with local state

Anyone who has run the pipeline locally will have untracked files under `data/pdfs/`, `data/artifacts/`, and a local `data/extraction-state.json`. The migration script handles everything it finds. Stale top-level `pdfs/artifacts/extraction-state.json` that predate the merge can be deleted manually — or ignored, since the new layout doesn't reference them.

## Pipeline code changes

### `src/schedules/paths.py`

Replace the existing `ARTIFACTS_DIR`, `PDF_CACHE_DIR`, `REVIEWED_SNAPSHOTS_DIR`, `STATE_PATH` constants (some go away entirely). Add:

```python
def review_dir(slug: str, date: str, pdf_sha256: str) -> Path
def pdf_path(slug: str, date: str, pdf_sha256: str) -> Path       # -> ".../source.pdf"
def artifact_path(slug: str, date: str, pdf_sha256: str, provider: str, model: str) -> Path
def reviewed_path(slug: str, date: str, pdf_sha256: str) -> Path  # -> ".../reviewed.json"
def latest_review_dir(slug: str) -> Path | None                    # sorts by date prefix
def all_review_dirs(slug: str) -> list[Path]
```

All paths resolve under `DATA_DIR` (renamed from the current `ARTIFACTS_DIR` parent). No `meta_path` — meta is folded into each provider JSON.

### `src/schedules/fetch.py`

Rewrite cache resolution to work on the new layout. On a cache miss, writes `source.pdf` into the target review directory (creating the directory if needed).

### `src/schedules/artifacts.py`

`save_artifact_bundle` writes a self-describing provider JSON (includes `prompt_sha256` + `schema_sha256` + `extracted_at`). Gains a `skip_if_fresh(slug, date, pdf_sha256, provider, model, prompt, schema)` helper: returns True if the provider file exists and its embedded hashes match current.

### `src/schedules/reviewed_snapshots.py`

- Delete `_validate_envelope`, `_REQUIRED_ENVELOPE_FIELDS`. All callers use `envelope.validate_envelope`.
- `load_reviewed_snapshot(slug, pdf_sha256)` resolves through `paths.reviewed_path`; returns `(envelope, fingerprint, path) | None`.

No `is_approved` helper. "Is this reviewed?" is `reviewed_path.exists()` — inline at the call site.

### `src/schedules/state.py`

Delete. No replacement.

### `src/schedules/pipeline.py`

- Remove all `load_state` / `save_state` / `build_state_entry` / `notes_for_entry` calls and imports.
- Fast-path `Unchanged`: if `reviewed_path(...).exists()` AND the run is not `--force` and not `--compare-with`, emit Unchanged using the envelope payload. `--force` and `--compare-with` always fall through to extraction.
- Pre-extraction skip: `artifacts.skip_if_fresh(...)` before invoking the LLM.
- Drop `pdf_text_sha256` threading; compute locally where needed.

### `src/schedules/review.py`

- `seed_draft` writes `reviewed.json` at its final path, ONLY if the file doesn't exist. Never overwrites. No idempotency branches.
- Queue scanning: iterate `data/<slug>/<date>-<sha12>/` dirs; include any where `reviewed.json` does not exist. Oldest-date-first, ties by slug.
- `finalize_draft` loses the rename step. New flow: validate → project. If anything fails, `reviewed.json` stays as-is; CLI returns non-zero with a clear error. To protect against partial writes when the CLI itself authors content, write to `reviewed.json.tmp` + `os.replace` (atomic within a single dir on POSIX/Windows).

### `src/schedules/report.py`

- Remove the `- pdf_text_sha256: ...` line.
- Artifact path listing becomes simpler since there's one directory per review.

### `src/schedules/project.py`

Reads `reviewed.json` via `paths.reviewed_path`. No other changes.

## Schema changes

`data/reviewed-snapshots/schema.json` → `src/schedules/schemas/reviewed-snapshot.json`.

Contents:
- Remove `$schema`, `version`, `reviewed_by`, `reviewed_against` properties.
- Update `required` to `["slug", "pdf_sha256", "reviewed_at", "source_pdf_url", "payload"]`.
- Keep `additionalProperties: false`.
- Payload sub-schema unchanged.

## Tests

All tests that construct fixture envelopes or mock the filesystem need path updates. No behavioral changes.

New tests:
- `test_extract_skip`: running `schedules extract` twice on the same PDF invokes the LLM exactly once. Bumping `prompt` causes re-extraction.
- `test_envelope_trim`: schema rejects envelopes carrying `version`, `$schema`, `reviewed_by`, or `reviewed_against` (sanity-check of `additionalProperties: false`).
- `test_review_queue_existence`: `reviewed.json` present → not in queue; absent → in queue. No git needed.
- `test_pipeline_force_ignores_reviewed`: `--force` and `--compare-with` bypass the fast-path even when `reviewed.json` exists.
- `test_migration_consolidated_layout`: the migration script moves existing fixtures into the new shape idempotently.

Delete tests coupled to the old layout: `test_migration_idempotent.py` becomes the above; anything referencing `STATE_PATH`, `ARTIFACTS_DIR`, `extraction-state.json` by path goes.

## Complexity to cut (summary)

This spec removes:

- `data/extraction-state.json` and all of `src/schedules/state.py`.
- `data/reviewed-snapshot-drafts/` tree.
- `_validate_envelope` hand-rolled checker; `_REQUIRED_ENVELOPE_FIELDS`.
- `meta.json` (folded into each provider JSON).
- The `is_approved` helper AND any git-based approval predicate — replaced by `path.exists()`.
- Envelope fields: `$schema`, `version`, `reviewed_by`, `reviewed_against`.
- Redundant fields in per-provider JSON (`slug`, `pdf_page_count`, `pdf_text_sha256`). `source_pdf_url` and `pdf_sha256` are retained — review seeding needs them and registry URLs drift.
- `pdf_text_sha256` threading through state/report/models.
- Three top-level `data/` subdirectories merged into per-review directories.
- The draft → snapshot rename step.
- The "reopen existing draft" idempotency branch in `seed_draft`.

Net code delta: ~-400 LOC estimated. The biggest single deletions are `state.py`, `meta.json` wiring, and the is_approved/approval-gate concept collapsing into `path.exists()`.

## Resolved decisions

- **Date prefix on dir name:** fetch date. Immutable once the PDF is first seen.
- **Multiple reviews per PDF hash:** same hash → same `reviewed.json`; re-reviewing overwrites; prior versions live in git history.
- **Approval signal:** `reviewed_path(slug, date, sha).exists()`. Present ⇒ reviewed. No git on the hot path.
- **`--force` / `--compare-with` override the fast-path:** even when `reviewed.json` exists, these flags fall through to extraction.
- **`reviewed_by`, `version`, `$schema`, `reviewed_against` envelope fields:** hard remove. All redundant with git + the directory layout.
- **Schema location:** `src/schedules/schemas/reviewed-snapshot.json`. Schema is code, not data. No per-envelope `$schema` pointer — the schema is loaded by `envelope.py` directly.
- **Wheel packaging:** add `[tool.hatch.build]` `include = ["src/schedules/**/*.json"]` (or `force-include`) so the schema ships in the wheel. Low priority since the app runs from source via `uv run`, but correct while `pyproject.toml` is open.
- **Extract-skip key:** embedded `prompt_sha256` + `schema_sha256` in each provider JSON. Known gap: model-version drift within a configured `model` string is invisible. Acceptable for now; revisit if providers ever silently rev.

## Rollout

Single PR. Merge order:

1. Migration script + path helpers (no runtime behavior change yet).
2. Pipeline and review code rewrites.
3. Schema move and envelope trim.
4. Delete `state.py` and callers.
5. Run migration script on the committed fixtures. Commit result.
6. Update `docs/schedules.md` to describe the new layout.
7. Update `NAPKIN.md` if any current rules reference the old paths.

Every step leaves `main` in a working state only at the end — this is a flag-day migration, not a rolling one. Acceptable because there's one maintainer and one deployment target.
