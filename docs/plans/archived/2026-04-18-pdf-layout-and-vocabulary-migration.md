---
status: complete
progress:
  - section: "Task 1: Rename review.py → diff.py"
    status: complete
    notes:
      - "Committed 380651c; 76 tests pass; src/schedules/__init__.py confirmed to have no review/diff re-exports"
      - "Inner loop fell back to Claude implementation (trivial 2-move + 3-import-edit change); no codex invocation"
  - section: "Task 2: Add path helpers + reviewed_snapshot glob resolution"
    status: complete
    notes:
      - "Committed fa6d91c; 83 tests pass (7 new in test_paths_layout.py)"
      - "PDF_CACHE_INDEX_PATH preserved in paths.py per magi-review fix (removal deferred to Task 3)"
      - "Pyright diagnostics on new test files are static-analysis false positives (pytest import, narrow-type Nones); runtime correct — same pattern as reviewed-snapshots plan archive"
  - section: "Task 3: Rewrite fetch.py cache layer"
    status: complete
    notes:
      - "Committed a98b6e0; 85 tests pass (was 83 + 3 new - 1 old)"
      - "PDF_CACHE_INDEX_PATH removed from both paths.py and fetch.py in this commit per plan's coupled-edit requirement"
      - "pipeline.py:134 caller compatible — only slug, pdf_url, force kwargs; no rename needed"
  - section: "Task 4: Migration script + idempotence test"
    status: complete
    notes:
      - "Committed f7aeab0; 88 tests pass (3 new in test_migration_idempotent.py)"
      - "gap: plan's Step-3 script body includes dead helper `_resolve_full_hash_from_index` (never called). Harmless; flag for post-ralph magi review."
  - section: "Task 5: Un-ignore data/pdfs/, fetch PDFs, delete index"
    status: complete
    notes:
      - "Committed 5009ccb; 88 tests pass; 9 PDFs checked in under new layout; 7 existing reviewed snapshots renamed to <date>-<prefix>.json; data/pdf-cache-index.json deleted"
      - "gap: registry grew from 7 to 9 pools since spec was written (mission-community-pool, sava-pool added). Commit message verbatim from plan still says '7 PDFs'. Flag for post-ralph magi review."
      - "PDFs fetched with today's date (2026-04-19); snapshots kept their reviewed_at date (2026-04-17). Intentional per spec — filenames share prefix, not date."
  - section: "Task 6: Vocabulary scrubs + config-format convention"
    status: complete
    notes:
      - "Committed 20dfae0; 88 tests pass; README/NAPKIN/7 spot MDs scrubbed; NAPKIN Conventions section appended"
      - "grep 'adjudicat' across in-scope paths is clean (archived plans untouched by design)"
      - "only 7 spot MDs needed updates — mission-community-pool and sava-pool are registry-only without spot content yet"
  - section: "Final verification"
    status: complete
    notes:
      - "88/88 tests pass; data layout matches YYYY-MM-DD-[0-9a-f]{12}.(pdf|json) everywhere"
      - "data/pdf-cache-index.json confirmed deleted"
      - "grep for 'pdf-cache-index|PDF_CACHE_INDEX' shows only deliberate refs in scripts/migrate_pdf_layout.py + test_migration_idempotent.py (migration cleanup contract); 'from schedules.review' matches are false positives hitting reviewed_snapshots"
last_review: 2026-04-19T08:22:00-07:00
iterations: 6
no_progress_count: 0
started_at: 2026-04-19T07:53:34-07:00
work_unit_granularity: task
---

# PDF Layout and Vocabulary Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the repo for a local review tool by (a) moving cached PDFs into per-slug date-prefixed directories that are checked into git, mirroring the layout for reviewed snapshots, and dropping `pdf-cache-index.json`; and (b) unifying vocabulary on "review" by renaming `src/schedules/review.py` → `src/schedules/diff.py` and scrubbing "adjudicator" references from docs and frontmatter.

**Architecture:** Pure filesystem-layout change + a module rename. No runtime-semantics change. The cache layer in `fetch.py` switches from a URL→filename index to a glob-by-sha-prefix lookup. `reviewed_snapshot_path` now glob-resolves `<slug>/*-<prefix>.json` to survive both naming conventions during migration. A committed `scripts/migrate_pdf_layout.py` brings existing clones over idempotently. All 6 commits below land as one atomic PR so `main` never sees an inconsistent on-disk state.

