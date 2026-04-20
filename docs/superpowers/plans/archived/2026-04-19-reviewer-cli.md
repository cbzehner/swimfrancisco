# Reviewer CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `schedules review` / `schedules project` CLI that lets a single developer approve pipeline-extracted pool schedules by editing JSON alongside the source PDF.

**Architecture:** Filesystem-as-state-machine. Review candidates are derived from `data/artifacts/` minus `data/reviewed-snapshots/` by `pdf_sha256`. Drafts land in `data/reviewed-snapshot-drafts/` (gitignored). Finalization = `os.rename` draft → reviewed-snapshots (the commit), then `schedules project <slug>` projects the committed snapshot into `content/spots/<slug>.md` via the existing tomlkit round-trip.

**Tech Stack:** Python 3.13, Click (CLI), `jsonschema` (new dep, draft 2020-12), `tomlkit` (existing), pytest (tests), helix + `vscode-json-language-server` (reviewer editor; already in devenv).

**Spec:** `docs/superpowers/specs/2026-04-19-reviewer-cli-design.md`

---

## File structure

**Create:**
- `src/schedules/review.py` — seed, scan, finalize helpers; no CLI concerns
- `src/schedules/project.py` — project a reviewed snapshot into `content/spots/<slug>.md`
- `tests/test_review_scan.py` — candidate enumeration
- `tests/test_review_seed.py` — draft seeding
- `tests/test_review_finalize.py` — finalize flow (validate → rename → project)
- `tests/test_project.py` — project() alone
- `tests/test_schema_compat.py` — schema accepts ratification envelopes

**Modify:**
- `data/reviewed-snapshots/schema.json` — add `reviewed_by`, `ratified_from_sha256`
- `src/schedules/paths.py` — add `REVIEWED_SNAPSHOT_DRAFTS_DIR`
- `src/schedules/cli.py` — add `review` and `project` subcommands
- `pyproject.toml` — add `jsonschema` to dependencies
- `.gitignore` — add `data/reviewed-snapshot-drafts/`
- `docs/schedules.md` — document the reviewer workflow

---

## Important correction (read first)

The spec's sketch shows `data/artifacts/<slug>/<pdf-hash>/`. The real on-disk layout (see `src/schedules/artifacts.py:29`) uses the **12-character prefix**, not the full hash:

```
data/artifacts/<slug>/<pdf_sha256[:12]>/<provider>-<model-slug>.json
data/artifacts/<slug>/<pdf_sha256[:12]>/meta.json
```

The "true" `pdf_sha256` lives inside the per-provider JSON under the `pdf_sha256` key. Scan code reads that field — do NOT treat the directory name as authoritative.

---

## Task 1: Schema compatibility — accept ratification envelopes

**Why:** `src/schedules/reviewed_snapshots.py:166,169` writes `reviewed_by` and `ratified_from_sha256` fields. The schema's `additionalProperties: false` would reject these today. Fix before any `schedules review` ships (spec §"Schema compatibility").

**Files:**
- Modify: `data/reviewed-snapshots/schema.json`
- Create: `tests/test_schema_compat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema_compat.py
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "reviewed-snapshots" / "schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _valid_envelope() -> dict:
    return {
        "version": 1,
        "slug": "hamilton-pool",
        "pdf_sha256": "a" * 64,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "manual review",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_schema_accepts_ratification_envelope():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["reviewed_by"] = "ratification"
    envelope["ratified_from_sha256"] = "b" * 64
    jsonschema.validate(instance=envelope, schema=schema)


def test_schema_accepts_reviewed_by_without_ratification():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["reviewed_by"] = "manual"
    jsonschema.validate(instance=envelope, schema=schema)


def test_schema_rejects_bad_ratified_from_sha256():
    schema = _load_schema()
    envelope = _valid_envelope()
    envelope["ratified_from_sha256"] = "not-a-hash"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=envelope, schema=schema)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema_compat.py -v`
Expected: `jsonschema` package not installed → skip, OR if installed, `test_schema_accepts_ratification_envelope` FAILS with `Additional properties are not allowed ('ratified_from_sha256', 'reviewed_by' were unexpected)`.

- [ ] **Step 3: Add `jsonschema` dependency**

Edit `pyproject.toml`. Replace:

```toml
dependencies = [
  "anthropic",
  "click",
  "google-genai",
  "httpx",
  "pypdf",
  "pytest",
  "tomlkit",
]
```

with:

```toml
dependencies = [
  "anthropic",
  "click",
  "google-genai",
  "httpx",
  "jsonschema",
  "pypdf",
  "pytest",
  "tomlkit",
]
```

Run: `uv sync`
Expected: `jsonschema` resolves and installs.

- [ ] **Step 4: Update schema — add the two optional fields**

Edit `data/reviewed-snapshots/schema.json`. In the top-level `properties` object (between `pdf_sha256` and `reviewed_at`, or anywhere inside `properties`), add:

```json
"reviewed_by": {
  "type": "string",
  "description": "Who/what produced this snapshot. 'ratification' for auto-ratified envelopes; omitted or 'manual' for human-reviewed."
},
"ratified_from_sha256": {
  "type": "string",
  "pattern": "^[0-9a-f]{64}$",
  "description": "When reviewed_by='ratification', the pdf_sha256 of the human-reviewed snapshot whose canonical payload matched."
},
```

Leave `required`, `additionalProperties: false`, and all other properties untouched. Do NOT add these to `required`.

- [ ] **Step 5: Run tests to verify all three pass**

Run: `uv run pytest tests/test_schema_compat.py -v`
Expected: all three PASS.

- [ ] **Step 6: Validate all existing snapshots against the updated schema**

Run:

```bash
uv run python -c "
import json, sys
from pathlib import Path
import jsonschema

schema = json.loads(Path('data/reviewed-snapshots/schema.json').read_text())
failures = []
for path in Path('data/reviewed-snapshots').rglob('*.json'):
    if path.name == 'schema.json':
        continue
    envelope = json.loads(path.read_text())
    try:
        jsonschema.validate(instance=envelope, schema=schema)
    except jsonschema.ValidationError as exc:
        failures.append((str(path), exc.message))
print(f'Validated {sum(1 for _ in Path(\"data/reviewed-snapshots\").rglob(\"*.json\")) - 1} files')
for path, msg in failures:
    print(f'FAIL: {path}: {msg}')
sys.exit(1 if failures else 0)
"
```

