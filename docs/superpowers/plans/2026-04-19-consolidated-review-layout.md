# Consolidated Review Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the three-tree data layout into `data/<slug>/<fetch-date>-<pdf-sha12>/`, commit artifacts alongside `reviewed.json`, delete `extraction-state.json`, unify envelope validation, teach `schedules extract` to skip already-extracted PDFs, and trim envelope + provider JSON of everything that isn't pulling its weight.

**Architecture:** Filesystem-as-state-machine; one directory per (slug, PDF) pair holds everything. Review status is just `reviewed.json` existence: present ⇒ reviewed; absent ⇒ needs work. No git on the hot path, no `is_approved` helper, no draft concept. `--force` and `--compare-with` override the fast-path. Each `<provider>-<model>.json` is self-describing — no `meta.json` — and retains `source_pdf_url` + `pdf_sha256` so review seeding stays correct if registry URLs drift. Extraction skips when the provider file's embedded `prompt_sha256` + `schema_sha256` match current values.

**Tech Stack:** Python 3.13, Click, `jsonschema`, `tomlkit`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-19-consolidated-review-layout-design.md`

---

## File structure

**Create:**
- `src/schedules/schemas/__init__.py` — package marker
- `src/schedules/schemas/reviewed-snapshot.json` — moved from `data/reviewed-snapshots/schema.json`
- `scripts/migrate_consolidated_layout.py` — one-shot migration
- `tests/test_migrate_consolidated_layout.py` — exercises the script against fixtures
- `tests/test_extract_skip.py` — pipeline skips extraction on prompt/schema hash match
- `tests/test_review_queue_existence.py` — queue scan returns candidates when `reviewed.json` is absent, skips when present
- `tests/test_pipeline_force.py` — `--force` and `--compare-with` bypass the `reviewed.json`-exists fast-path

**Modify:**
- `src/schedules/paths.py` — new per-review helpers; drop obsolete constants
- `src/schedules/fetch.py` — write `source.pdf` into review dir
- `src/schedules/artifacts.py` — self-describing provider JSON (embeds `prompt_sha256` + `schema_sha256` + `extracted_at`); add `skip_if_fresh`; no `meta.json`
- `src/schedules/reviewed_snapshots.py` — drop `_validate_envelope`; all loads via `envelope.validate_envelope`
- `src/schedules/envelope.py` — update `_SCHEMA_PATH` to new location
- `src/schedules/review.py` — `seed_draft` writes only if missing; queue via `reviewed_path.exists()`; finalize uses `os.replace`
- `src/schedules/project.py` — read `reviewed.json` via new paths
- `src/schedules/pipeline.py` — drop state.py wiring; per-provider extract-skip; `Unchanged` when `reviewed.json` exists AND not `--force`/`--compare-with`
- `src/schedules/report.py` — drop `pdf_text_sha256` line
- `src/schedules/models.py` — drop `pdf_text_sha256` from `Unchanged`, `Proposed`, `Failed`
- `pyproject.toml` — add `[tool.hatch.build.targets.wheel.force-include]` entry for `src/schedules/schemas`
- `.gitignore` — remove `data/artifacts/` and `data/reviewed-snapshot-drafts/`
- `docs/schedules.md`, `docs/plans/schedules.md`, `README.md` — new layout
- `NAPKIN.md` — revise any path-specific rules
- All tests that construct envelopes or assert on paths

**Delete:**
- `src/schedules/state.py`
- `tests/test_state.py` (if it exists) or relevant state-coupled tests
- `scripts/migrate_pdf_layout.py` (obsolete prior-migration script)
- `data/extraction-state.json` (after migration)
- `data/reviewed-snapshots/` (after migration, moved out)
- `data/pdfs/` (after migration)
- `data/artifacts/` (after migration)

---

## Notes for implementer

- Tests come before code where TDD applies. For pure moves (schema relocation, directory renames), the "test" is the post-move assertion — pytest still runs between steps.
- Keep `main` green only at the START and END of the plan. Middle steps may leave tests red; that's expected because the migration is a flag-day.
- Commit after each task completes. Task-level commits keep the diff reviewable.

---

## Task 1: Schema relocation and trim

**Why:** Schema is code, not data. Moving it out of `data/` decouples it from the runtime data lake. The same step removes `version`, `$schema`, `reviewed_by`, `reviewed_against` — all redundant with git + the directory layout.

**Files:**
- Create: `src/schedules/schemas/__init__.py` (empty)
- Move: `data/reviewed-snapshots/schema.json` → `src/schedules/schemas/reviewed-snapshot.json`
- Modify: `src/schedules/envelope.py`, `pyproject.toml`, all 7 `reviewed.json` files in `data/reviewed-snapshots/`, `tests/test_envelope.py`, `tests/test_schema_compat.py`

- [ ] **Step 1: Create the schemas package**

```bash
mkdir -p src/schedules/schemas
touch src/schedules/schemas/__init__.py
git mv data/reviewed-snapshots/schema.json src/schedules/schemas/reviewed-snapshot.json
```

- [ ] **Step 2: Trim the schema**

In `src/schedules/schemas/reviewed-snapshot.json`:
- Delete the `$schema` (optional envelope-side pointer), `version`, `reviewed_by`, `reviewed_against` property blocks.
- Update `required` to `["slug", "pdf_sha256", "reviewed_at", "source_pdf_url", "payload"]`.
- Keep the top-level `$id`, `$schema` (JSON-Schema dialect pointer at the schema file itself), `additionalProperties: false`, and the payload sub-schema.

- [ ] **Step 3: Update `envelope.py` to point at the new location**

```python
# src/schedules/envelope.py
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "reviewed-snapshot.json"
```

Remove the `from .paths import REVIEWED_SNAPSHOTS_DIR` import.

- [ ] **Step 4: Strip removed fields from existing snapshots**

```bash
python3 - <<'PY'
import json
from pathlib import Path

