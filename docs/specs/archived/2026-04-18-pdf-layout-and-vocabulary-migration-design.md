# PDF Layout and Vocabulary Migration — Design

Date: 2026-04-18
Status: Draft for review (magi round 3 revisions applied)
Order: Ships before the reviewer-tool spec.

## Purpose

Prepare the repository for a local review tool by doing two mechanical changes up front:

1. Move cached PDFs into per-slug, date-prefixed directories; check them in; mirror the layout for reviewed snapshots; drop `pdf-cache-index.json`.
2. Unify vocabulary on "review" — rename `src/schedules/review.py` → `src/schedules/diff.py`, scrub lingering "adjudicator/adjudicated" references, and codify the config-format convention.

Each change is reversible; the two ship atomically in one PR so `main` never sees an inconsistent on-disk state.

## Non-goals

- The reviewer tool itself (separate spec).
- Any semantics change to the existing envelope fields (`reviewed_by`, `source_pdf_url`, `reviewed_against`, `ratified_from_sha256`, `summary`, `payload`) — these are preserved exactly as `write_ratified_snapshot` writes them today.
- Changing extraction, validation, merge, or grounding logic.
- Migrating artifacts (`data/artifacts/` stays flat and gitignored).
- Touching Zola frontmatter schema beyond the one comment-line rewording.

## Part 1 — Filesystem layout

### Current

```
data/pdfs/balboa-pool-ba9b279ae183.pdf       (flat, gitignored)
data/pdf-cache-index.json                    (slug|url → filename)
data/reviewed-snapshots/balboa-pool/ba9b279ae183b142c0c675368bceb39e49b80ed5ddb12fe37736536e92c8ac2c.json
```

### New

```
data/pdfs/balboa-pool/2026-04-17-ba9b279ae183.pdf             (checked in)
data/reviewed-snapshots/balboa-pool/2026-04-17-ba9b279ae183.json
```

- **Filename pattern**: `<YYYY-MM-DD>-<hash_prefix>.<ext>`. Hash prefix is the **first 12 chars** of sha256, matching `fetch.py:61` and `artifacts.py:29`.
- **Date semantics (reconciled)**:
  - For PDFs: the date is the **first-seen fetch date** — the date `fetch.py` wrote the file for the first time. After that, the date does not change; re-downloading the same hash short-circuits before rename.
  - For reviewed snapshots: the date is the envelope's existing `reviewed_at` field. Unchanged semantics.
  - These may legitimately differ (a PDF can be fetched on day N and reviewed on day N+K). The filenames do not have to match dates; they share only the hash prefix. The full 64-char `pdf_sha256` inside each snapshot is the true join key.
- **Latest PDF for a slug**: `ls data/pdfs/<slug>/ | sort | tail -1`. No index file.
- **Reviewed-snapshot filenames mirror PDF hash prefix** — a human scanning `data/pdfs/balboa-pool/` and `data/reviewed-snapshots/balboa-pool/` sees matching prefixes for paired `(input, reviewed)` assets.
- **Prefix collision**: 12-char sha256 prefix collision within a slug is astronomically unlikely (48 bits → 1-in-a-million at ~24k PDFs per slug). The writer still checks and raises `FetchError` with both full 64-char hex digests when prefix matches but content differs.

### `.gitignore` delta

```diff
-data/pdfs/
```

`data/artifacts/` remains gitignored. `data/pdf-cache-index.json` is deleted (not ignored — removed from tracking).

**PR description must include a developer heads-up** (not part of the spec body): developers who have previously run the pipeline locally will have untracked `data/pdfs/*.pdf` files. A `git pull` that tries to check in the new tracked PDFs will abort with "untracked working tree files would be overwritten." Instruct them to `rm -rf data/pdfs/` before pulling.

### Pipeline code changes

#### `src/schedules/paths.py`

Add pure-function helpers:

```python
def pdf_dir(slug: str) -> Path:                                # data/pdfs/<slug>/
def reviewed_snapshot_dir(slug: str) -> Path:                  # data/reviewed-snapshots/<slug>/
def pdf_filename(date: str, pdf_sha256: str) -> str:           # "<date>-<hash[:12]>.pdf"
def snapshot_filename(date: str, pdf_sha256: str) -> str:      # "<date>-<hash[:12]>.json"
def latest_pdf(slug: str) -> Path | None:                      # sorted, highest date wins
def latest_reviewed_snapshot(slug: str) -> Path | None:
```

All return absolute paths under the existing `DATA_DIR` constant. Callers ensure directory existence (current pattern).

#### `src/schedules/reviewed_snapshots.py`