Expected: prints count, zero failures, exit 0.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock data/reviewed-snapshots/schema.json tests/test_schema_compat.py
git commit -m "$(cat <<'EOF'
feat(schema): accept reviewed_by and ratified_from_sha256

Schema previously forbade additional properties, which would have rejected
envelopes written by the ratification path. Reviewer CLI validates envelopes
against this schema at finalize, so compatibility must land first.
EOF
)"
```

---

## Task 2: Add draft tree path + gitignore entry

**Files:**
- Modify: `src/schedules/paths.py:11`
- Modify: `.gitignore`
- Test: `tests/test_paths_layout.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paths_layout.py`:

```python
def test_reviewed_snapshot_drafts_dir_is_in_data():
    from schedules.paths import DATA_DIR, REVIEWED_SNAPSHOT_DRAFTS_DIR
    assert REVIEWED_SNAPSHOT_DRAFTS_DIR == DATA_DIR / "reviewed-snapshot-drafts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_paths_layout.py::test_reviewed_snapshot_drafts_dir_is_in_data -v`
Expected: FAIL with `ImportError: cannot import name 'REVIEWED_SNAPSHOT_DRAFTS_DIR'`.

- [ ] **Step 3: Add the path constant**

Edit `src/schedules/paths.py`. After the `REVIEWED_SNAPSHOTS_DIR = ...` line, add:

```python
REVIEWED_SNAPSHOT_DRAFTS_DIR = DATA_DIR / "reviewed-snapshot-drafts"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_paths_layout.py::test_reviewed_snapshot_drafts_dir_is_in_data -v`
Expected: PASS.

- [ ] **Step 5: Add to .gitignore**

Edit `.gitignore`. In the existing Python section (near `data/artifacts/`), add a sibling line:

```
data/artifacts/
data/reviewed-snapshot-drafts/
```

- [ ] **Step 6: Commit**

```bash
git add src/schedules/paths.py tests/test_paths_layout.py .gitignore
git commit -m "$(cat <<'EOF'
feat(paths): add reviewed-snapshot-drafts layout

Drafts live in a gitignored sibling to reviewed-snapshots so the reviewer
can stash WIP envelopes without polluting the committed snapshot set.
EOF
)"
```

---

## Task 3: Envelope schema-validation helper

Centralize schema validation so review.py and future callers share one implementation.

**Files:**
- Create: `src/schedules/envelope.py`
- Create: `tests/test_envelope.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_envelope.py
import json
from pathlib import Path

import pytest

from schedules.envelope import (
    EnvelopeValidationError,
    load_envelope_schema,
    validate_envelope,
)


def _valid_envelope() -> dict:
    return {
        "version": 1,
        "slug": "hamilton-pool",
        "pdf_sha256": "a" * 64,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "manual review",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_load_envelope_schema_returns_dict():
    schema = load_envelope_schema()
    assert isinstance(schema, dict)
    assert schema["title"].startswith("Reviewed Snapshot")


def test_validate_envelope_accepts_valid():
    validate_envelope(_valid_envelope())


def test_validate_envelope_rejects_missing_required():
    envelope = _valid_envelope()
    del envelope["summary"]
    with pytest.raises(EnvelopeValidationError) as exc:
        validate_envelope(envelope)
    assert "summary" in str(exc.value)


def test_validate_envelope_rejects_bad_time_format():
    envelope = _valid_envelope()
    envelope["payload"]["sessions"][0]["start"] = "7:00"  # schema requires HH:MM zero-padded
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)


def test_validate_envelope_rejects_extra_top_level():
    envelope = _valid_envelope()
    envelope["bogus_field"] = True
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(envelope)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_envelope.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schedules.envelope'`.

- [ ] **Step 3: Implement the helper**

Create `src/schedules/envelope.py`:

```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema

from .paths import REVIEWED_SNAPSHOTS_DIR


class EnvelopeValidationError(ValueError):
    """Raised when a reviewed-snapshot envelope fails schema validation."""


_SCHEMA_PATH = REVIEWED_SNAPSHOTS_DIR / "schema.json"


@lru_cache(maxsize=1)
def load_envelope_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def validate_envelope(envelope: dict) -> None:
    """Validate an envelope against the committed schema.

    Raises EnvelopeValidationError with a human-readable message on failure.
    """
    try:
        jsonschema.validate(instance=envelope, schema=load_envelope_schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise EnvelopeValidationError(f"{location}: {exc.message}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_envelope.py -v`
Expected: all five PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/envelope.py tests/test_envelope.py
git commit -m "$(cat <<'EOF'
feat(envelope): add schema-validation helper

Single entry point for validating reviewed-snapshot envelopes. Reviewer CLI
and any future loader can call validate_envelope() without duplicating
jsonschema plumbing.
EOF
)"
```

---

## Task 4: Scan for review candidates

Enumerate `(slug, pdf_sha256, artifact_dir)` tuples that need review: artifact exists, no reviewed snapshot matches `pdf_sha256`.

**Files:**
- Create: `src/schedules/review.py`
- Create: `tests/test_review_scan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_scan.py
import json
from pathlib import Path

import pytest

from schedules.review import ReviewCandidate, find_review_candidates