**Tech Stack:** Python 3.13 + `uv` + `pytest`. Stdlib only for the migration script. No new runtime dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-18-pdf-layout-and-vocabulary-migration-design.md`

---

## File Structure

### Created

- `src/schedules/diff.py` — replaces `src/schedules/review.py` (rename only; body identical).
- `tests/test_diff.py` — replaces `tests/test_review.py` (rename only; body identical).
- `scripts/migrate_pdf_layout.py` — stdlib-only idempotent migration. Checked in permanently.
- `tests/test_paths_layout.py` — covers the new helpers in `paths.py`.
- `tests/test_migration_idempotent.py` — runs migration twice in a tmp tree; asserts second run is no-op.

### Modified

- `src/schedules/paths.py` — add `pdf_dir`, `reviewed_snapshot_dir`, `pdf_filename`, `snapshot_filename`, `latest_pdf`, `latest_reviewed_snapshot` helpers; remove `PDF_CACHE_INDEX_PATH`.
- `src/schedules/fetch.py` — rewrite cache layer (glob-by-prefix + collision detection); drop index.
- `src/schedules/reviewed_snapshots.py` — `reviewed_snapshot_path` glob-resolves new layout; write-path returns canonical `<date>-<prefix>.json` when no match.
- `src/schedules/pipeline.py` — update `.review` import → `.diff`.
- `src/schedules/state.py` — update `.review` import → `.diff`.
- `tests/test_fetch.py` — fixture layout updated; `pdf-cache-index.json` references removed; `FetchError` collision case added.
- `tests/test_reviewed_snapshots.py` — fixtures write at `<slug>/<date>-<prefix>.json`.
- `tests/test_ratification.py` — same fixture updates.
- `.gitignore` — remove `data/pdfs/` line.
- `README.md` — line 55 path + line 63 wording scrubs.
- `NAPKIN.md` — line 25 wording scrub + add "Conventions" section documenting config-format rule.
- `content/spots/{balboa,coffman,garfield,hamilton,martin-luther-king-jr,north-beach,rossi}-pool.md` — line 16 comment wording.

### Moved (via `git mv`)

- `src/schedules/review.py` → `src/schedules/diff.py`
- `tests/test_review.py` → `tests/test_diff.py`

### Deleted

- `data/pdf-cache-index.json`

---

## Task 1: Rename `review.py` → `diff.py`

**Files:**
- Move: `src/schedules/review.py` → `src/schedules/diff.py`
- Move: `tests/test_review.py` → `tests/test_diff.py`
- Modify: `src/schedules/pipeline.py:20`
- Modify: `src/schedules/state.py:9`

The file contains only `compare_payloads()`, `serialize_note()`, `deserialize_notes()` — a cross-provider diff utility. "Review" is the wrong noun. `ReviewNote` keeps its name (it's consumed *by* the reviewer).

- [ ] **Step 1: Verify current call sites**

```bash
grep -rn "from .review import\|from schedules.review\|review\|diff" src/schedules/__init__.py
grep -rn "from .review import\|from schedules.review" src/ tests/
```

Expected first grep: no `review` or `diff` lines (the `__init__.py` exports only `__version__`, so no re-export update is needed — but confirm this rather than assume).

Expected second grep (exactly two production lines plus the in-file imports of `tests/test_review.py` itself):
```
src/schedules/state.py:9:from .review import deserialize_notes, serialize_note
src/schedules/pipeline.py:20:from .review import compare_payloads
```

- [ ] **Step 2: Rename files with `git mv`**

```bash
git mv src/schedules/review.py src/schedules/diff.py
git mv tests/test_review.py tests/test_diff.py
```

- [ ] **Step 3: Update internal imports inside `tests/test_diff.py`**

Read the file first. If it contains `from schedules.review import …`, rewrite to `from schedules.diff import …`. The symbols exported are unchanged: `compare_payloads`, `serialize_note`, `deserialize_notes`.

- [ ] **Step 4: Update `src/schedules/pipeline.py:20`**

Replace:
```python
from .review import compare_payloads
```
With:
```python
from .diff import compare_payloads
```

- [ ] **Step 5: Update `src/schedules/state.py:9`**

Replace:
```python
from .review import deserialize_notes, serialize_note
```
With:
```python
from .diff import deserialize_notes, serialize_note
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest
```

Expected: all tests pass (same count as before rename). If any test fails with `ModuleNotFoundError: No module named 'schedules.review'`, a call site was missed — grep again.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(schedules): rename review module to diff

compare_payloads is a cross-provider diff utility, not a human-review
concern. Rename the module to match its actual purpose, clearing the
'review' namespace for the upcoming reviewer tool."
```

---

## Task 2: Add path helpers + reviewed_snapshot glob resolution

**Files:**
- Modify: `src/schedules/paths.py`
- Modify: `src/schedules/reviewed_snapshots.py:23-24` (reviewed_snapshot_path)
- Create: `tests/test_paths_layout.py`
- Modify: `tests/test_reviewed_snapshots.py` (fixture paths)
- Modify: `tests/test_ratification.py` (fixture paths)

New helpers are pure functions. `reviewed_snapshot_path` is rewritten to glob-resolve `<slug>/*-<prefix>.json` — it still accepts full 64-char `pdf_sha256` (signature unchanged). When no match, returns the canonical write path using today's date.

- [ ] **Step 1: Write failing test for new helpers**

Create `tests/test_paths_layout.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from schedules import paths


def test_pdf_dir_is_under_data_dir():
    assert paths.pdf_dir("hamilton-pool") == paths.DATA_DIR / "pdfs" / "hamilton-pool"


def test_reviewed_snapshot_dir_is_under_data_dir():
    assert paths.reviewed_snapshot_dir("hamilton-pool") == paths.DATA_DIR / "reviewed-snapshots" / "hamilton-pool"


def test_pdf_filename_is_date_dash_prefix():
    sha = "a" * 64
    assert paths.pdf_filename("2026-04-17", sha) == "2026-04-17-aaaaaaaaaaaa.pdf"


def test_snapshot_filename_is_date_dash_prefix():
    sha = "a" * 64
    assert paths.snapshot_filename("2026-04-17", sha) == "2026-04-17-aaaaaaaaaaaa.json"


def test_latest_pdf_returns_none_when_dir_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    assert paths.latest_pdf("hamilton-pool") is None


def test_latest_pdf_picks_highest_date(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    slug_dir = tmp_path / "pdfs" / "hamilton-pool"
    slug_dir.mkdir(parents=True)
    older = slug_dir / "2026-01-01-aaaaaaaaaaaa.pdf"
    newer = slug_dir / "2026-04-17-bbbbbbbbbbbb.pdf"
    older.write_bytes(b"x")
    newer.write_bytes(b"y")
    assert paths.latest_pdf("hamilton-pool") == newer


def test_latest_reviewed_snapshot_picks_highest_date(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    slug_dir = tmp_path / "reviewed-snapshots" / "hamilton-pool"
    slug_dir.mkdir(parents=True)
    older = slug_dir / "2026-01-01-aaaaaaaaaaaa.json"
    newer = slug_dir / "2026-04-17-bbbbbbbbbbbb.json"
    older.write_text("{}")
    newer.write_text("{}")
    assert paths.latest_reviewed_snapshot("hamilton-pool") == newer
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/test_paths_layout.py -v
```