REMOVED = ("$schema", "version", "reviewed_by", "reviewed_against")
for p in Path("data/reviewed-snapshots").rglob("*.json"):
    if p.name == "schema.json":
        continue
    data = json.loads(p.read_text())
    dirty = False
    for k in REMOVED:
        if k in data:
            del data[k]
            dirty = True
    if dirty:
        p.write_text(json.dumps(data, indent=2) + "\n")
PY
```

- [ ] **Step 5: Include schema in the wheel**

In `pyproject.toml`, add alongside the existing `[tool.hatch.build.targets.wheel]`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/schedules/schemas" = "schedules/schemas"
```

(Or equivalent `include = ["src/schedules/**/*.json"]` under `[tool.hatch.build]` — either ships the JSON.)

- [ ] **Step 6: Update tests**

- `tests/test_envelope.py`: delete tests asserting on removed fields; add/rename `test_schema_accepts_minimal_envelope` with no `version`/`$schema`/`reviewed_by`/`reviewed_against`.
- `tests/test_schema_compat.py`: add `test_schema_rejects_removed_fields` — parametrize over the four removed keys; each should trip `additionalProperties: false`.
- `tests/test_review_finalize.py::test_finalize_accepts_human_reviewer_identity`: delete.

- [ ] **Step 7: Run pytest**

```bash
uv run pytest
```

Expected: tests pass after the deletions land.

---

## Task 2: Path helpers for consolidated layout

**Why:** Adding new helpers first lets later tasks call them without touching old paths. The old constants stay until their callers are migrated in Task 4+.

**Files:**
- Modify: `src/schedules/paths.py`
- Create: `tests/test_paths_layout.py` (new assertions)

- [ ] **Step 1: Write the tests first**

In `tests/test_paths_layout.py`, add assertions for the new helpers:

```python
from schedules.paths import (
    review_dir,
    pdf_path,
    artifact_path,
    reviewed_path,
    latest_review_dir,
    all_review_dirs,
)

def test_review_dir_shape():
    path = review_dir("hamilton-pool", "2026-04-19", "a" * 64, root=SOME_TMP)
    assert path.name == "2026-04-19-aaaaaaaaaaaa"
    assert path.parent.name == "hamilton-pool"

def test_pdf_path_is_source_pdf():
    assert pdf_path("hamilton-pool", "2026-04-19", "a" * 64, root=...).name == "source.pdf"

def test_artifact_path_includes_provider_and_model():
    p = artifact_path("hamilton-pool", "2026-04-19", "a" * 64, "gemini", "gemini-3.1-flash-lite-preview", root=...)
    assert p.name == "gemini-gemini-3-1-flash-lite-preview.json"

def test_reviewed_path_is_reviewed_json():
    assert reviewed_path("hamilton-pool", "2026-04-19", "a" * 64, root=...).name == "reviewed.json"

def test_latest_review_dir_sorts_by_date_prefix(tmp_path):
    # Two dirs with different dates; latest_review_dir returns the newer one
    ...
```

- [ ] **Step 2: Implement the helpers in `paths.py`**

Add to `src/schedules/paths.py`:

```python
from .artifacts import slugify  # or move slugify to paths.py to avoid circular import

DATA_DIR = REPO_ROOT / "data"  # may already exist under another name

def review_dir(slug: str, date: str, pdf_sha256: str, *, root: Path = DATA_DIR) -> Path:
    return root / slug / f"{date}-{pdf_sha256[:12]}"

def pdf_path(slug: str, date: str, pdf_sha256: str, *, root: Path = DATA_DIR) -> Path:
    return review_dir(slug, date, pdf_sha256, root=root) / "source.pdf"

def artifact_path(slug: str, date: str, pdf_sha256: str, provider: str, model: str, *, root: Path = DATA_DIR) -> Path:
    return review_dir(slug, date, pdf_sha256, root=root) / f"{provider}-{slugify(model)}.json"

def reviewed_path(slug: str, date: str, pdf_sha256: str, *, root: Path = DATA_DIR) -> Path:
    return review_dir(slug, date, pdf_sha256, root=root) / "reviewed.json"

def all_review_dirs(slug: str, *, root: Path = DATA_DIR) -> list[Path]:
    slug_dir = root / slug
    if not slug_dir.is_dir():
        return []
    return sorted(d for d in slug_dir.iterdir() if d.is_dir())

def latest_review_dir(slug: str, *, root: Path = DATA_DIR) -> Path | None:
    dirs = all_review_dirs(slug, root=root)
    return dirs[-1] if dirs else None
```