**No signature changes** to `write_ratified_snapshot` or `load_reviewed_snapshot` — both still take `pdf_sha256` (full 64-char). The full envelope (`reviewed_by`, `source_pdf_url`, `reviewed_against`, `ratified_from_sha256`, `summary`, `payload`) is preserved bit-for-bit.

What changes:

- `reviewed_snapshot_path(slug, pdf_sha256, root=…)` — now resolves the new layout. Implementation: glob `<slug>/*-<pdf_sha256[:12]>.json`; if one file matches, return it; if none, return the canonical write path `<slug>/<today>-<pdf_sha256[:12]>.json`; if more than one matches (shouldn't happen), raise.
- `load_reviewed_snapshot` uses the same helper unchanged — still verifies `raw["pdf_sha256"] == expected_pdf_sha256` (full 64-char), which catches prefix-collision drift.
- `write_ratified_snapshot` uses the same helper for the write path. Envelope unchanged.
- `find_snapshots_for_slug` unchanged (already returns `sorted(slug_dir.glob("*.json"))`).

#### `src/schedules/fetch.py`

Rewrite the cache layer. Today it uses `pdf-cache-index.json` as a URL→filename index. New behavior:

1. GET the URL, stream to memory, compute sha256.
2. Take the 12-char prefix. Glob `data/pdfs/<slug>/*-<prefix>.pdf`.
3. If a match exists and its full-file sha256 matches: cache hit, return that path with `from_cache=True`. Date in the filename stays untouched.
4. If a match exists but the full sha256 differs: raise `FetchError(f"prefix collision in {slug}: existing={existing_full_hash} new={new_full_hash}")`.
5. If no match: write to `data/pdfs/<slug>/<today>-<prefix>.pdf`, return path with `from_cache=False`. Today = first-seen fetch date, which is then immutable for this hash.

Cost: one extra GET per cache hit compared to the index lookup. Acceptable — the pipeline runs at most daily, `debug bakeoff` hits 7 pools × 2 providers = 14 fetches, each is <50KB. No measurable impact.

Behavior change to note in the PR description: the URL → hash mapping is no longer cached. If an upstream URL changes but content is identical, we re-GET instead of short-circuiting. User-visible effect: an extra network call, not re-extraction (downstream logic keys on `pdf_sha256`).

#### `src/schedules/pipeline.py`, `state.py`

No logic changes. Paths propagate through the helpers above. `state.py:9` is affected by the rename in Part 2 (below), not the layout work.

### Migration script

`scripts/migrate_pdf_layout.py` — stdlib only, **committed permanently** under `scripts/`. Idempotent. Documented as the canonical way to bring a fresh clone or an older branch into the new layout.

Behavior:

1. **Check target completeness first** (so the script survives a deleted `pdf-cache-index.json`). If every slug directory under `data/pdfs/` already contains one-or-more files matching `^\d{4}-\d{2}-\d{2}-[0-9a-f]{12}\.pdf$` AND `data/pdf-cache-index.json` is absent AND no files exist matching the old flat pattern `data/pdfs/<slug>-<hash>.pdf`, print "already migrated" and exit 0.
2. Otherwise, read `data/pdf-cache-index.json` if present. For each `slug|url → filename` entry:
   - Source: `data/pdfs/<filename>` (old flat path).
   - Determine date:
     - If a `data/reviewed-snapshots/<slug>/<full-hash>.json` exists, use its `reviewed_at` field.
     - Else, use the source file's mtime date.
   - Hash prefix: first 12 chars of the hash embedded in the old filename.
   - Destination: `data/pdfs/<slug>/<date>-<prefix>.pdf`.
   - Move file.
3. For each old flat reviewed-snapshot at `data/reviewed-snapshots/<slug>/<full_hash>.json`:
   - Pull `reviewed_at` from the JSON envelope.
   - Rename to `<reviewed_at>-<prefix>.json`.
4. Delete `data/pdf-cache-index.json`.
5. Print summary: N PDFs moved, M snapshots renamed, index deleted.

Failure modes: if any source file is missing or any hash cannot be resolved, fail fast with the offending slug/path; leave the rest untouched.

### Tests — new

- `tests/test_paths_layout.py` — helpers return correctly shaped paths; `latest_pdf` / `latest_reviewed_snapshot` sort lexicographically (ISO dates sort correctly).
- `tests/test_fetch_cache.py` — cache-hit, cache-miss, prefix-collision → `FetchError` with both full hashes. Uses tmp `DATA_DIR`.
- `tests/test_migration_idempotent.py` — runs the migration twice in a tmp tree; second run is a no-op; also verifies the "already migrated, index already deleted" branch.

### Tests — existing, must be updated

- `tests/test_fetch.py` — fixture layout updated to new path shape; `pdf-cache-index.json` references removed; new `FetchError` case asserted.
- `tests/test_reviewed_snapshots.py` — all `tmp_path` fixtures now write snapshots at `<slug>/<date>-<prefix>.json` instead of `<slug>/<full-hash>.json`. The `load_reviewed_snapshot` assertions still pass unchanged because the glob-by-prefix helper resolves correctly.
- `tests/test_ratification.py` — same fixture updates; `write_ratified_snapshot` + `find_snapshots_for_slug` behavior unchanged at the envelope level.

## Part 2 — Vocabulary unification

### `src/schedules/review.py` → `src/schedules/diff.py`

The file contains only `compare_payloads()`, `serialize_note()`, `deserialize_notes()` — a cross-provider diff utility, nothing human-review about it. Rename:

- `src/schedules/review.py` → `src/schedules/diff.py`. Body unchanged.
- `tests/test_review.py` → `tests/test_diff.py`. Body unchanged.
- Update call sites:
  - `src/schedules/pipeline.py` (2 imports: `compare_payloads` and related)
  - `src/schedules/state.py:9` (imports `deserialize_notes`, `serialize_note`)
  - No `cli.py` import (verified).
- Re-export from `src/schedules/__init__.py` if any symbol was exported there.
- `ReviewNote`, `needs_review()` keep their names — they're consumed *by* the reviewer, which justifies the noun.

### Text scrubs

Concrete edits:

| File | Line | Change |
|---|---|---|
| `README.md` | 55 | `data/adjudications/` → `data/reviewed-snapshots/` (stale path); reword "manually reviewed payloads" |
| `README.md` | 63 | "manually adjudicated" → "manually reviewed" |
| `NAPKIN.md` | 25 | "then adjudicate that new hash" → "then review that new hash" |
| `content/spots/balboa-pool.md` | 16 | "Manually adjudicated against …" → "Manually reviewed against …" |
| `content/spots/coffman-pool.md` | 16 | same |
| `content/spots/garfield-pool.md` | 16 | same |
| `content/spots/hamilton-pool.md` | 16 | same |
| `content/spots/martin-luther-king-jr-pool.md` | 16 | same |
| `content/spots/north-beach-pool.md` | 16 | same |
| `content/spots/rossi-pool.md` | 16 | same |

TOML frontmatter `#` comments — Zola ignores; no pipeline behavior change.

Archived plan `docs/plans/archived/reviewed-snapshots.md` left untouched.

### Config format convention

Add a "Conventions" section to `NAPKIN.md`:

> **Config formats**: TOML for human-authored config (Zola frontmatter, `pyproject.toml`, `config.toml`, `src/schedules/registry.toml`). JSON for machine-generated data (`data/**/*.json`). YAML only where a vendor tool requires it (`devenv.yaml`). New files follow this rule.

## Sequence — single atomic PR

All changes below ship in one PR. The code rewrite, the migration script run, the moved files, and the fixture updates all land together so `main` never sees an inconsistent on-disk layout. Commit breakdown inside the PR (for review ergonomics, not release gating):

1. Rename `review.py` → `diff.py`; rename test file; update imports in `pipeline.py` and `state.py:9`; update `src/schedules/__init__.py` re-exports.
2. Add paths helpers; update `reviewed_snapshot_path` glob resolution; rewrite `fetch.py` cache layer; update affected existing tests.
3. Land `scripts/migrate_pdf_layout.py`; run it locally; commit the moved files; delete `data/pdf-cache-index.json`.
4. Remove `data/pdfs/` from `.gitignore`; commit the 7 checked-in PDFs.
5. Text scrubs + config-format convention addition.

All 5 commits push together. Rebase-and-merge or squash — either works; the PR stays atomic from `main`'s perspective.

## Risks

- **Fresh-clone developer experience**: `data/pdfs/` is now tracked. `git clone` includes the 7 PDFs (~200KB total). No runtime cost.
- **Existing-clone `git pull` with untracked `data/pdfs/*.pdf`**: see the PR-description heads-up note. The migration script handles the repo side; `rm -rf data/pdfs/` handles the clone side.
- **Prefix collision**: impossible at 12 chars within a slug in practice, but `FetchError` with both full hashes guarantees loud failure rather than silent overwrite.
- **Migration re-run on a partially-migrated tree**: idempotent by design; test enforces it; the "index deleted on first run" case is explicitly handled by checking target-layout completeness first.
- **`state.py:9` import rename**: captured in the commit-1 checklist; test suite catches it immediately.