Expected: `AttributeError: module 'schedules.paths' has no attribute 'pdf_dir'` (or similar for each helper).

- [ ] **Step 3: Implement helpers in `src/schedules/paths.py`**

Keep ALL existing module-level constants — including `PDF_CACHE_INDEX_PATH`. The index constant stays until Task 3 rewrites `fetch.py` (its only importer). Removing it here would break the `from .paths import PDF_CACHE_INDEX_PATH` line in `fetch.py:13` at commit 2 and crash pytest collection. Append the helpers to the existing file (do not rewrite it):

```python
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = SRC_ROOT.parent

CONTENT_SPOTS_DIR = REPO_ROOT / "content" / "spots"
DATA_DIR = REPO_ROOT / "data"
PDF_CACHE_DIR = DATA_DIR / "pdfs"
PDF_CACHE_INDEX_PATH = DATA_DIR / "pdf-cache-index.json"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
REVIEWED_SNAPSHOTS_DIR = DATA_DIR / "reviewed-snapshots"
STATE_PATH = DATA_DIR / "extraction-state.json"
TMP_DIR = REPO_ROOT / "tmp"
REPORT_PATH = TMP_DIR / "extraction-report.md"
REGISTRY_PATH = PACKAGE_ROOT / "registry.toml"
PROMPT_PATH = PACKAGE_ROOT / "prompts" / "extract.txt"


def relative_to_repo(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def pdf_dir(slug: str) -> Path:
    return DATA_DIR / "pdfs" / slug


def reviewed_snapshot_dir(slug: str) -> Path:
    return DATA_DIR / "reviewed-snapshots" / slug


def pdf_filename(date: str, pdf_sha256: str) -> str:
    return f"{date}-{pdf_sha256[:12]}.pdf"


def snapshot_filename(date: str, pdf_sha256: str) -> str:
    return f"{date}-{pdf_sha256[:12]}.json"


def latest_pdf(slug: str) -> Path | None:
    directory = pdf_dir(slug)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.pdf"))
    return files[-1] if files else None


def latest_reviewed_snapshot(slug: str) -> Path | None:
    directory = reviewed_snapshot_dir(slug)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.json"))
    return files[-1] if files else None
```

Note: the helpers above reference module-level `DATA_DIR`. The monkeypatched tests in Step 1 patch `DATA_DIR` — but because the helpers compute `DATA_DIR / ...` at call time (not at import time), the patch works. Verify.

- [ ] **Step 4: Run helper tests to verify pass**

```bash
uv run pytest tests/test_paths_layout.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Rewrite `reviewed_snapshot_path` in `src/schedules/reviewed_snapshots.py`**

Current (line 23):
```python
def reviewed_snapshot_path(slug: str, pdf_sha256: str, root: Path = REVIEWED_SNAPSHOTS_DIR) -> Path:
    return root / slug / f"{pdf_sha256}.json"
```

Replace with:
```python
from datetime import date