If `slugify` lives in `artifacts.py`, either move it to `paths.py` (it's a pure helper) or inline it here.

- [ ] **Step 3: Run pytest**

Expected: new tests green, existing tests unchanged.

---

## Task 3: Unify envelope validation

**Why:** Drop the hand-rolled `_validate_envelope` in `reviewed_snapshots.py`. All load paths funnel through `envelope.validate_envelope` (jsonschema, strict). This catches extra fields everywhere, not just at finalize.

**Files:**
- Modify: `src/schedules/reviewed_snapshots.py`
- Modify: `tests/test_reviewed_snapshots.py`

- [ ] **Step 1: Write a failing test**

In `tests/test_reviewed_snapshots.py`, add:

```python
def test_load_rejects_extra_top_level_key(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    envelope["bogus_field"] = True
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises((ValueError, EnvelopeValidationError)):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)
```

- [ ] **Step 2: Delete `_validate_envelope` and wire in `validate_envelope`**

In `src/schedules/reviewed_snapshots.py`:
- Delete `_validate_envelope` and `_REQUIRED_ENVELOPE_FIELDS`.
- `load_reviewed_snapshot` and `load_reviewed_snapshot_from_path` call `envelope.validate_envelope(raw)` before fingerprinting. Wrap `EnvelopeValidationError` as `ValueError(f"{path}: {exc}")` for backward-compat with existing call sites that raise ValueError.
- Then do the three semantic checks that jsonschema can't do: `raw["slug"] == expected_slug`, `raw["pdf_sha256"] == expected_pdf_sha256` (for `load_reviewed_snapshot`), `raw["version"] == REVIEWED_SNAPSHOT_VERSION`.

- [ ] **Step 3: Run pytest**

New test passes. Other `test_reviewed_snapshots.py` tests may fail if they construct invalid envelopes; audit and fix.

---

## Task 4: `reviewed.json` IS the only review file

**Why:** No drafts tree, no rename, no "reopen draft" branch. One file on disk; git tells you its state. `seed_draft` = "write if missing, never overwrite." Finalize = validate + project, atomic via `os.replace`.

**Files:**
- Modify: `src/schedules/review.py`
- Modify: `src/schedules/paths.py` (remove `REVIEWED_SNAPSHOT_DRAFTS_DIR`)
- Modify: `tests/test_review_seed.py`, `tests/test_review_finalize.py`, `tests/test_cli_review.py`

- [ ] **Step 1: Collapse `seed_draft` to "write if missing"**

```python
def seed_draft(candidate, *, today: date | None = None) -> Path:
    target = paths.reviewed_path(candidate.slug, candidate.fetch_date, candidate.pdf_sha256)
    if target.exists():
        return target  # no overwrite; caller decides whether to proceed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_build_envelope(candidate, today=today), indent=2) + "\n")
    return target
```

No idempotency branch, no tracked-vs-untracked distinction at seed time. Reviewers who want to throw away WIP use `git restore`; reviewers who want to start fresh from raw extraction use `rm` then re-run `schedules review`.

- [ ] **Step 2: Update `finalize_draft`**

New flow:
1. Read `reviewed.json` from its target location.
2. `envelope.validate_envelope(raw)`.
3. Run `validate()` semantic invariants.
4. Run `project()` into `content/spots/<slug>.md`.
5. If all pass and the CLI itself is rewriting the file (e.g., normalizing on finalize), write to `reviewed.json.tmp` and `os.replace` — atomic within a single dir on POSIX/Windows.
6. If any step fails, raise `FinalizeError` — `reviewed.json` stays on disk unchanged; CLI returns non-zero.

No rename across dirs. No destination-conflict check.

- [ ] **Step 3: Update tests**

- `test_review_finalize.py::test_finalize_aborts_on_destination_conflict`: delete.
- `test_review_finalize.py::test_finalize_happy_path`: assert `reviewed.json` contains finalized envelope content; no rename assertion.
- `test_review_seed.py::test_seed_draft_is_idempotent`: rename to `test_seed_draft_does_not_overwrite_existing` — seed, mutate, re-seed, assert mutation survives because seed is a no-op when the file exists.

- [ ] **Step 4: Run pytest**

---

## Task 5: Artifact bundle trim, self-describing provider JSON, and `skip_if_fresh`

**Why:** Each `<provider>-<model>.json` becomes self-describing. No sibling `meta.json`. Fields that used to live in `meta.json` (`prompt_sha256`, `schema_sha256`, `extracted_at`) move into each provider file. `skip_if_fresh` reads the provider file directly.

**Files:**
- Modify: `src/schedules/artifacts.py`
- Create: `tests/test_artifact_skip.py` (or part of `test_artifacts.py`)

- [ ] **Step 1: Write the trim test**

```python
def test_artifact_bundle_writes_self_describing_provider_json(tmp_path):
    save_artifact_bundle(...)
    data = json.loads(artifact_path(...).read_text())
    # Keeps (including fields review seeding needs):
    assert set(data) >= {
        "provider", "model", "extracted_at",
        "prompt_sha256", "schema_sha256",
        "source_pdf_url", "pdf_sha256",
        "usage", "cost_estimate", "payload",
    }
    # Drops:
    assert not {"slug", "pdf_page_count", "pdf_text_sha256"} & set(data)
```

- [ ] **Step 2: Update `save_artifact_bundle`**

- No `meta.json` is written.
- Provider JSON: `provider`, `model`, `extracted_at`, `prompt_sha256`, `schema_sha256`, `source_pdf_url`, `pdf_sha256`, `usage`, `cost_estimate`, `payload`, `grounding` (optional). `source_pdf_url` + `pdf_sha256` are retained because `review.py` seeds envelopes from provider artifacts and registry URLs drift.
- Target path resolves through `paths.artifact_path`, not the old `ARTIFACTS_DIR`.

- [ ] **Step 3: Write the skip test**

```python
def test_skip_if_fresh_returns_true_when_hashes_match(tmp_path):
    save_artifact_bundle(..., prompt="P", schema={...}, ...)
    assert artifacts.skip_if_fresh(slug, date, sha, provider, model, prompt="P", schema={...}) is True

def test_skip_if_fresh_false_on_prompt_change(tmp_path):
    save_artifact_bundle(..., prompt="P", ...)
    assert artifacts.skip_if_fresh(slug, date, sha, provider, model, prompt="P-NEW", schema={...}) is False
```

- [ ] **Step 4: Implement `skip_if_fresh`**

```python
def skip_if_fresh(
    *,
    slug: str,
    date: str,
    pdf_sha256: str,
    provider: str,
    model: str,
    prompt: str,
    schema: dict,
) -> bool:
    provider_file = artifact_path(slug, date, pdf_sha256, provider, model)
    if not provider_file.exists():
        return False
    data = json.loads(provider_file.read_text())
    return (
        data.get("prompt_sha256") == _sha256_text(prompt)
        and data.get("schema_sha256") == _sha256_json(schema)
    )
```

- [ ] **Step 5: Run pytest**

---

## Task 6: Rewrite `fetch.py` for the new layout

**Why:** PDFs now live inside review dirs. `fetch.py` owns the first-seen date.

**Files:**
- Modify: `src/schedules/fetch.py`
- Modify: relevant tests

- [ ] **Step 1: Update the fetch test fixture paths**

`tests/test_fetch.py` currently expects `data/pdfs/<slug>/<date>-<sha12>.pdf`. Change expectations to `data/<slug>/<date>-<sha12>/source.pdf`.

- [ ] **Step 2: Rewrite `fetch_pdf`**

Resolution order:
1. GET URL, stream to memory, compute sha256.
2. Glob `data/<slug>/*-<sha256[:12]>/source.pdf`.
3. If exactly one match and its sha256 matches: cache hit; return that path with `from_cache=True`. Date is immutable.
4. If a match exists but full sha differs: `FetchError("prefix collision: existing=<x> new=<y>")`.
5. If no match: write to `data/<slug>/<today>-<sha256[:12]>/source.pdf`, creating dirs. Return `from_cache=False`.

- [ ] **Step 3: Run pytest**

---

## Task 7: Migration script

**Why:** Move existing committed data (PDFs, artifacts, snapshots) into the new per-review layout so the PR ships a self-consistent tree.

**Files:**
- Create: `scripts/migrate_consolidated_layout.py`
- Create: `tests/test_migrate_consolidated_layout.py`

- [ ] **Step 1: Write a test that uses a fixture tree**

Build a `tmp_path` mirror of the current repo data layout (pdfs/, artifacts/, reviewed-snapshots/) with 1-2 sample pools. Run the migration function against it. Assert:
- New review dirs exist at expected paths.
- `source.pdf` moved in.
- `reviewed.json` stripped of `version`, `$schema`, `reviewed_by`, `reviewed_against`.
- Provider JSONs are self-describing: contain `prompt_sha256`, `schema_sha256`, `extracted_at`, `source_pdf_url`, `pdf_sha256`; lack `slug`/`pdf_page_count`/`pdf_text_sha256`.
- No `meta.json` in the new layout.
- Old dirs are gone (`data/pdfs`, `data/artifacts`, `data/reviewed-snapshots`).
- Re-running is a no-op (idempotency).

- [ ] **Step 2: Implement the script**

Expose a `main(data_root: Path, repo_root: Path) -> Summary` function for testability. CLI wrapper at the bottom.

Logic:
```
for snapshot in data/reviewed-snapshots/*/*.json:
    envelope = json.load(snapshot)
    slug = envelope["slug"]
    pdf_sha = envelope["pdf_sha256"]
    sha12 = pdf_sha[:12]

    # Determine fetch date: prefer PDF filename's date prefix; fall back to reviewed_at.
    pdfs = glob(data/pdfs/{slug}/*-{sha12}.pdf)
    if len(pdfs) == 1:
        date = pdfs[0].name[:10]
    else:
        date = envelope["reviewed_at"]

    target_dir = data/{slug}/{date}-{sha12}/
    target_dir.mkdir(parents=True, exist_ok=True)

    # Read old meta.json (if it exists) to harvest prompt/schema hashes and extracted_at.
    artifacts_src = data/artifacts/{slug}/{sha12}/
    old_meta = {}
    if (artifacts_src / "meta.json").exists():
        old_meta = json.loads((artifacts_src / "meta.json").read_text())
    prompt_sha256 = old_meta.get("prompt_sha256") or old_meta.get("prompt_hash") \
                    or sha256(PROMPT_PATH.read_text().strip())
    schema_sha256 = old_meta.get("schema_sha256") or old_meta.get("schema_hash") \
                    or sha256(json.dumps(EXTRACTION_SCHEMA, sort_keys=True))

    # Move PDF
    if pdfs:
        move(pdfs[0], target_dir / "source.pdf")

    # Move and trim each provider JSON; fold meta fields in; preserve source_pdf_url + pdf_sha256.
    if artifacts_src.exists():
        for f in artifacts_src.iterdir():
            if f.name == "meta.json":
                f.unlink()  # folded away; don't carry forward
                continue
            data = json.loads(f.read_text())
            # Preserve source_pdf_url + pdf_sha256; fall back to envelope/meta if absent.
            source_pdf_url = data.get("source_pdf_url") or data.get("pdf_url") \
                             or old_meta.get("source_pdf_url") or envelope.get("source_pdf_url")
            pdf_sha256_val = data.get("pdf_sha256") or old_meta.get("pdf_sha256") or pdf_sha
            for k in ("slug", "pdf_url", "pdf_page_count", "pdf_text_sha256"):
                data.pop(k, None)
            data["source_pdf_url"] = source_pdf_url
            data["pdf_sha256"] = pdf_sha256_val
            data.setdefault("prompt_sha256", prompt_sha256)
            data.setdefault("schema_sha256", schema_sha256)
            data.setdefault("extracted_at", old_meta.get("extracted_at"))
            (target_dir / f.name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            f.unlink()
        artifacts_src.rmdir()

    # Move reviewed.json
    for k in ("version", "$schema", "reviewed_by", "reviewed_against"):
        envelope.pop(k, None)
    (target_dir / "reviewed.json").write_text(json.dumps(envelope, indent=2) + "\n")
    snapshot.unlink()
```

After the loop: remove empty `data/pdfs/<slug>/`, `data/artifacts/<slug>/`, `data/reviewed-snapshots/<slug>/` dirs and the roots. Delete `data/extraction-state.json`. Delete `data/pdf-cache-index.json` if still around.

- [ ] **Step 3: Run the test**

Expected: green, including idempotent re-run.

- [ ] **Step 4: Don't run the script on real data yet** — wait for Task 10.

---

## Task 8: Extract-skip in the pipeline + delete state.py

**Why:** The fast path now looks at the per-review directory, not `extraction-state.json`. Review status is `reviewed.json` existence — no git, no helper. `--force` and `--compare-with` override the fast-path.

**Files:**
- Modify: `src/schedules/pipeline.py`
- Delete: `src/schedules/state.py`
- Modify: `src/schedules/models.py` (drop `pdf_text_sha256` from `Unchanged`, `Proposed`, `Failed`)
- Modify: `src/schedules/report.py` (remove `pdf_text_sha256` line)
- Create: `tests/test_extract_skip.py`, `tests/test_pipeline_force.py`
- Delete: tests coupled to `state.py`, if any

- [ ] **Step 1: Write the extract-skip and force tests**

```python
def test_extract_skips_llm_when_reviewed_exists(monkeypatch, tmp_path):
    # Seed target dir with source.pdf + reviewed.json.
    # Stub extract_with_provider to raise if called.
    # Run the pipeline with no flags; expect Unchanged, no LLM call.
    ...

def test_extract_reruns_after_prompt_change(monkeypatch, tmp_path):
    # Provider JSON's embedded prompt_sha256 differs from current prompt's hash.
    # reviewed.json is absent. Run pipeline; expect LLM invoked exactly once.
    ...

def test_force_bypasses_reviewed_fast_path(monkeypatch, tmp_path):
    # reviewed.json exists. Run with force=True; expect LLM IS invoked.
    ...

def test_compare_with_bypasses_reviewed_fast_path(monkeypatch, tmp_path):
    # reviewed.json exists. Run with compare_with=<provider>; expect LLM IS invoked.
    ...
```

- [ ] **Step 2: Rewire the pipeline**

In `src/schedules/pipeline.py`:
- Delete `from .state import ...` and all `load_state`/`save_state`/`build_state_entry`/`notes_for_entry` calls.
- After `fetch_pdf`, derive `(slug, date, pdf_sha256)` from the returned path.
- Fast-path `Unchanged`: if `reviewed_path(...).exists()` AND `not force` AND `not compare_with`: load envelope, emit `Unchanged` using the envelope's payload for counts.
- Otherwise, if `artifacts.skip_if_fresh(...)` for the configured provider AND `not force`: load the cached payload from the provider JSON. Emit `Proposed` with `review_notes` regenerated from the cached payload (re-run grounding/delta checks).
- Otherwise, call `extract_with_provider` and write via `save_artifact_bundle`.

No `_is_reviewed` helper. No git invocation. `reviewed_path.exists()` is the whole predicate, inlined at the call site.

- [ ] **Step 3: Drop `pdf_text_sha256` threading**

In `models.py`, remove the field from `Unchanged`, `Proposed`, `Failed`. In `report.py`, remove the `- pdf_text_sha256: ...` line. In `pipeline.py`, remove all callsites passing the field.

- [ ] **Step 4: Delete `state.py`**

```bash
git rm src/schedules/state.py
```

Delete any remaining imports.

- [ ] **Step 5: Run pytest**

---

## Task 9: Review CLI — queue scan uses `reviewed.json` existence

**Why:** Queue scan moves from `data/artifacts/` to `data/<slug>/`. Candidate = any review dir with at least one provider JSON and no `reviewed.json`. No git, no helper.

**Files:**
- Modify: `src/schedules/review.py`
- Modify: `tests/test_review_scan.py`, `tests/test_cli_review.py`
- Create: `tests/test_review_queue_existence.py`

- [ ] **Step 1: Write the queue-semantics test**

For each of {no reviewed.json, reviewed.json present}, assert the dir does or does not appear in `scan_candidates`. No git repo needed — pure filesystem.

- [ ] **Step 2: Update `scan_candidates`**

Iterate `data/*/` (top-level slug dirs). For each slug, iterate `all_review_dirs(slug)`. A candidate = a review dir where:
- At least one `<provider>-<model>.json` exists AND
- `reviewed.json` does not exist.

Sort by date prefix ascending (oldest first), ties by slug.

- [ ] **Step 3: Verify `seed_draft` and `finalize_draft`** match Task 4 — seed writes if missing, finalize uses `os.replace` on rewrite.

- [ ] **Step 4: Update tests**

Rewrite fixtures in `test_review_scan.py` for the new per-review dirs and git-native queue semantics.

- [ ] **Step 5: Run pytest**

---

## Task 10: Run the migration script on real data

**Why:** Bring the committed data tree into the new shape.

- [ ] **Step 1: Dry-run**

Add a `--dry-run` flag to the script; run it first and inspect the printed summary.

- [ ] **Step 2: Execute for real**

```bash
uv run python scripts/migrate_consolidated_layout.py
```

Summary should show 7 review dirs created, 7 snapshots migrated, 0 re-extractions pending.

- [ ] **Step 3: `git status` review**

Expect:
- New tracked dirs under `data/<slug>/<date>-<sha12>/`
- `data/pdfs/`, `data/artifacts/`, `data/reviewed-snapshots/`, `data/extraction-state.json` deleted

- [ ] **Step 4: Update `.gitignore`**

```diff
-data/artifacts/
-data/reviewed-snapshot-drafts/
```

- [ ] **Step 5: Commit the migration result**

Single commit: "migrate to consolidated review layout".

---

## Task 11: Smoke tests

**Why:** Exercise the integrated system end-to-end on the new tree before finalizing docs.

- [ ] **Step 1: `uv run pytest`**

Expected: all tests pass. Migration-era coupling tests are updated or deleted.

- [ ] **Step 2: `uv run schedules extract --only hamilton-pool --dry-run`**

Expected: emits `Unchanged` for hamilton-pool (reviewed snapshot already approved for this hash). No LLM call.

- [ ] **Step 3: `uv run schedules review`**

Expected: "nothing to review". (All 7 pools have committed `reviewed.json`.)

- [ ] **Step 4: `uv run schedules extract --only hamilton-pool --force`**

Expected: re-fetches PDF (same hash, cache hit), re-invokes LLM (forced), overwrites provider JSON in the existing review dir. `reviewed.json` is untouched, so the queue does NOT pick hamilton-pool up automatically. Open UX question (deferred): should `--force` trigger a delta check against reviewed.json and warn when payloads diverge? For now, manual test is the safety net.

- [ ] **Step 5: Roll back the `--force` effects**

```bash
git restore data/hamilton-pool/
```

---

## Task 12: Docs update

**Files:**
- Modify: `docs/schedules.md`
- Modify: `docs/plans/schedules.md`
- Modify: `NAPKIN.md`
- Modify: `README.md`
- Delete: `scripts/migrate_pdf_layout.py` (pre-existing prior-migration script; obsolete post-consolidation)
- Move: spec and plan to `archived/` once merged

- [ ] **Step 1: Rewrite `docs/schedules.md`**

Sections to rewrite:
- "Review Flow" — describe the existence-based queue semantics (`reviewed.json` present = done; absent = needs work). `--force` / `--compare-with` bypass the fast-path.
- Any path references: `data/artifacts/` → `data/<slug>/<date>-<sha12>/`; same for snapshots, drafts.
- "Current Blockers" — keep content; paths don't change meaning.

- [ ] **Step 2: Update `docs/plans/schedules.md`** and `README.md`

Replace old-path literals with new-layout examples.

- [ ] **Step 3: Update `NAPKIN.md`**

Check Domain Behavior Guardrails for old-path references. Update.

- [ ] **Step 4: Delete obsolete migration script**

```bash
git rm scripts/migrate_pdf_layout.py
```

- [ ] **Step 5: Archive the spec and plan**

```bash
git mv docs/superpowers/specs/2026-04-19-consolidated-review-layout-design.md docs/superpowers/specs/archived/
git mv docs/superpowers/plans/2026-04-19-consolidated-review-layout.md docs/superpowers/plans/archived/
```

---

## Post-merge checklist

- [ ] Run `uv run schedules extract` (no flags) on a fresh checkout. Expect all 7 pools emit `Unchanged`.
- [ ] Delete a provider JSON from one review dir. Re-run extract. Expect LLM is invoked for that provider only.
- [ ] Introduce a trivial edit to the extraction prompt. Re-run extract. Expect LLM is invoked for every pool, writing new provider JSONs.
- [ ] Revert the prompt edit.
- [ ] Confirm `git log --stat` shows reasonable diff sizes (no catastrophic blow-up in committed artifact JSON size).