def _write_artifact(root: Path, slug: str, pdf_sha256: str, provider: str = "gemini") -> Path:
    artifact_dir = root / slug / pdf_sha256[:12]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    provider_path = artifact_dir / f"{provider}-model.json"
    provider_path.write_text(json.dumps({
        "slug": slug,
        "provider": provider,
        "model": "model",
        "pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))
    return provider_path


def _write_snapshot(root: Path, slug: str, pdf_sha256: str) -> Path:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"2026-04-10-{pdf_sha256[:12]}.json"
    path.write_text(json.dumps({"pdf_sha256": pdf_sha256, "slug": slug}))
    return path


def _write_pdf(root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"{date}-{pdf_sha256[:12]}.pdf"
    path.write_bytes(b"%PDF-fake")
    return path


def test_find_review_candidates_empty(tmp_path):
    result = find_review_candidates(
        artifacts_root=tmp_path / "artifacts",
        snapshots_root=tmp_path / "reviewed-snapshots",
        pdfs_root=tmp_path / "pdfs",
    )
    assert result == []


def test_find_review_candidates_returns_unreviewed(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)

    candidates = find_review_candidates(
        artifacts_root=artifacts, snapshots_root=snapshots, pdfs_root=pdfs,
    )
    assert len(candidates) == 1
    assert candidates[0].slug == "hamilton-pool"
    assert candidates[0].pdf_sha256 == "a" * 64


def test_find_review_candidates_skips_already_reviewed(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64)

    assert find_review_candidates(
        artifacts_root=artifacts, snapshots_root=snapshots, pdfs_root=pdfs,
    ) == []


def test_find_review_candidates_orders_by_pdf_date_then_slug(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "zulu-pool", "a" * 64)
    _write_artifact(artifacts, "alpha-pool", "b" * 64)
    _write_artifact(artifacts, "bravo-pool", "c" * 64)
    _write_pdf(pdfs, "zulu-pool", "2026-01-01", "a" * 64)
    _write_pdf(pdfs, "alpha-pool", "2026-03-01", "b" * 64)
    _write_pdf(pdfs, "bravo-pool", "2026-03-01", "c" * 64)

    candidates = find_review_candidates(
        artifacts_root=artifacts, snapshots_root=snapshots, pdfs_root=pdfs,
    )
    assert [c.slug for c in candidates] == ["zulu-pool", "alpha-pool", "bravo-pool"]


def test_find_review_candidates_filters_by_slug(tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    pdfs = tmp_path / "pdfs"

    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_artifact(artifacts, "balboa-pool", "b" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_pdf(pdfs, "balboa-pool", "2026-04-01", "b" * 64)

    candidates = find_review_candidates(
        artifacts_root=artifacts,
        snapshots_root=snapshots,
        pdfs_root=pdfs,
        only_slug="balboa-pool",
    )
    assert [c.slug for c in candidates] == ["balboa-pool"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schedules.review'`.

- [ ] **Step 3: Implement the scan**

Create `src/schedules/review.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import (
    ARTIFACTS_DIR,
    PDF_CACHE_DIR,
    REVIEWED_SNAPSHOTS_DIR,
)


@dataclass(frozen=True)
class ReviewCandidate:
    slug: str
    pdf_sha256: str
    artifact_dir: Path
    pdf_path: Path | None
    pdf_date: str  # YYYY-MM-DD extracted from PDF filename; empty string if no PDF


_PDF_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{12})\.pdf$")


def _reviewed_sha256s_for_slug(snapshots_root: Path, slug: str) -> set[str]:
    slug_dir = snapshots_root / slug
    if not slug_dir.is_dir():
        return set()
    out: set[str] = set()
    for path in slug_dir.glob("*.json"):
        try:
            envelope = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sha = envelope.get("pdf_sha256")
        if isinstance(sha, str):
            out.add(sha)
    return out


def _full_sha_from_artifact(artifact_dir: Path) -> str | None:
    """Recover the full pdf_sha256 from any provider payload in the dir."""
    for provider_path in sorted(artifact_dir.glob("*.json")):
        if provider_path.name == "meta.json":
            continue
        try:
            payload = json.loads(provider_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sha = payload.get("pdf_sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    # Fall back to meta.json, which also carries pdf_sha256.
    meta_path = artifact_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        sha = meta.get("pdf_sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    return None


def _pdf_date_for(pdfs_root: Path, slug: str, pdf_sha256: str) -> tuple[str, Path | None]:
    slug_dir = pdfs_root / slug
    if not slug_dir.is_dir():
        return "", None
    prefix = pdf_sha256[:12]
    for path in sorted(slug_dir.glob(f"*-{prefix}.pdf")):
        m = _PDF_NAME.match(path.name)
        if m:
            return m.group(1), path
    return "", None


def find_review_candidates(
    *,
    artifacts_root: Path = ARTIFACTS_DIR,
    snapshots_root: Path = REVIEWED_SNAPSHOTS_DIR,
    pdfs_root: Path = PDF_CACHE_DIR,
    only_slug: str | None = None,
) -> list[ReviewCandidate]:
    """Return review candidates ordered by PDF publication date, then slug."""
    if not artifacts_root.is_dir():
        return []

    candidates: list[ReviewCandidate] = []
    for slug_dir in sorted(artifacts_root.iterdir()):
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        if only_slug is not None and slug != only_slug:
            continue
        reviewed = _reviewed_sha256s_for_slug(snapshots_root, slug)
        for hash_dir in sorted(slug_dir.iterdir()):
            if not hash_dir.is_dir():
                continue
            full_sha = _full_sha_from_artifact(hash_dir)
            if full_sha is None or full_sha in reviewed:
                continue
            pdf_date, pdf_path = _pdf_date_for(pdfs_root, slug, full_sha)
            candidates.append(
                ReviewCandidate(
                    slug=slug,
                    pdf_sha256=full_sha,
                    artifact_dir=hash_dir,
                    pdf_path=pdf_path,
                    pdf_date=pdf_date,
                )
            )
    candidates.sort(key=lambda c: (c.pdf_date, c.slug))
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_scan.py -v`
Expected: all five PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/review.py tests/test_review_scan.py
git commit -m "$(cat <<'EOF'
feat(review): enumerate review candidates from filesystem

Scans data/artifacts/ for (slug, pdf_sha256) pairs with no matching
reviewed snapshot. Orders by PDF publication date (from the cached
filename) then slug, matching the spec's review order.
EOF
)"
```

---

## Task 5: Seed a draft envelope from an artifact

Wrap a provider artifact in the reviewed-snapshot envelope shape and write to the drafts tree. Idempotent on re-entry (don't clobber an existing draft).

**Files:**
- Modify: `src/schedules/review.py`
- Create: `tests/test_review_seed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_seed.py
import json
from datetime import date
from pathlib import Path

import pytest

from schedules.review import ReviewCandidate, seed_draft


def _write_provider(artifact_dir: Path, provider: str, model: str, pdf_sha256: str, sessions_count: int = 5) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    from schedules.artifacts import slugify
    path = artifact_dir / f"{provider}-{slugify(model)}.json"
    path.write_text(json.dumps({
        "slug": "hamilton-pool",
        "provider": provider,
        "model": model,
        "pdf_url": "https://example.com/hamilton.pdf",
        "pdf_sha256": pdf_sha256,
        "extracted_at": "2026-04-10T12:00:00+00:00",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")[:sessions_count]
            ],
            "closures": [],
        },
    }))
    return path


def _make_candidate(artifact_dir: Path, pdf_sha256: str, slug: str = "hamilton-pool") -> ReviewCandidate:
    return ReviewCandidate(
        slug=slug,
        pdf_sha256=pdf_sha256,
        artifact_dir=artifact_dir,
        pdf_path=None,
        pdf_date="2026-04-01",
    )


def test_seed_draft_prefers_gemini(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)
    _write_provider(artifact_dir, "anthropic", "claude-sonnet-4-6", "a" * 64)
    drafts_root = tmp_path / "drafts"

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        drafts_root=drafts_root,
        today=date(2026, 4, 19),
    )

    envelope = json.loads(path.read_text())
    providers = [r["provider"] for r in envelope["reviewed_against"]]
    assert providers[0] == "gemini"
    assert set(providers) == {"gemini", "anthropic"}
    assert envelope["slug"] == "hamilton-pool"
    assert envelope["pdf_sha256"] == "a" * 64
    assert envelope["reviewed_at"] == "2026-04-19"
    assert envelope["summary"] == "(draft)"
    assert envelope["payload"]["schedule_effective"] == "2026-03-17"


def test_seed_draft_falls_back_to_anthropic_when_no_gemini(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "anthropic", "claude-sonnet-4-6", "a" * 64)
    drafts_root = tmp_path / "drafts"

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        drafts_root=drafts_root,
        today=date(2026, 4, 19),
    )
    envelope = json.loads(path.read_text())
    assert envelope["reviewed_against"][0]["provider"] == "anthropic"


def test_seed_draft_falls_back_to_latest_mtime_for_unknown_provider(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    older = _write_provider(artifact_dir, "future", "model-v1", "a" * 64)
    newer = _write_provider(artifact_dir, "other", "model-v2", "a" * 64)
    import os, time
    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    path = seed_draft(
        candidate=_make_candidate(artifact_dir, "a" * 64),
        drafts_root=tmp_path / "drafts",
        today=date(2026, 4, 19),
    )
    envelope = json.loads(path.read_text())
    assert envelope["reviewed_against"][0]["provider"] == "other"


def test_seed_draft_is_idempotent(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    _write_provider(artifact_dir, "gemini", "gemini-3.1-flash-lite-preview", "a" * 64)
    drafts_root = tmp_path / "drafts"
    candidate = _make_candidate(artifact_dir, "a" * 64)

    first = seed_draft(candidate=candidate, drafts_root=drafts_root, today=date(2026, 4, 19))
    first.write_text(first.read_text().replace('"(draft)"', '"reviewer edits"'))
    second = seed_draft(candidate=candidate, drafts_root=drafts_root, today=date(2026, 4, 20))

    assert first == second
    assert '"reviewer edits"' in second.read_text()


def test_seed_draft_raises_when_no_provider_artifact(tmp_path):
    empty_dir = tmp_path / "artifacts" / "hamilton-pool" / ("a" * 12)
    empty_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        seed_draft(
            candidate=_make_candidate(empty_dir, "a" * 64),
            drafts_root=tmp_path / "drafts",
            today=date(2026, 4, 19),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_seed.py -v`
Expected: FAIL with `ImportError: cannot import name 'seed_draft'`.

- [ ] **Step 3: Implement seed_draft**

Append to `src/schedules/review.py`:

```python
import json as _json
from datetime import date as _date
from .paths import REVIEWED_SNAPSHOT_DRAFTS_DIR
from .reviewed_snapshots import REVIEWED_SNAPSHOT_VERSION


_PROVIDER_PREFERENCE = ("gemini", "anthropic")


def _pick_provider_artifact(artifact_dir: Path) -> Path:
    """Return the provider artifact to seed from. gemini → anthropic → newest mtime."""
    provider_paths: dict[str, list[Path]] = {}
    for path in artifact_dir.glob("*.json"):
        if path.name == "meta.json":
            continue
        provider = path.name.split("-", 1)[0]
        provider_paths.setdefault(provider, []).append(path)

    for preferred in _PROVIDER_PREFERENCE:
        if preferred in provider_paths:
            return sorted(provider_paths[preferred], key=lambda p: p.stat().st_mtime)[-1]

    all_paths = [p for paths in provider_paths.values() for p in paths]
    if not all_paths:
        raise FileNotFoundError(f"No provider artifacts found in {artifact_dir}")
    return max(all_paths, key=lambda p: p.stat().st_mtime)


def _all_provider_descriptors(artifact_dir: Path) -> list[dict]:
    descriptors: list[dict] = []
    for path in sorted(artifact_dir.glob("*.json")):
        if path.name == "meta.json":
            continue
        try:
            payload = _json.loads(path.read_text())
        except (OSError, _json.JSONDecodeError):
            continue
        provider = payload.get("provider")
        model = payload.get("model")
        if isinstance(provider, str) and isinstance(model, str):
            descriptors.append({
                "provider": provider,
                "model": model,
                "artifact_relpath": str(path),
            })
    # Sort with preferred providers first, matching the seeding order.
    def _rank(d: dict) -> tuple[int, str]:
        try:
            idx = _PROVIDER_PREFERENCE.index(d["provider"])
        except ValueError:
            idx = len(_PROVIDER_PREFERENCE)
        return (idx, d["provider"])
    descriptors.sort(key=_rank)
    return descriptors


def draft_path_for(slug: str, pdf_sha256: str, today: _date, root: Path = REVIEWED_SNAPSHOT_DRAFTS_DIR) -> Path:
    return root / slug / f"{today.isoformat()}-{pdf_sha256[:12]}.json"


def seed_draft(
    *,
    candidate: ReviewCandidate,
    drafts_root: Path = REVIEWED_SNAPSHOT_DRAFTS_DIR,
    today: _date | None = None,
) -> Path:
    """Seed a draft envelope in the drafts tree. Returns its path.

    If a draft for this (slug, pdf_sha256) already exists, returns it
    unchanged — resuming work is idempotent across days. The existing
    filename's date prefix is preserved so reviewer edits survive even
    when the reviewer resumes on a later date.
    """
    today = today or _date.today()
    slug_dir = drafts_root / candidate.slug
    prefix = candidate.pdf_sha256[:12]
    if slug_dir.is_dir():
        existing = sorted(slug_dir.glob(f"*-{prefix}.json"))
        if existing:
            return existing[0]
    path = draft_path_for(candidate.slug, candidate.pdf_sha256, today, root=drafts_root)

    provider_path = _pick_provider_artifact(candidate.artifact_dir)
    provider_payload = _json.loads(provider_path.read_text())
    source_pdf_url = provider_payload.get("pdf_url", "")
    payload = provider_payload.get("payload", {})

    envelope = {
        "$schema": "../../reviewed-snapshots/schema.json",
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": candidate.slug,
        "pdf_sha256": candidate.pdf_sha256,
        "reviewed_at": today.isoformat(),
        "source_pdf_url": source_pdf_url,
        "reviewed_against": _all_provider_descriptors(candidate.artifact_dir),
        "summary": "(draft)",
        "payload": payload,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(envelope, indent=2) + "\n")
    return path
```

Note: the `$schema` key is accepted by the schema (it's declared as an optional property) and gives helix's JSON LSP the hint it needs for autocomplete.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_seed.py -v`
Expected: all five PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/review.py tests/test_review_seed.py
git commit -m "$(cat <<'EOF'
feat(review): seed draft envelopes from provider artifacts

Prefers gemini, falls back to anthropic, then newest-mtime. Idempotent
on re-entry across days: resume globs drafts_root/<slug>/*-<prefix>.json
so an editor crash or overnight pause doesn't lose reviewer edits. Adds
a $schema pointer so helix's JSON LSP picks up autocomplete automatically.
EOF
)"
```

---

## Task 6: Projection function (reviewed snapshot → content MD)

Standalone `project()` that reads a reviewed snapshot, canonicalizes, validates, and rewrites `content/spots/<slug>.md` by delegating to the existing `merge.merge()`.

**Files:**
- Create: `src/schedules/project.py`
- Create: `tests/test_project.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project.py
import json
import shutil
from pathlib import Path

import pytest

from schedules.project import ProjectError, project


REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "version": 1,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "test",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _write_snapshot(root: Path, slug: str, pdf_sha256: str, envelope: dict) -> Path:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"2026-04-18-{pdf_sha256[:12]}.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"Hamilton Pool\"\n\n[extra]\n+++\nBody\n")
    return path


def test_project_writes_sessions_to_content_md(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)

    rendered = (content / "hamilton-pool.md").read_text()
    assert "schedule_effective = \"2026-03-17\"" in rendered
    assert rendered.count("[[extra.sessions]]") == 5


def test_project_rejects_draft_path(tmp_path):
    drafts = tmp_path / "reviewed-snapshot-drafts"
    content = tmp_path / "content" / "spots"
    _write_snapshot(drafts, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(ProjectError, match="draft"):
        project(slug="hamilton-pool", snapshots_root=drafts, content_spots_dir=content)


def test_project_rejects_missing_slug(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    with pytest.raises(ProjectError, match="no reviewed snapshot"):
        project(slug="ghost-pool", snapshots_root=snapshots, content_spots_dir=content)


def test_project_is_idempotent(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64, _valid_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)
    first = (content / "hamilton-pool.md").read_text()
    project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)
    second = (content / "hamilton-pool.md").read_text()
    assert first == second


def test_project_rejects_invalid_payload(tmp_path):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    envelope = _valid_envelope("hamilton-pool", "a" * 64)
    envelope["payload"]["sessions"] = envelope["payload"]["sessions"][:2]  # < 5
    _write_snapshot(snapshots, "hamilton-pool", "a" * 64, envelope)
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(ProjectError, match="fewer than 5"):
        project(slug="hamilton-pool", snapshots_root=snapshots, content_spots_dir=content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_project.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schedules.project'`.

- [ ] **Step 3: Implement project()**

Create `src/schedules/project.py`:

```python
from __future__ import annotations

from pathlib import Path

from .merge import merge
from .paths import CONTENT_SPOTS_DIR, REVIEWED_SNAPSHOTS_DIR
from .reviewed_snapshots import (
    canonicalize_payload,
    load_reviewed_snapshot_from_path,
)
from .validate import validate


class ProjectError(RuntimeError):
    """Raised when projection fails; message is reviewer-facing."""


def _latest_snapshot_path(snapshots_root: Path, slug: str) -> Path | None:
    slug_dir = snapshots_root / slug
    if not slug_dir.is_dir():
        return None
    candidates = sorted(slug_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def project(
    *,
    slug: str,
    snapshots_root: Path = REVIEWED_SNAPSHOTS_DIR,
    content_spots_dir: Path = CONTENT_SPOTS_DIR,
) -> Path:
    """Project the latest reviewed snapshot for `slug` into content/spots/<slug>.md.

    Raises ProjectError with a reviewer-facing message on any failure.
    Returns the path to the written MD. Idempotent.
    """
    # Explicit draft-tree guard: spec contract. Compare by basename so the
    # guard fires whether callers pass the real constant or a test-injected
    # tmp_path that mirrors the on-disk layout.
    if snapshots_root.name == "reviewed-snapshot-drafts":
        raise ProjectError(
            f"refusing to project from draft tree {snapshots_root}; "
            "drafts must be finalized into reviewed-snapshots first"
        )

    snapshot_path = _latest_snapshot_path(snapshots_root, slug)
    if snapshot_path is None:
        raise ProjectError(f"no reviewed snapshot found for slug={slug!r}")

    envelope, _, _ = load_reviewed_snapshot_from_path(snapshot_path, expected_slug=slug)
    canonical = canonicalize_payload(envelope["payload"])

    result = validate(canonical)
    if not result.ok:
        raise ProjectError("; ".join(result.violations))

    md_path = content_spots_dir / f"{slug}.md"
    if not md_path.exists():
        raise ProjectError(f"content file missing: {md_path}")

    merge(md_path, canonical)
    return md_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_project.py -v`
Expected: all five PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/project.py tests/test_project.py
git commit -m "$(cat <<'EOF'
feat(project): project reviewed snapshot into content MD

Standalone command that canonicalizes, validates, and hands off to the
existing merge.merge() for the tomlkit round-trip. Guards against being
called with the draft tree, and surfaces validation failures with a
reviewer-facing message.
EOF
)"
```

---

## Task 7: CLI — `schedules project <slug>`

**Files:**
- Modify: `src/schedules/cli.py`
- Create: `tests/test_cli_project.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_project.py
import json
from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli


def _valid_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "version": 1,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "test",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_cli_project_happy_path(tmp_path, monkeypatch):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    (snapshots / "hamilton-pool").mkdir(parents=True)
    (snapshots / "hamilton-pool" / "2026-04-18-aaaaaaaaaaaa.json").write_text(
        json.dumps(_valid_envelope("hamilton-pool", "a" * 64))
    )
    content.mkdir(parents=True)
    (content / "hamilton-pool.md").write_text("+++\ntitle = \"Hamilton\"\n\n[extra]\n+++\n")

    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOTS_DIR", snapshots)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    runner = CliRunner()
    result = runner.invoke(cli, ["project", "hamilton-pool"])
    assert result.exit_code == 0, result.output
    assert "hamilton-pool.md" in result.output


def test_cli_project_missing_slug_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOTS_DIR", tmp_path / "reviewed-snapshots")
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", tmp_path / "content" / "spots")
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "ghost-pool"])
    assert result.exit_code != 0
    assert "no reviewed snapshot" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_project.py -v`
Expected: FAIL with `Error: No such command 'project'`.

- [ ] **Step 3: Wire the CLI command**

Edit `src/schedules/cli.py`. At the top with other imports, add:

```python
from .paths import CONTENT_SPOTS_DIR, REVIEWED_SNAPSHOTS_DIR
from .project import ProjectError, project as _project
```

Then after the `extract` command (before `@cli.group() def debug`), add:

```python
@cli.command("project")
@click.argument("slug")
def project_command(slug: str) -> None:
    """Project the latest reviewed snapshot for SLUG into content/spots/<slug>.md."""
    try:
        path = _project(
            slug=slug,
            snapshots_root=REVIEWED_SNAPSHOTS_DIR,
            content_spots_dir=CONTENT_SPOTS_DIR,
        )
    except ProjectError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote {path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_project.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/cli.py tests/test_cli_project.py
git commit -m "$(cat <<'EOF'
feat(cli): add `schedules project <slug>` subcommand

Thin Click wrapper over schedules.project.project(). Surfaces ProjectError
messages through ClickException so validation failures get a clean exit
code without a stack trace.
EOF
)"
```

---

## Task 8: Finalize a draft

Load draft → schema-validate → validate invariants → destination conflict check → `os.rename` → project. Returns the final snapshot path or raises with a reviewer-facing message.

**Files:**
- Modify: `src/schedules/review.py`
- Create: `tests/test_review_finalize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_finalize.py
import json
from pathlib import Path

import pytest

from schedules.review import FinalizeError, finalize_draft


def _valid_draft_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "version": 1,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-19",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "summary": "reviewer edits",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _write_draft(drafts_root: Path, slug: str, pdf_sha256: str, envelope: dict) -> Path:
    slug_dir = drafts_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / f"2026-04-19-{pdf_sha256[:12]}.json"
    path.write_text(json.dumps(envelope))
    return path


def _seed_content_md(content_dir: Path, slug: str) -> Path:
    path = content_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")
    return path


def test_finalize_happy_path(tmp_path):
    drafts = tmp_path / "drafts"
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, _valid_draft_envelope("hamilton-pool", "a" * 64))
    _seed_content_md(content, "hamilton-pool")

    result = finalize_draft(
        draft_path=draft,
        snapshots_root=snapshots,
        content_spots_dir=content,
    )

    assert result.is_relative_to(snapshots)
    assert not draft.exists()
    assert (snapshots / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json").exists()
    assert "[[extra.sessions]]" in (content / "hamilton-pool.md").read_text()


def test_finalize_rejects_malformed_json(tmp_path):
    drafts = tmp_path / "drafts"
    (drafts / "hamilton-pool").mkdir(parents=True)
    draft = drafts / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json"
    draft.write_text("{ bogus")

    with pytest.raises(FinalizeError, match="invalid JSON"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=tmp_path / "reviewed-snapshots",
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert draft.exists()


def test_finalize_rejects_schema_invalid(tmp_path):
    drafts = tmp_path / "drafts"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    del envelope["summary"]  # violates required
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, envelope)

    with pytest.raises(FinalizeError, match="summary"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=tmp_path / "reviewed-snapshots",
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert draft.exists()


def test_finalize_rejects_validate_failure(tmp_path):
    drafts = tmp_path / "drafts"
    envelope = _valid_draft_envelope("hamilton-pool", "a" * 64)
    # Schema-valid (5 sessions, well-formed HH:MM), but validate() catches
    # the start >= end ordering the schema pattern cannot express.
    envelope["payload"]["sessions"][0]["start"] = "09:00"
    envelope["payload"]["sessions"][0]["end"] = "08:00"
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, envelope)

    with pytest.raises(FinalizeError, match="invalid time range"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=tmp_path / "reviewed-snapshots",
            content_spots_dir=tmp_path / "content" / "spots",
        )
    assert draft.exists()


def test_finalize_aborts_on_destination_conflict(tmp_path):
    drafts = tmp_path / "drafts"
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, _valid_draft_envelope("hamilton-pool", "a" * 64))
    (snapshots / "hamilton-pool").mkdir(parents=True)
    (snapshots / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json").write_text("{}")
    _seed_content_md(content, "hamilton-pool")

    with pytest.raises(FinalizeError, match="already exists"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=snapshots,
            content_spots_dir=content,
        )
    assert draft.exists()


def test_finalize_surfaces_post_rename_projection_failure(tmp_path):
    """Rename is the commit point: if project() fails after rename, the draft
    is gone, the snapshot exists, and the error tells the reviewer how to
    recover by re-running `schedules project <slug>`."""
    drafts = tmp_path / "drafts"
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    draft = _write_draft(drafts, "hamilton-pool", "a" * 64, _valid_draft_envelope("hamilton-pool", "a" * 64))
    # Deliberately omit content/spots/hamilton-pool.md — project() will raise
    # a ProjectError("content file missing: ...") AFTER the rename succeeds.
    content.mkdir(parents=True)

    with pytest.raises(FinalizeError, match="projection failed"):
        finalize_draft(
            draft_path=draft,
            snapshots_root=snapshots,
            content_spots_dir=content,
        )

    assert not draft.exists()
    assert (snapshots / "hamilton-pool" / "2026-04-19-aaaaaaaaaaaa.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_finalize.py -v`
Expected: FAIL with `ImportError: cannot import name 'finalize_draft'`.

- [ ] **Step 3: Implement finalize_draft**

Append to `src/schedules/review.py`:

```python
from .envelope import EnvelopeValidationError, validate_envelope
from .paths import CONTENT_SPOTS_DIR
from .project import ProjectError, project
from .validate import validate


class FinalizeError(RuntimeError):
    """Raised when finalizing a draft fails; message is reviewer-facing."""


def finalize_draft(
    *,
    draft_path: Path,
    snapshots_root: Path = REVIEWED_SNAPSHOTS_DIR,
    content_spots_dir: Path = CONTENT_SPOTS_DIR,
) -> Path:
    """Finalize a draft envelope into a reviewed snapshot and project its MD.

    Returns the final snapshot path on success. Leaves the draft in place
    on any failure. Commit point is the os.rename; project() runs after.
    """
    try:
        raw = _json.loads(draft_path.read_text())
    except _json.JSONDecodeError as exc:
        raise FinalizeError(f"{draft_path}: invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    except OSError as exc:
        raise FinalizeError(f"{draft_path}: cannot read: {exc}") from exc

    if not isinstance(raw, dict):
        raise FinalizeError(f"{draft_path}: envelope must be a JSON object")

    try:
        validate_envelope(raw)
    except EnvelopeValidationError as exc:
        raise FinalizeError(f"schema: {exc}") from exc

    result = validate(raw.get("payload", {}))
    if not result.ok:
        raise FinalizeError("; ".join(result.violations))

    slug = raw["slug"]
    pdf_sha256 = raw["pdf_sha256"]
    reviewed_at = raw["reviewed_at"]
    destination = snapshots_root / slug / f"{reviewed_at}-{pdf_sha256[:12]}.json"

    if destination.exists():
        raise FinalizeError(
            f"destination {destination} already exists; resolve by deleting either "
            "the existing snapshot or the draft, then retry"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    import os as _os
    _os.rename(draft_path, destination)

    try:
        project(slug=slug, snapshots_root=snapshots_root, content_spots_dir=content_spots_dir)
    except ProjectError as exc:
        raise FinalizeError(
            f"snapshot committed at {destination}, but projection failed: {exc}. "
            f"Re-run `schedules project {slug}` to finish."
        ) from exc

    return destination
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_finalize.py -v`
Expected: all six PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/review.py tests/test_review_finalize.py
git commit -m "$(cat <<'EOF'
feat(review): finalize drafts into reviewed snapshots

Rename is the commit point; projection runs after. Draft stays in place
on any pre-rename failure (malformed JSON, schema violation, validate
failure, destination conflict). Post-rename projection failures leave
the snapshot committed and surface a message telling the reviewer how
to finish via `schedules project`, exercised by a dedicated test.
EOF
)"
```

---

## Task 9: CLI — `schedules review [--slug <slug>]`

**Files:**
- Modify: `src/schedules/cli.py`
- Create: `tests/test_cli_review.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_review.py
import json
import os
from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli


def _write_artifact(root: Path, slug: str, pdf_sha256: str) -> None:
    artifact_dir = root / slug / pdf_sha256[:12]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "gemini-model.json").write_text(json.dumps({
        "slug": slug,
        "provider": "gemini",
        "model": "model",
        "pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))


def _write_pdf(root: Path, slug: str, date: str, pdf_sha256: str) -> None:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / f"{date}-{pdf_sha256[:12]}.pdf").write_bytes(b"%PDF-fake")


def _seed_content_md(content_dir: Path, slug: str) -> None:
    content_dir.mkdir(parents=True, exist_ok=True)
    (content_dir / f"{slug}.md").write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")


def _patch_dirs(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    drafts = tmp_path / "reviewed-snapshot-drafts"
    pdfs = tmp_path / "pdfs"
    content = tmp_path / "content" / "spots"
    artifacts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("schedules.cli.ARTIFACTS_DIR", artifacts)
    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOTS_DIR", snapshots)
    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOT_DRAFTS_DIR", drafts)
    monkeypatch.setattr("schedules.cli.PDF_CACHE_DIR", pdfs)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)
    return artifacts, snapshots, drafts, pdfs, content


def test_cli_review_reports_nothing_to_review(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0
    assert "nothing to review" in result.output


def test_cli_review_hints_extract_when_artifacts_missing(tmp_path, monkeypatch):
    # Patch paths then remove the artifacts directory.
    artifacts, *_ = _patch_dirs(monkeypatch, tmp_path)
    import shutil
    shutil.rmtree(artifacts)
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0
    assert "schedules extract" in result.output


def test_cli_review_end_to_end_with_editor_noop(tmp_path, monkeypatch):
    artifacts, snapshots, drafts, pdfs, content = _patch_dirs(monkeypatch, tmp_path)
    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_content_md(content, "hamilton-pool")

    # Replace subprocess.run with no-ops: PDF open + editor both succeed immediately.
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        class R: returncode = 0
        return R()
    monkeypatch.setattr("schedules.cli.subprocess.run", fake_run)
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0, result.output
    final = snapshots / "hamilton-pool"
    assert list(final.glob("*.json"))  # a snapshot was committed
    assert "Wrote" in result.output
    # Editor and `open` were both invoked.
    assert any(call[0] == "open" for call in calls)
    assert any(call[0] in {"hx", "$EDITOR"} or call[0].endswith("hx") for call in calls)


def test_cli_review_filters_by_slug(tmp_path, monkeypatch):
    artifacts, snapshots, drafts, pdfs, content = _patch_dirs(monkeypatch, tmp_path)
    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_artifact(artifacts, "balboa-pool", "b" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_pdf(pdfs, "balboa-pool", "2026-04-01", "b" * 64)
    _seed_content_md(content, "balboa-pool")

    monkeypatch.setattr("schedules.cli.subprocess.run", lambda *a, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review", "--slug", "balboa-pool"])
    assert result.exit_code == 0, result.output
    assert (snapshots / "balboa-pool").exists()
    assert not (snapshots / "hamilton-pool").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_review.py -v`
Expected: FAIL with `Error: No such command 'review'`.

- [ ] **Step 3: Wire the CLI command**

Edit `src/schedules/cli.py`. At the top (with the other imports), add:

```python
import subprocess

from .paths import (
    ARTIFACTS_DIR,
    CONTENT_SPOTS_DIR,
    PDF_CACHE_DIR,
    REVIEWED_SNAPSHOT_DRAFTS_DIR,
    REVIEWED_SNAPSHOTS_DIR,
)
from .review import (
    FinalizeError,
    draft_path_for,
    finalize_draft,
    find_review_candidates,
    seed_draft,
)
```

(Merge with the existing `from .paths import` if Task 7 already added one.)

Then after `project_command`, add:

```python
@cli.command("review")
@click.option("--slug", help="Restrict review to this pool slug.")
def review_command(slug: str | None) -> None:
    """Approve the next pipeline-extracted pool schedule."""
    if not ARTIFACTS_DIR.is_dir():
        click.echo("nothing to review (run `schedules extract` first?)")
        return

    candidates = find_review_candidates(
        artifacts_root=ARTIFACTS_DIR,
        snapshots_root=REVIEWED_SNAPSHOTS_DIR,
        pdfs_root=PDF_CACHE_DIR,
        only_slug=slug,
    )
    if not candidates:
        click.echo("nothing to review")
        return

    candidate = candidates[0]
    draft = seed_draft(candidate=candidate, drafts_root=REVIEWED_SNAPSHOT_DRAFTS_DIR)
    click.echo(f"Reviewing {candidate.slug} ({candidate.pdf_sha256[:12]})")
    click.echo(f"Draft:  {draft}")

    if candidate.pdf_path and candidate.pdf_path.exists():
        try:
            subprocess.run(["open", str(candidate.pdf_path)], check=False)
        except FileNotFoundError:
            click.echo(f"(note: `open` not available; PDF at {candidate.pdf_path})")

    editor = os.getenv("EDITOR") or "hx"
    subprocess.run([editor, str(draft)], check=False)

    try:
        final = finalize_draft(
            draft_path=draft,
            snapshots_root=REVIEWED_SNAPSHOTS_DIR,
            content_spots_dir=CONTENT_SPOTS_DIR,
        )
    except FinalizeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote {final}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_review.py -v`
Expected: all four PASS.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest`
Expected: all tests PASS; no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/schedules/cli.py tests/test_cli_review.py
git commit -m "$(cat <<'EOF'
feat(cli): add `schedules review [--slug <slug>]` subcommand

Scans for the next review candidate, seeds a draft, opens the PDF in
Preview (macOS), launches \$EDITOR or hx on the draft, and finalizes on
editor exit. Clean-checkout state (no artifacts dir) prints a helpful
hint to run extract first.
EOF
)"
```

---

## Task 10: Document the workflow

**Files:**
- Modify: `docs/schedules.md`

- [ ] **Step 1: Read existing docs to understand tone and sections**

Run: `head -80 docs/schedules.md`
Expected: output showing the existing headings. Identify a natural spot to add a "Reviewing extracted schedules" section (likely near existing pipeline docs or at the end).

- [ ] **Step 2: Append the review workflow section**

Add to `docs/schedules.md`, at a logical position (after pipeline/extract docs):

````markdown
## Reviewing extracted schedules

When the extraction pipeline can't auto-ratify a pool (grounding flagged something, `validate` failed, or extraction failed), the pool joins a review queue. Approve extractions by running:

```
schedules review
```

The CLI scans `data/artifacts/` for `(slug, pdf_sha256)` pairs with no matching reviewed snapshot, picks the oldest-PDF-first, and:

1. Seeds a draft envelope at `data/reviewed-snapshot-drafts/<slug>/<reviewed_at>-<prefix>.json` (gitignored).
2. Opens the PDF in Preview (macOS `open`).
3. Launches `$EDITOR` (or `hx`) on the draft. Helix's JSON LSP picks up the `$schema` pointer and gives you autocomplete + inline validation.
4. On editor exit, validates and finalizes: schema → `validate()` invariants → destination check → rename draft into `data/reviewed-snapshots/` → project into `content/spots/<slug>.md`.

To review a specific pool: `schedules review --slug hamilton-pool`.

If finalization fails after the snapshot is committed (rare; projection error), re-run `schedules project <slug>` to finish.

The draft tree is ignored by git. If the pipeline writes a new artifact for a PDF you've already reviewed, the filesystem diff automatically re-surfaces it.
````

- [ ] **Step 3: Commit**

```bash
git add docs/schedules.md
git commit -m "docs(schedules): document the reviewer workflow"
```

---

## Self-review checklist (run after completing all tasks)

- [ ] All tests pass: `uv run pytest`
- [ ] Spec §"Finalization order" satisfied: rename is the commit point (Task 8)
- [ ] Spec §"Review-status detector" satisfied: scans by pdf_sha256, not directory name (Task 4)
- [ ] Spec §"Review order" satisfied: ordered by PDF date then slug (Task 4 test)
- [ ] Spec §"Draft seeding" satisfied: gemini → anthropic → mtime fallback (Task 5 tests)
- [ ] Spec §"Schema compatibility" satisfied: `reviewed_by` and `ratified_from_sha256` accepted (Task 1)
- [ ] Spec §"CLI surface: schedules review" — all 6 sub-steps implemented (Tasks 4,5,8,9)
- [ ] Spec §"CLI surface: schedules project" — all 4 sub-steps implemented (Task 6)
- [ ] Spec contract "schedules project never writes a spot .md from a draft" — enforced (Task 6, test_project_rejects_draft_path)
- [ ] `.gitignore` covers `data/reviewed-snapshot-drafts/` (Task 2)
- [ ] Docs updated (Task 10)