def reviewed_snapshot_path(slug: str, pdf_sha256: str, root: Path = REVIEWED_SNAPSHOTS_DIR) -> Path:
    """Resolve the snapshot path for (slug, pdf_sha256).

    Globs `<slug>/*-<prefix>.json` where prefix is the first 12 chars of
    pdf_sha256. If exactly one file matches, return it. If none match,
    return the canonical write path using today's date. If more than one
    matches (should not happen in practice), raise.
    """
    prefix = pdf_sha256[:12]
    slug_dir = root / slug
    if slug_dir.is_dir():
        matches = sorted(slug_dir.glob(f"*-{prefix}.json"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Multiple reviewed snapshots for {slug} with prefix {prefix}: {matches}"
            )
    return slug_dir / f"{date.today().isoformat()}-{prefix}.json"
```

This keeps `load_reviewed_snapshot` unchanged — its `raw["pdf_sha256"] == expected_pdf_sha256` check still catches any prefix collision. `write_ratified_snapshot` is also unchanged at the envelope level; it writes to whatever path `reviewed_snapshot_path` returns.

- [ ] **Step 6: Update fixtures in `tests/test_reviewed_snapshots.py`**

Find every fixture that writes to `root / slug / f"{pdf_sha256}.json"` and rewrite to the new layout. The helper `_write_snapshot` and the inline `file_path = root / "hamilton-pool" / f"{pdf_sha256}.json"` lines all need updating.

New pattern — for all fixtures where `pdf_sha256 = "a" * 64`:
```python
file_path = root / slug / f"2026-04-18-{pdf_sha256[:12]}.json"
```

Change `_write_snapshot`:
```python
def _write_snapshot(root, slug, pdf_sha256, envelope):
    file_path = root / slug / f"2026-04-18-{pdf_sha256[:12]}.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(envelope))
    return file_path
```

And change `test_load_reviewed_snapshot`:
```python
def test_load_reviewed_snapshot(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    file_path = root / "hamilton-pool" / f"2026-04-18-{pdf_sha256[:12]}.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        json.dumps(
            {
                "version": REVIEWED_SNAPSHOT_VERSION,
                "slug": "hamilton-pool",
                "pdf_sha256": pdf_sha256,
                "reviewed_at": "2026-04-18",
                "summary": "manual review",
                "source_pdf_url": "https://example.com/schedule.pdf",
                "reviewed_against": [
                    {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}
                ],
                "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
            }
        )
    )
    snapshot, fingerprint, relative_path = load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)
    assert snapshot["summary"] == "manual review"
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert relative_path == str(file_path)
```

- [ ] **Step 7: Update fixtures in `tests/test_ratification.py`**

In `test_find_snapshots_for_slug_lists_all` (tmp_path variant) the current code writes two snapshots at `root / "hamilton-pool" / f"{sha}.json"`. Change to:

```python
    for sha in ("a" * 64, "b" * 64):
        path = root / "hamilton-pool" / f"2026-04-18-{sha[:12]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_envelope("hamilton-pool", sha, payload)))
    assert len(find_snapshots_for_slug("hamilton-pool", root=root)) == 2
```

In `test_write_ratified_snapshot_round_trips` — no fixture write is manual there; `write_ratified_snapshot` writes for us. But because `reviewed_snapshot_path` now returns `<date>-<prefix>` rather than `<full>.json`, and the test calls `load_reviewed_snapshot(... new_sha ...)` directly after, the glob must resolve the just-written file. Run the test to confirm — should still pass as-is because both write and load go through `reviewed_snapshot_path`.

- [ ] **Step 8: Run full test suite**

```bash
uv run pytest
```

Expected: all tests pass. `test_fetch.py` may still pass because it uses `index_path=tmp_path / "pdf-cache-index.json"` which is unrelated to our changes in this task — that test will be rewritten in Task 3.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(schedules): add per-slug path helpers and glob-resolve reviewed snapshots

Introduce pure-function helpers (pdf_dir, reviewed_snapshot_dir,
pdf_filename, snapshot_filename, latest_pdf, latest_reviewed_snapshot)
that encode the new <slug>/<date>-<prefix> layout. Rewrite
reviewed_snapshot_path to glob-resolve by sha prefix so it survives
both the old flat naming and the new date-prefixed naming during
migration. Envelope and load behavior are unchanged."
```

---

## Task 3: Rewrite `fetch.py` cache layer

**Files:**
- Modify: `src/schedules/fetch.py`
- Modify: `tests/test_fetch.py`

Replaces the `pdf-cache-index.json` URL→filename map with a glob-by-sha-prefix check. Adds a `FetchError` raised on 12-char prefix collision with distinct 64-char hashes.

- [ ] **Step 1: Write failing test for cache-miss → writes to new layout**

Rewrite `tests/test_fetch.py` completely:

```python
from __future__ import annotations

import httpx
import pytest
from pypdf import PdfWriter

from schedules.fetch import FetchError, fetch_pdf


def _make_pdf_bytes(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_path = tmp_path / "fixture.pdf"
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    return pdf_path.read_bytes()


def _fake_client_factory(pdf_bytes, counter):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def get(self, url):
            counter["count"] += 1
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
                request=request,
            )
    return FakeClient


def test_fetch_pdf_writes_to_per_slug_dir_on_cache_miss(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    cache_root = tmp_path / "pdfs"
    url = "http://example.test/schedule.pdf"
    result = fetch_pdf("test-pool", url, cache_root=cache_root)

    assert result.from_cache is False
    assert result.path.parent == cache_root / "test-pool"
    assert result.path.name.endswith(f"-{result.sha256[:12]}.pdf")
    # Filename is <YYYY-MM-DD>-<prefix>.pdf
    assert len(result.path.stem.split("-")) == 4  # YYYY MM DD prefix
    assert counter["count"] == 1


def test_fetch_pdf_cache_hit_short_circuits(tmp_path, monkeypatch):
    pdf_bytes = _make_pdf_bytes(tmp_path)
    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes, counter))

    cache_root = tmp_path / "pdfs"
    url = "http://example.test/schedule.pdf"
    first = fetch_pdf("test-pool", url, cache_root=cache_root)
    second = fetch_pdf("test-pool", url, cache_root=cache_root)

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.sha256 == second.sha256
    assert first.path == second.path  # date-in-filename is stable after first fetch
    assert counter["count"] == 2  # note: one extra GET per cache-hit compared to old index


def test_fetch_pdf_raises_on_prefix_collision(tmp_path, monkeypatch):
    # Simulate: a file at the expected prefix location exists, but its sha differs.
    cache_root = tmp_path / "pdfs"
    slug_dir = cache_root / "test-pool"
    slug_dir.mkdir(parents=True)

    pdf_bytes_a = _make_pdf_bytes(tmp_path)
    import hashlib
    prefix = hashlib.sha256(pdf_bytes_a).hexdigest()[:12]

    # Plant a DIFFERENT file with the same 12-char prefix (contrived by writing bytes at that path).
    collision_path = slug_dir / f"2026-04-17-{prefix}.pdf"
    collision_path.write_bytes(b"different content, same prefix by construction")

    counter = {"count": 0}
    monkeypatch.setattr("schedules.fetch.httpx.Client", _fake_client_factory(pdf_bytes_a, counter))

    with pytest.raises(FetchError, match="prefix collision"):
        fetch_pdf("test-pool", "http://example.test/x.pdf", cache_root=cache_root)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/test_fetch.py -v
```

Expected: tests fail because `cache_root` is not a parameter of current `fetch_pdf`, and layout is different.

- [ ] **Step 3: Rewrite `src/schedules/fetch.py` AND remove `PDF_CACHE_INDEX_PATH` from `paths.py`**

Two edits in this step — they must land together because the import and the export are coupled.

First, edit `src/schedules/paths.py` to delete the `PDF_CACHE_INDEX_PATH = DATA_DIR / "pdf-cache-index.json"` line. (The constant was kept in Task 2 to preserve the import in the unrewritten `fetch.py`; removing it now is safe because the fetch.py rewrite below drops the import.)

Then replace the contents of `src/schedules/fetch.py`:

```python
from __future__ import annotations

import hashlib
import time
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from .models import FetchResult
from .paths import PDF_CACHE_DIR


class FetchError(RuntimeError):
    """Raised when a PDF cannot be fetched or validated."""


def fetch_pdf(
    slug: str,
    url: str,
    *,
    cache_root: Path = PDF_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
    retries: int = 2,
) -> FetchResult:
    """Fetch a PDF, caching under data/pdfs/<slug>/<date>-<prefix>.pdf."""
    slug_dir = cache_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for attempt in range(retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.content
                sha256 = hashlib.sha256(payload).hexdigest()
                prefix = sha256[:12]

                # Glob by prefix to detect cache hit or collision.
                matches = sorted(slug_dir.glob(f"*-{prefix}.pdf"))
                if not force and matches:
                    for existing in matches:
                        existing_bytes = existing.read_bytes()
                        existing_sha = hashlib.sha256(existing_bytes).hexdigest()
                        if existing_sha == sha256:
                            return FetchResult(
                                path=existing,
                                sha256=sha256,
                                bytes=existing_bytes,
                                from_cache=True,
                                page_count=_count_pdf_pages(existing_bytes),
                                response_url=str(response.url),
                            )
                        # Same 12-char prefix, different full hash — collision.
                        raise FetchError(
                            f"prefix collision in {slug}: existing={existing_sha} new={sha256}"
                        )

                # Cache miss — write with today's date.
                filename = f"{date.today().isoformat()}-{prefix}.pdf"
                path = slug_dir / filename
                path.write_bytes(payload)
                return FetchResult(
                    path=path,
                    sha256=sha256,
                    bytes=payload,
                    from_cache=False,
                    page_count=_count_pdf_pages(payload),
                    response_url=str(response.url),
                )
            except FetchError:
                raise  # don't retry prefix collisions
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(0.25 * (attempt + 1))

    raise FetchError(f"Failed to fetch {slug} from {url}: {last_error}") from last_error


def _count_pdf_pages(payload: bytes) -> int:
    try:
        reader = PdfReader(BytesIO(payload))
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise FetchError("Downloaded file is not a readable PDF.") from exc

    if page_count <= 0:
        raise FetchError("Downloaded PDF contains zero pages.")
    return page_count
```

Note the signature change: `index_path` parameter is gone; `cache_dir` → `cache_root`. Callers in `pipeline.py` must be checked.

- [ ] **Step 4: Update callers of `fetch_pdf`**

```bash
grep -n "fetch_pdf(" src/
```

Inspect every call site. If any caller passes `cache_dir=` or `index_path=`, rewrite. The `pipeline.py` call passes `slug`, `pdf_url`, and `force=force` — none of these were removed or renamed, so no change is needed. Verify with the grep above.

- [ ] **Step 5: Run fetch tests to verify pass**

```bash
uv run pytest tests/test_fetch.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest
```

Expected: all tests pass. Pay attention to `test_pipeline.py` — if it monkey-patches `fetch_pdf`, the stubs should still be compatible (they return `FetchResult` directly).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(fetch): glob-by-prefix cache with collision detection

Drop the pdf-cache-index.json URL→filename map. The new cache layer
globs data/pdfs/<slug>/*-<prefix>.pdf to detect hits, and raises
FetchError on prefix collision (same 12-char prefix, different full
sha). Cost: one extra GET per cache hit; negligible at 7 pools/day."
```

---

## Task 4: Migration script + idempotence test

**Files:**
- Create: `scripts/migrate_pdf_layout.py`
- Create: `tests/test_migration_idempotent.py`

Committed permanently. Stdlib-only. Idempotent. Checks target-layout completeness first so it survives a deleted `pdf-cache-index.json`.

- [ ] **Step 1: Write failing idempotence test**

Create `tests/test_migration_idempotent.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_pdf_layout.py"


def _setup_old_layout(tmp_data: Path):
    """Simulate pre-migration state: flat data/pdfs/ + index + full-hash snapshots."""
    (tmp_data / "pdfs").mkdir(parents=True)
    (tmp_data / "reviewed-snapshots" / "balboa-pool").mkdir(parents=True)

    # One PDF in flat layout.
    full_sha = "ba9b279ae183" + "a" * 52
    old_pdf = tmp_data / "pdfs" / f"balboa-pool-{full_sha[:12]}.pdf"
    old_pdf.write_bytes(b"fake pdf bytes")

    # Matching snapshot with reviewed_at field.
    snapshot_path = tmp_data / "reviewed-snapshots" / "balboa-pool" / f"{full_sha}.json"
    snapshot_path.write_text(json.dumps({
        "version": 1,
        "slug": "balboa-pool",
        "pdf_sha256": full_sha,
        "reviewed_at": "2026-04-10",
        "source_pdf_url": "https://example.test/balboa.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "flash"}],
        "summary": "test",
        "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
    }))

    index = tmp_data / "pdf-cache-index.json"
    index.write_text(json.dumps({
        f"balboa-pool|https://example.test/balboa.pdf": f"balboa-pool-{full_sha[:12]}.pdf"
    }))


def _run_migration(tmp_data: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(tmp_data)],
        capture_output=True, text=True, check=True,
    )


def test_migration_moves_pdfs_and_renames_snapshots(tmp_path):
    tmp_data = tmp_path / "data"
    _setup_old_layout(tmp_data)

    _run_migration(tmp_data)

    # PDF moved to per-slug dir with date-prefix filename.
    full_sha = "ba9b279ae183" + "a" * 52
    prefix = full_sha[:12]
    new_pdf = tmp_data / "pdfs" / "balboa-pool" / f"2026-04-10-{prefix}.pdf"
    assert new_pdf.exists(), list((tmp_data / "pdfs" / "balboa-pool").iterdir())

    # Snapshot renamed to date-prefix.
    new_snap = tmp_data / "reviewed-snapshots" / "balboa-pool" / f"2026-04-10-{prefix}.json"
    assert new_snap.exists()

    # Index deleted.
    assert not (tmp_data / "pdf-cache-index.json").exists()


def test_migration_is_idempotent(tmp_path):
    tmp_data = tmp_path / "data"
    _setup_old_layout(tmp_data)

    _run_migration(tmp_data)
    result = _run_migration(tmp_data)

    assert "already migrated" in result.stdout


def test_migration_handles_missing_index_post_run(tmp_path):
    """After a first run deletes the index, a second run sees target-layout complete."""
    tmp_data = tmp_path / "data"
    _setup_old_layout(tmp_data)
    _run_migration(tmp_data)
    # Simulate fresh clone with migrated data but no index.
    assert not (tmp_data / "pdf-cache-index.json").exists()

    result = _run_migration(tmp_data)
    assert "already migrated" in result.stdout
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/test_migration_idempotent.py -v
```

Expected: `FileNotFoundError` or similar because the script doesn't exist yet.

- [ ] **Step 3: Implement `scripts/migrate_pdf_layout.py`**

Create the file:

```python
#!/usr/bin/env python3
"""Migrate cached PDFs + reviewed snapshots to per-slug date-prefixed layout.

Usage:
    python scripts/migrate_pdf_layout.py [--data-dir data]

Idempotent. Safe to run on a fresh clone, a partially migrated tree, or
a fully migrated tree. Prints a summary and exits 0 on success.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


TARGET_PDF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{12}\.pdf$")
OLD_FLAT_PDF_RE = re.compile(r"^(?P<slug>[a-z0-9-]+)-(?P<prefix>[0-9a-f]{12})\.pdf$")


def _is_target_layout_complete(data_dir: Path) -> bool:
    """Return True iff every PDF directory contains only new-layout files
    and no old-flat PDFs exist and the index is absent."""
    pdfs_root = data_dir / "pdfs"
    if (data_dir / "pdf-cache-index.json").exists():
        return False
    if not pdfs_root.is_dir():
        # No PDFs at all — technically "complete" (nothing to migrate).
        return True
    for entry in pdfs_root.iterdir():
        if entry.is_file() and OLD_FLAT_PDF_RE.match(entry.name):
            return False
        if entry.is_dir():
            for pdf in entry.glob("*.pdf"):
                if not TARGET_PDF_RE.match(pdf.name):
                    return False
    return True


def _read_snapshot_reviewed_at(snapshot_path: Path) -> str | None:
    try:
        raw = json.loads(snapshot_path.read_text())
    except Exception:
        return None
    value = raw.get("reviewed_at") if isinstance(raw, dict) else None
    return value if isinstance(value, str) else None


def _resolve_pdf_date(slug: str, full_hash: str, data_dir: Path, source_path: Path) -> str:
    """Use reviewed_at from matching snapshot if present, else source mtime."""
    snapshot = data_dir / "reviewed-snapshots" / slug / f"{full_hash}.json"
    if snapshot.exists():
        reviewed_at = _read_snapshot_reviewed_at(snapshot)
        if reviewed_at:
            return reviewed_at
    mtime = dt.datetime.fromtimestamp(source_path.stat().st_mtime)
    return mtime.date().isoformat()


def _parse_old_flat(filename: str) -> tuple[str, str] | None:
    m = OLD_FLAT_PDF_RE.match(filename)
    return (m.group("slug"), m.group("prefix")) if m else None


def _resolve_full_hash_from_index(index: dict, slug: str, prefix: str) -> str | None:
    """Find the full hash from index entries — each value is <slug>-<prefix>.pdf.
    If the snapshot file for this prefix exists under reviewed-snapshots/<slug>/,
    its filename IS the full hash."""
    for _key, filename in index.items():
        parsed = _parse_old_flat(filename)
        if parsed == (slug, prefix):
            return None  # index knows prefix; full hash comes from snapshot dir
    return None


def _find_full_hash_in_snapshots(data_dir: Path, slug: str, prefix: str) -> str | None:
    snap_dir = data_dir / "reviewed-snapshots" / slug
    if not snap_dir.is_dir():
        return None
    candidates: list[str] = []
    for snap in snap_dir.glob(f"{prefix}*.json"):
        stem = snap.stem
        if len(stem) == 64 and all(c in "0123456789abcdef" for c in stem):
            candidates.append(stem)
    if len(candidates) > 1:
        raise SystemExit(
            f"ambiguous prefix {prefix} in {snap_dir}: {candidates}"
        )
    return candidates[0] if candidates else None


def migrate(data_dir: Path) -> tuple[int, int]:
    pdfs_moved = 0
    snapshots_renamed = 0

    pdfs_root = data_dir / "pdfs"
    if pdfs_root.is_dir():
        for entry in list(pdfs_root.iterdir()):
            if not entry.is_file():
                continue
            parsed = _parse_old_flat(entry.name)
            if not parsed:
                continue
            slug, prefix = parsed

            # Resolve full hash: prefer matching snapshot filename.
            full_hash = _find_full_hash_in_snapshots(data_dir, slug, prefix)
            if full_hash is None:
                raise SystemExit(
                    f"could not resolve full hash for {entry} — no matching snapshot at "
                    f"data/reviewed-snapshots/{slug}/{prefix}*.json"
                )
            date_str = _resolve_pdf_date(slug, full_hash, data_dir, entry)
            dest_dir = pdfs_root / slug
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{date_str}-{prefix}.pdf"
            entry.rename(dest)
            pdfs_moved += 1

    snapshots_root = data_dir / "reviewed-snapshots"
    if snapshots_root.is_dir():
        for slug_dir in snapshots_root.iterdir():
            if not slug_dir.is_dir():
                continue
            for snap in list(slug_dir.glob("*.json")):
                stem = snap.stem
                # Only rename files whose stem is a bare 64-char sha256.
                if len(stem) != 64 or not all(c in "0123456789abcdef" for c in stem):
                    continue
                reviewed_at = _read_snapshot_reviewed_at(snap)
                if not reviewed_at:
                    raise SystemExit(f"{snap} has no reviewed_at field")
                new_name = f"{reviewed_at}-{stem[:12]}.json"
                snap.rename(slug_dir / new_name)
                snapshots_renamed += 1

    index_path = data_dir / "pdf-cache-index.json"
    if index_path.exists():
        index_path.unlink()

    return pdfs_moved, snapshots_renamed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", help="Path to data directory (default: data/)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"error: {data_dir} does not exist", file=sys.stderr)
        return 1

    if _is_target_layout_complete(data_dir):
        print("already migrated (or no data to migrate)")
        return 0

    pdfs_moved, snapshots_renamed = migrate(data_dir)
    print(f"migrated: {pdfs_moved} PDFs moved, {snapshots_renamed} snapshots renamed, index deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:
```bash
chmod +x scripts/migrate_pdf_layout.py
```

- [ ] **Step 4: Run idempotence tests to verify pass**

```bash
uv run pytest tests/test_migration_idempotent.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(scripts): add idempotent PDF layout migration

scripts/migrate_pdf_layout.py is committed permanently as the canonical
way to bring an older branch into the new per-slug date-prefixed
layout. Target-layout completeness is checked first so the script
survives a deleted pdf-cache-index.json."
```

---

## Task 5: Un-ignore `data/pdfs/`, fetch PDFs into new layout, delete index

**Files:**
- Modify: `.gitignore:26`
- Delete: `data/pdf-cache-index.json`
- Add (git-add): `data/pdfs/<slug>/<date>-<prefix>.pdf` × 7

This is the commit that physically adds PDFs to the repo. It depends on the rewritten `fetch.py` (Task 3) writing to the new layout.

- [ ] **Step 1: Remove `data/pdfs/` from `.gitignore`**

Current `.gitignore:26`:
```
data/pdfs/
```

Delete that line. Keep `data/artifacts/`.

Verify with:
```bash
grep -n "data/pdfs\|data/artifacts" .gitignore
```
Expected: only `data/artifacts/` line remains.

- [ ] **Step 2: Migrate any old-layout data, then fetch into the new layout**

Always run the migration script first. It's idempotent — safe on a fresh clone, on an index-only state (no PDFs yet), on a flat-PDFs state, and on an already-migrated state. Avoids the fragile "does flat data exist?" heuristic.

```bash
uv run python scripts/migrate_pdf_layout.py --data-dir data
```

Expected output: either a summary of PDFs moved + snapshots renamed, or `already migrated (or no data to migrate)`.

Then fetch PDFs directly via the rewritten `fetch_pdf` (no API credentials required — this is pure HTTP):
```bash
uv run python -c "
from schedules.fetch import fetch_pdf
from schedules.registry import load_registry
for entry in load_registry():
    result = fetch_pdf(entry.slug, entry.pdf_url)
    print(f'{entry.slug}: {result.path.name} (from_cache={result.from_cache})')
"
```

Verify:
```bash
ls data/pdfs/*/
```
Expected: 7 directories each containing one `.pdf` matching `YYYY-MM-DD-[0-9a-f]{12}.pdf`.

- [ ] **Step 3: Delete the now-stale index (if migration didn't)**

```bash
rm -f data/pdf-cache-index.json
```

- [ ] **Step 4: Run the migration script as a final idempotence check**

```bash
uv run python scripts/migrate_pdf_layout.py --data-dir data
```

Expected output: `already migrated (or no data to migrate)`.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add .gitignore data/pdfs/ data/reviewed-snapshots/ data/pdf-cache-index.json
git status  # confirm: index.json is deleted, pdfs/ added, reviewed-snapshots renamed
git commit -m "chore(data): check in PDFs under new layout; drop cache index

data/pdfs/ is now tracked — 7 PDFs (~200KB). Reviewed-snapshot
filenames mirror the PDF hash prefix so paired (input, reviewed)
assets scan visually together. pdf-cache-index.json is deleted;
fetch.py's glob-by-prefix replaces it.

Heads-up for existing clones: run 'rm -rf data/pdfs/' before pulling
to avoid 'untracked working tree files would be overwritten'."
```

---

## Task 6: Vocabulary scrubs + config-format convention

**Files:**
- Modify: `README.md:55,63`
- Modify: `NAPKIN.md:25` + append Conventions section
- Modify: `content/spots/balboa-pool.md:16`
- Modify: `content/spots/coffman-pool.md:16`
- Modify: `content/spots/garfield-pool.md:16`
- Modify: `content/spots/hamilton-pool.md:16`
- Modify: `content/spots/martin-luther-king-jr-pool.md:16`
- Modify: `content/spots/north-beach-pool.md:16`
- Modify: `content/spots/rossi-pool.md:16`

Pure text edits. No logic impact. TOML `#` comments — Zola ignores.

- [ ] **Step 1: Verify current content at each location**

```bash
grep -n "adjudicat\|adjudication" README.md NAPKIN.md content/spots/*.md
```

Record the exact current text for each match — use it as the `old_string` for each Edit call. Do not trust line numbers; trust the string content.

- [ ] **Step 2: Update `README.md:55`**

Replace `data/adjudications/` → `data/reviewed-snapshots/`. Reword the surrounding sentence from "manually reviewed payloads" phrasing to match the spec table.

- [ ] **Step 3: Update `README.md:63`**

Replace "manually adjudicated" → "manually reviewed".

- [ ] **Step 4: Update `NAPKIN.md:25`**

Replace "then adjudicate that new hash" → "then review that new hash".

- [ ] **Step 5: Append Conventions section to `NAPKIN.md`**

At the bottom of the file, append:

```markdown

## Conventions

- **Config formats**: TOML for human-authored config (Zola frontmatter, `pyproject.toml`, `config.toml`, `src/schedules/registry.toml`). JSON for machine-generated data (`data/**/*.json`). YAML only where a vendor tool requires it (`devenv.yaml`). New files follow this rule.
```

- [ ] **Step 6: Update all 7 spot MDs at line 16**

For each of the 7 files, replace the comment line `# Manually adjudicated against …` with `# Manually reviewed against …`. The suffix (provider/model reference) stays intact.

- [ ] **Step 7: Verify no remaining occurrences in scope**

```bash
grep -rn "adjudicat" README.md NAPKIN.md content/spots/
```

Expected: empty (no matches). The archived plan `docs/plans/archived/reviewed-snapshots.md` is intentionally untouched.

- [ ] **Step 8: Run full test suite and site render test**

```bash
uv run pytest
```

Expected: all tests pass, including `test_site_render.py` which exercises the spot frontmatter.

- [ ] **Step 9: Commit**

```bash
git add README.md NAPKIN.md content/spots/
git commit -m "docs: unify vocabulary on 'reviewed' and codify config-format rule

Scrub residual 'adjudicator/adjudication' references from README,
NAPKIN, and spot frontmatter comments. Add a Conventions section to
NAPKIN.md documenting the TOML/JSON/YAML rule so new files follow it
without fresh judgment calls."
```

---

## Final verification

- [ ] **Step 1: Run the full test suite one more time**

```bash
uv run pytest
```

Expected: 100% pass, including `test_paths_layout.py`, `test_fetch.py`, `test_migration_idempotent.py`, `test_reviewed_snapshots.py`, `test_ratification.py`, `test_diff.py`.

- [ ] **Step 2: Grep for leftover references**

```bash
grep -rn "pdf-cache-index\|PDF_CACHE_INDEX\|from .review import\|from schedules.review" src/ tests/ scripts/ content/
```

Expected: empty.

- [ ] **Step 3: Verify data layout**

```bash
ls data/pdfs/*/ | head -20
ls data/reviewed-snapshots/*/ | head -20
```

Expected: all filenames match `YYYY-MM-DD-[0-9a-f]{12}\.(pdf|json)`.

- [ ] **Step 4: Confirm `data/pdf-cache-index.json` is gone**

```bash
test ! -f data/pdf-cache-index.json && echo "OK: index deleted"
```

- [ ] **Step 5: Summary**

Six commits on this branch, all atomic together. Open PR with the heads-up note in the description:

> **For developers with existing clones:** Your working tree has untracked `data/pdfs/*.pdf` files. A `git pull` will abort with "untracked working tree files would be overwritten." Run `rm -rf data/pdfs/` before pulling.
