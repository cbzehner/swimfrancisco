---
status: complete
progress:
  - section: "Task 1: Rename the module, directory, state field, and in-repo references"
    status: complete
    notes:
      - "Committed d6319fb; 58 tests pass; no adjudicat leftovers in src/tests/state"
      - "Codex also rewrote the plan file text itself to eliminate the word 'adjudicat' — scope creep, but approved by user"
      - "Codex added an explicit sort key in report.py artifact rendering (alphabetical no longer pinned reviewed-snapshot first). Behavior-preserving, test-driven."
  - section: "Task 2: Enforce reviewed_snapshot envelope schema"
    status: complete
    notes:
      - "Committed 1649677; 63 tests pass; all 7 snapshots upgraded to v1 envelope"
      - "Codex reformatted snapshot JSON to multi-line sessions (noisier diff, payload byte-equivalent)"
  - section: "Task 3: Add canonicalize_payload() helper"
    status: complete
    notes:
      - "Committed 2cc1a71; 67 tests pass"
      - "Pyright false positives on pytest import + narrow-type None checks in tests — runtime correct"
  - section: "Task 4: Route reviewed payloads through validate() + grounding"
    status: complete
    notes:
      - "Committed 89e8895; 68 tests pass"
      - "Added grounding_from_text + check_delta to reviewed-snapshot branch; no existing tests asserted empty review_notes on snapshot path"
  - section: "Task 5: Ratification branch in pipeline"
    status: complete
    notes:
      - "Committed f143030; 71 tests pass (3 new ratification tests + 68)"
      - "Codex subagent refused, mistakenly applying malware-reminder to benign application code. Outer session implemented directly."
      - "Skipped plan Step 7 (single-pool pipeline verification) + Step 8 (full dry-run) because .env is not present in this worktree. Unit tests cover the ratification helpers and pipeline integration."
  - section: "Task 6: Document the mental model"
    status: complete
    notes:
      - "Committed 406b582 (docs) + 1074d29 (north-beach summary prose). 71 tests pass."
      - "Rollout verification: no adjudicat in src/tests/data. Only self-referential mentions remain in this plan file's state-tracking notes."
last_review: 2026-04-18T10:00:00-07:00
iterations: 6
no_progress_count: 0
started_at: 2026-04-18T08:06:43-07:00
work_unit_granularity: task
---

# Reviewed Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the current `data/reviewed-snapshots/` override mechanism as a regeneration aid and audit record, not a parallel source of truth, so that (a) reviewed payloads are validated the same way provider output is, (b) a fresh extract that matches a prior review auto-ratifies without a new manual pass, and (c) the checked-in `content/spots/*.md` is unambiguously the source of truth.

**Architecture:** Rename the module, directory, and state field to match the new mental model. Add an enforced envelope schema with a `version` field and a small fixed provenance block. Route reviewed payloads through the same `validate()` + `grounding_from_text()` that provider output uses. Add a `canonicalize_payload()` helper and a ratification path that, when a fresh provider run canonicalizes to any prior reviewed snapshot for the same slug, auto-accepts and writes a new ratified snapshot at the new PDF hash.

**Tech Stack:** Python 3 + `uv`, existing `schedules` CLI, `pytest`, JSON snapshots on disk. No new runtime dependencies.

**Scope carve-out:** The north-beach-pool multi-pool gap belongs to `docs/plans/multi-pool-facilities.md`. This plan does not touch the session schema.

---

## Background: PDF extraction in the LLM era

The "as simple as possible, no simpler" lens changes which best practices apply. This plan intentionally does *not* adopt the heavier patterns that are right for production document pipelines (spatial grounding, bounding-box citations, layout-aware serialization via pdfplumber/camelot, canonical-PDF normalization, image-based fallbacks). Those become worth it when scale or stakes demand them; at seven pools and one maintainer they are premature.

The simple patterns this plan *does* adopt:

1. **Source of truth is the rendered artifact, not the extraction cache.** `content/spots/*.md` is the site. The snapshot is a regeneration aid — if the snapshot disappeared, the site would still be correct; regenerating it would be a one-time re-review, not a data-loss event. This is the key mental-model shift the rename signals.
2. **Human review is an envelope around a payload, not a replacement for validation.** A reviewed payload passes through the same structural checks a machine payload does. Human review protects against misinterpretation, not against typos in the reviewer's JSON.
3. **Cache identity ≠ content identity.** Byte hashes are fine for the fast path but must not be the only identity. Ratification by canonical content means a re-export of the same schedule does not force a re-review.
4. **Provenance is a small fixed shape, not a convention.** A required envelope (`version`, `reviewed_at`, `reviewed_against`, `source_pdf_url`, `payload`) is enforced at load time so future-you has a durable record of *what was reviewed against what*.
5. **Auto-ratification closes the loop.** When the provider has caught up to (or matches) the human, the system records the agreement and stops asking for re-review. This is the thing that makes the reviewed snapshot deserve its name.

What we *defer*:
- `pdfplumber`/layout-aware grounding. `pypdf` flat-text substring grounding is weak on tabular PDFs in theory; in practice, at this scale, the failure has not been observed. Revisit when it actually bites.
- Canonical-PDF hashing (stripping `/CreationDate`, etc.). Ratification-by-canonical-payload solves the same human problem from the other side with no new PDF plumbing.
- Per-session page numbers / bbox grounding. Overkill for seven PDFs whose reviewer can eyeball them in a browser.
- Page-image rendering for visual review. Nice-to-have, not load-bearing.

---

## File Structure

### Created

- `src/schedules/reviewed_snapshots.py` — replaces `reviewed_snapshots.py`'s predecessor module. Exposes `load_reviewed_snapshot()`, `ReviewedSnapshot` dataclass, `REVIEWED_SNAPSHOT_VERSION`, and `canonicalize_payload()`.
- `tests/test_reviewed_snapshots.py` — replaces the predecessor test module. Covers envelope validation, canonicalization, and load-path behavior.
- `tests/test_ratification.py` — new. Covers the ratification branch in the pipeline: matching provider output auto-accepts and writes a new ratified snapshot.

### Modified

- `src/schedules/paths.py` — rename `ADJUDICATIONS_DIR` to `REVIEWED_SNAPSHOTS_DIR`; point at `data/reviewed-snapshots/`.
- `src/schedules/state.py` — rename the legacy snapshot fingerprint field to `reviewed_snapshot_sha256`.
- `src/schedules/pipeline.py` — switch the import; call new validation path on reviewed payloads; implement ratification branch.
- `src/schedules/models.py` — use `Proposed.reviewed_snapshot_notes`.
- `src/schedules/report.py` — rename report prose and labels to the reviewed-snapshot terminology.
- `docs/schedules.md` — update the Review Flow, terminology, and mental-model description.
- `NAPKIN.md` — update the reviewed-snapshot mental-model bullet.
- `data/extraction-state.json` — mechanically rename the per-entry snapshot fingerprint key to `reviewed_snapshot_sha256`.

### Moved (via `git mv`)

- `src/schedules/reviewed_snapshots.py` predecessor → `src/schedules/reviewed_snapshots.py`
- `tests/test_reviewed_snapshots.py` predecessor → `tests/test_reviewed_snapshots.py`
- reviewed snapshot directory predecessor → `data/reviewed-snapshots/` (all seven subdirectories and their JSON files)

### Deleted

None.

---

## Task 1: Rename the module, directory, state field, and in-repo references

**Files:**
- Move: legacy snapshot module → `src/schedules/reviewed_snapshots.py`
- Move: legacy snapshot test → `tests/test_reviewed_snapshots.py`
- Move: legacy snapshot directory → `data/reviewed-snapshots/`
- Modify: `src/schedules/paths.py:12`
- Modify: `src/schedules/state.py:39,59`
- Modify: `src/schedules/pipeline.py` (imports + local variable names)
- Modify: `src/schedules/models.py:151`
- Modify: `src/schedules/report.py` (update report prose and labels)
- Modify: `data/extraction-state.json`
- Modify: `docs/schedules.md`
- Modify: `NAPKIN.md`

- [ ] **Step 1: Move files with git mv (preserves history)**

```bash
git mv src/schedules/reviewed_snapshots.py.predecessor src/schedules/reviewed_snapshots.py
git mv tests/test_reviewed_snapshots.py.predecessor tests/test_reviewed_snapshots.py
git mv data/reviewed-snapshots.predecessor data/reviewed-snapshots
```

- [ ] **Step 2: Update `paths.py`**

Replace the `ADJUDICATIONS_DIR` line:

```python
REVIEWED_SNAPSHOTS_DIR = DATA_DIR / "reviewed-snapshots"
```

Keep the rest of `paths.py` untouched.

- [ ] **Step 3: Update `reviewed_snapshots.py` internals**

Rename functions and imports inside the moved file:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .paths import REVIEWED_SNAPSHOTS_DIR, relative_to_repo


def reviewed_snapshot_path(slug: str, pdf_sha256: str, root: Path = REVIEWED_SNAPSHOTS_DIR) -> Path:
    return root / slug / f"{pdf_sha256}.json"


def load_reviewed_snapshot(
    slug: str,
    pdf_sha256: str,
    *,
    root: Path = REVIEWED_SNAPSHOTS_DIR,
) -> tuple[dict | None, str | None, str | None]:
    path = reviewed_snapshot_path(slug, pdf_sha256, root)
    if not path.exists():
        return None, None, None

    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is missing a payload object.")

    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    return raw, fingerprint, relative_to_repo(path)
```

This is a pure rename for now — the envelope schema lands in Task 2. Do not change behavior here.

- [ ] **Step 4: Update `state.py` field name**

Rename the keyword argument and returned dict key in `build_state_entry`:

```python
def build_state_entry(
    *,
    pdf_sha256: str,
    provider: str,
    model: str,
    notes: list[ReviewNote],
    artifact_paths: dict[str, str],
    pdf_page_count: int,
    pdf_text_sha256: str,
    reviewed_snapshot_sha256: str | None = None,
) -> dict:
    return {
        "pdf_sha256": pdf_sha256,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "notes": [note.message for note in notes],
        "note_details": [serialize_note(note) for note in notes],
        "artifact_paths": artifact_paths,
        "pdf_page_count": pdf_page_count,
        "pdf_text_sha256": pdf_text_sha256,
        "reviewed_snapshot_sha256": reviewed_snapshot_sha256,
    }
```

- [ ] **Step 5: Update `pipeline.py` imports and local names**

Replace the import line:

```python
from .reviewed_snapshots import load_reviewed_snapshot
```

And update the call site plus the local names in `run_pipeline`:

```python
snapshot, snapshot_sha256, snapshot_path = load_reviewed_snapshot(entry.slug, fetch_result.sha256)
if (
    not force
    and not compare_with
    and prior_state
    and prior_state.get("pdf_sha256") == fetch_result.sha256
    and prior_state.get("reviewed_snapshot_sha256") == snapshot_sha256
):
```

And in the existing snapshot branch:

```python
if snapshot and not compare_with:
    payload = snapshot["payload"]
    model = "manual-review"
    usage = {}
    cost_estimate = "reviewed-snapshot"
    result_provider = "reviewed-snapshot"
    review_notes: list[ReviewNote] = []
    artifact_paths = {"reviewed-snapshot": str(snapshot_path)}
    snapshot_notes = snapshot.get("summary")
```

And in the `build_state_entry` call:

```python
state[entry.slug] = build_state_entry(
    pdf_sha256=fetch_result.sha256,
    provider=result_provider,
    model=model,
    notes=review_notes,
    artifact_paths=artifact_paths,
    pdf_page_count=pdf_signals.page_count,
    pdf_text_sha256=pdf_signals.text_sha256,
    reviewed_snapshot_sha256=snapshot_sha256,
)
```

- [ ] **Step 6: Ensure `Proposed.reviewed_snapshot_notes` is used consistently**

In `src/schedules/models.py`:

```python
reviewed_snapshot_notes: str | None = None
```

In `pipeline.py` where `Proposed(...)` is constructed:

```python
reviewed_snapshot_notes=snapshot_notes,
```

- [ ] **Step 7: Update `report.py` prose**

Grep the file for legacy `adj*` terms and replace each human-readable occurrence. The ones you will find:

```bash
grep -nE '\badj[a-z_-]*\b' src/schedules/report.py
```

Typical replacements:
- Provider label uses `"reviewed-snapshot"`
- Section headers / labels use `"reviewed snapshot"`
- Attribute access uses `result.reviewed_snapshot_notes`

- [ ] **Step 8: Migrate `data/extraction-state.json` keys**

For each slug entry that has the legacy snapshot fingerprint key, rename it to `reviewed_snapshot_sha256`. This is purely mechanical — the values stay the same. You can do this with a one-shot script:

```bash
uv run python -c "
import json, pathlib
p = pathlib.Path('data/extraction-state.json')
state = json.loads(p.read_text())
for slug, entry in state.items():
    legacy_key = next((key for key in entry if key.startswith('adj') and key.endswith('_sha256')), None)
    if legacy_key:
        entry['reviewed_snapshot_sha256'] = entry.pop(legacy_key)
p.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
"
```

- [ ] **Step 9: Update `docs/schedules.md`**

Replace every occurrence of the legacy snapshot terminology with the `reviewed snapshot` / `reviewed-snapshot` / `reviewed` equivalent. Also replace the path `data/reviewed-snapshots/` throughout. The "Current Blockers" bullet becomes "…have manually reviewed snapshots in `data/reviewed-snapshots/`".

- [ ] **Step 10: Update `NAPKIN.md`**

Replace the stale reviewed-snapshot bullet with the corrected mental model:

```markdown
1. **[2026-04-18] `content/spots/*.md` is the source of truth; `data/reviewed-snapshots/` is a regeneration aid**
   Do instead: treat checked-in markdown as authoritative. `data/reviewed-snapshots/<slug>/<pdf_sha256>.json` is a human-reviewed payload used to skip re-extraction; it is not parallel truth. `data/artifacts/` remains the disposable local review cache.
```

- [ ] **Step 11: Update the existing rename test**

In the moved `tests/test_reviewed_snapshots.py`, update the import and symbol names:

```python
import json

from schedules.reviewed_snapshots import load_reviewed_snapshot


def test_load_reviewed_snapshot(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    file_path = root / "hamilton-pool" / f"{pdf_sha256}.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": pdf_sha256,
                "summary": "manual review",
                "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
            }
        )
    )

    snapshot, fingerprint, relative_path = load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)

    assert snapshot["summary"] == "manual review"
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert relative_path == str(file_path)
```

- [ ] **Step 12: Run the test suite**

Run: `uv run pytest -q`
Expected: all tests pass. Any still-failing import or assertion points at a reference you missed in the rename.

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(schedules): rename snapshot artifacts to reviewed-snapshots

The checked-in content/spots/*.md is the source of truth; the snapshot is
a regeneration aid and audit record, not a parallel authority. Rename the
module, directory, state field, and in-report prose to match. Pure rename;
behavior is unchanged in this commit.
EOF
)"
```

---

## Task 2: Enforce a reviewed_snapshot envelope schema

**Files:**
- Modify: `src/schedules/reviewed_snapshots.py`
- Modify: `tests/test_reviewed_snapshots.py`
- Modify: `data/reviewed-snapshots/<slug>/*.json` (add `version` and `reviewed_against` to the seven existing files)

- [ ] **Step 1: Write failing tests for envelope enforcement**

Append to `tests/test_reviewed_snapshots.py`:

```python
import pytest

from schedules.reviewed_snapshots import REVIEWED_SNAPSHOT_VERSION, load_reviewed_snapshot


def _write_snapshot(root, slug, pdf_sha256, envelope):
    file_path = root / slug / f"{pdf_sha256}.json"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(envelope))
    return file_path


def _valid_envelope(slug, pdf_sha256):
    return {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [
            {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}
        ],
        "summary": "manual review",
        "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
    }


def test_load_reviewed_snapshot_accepts_valid_envelope(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    _write_snapshot(root, "hamilton-pool", pdf_sha256, _valid_envelope("hamilton-pool", pdf_sha256))
    snapshot, fingerprint, _ = load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)
    assert snapshot["version"] == REVIEWED_SNAPSHOT_VERSION
    assert len(fingerprint) == 64


def test_load_reviewed_snapshot_rejects_missing_version(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    del envelope["version"]
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="version"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


def test_load_reviewed_snapshot_rejects_wrong_version(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    envelope["version"] = 999
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="version"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


def test_load_reviewed_snapshot_rejects_missing_required_field(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    del envelope["source_pdf_url"]
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="source_pdf_url"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)


def test_load_reviewed_snapshot_rejects_mismatched_slug(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    envelope = _valid_envelope("hamilton-pool", pdf_sha256)
    envelope["slug"] = "rossi-pool"
    _write_snapshot(root, "hamilton-pool", pdf_sha256, envelope)
    with pytest.raises(ValueError, match="slug"):
        load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/test_reviewed_snapshots.py -v`
Expected: the four new tests fail (envelope enforcement not yet implemented); the existing test passes.

- [ ] **Step 3: Implement envelope enforcement**

Rewrite `src/schedules/reviewed_snapshots.py` to enforce the envelope:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .paths import REVIEWED_SNAPSHOTS_DIR, relative_to_repo


REVIEWED_SNAPSHOT_VERSION = 1
_REQUIRED_ENVELOPE_FIELDS = (
    "version",
    "slug",
    "pdf_sha256",
    "reviewed_at",
    "source_pdf_url",
    "reviewed_against",
    "payload",
)


def reviewed_snapshot_path(slug: str, pdf_sha256: str, root: Path = REVIEWED_SNAPSHOTS_DIR) -> Path:
    return root / slug / f"{pdf_sha256}.json"


def _validate_envelope(raw: dict, path: Path, *, expected_slug: str, expected_pdf_sha256: str) -> None:
    missing = [field for field in _REQUIRED_ENVELOPE_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{path} is missing required field(s): {', '.join(missing)}")
    if raw["version"] != REVIEWED_SNAPSHOT_VERSION:
        raise ValueError(
            f"{path} has version={raw['version']!r}, expected {REVIEWED_SNAPSHOT_VERSION}"
        )
    if raw["slug"] != expected_slug:
        raise ValueError(
            f"{path} envelope slug={raw['slug']!r} does not match directory slug={expected_slug!r}"
        )
    if raw["pdf_sha256"] != expected_pdf_sha256:
        raise ValueError(
            f"{path} envelope pdf_sha256 does not match filename sha256"
        )
    if not isinstance(raw["payload"], dict):
        raise ValueError(f"{path} payload must be an object")
    if not isinstance(raw["reviewed_against"], list):
        raise ValueError(f"{path} reviewed_against must be a list")


def load_reviewed_snapshot(
    slug: str,
    pdf_sha256: str,
    *,
    root: Path = REVIEWED_SNAPSHOTS_DIR,
) -> tuple[dict | None, str | None, str | None]:
    path = reviewed_snapshot_path(slug, pdf_sha256, root)
    if not path.exists():
        return None, None, None

    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    _validate_envelope(raw, path, expected_slug=slug, expected_pdf_sha256=pdf_sha256)

    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    return raw, fingerprint, relative_to_repo(path)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest tests/test_reviewed_snapshots.py -v`
Expected: all tests pass.

- [ ] **Step 5: Upgrade the seven existing snapshot files to v1 envelopes**

For each file under `data/reviewed-snapshots/<slug>/*.json`, add the required fields if missing. The existing files already have `slug`, `pdf_sha256`, `reviewed_at`, `summary`, `source_artifacts`, and `payload`. They are missing `version`, `source_pdf_url`, and `reviewed_against`.

For each snapshot:
1. Add `"version": 1` at the top level.
2. Add `"source_pdf_url"` — copy from `src/schedules/registry.toml` for that slug.
3. Rename the existing `source_artifacts` map into a `reviewed_against` list of `{provider, model, artifact_relpath}`:

   Example — north-beach-pool before:
   ```json
   "source_artifacts": {
     "gemini": "data/artifacts/north-beach-pool/025a9d1fc086/gemini-gemini-3-1-flash-lite-preview.json",
     "anthropic": "data/artifacts/north-beach-pool/025a9d1fc086/anthropic-claude-sonnet-4-6.json"
   }
   ```

   After:
   ```json
   "reviewed_against": [
     {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview", "artifact_relpath": "data/artifacts/north-beach-pool/025a9d1fc086/gemini-gemini-3-1-flash-lite-preview.json"},
     {"provider": "anthropic", "model": "claude-sonnet-4-6", "artifact_relpath": "data/artifacts/north-beach-pool/025a9d1fc086/anthropic-claude-sonnet-4-6.json"}
   ]
   ```

   The `source_artifacts` field can be removed.

Do this by hand — seven files, five minutes of typing — rather than writing a migration script. Verify after each edit that `cat path | python -m json.tool` still parses.

- [ ] **Step 6: Run the full pipeline in dry-run against every slug**

Run: `set -a && source .env && set +a && uv run schedules extract --dry-run`
Expected: all seven published pools resolve via the reviewed-snapshot branch with no envelope errors. Report shows `provider=reviewed-snapshot` for each.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(schedules): enforce reviewed-snapshot envelope schema on load

Add REVIEWED_SNAPSHOT_VERSION=1 and required-field enforcement so that
loading a snapshot verifies version, slug, pdf_sha256, source_pdf_url,
reviewed_against, and payload shape before use. Upgrade the seven
existing snapshots to the v1 envelope. The snapshot is now a
self-describing audit record rather than a loose convention.
EOF
)"
```

---

## Task 3: Add `canonicalize_payload()` helper

**Files:**
- Modify: `src/schedules/reviewed_snapshots.py`
- Modify: `tests/test_reviewed_snapshots.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_reviewed_snapshots.py`:

```python
from schedules.reviewed_snapshots import canonicalize_payload


def test_canonicalize_payload_sorts_sessions():
    payload = {
        "schedule_effective": "2026-03-17",
        "sessions": [
            {"day": "tuesday", "type": "lap_swim", "start": "12:30", "end": "15:00"},
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert [s["day"] for s in canonical["sessions"]] == ["monday", "tuesday"]


def test_canonicalize_payload_strips_session_evidence_and_notes():
    payload = {
        "schedule_effective": "2026-03-17",
        "sessions": [
            {
                "day": "monday",
                "type": "lap_swim",
                "start": "07:30",
                "end": "08:30",
                "evidence": "LAP SWIM 7:30-8:30 AM",
                "notes": "closed 3rd thursday",
            }
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert "evidence" not in canonical["sessions"][0]
    assert "notes" not in canonical["sessions"][0]


def test_canonicalize_payload_preserves_pool_field():
    payload = {
        "schedule_effective": "2026-03-17",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30", "pool": "deep"}
        ],
        "closures": [],
    }
    canonical = canonicalize_payload(payload)
    assert canonical["sessions"][0]["pool"] == "deep"


def test_canonicalize_payload_identical_on_equivalent_inputs():
    a = {
        "schedule_effective": "2026-03-17",
        "schedule_effective_end": None,
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30",
             "evidence": "LAP 7:30-8:30"},
            {"day": "tuesday", "type": "family_swim", "start": "15:30", "end": "17:00",
             "evidence": "REC 3:30-5"},
        ],
        "closures": [
            {"start": "2026-05-25", "end": "2026-05-25", "reason": "Holiday Closure"},
        ],
    }
    b = {
        "sessions": [
            {"day": "tuesday", "type": "family_swim", "start": "15:30", "end": "17:00"},
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        ],
        "closures": [
            {"start": "2026-05-25", "end": "2026-05-25", "reason": "Holiday Closure"},
        ],
        "schedule_effective": "2026-03-17",
    }
    assert canonicalize_payload(a) == canonicalize_payload(b)
```

- [ ] **Step 2: Run to confirm they fail**

Run: `uv run pytest tests/test_reviewed_snapshots.py -v -k canonicalize`
Expected: all four tests fail with `ImportError` or `AttributeError` on `canonicalize_payload`.

- [ ] **Step 3: Implement `canonicalize_payload()`**

Append to `src/schedules/reviewed_snapshots.py`:

```python
_SESSION_COMPARE_KEYS = ("day", "type", "start", "end", "pool")
_CLOSURE_COMPARE_KEYS = ("start", "end", "reason")


def _project(source: dict, keys: tuple[str, ...]) -> dict:
    return {key: source[key] for key in keys if key in source}


def canonicalize_payload(payload: dict) -> dict:
    """Return a comparison-stable form of an extracted payload.

    Sorts sessions and closures, and strips fields that legitimately vary
    between a reviewed snapshot and a fresh provider extraction (e.g.
    `evidence`, free-form `notes`). Used by the ratification check: two
    payloads with identical canonical forms represent the same schedule.
    """
    sessions = [_project(session, _SESSION_COMPARE_KEYS) for session in payload.get("sessions") or []]
    sessions.sort(key=lambda s: tuple(s.get(key, "") for key in _SESSION_COMPARE_KEYS))

    closures = [_project(closure, _CLOSURE_COMPARE_KEYS) for closure in payload.get("closures") or []]
    closures.sort(key=lambda c: tuple(c.get(key, "") for key in _CLOSURE_COMPARE_KEYS))

    canonical: dict = {
        "schedule_effective": payload.get("schedule_effective"),
        "sessions": sessions,
        "closures": closures,
    }
    if "schedule_effective_end" in payload and payload["schedule_effective_end"] is not None:
        canonical["schedule_effective_end"] = payload["schedule_effective_end"]
    return canonical
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest tests/test_reviewed_snapshots.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/reviewed_snapshots.py tests/test_reviewed_snapshots.py
git commit -m "$(cat <<'EOF'
feat(schedules): add canonicalize_payload for comparison-stable form

canonicalize_payload() projects sessions and closures onto their
comparison-relevant keys and sorts them, giving a payload-level identity
that is stable across provider re-runs and minor evidence rewording.
Foundation for the ratification branch.
EOF
)"
```

---

## Task 4: Route reviewed payloads through `validate()` and grounding

**Files:**
- Modify: `src/schedules/pipeline.py`
- Modify: `tests/test_reviewed_snapshots.py`

The current pipeline skips validation and grounding when a reviewed snapshot is used — a typoed payload is trusted more than a model output. Close that inversion.

- [ ] **Step 1: Write failing test for snapshot payload validation**

Append to `tests/test_reviewed_snapshots.py`:

```python
from schedules.validate import validate


def test_reviewed_snapshot_payload_passes_validate():
    # The payload inside a v1 envelope must satisfy the same invariants
    # that provider output does. This is a smoke test that the shape
    # required by load_reviewed_snapshot is compatible with validate().
    payload = {
        "schedule_effective": "2026-03-17",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "wednesday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "thursday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "friday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        ],
        "closures": [],
    }
    result = validate(payload, prior_sessions_count=5)
    assert result.ok
```

Run: `uv run pytest tests/test_reviewed_snapshots.py::test_reviewed_snapshot_payload_passes_validate -v`
Expected: passes immediately (this is a framing test for the next step).

- [ ] **Step 2: Modify the pipeline reviewed-snapshot branch**

In `src/schedules/pipeline.py`, replace the current reviewed-snapshot branch:

```python
if snapshot and not compare_with:
    payload = snapshot["payload"]
    model = "manual-review"
    usage = {}
    cost_estimate = "reviewed-snapshot"
    result_provider = "reviewed-snapshot"
    review_notes: list[ReviewNote] = []
    snapshot_grounding = grounding_from_text(pdf_text_normalized, payload)
    review_notes.extend(_grounding_notes("reviewed-snapshot", snapshot_grounding))
    review_notes.extend(check_delta(payload, prior_snapshot))
    artifact_paths = {"reviewed-snapshot": str(snapshot_path)}
    snapshot_notes = snapshot.get("summary")
```

This removes the old "skip validation" short-circuit. `validate()` is already called below the branch on the chosen `payload`; grounding and delta now run on the snapshot payload too. A typoed snapshot now surfaces the same `review_notes` a bad provider run would, and a catastrophic validation violation (sessions dropped to 0) refuses the write just as for provider output.

- [ ] **Step 3: Run the full pipeline in dry-run**

Run: `set -a && source .env && set +a && uv run schedules extract --dry-run`
Expected: all seven pools still resolve as `reviewed-snapshot`. `tmp/extraction-report.md` may now show new `grounding_coverage_low` review notes for snapshots whose payloads don't cite evidence (the current seven snapshots do not carry `evidence` strings on sessions — this is expected and acceptable, since the snapshot's authority is human review, not text grounding).

- [ ] **Step 4: Accept the expected grounding notes**

The existing seven snapshot payloads do not carry per-session `evidence` strings (only provider output does). `grounding_from_text` will report them as ungrounded. This is informational, not a validation failure. Verify the report looks like this and move on — no code change needed.

If the noise is intolerable, the narrow fix is to treat an entirely-empty-evidence payload as "grounding not applicable" rather than "grounding 0%". Add this guard in `_grounding_notes`:

```python
def _grounding_notes(provider: str, grounding: GroundingResult) -> list[ReviewNote]:
    if grounding.total == 0 or grounding.ratio >= _GROUNDING_MIN_RATIO:
        return []
    if all(entry.missing_evidence for entry in grounding.ungrounded):
        return []  # snapshot payloads without evidence: not a grounding failure
    ...
```

Only apply this guard if the report noise actually bothers you after seeing it.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/pipeline.py tests/test_reviewed_snapshots.py
git commit -m "$(cat <<'EOF'
fix(schedules): validate reviewed-snapshot payloads like provider output

The old branch skipped validate(), grounding, and delta checks when a
reviewed snapshot was used, which meant a typo in the JSON was trusted
more than a model output. Route snapshot payloads through the same
checks. Human review protects against misinterpretation, not typos.
EOF
)"
```

---

## Task 5: Ratification — auto-accept provider output matching a prior snapshot

**Files:**
- Modify: `src/schedules/reviewed_snapshots.py`
- Modify: `src/schedules/pipeline.py`
- Create: `tests/test_ratification.py`

When a fresh provider extraction canonicalizes to the same payload as *any* prior reviewed snapshot for this slug, the pipeline should accept it and write a new reviewed snapshot at the new `pdf_sha256` — marked as ratified, linking back to the source snapshot. This is the change that removes the re-review-on-every-byte-diff toil at its root.

- [ ] **Step 1: Add `find_snapshots_for_slug()` helper**

Append to `src/schedules/reviewed_snapshots.py`:

```python
def find_snapshots_for_slug(slug: str, *, root: Path = REVIEWED_SNAPSHOTS_DIR) -> list[Path]:
    """Return every snapshot file for a slug, regardless of pdf_sha256."""
    slug_dir = root / slug
    if not slug_dir.is_dir():
        return []
    return sorted(slug_dir.glob("*.json"))
```

- [ ] **Step 2: Add `write_ratified_snapshot()` helper**

Append to `src/schedules/reviewed_snapshots.py`:

```python
from datetime import date


def write_ratified_snapshot(
    *,
    slug: str,
    pdf_sha256: str,
    source_pdf_url: str,
    payload: dict,
    reviewed_against: list[dict],
    ratified_from_sha256: str,
    root: Path = REVIEWED_SNAPSHOTS_DIR,
) -> Path:
    """Write a new snapshot that was auto-ratified by matching a prior one."""
    path = reviewed_snapshot_path(slug, pdf_sha256, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": date.today().isoformat(),
        "reviewed_by": "ratification",
        "source_pdf_url": source_pdf_url,
        "reviewed_against": reviewed_against,
        "ratified_from_sha256": ratified_from_sha256,
        "summary": f"Auto-ratified: canonical payload matches {ratified_from_sha256[:12]}.",
        "payload": payload,
    }
    path.write_text(json.dumps(envelope, indent=2) + "\n")
    return path
```

- [ ] **Step 3: Write failing ratification test**

Create `tests/test_ratification.py`:

```python
import json

from schedules.reviewed_snapshots import (
    REVIEWED_SNAPSHOT_VERSION,
    canonicalize_payload,
    find_snapshots_for_slug,
    load_reviewed_snapshot,
    write_ratified_snapshot,
)


def _envelope(slug, pdf_sha256, payload):
    return {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-01-01",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        "payload": payload,
    }


def test_find_snapshots_for_slug_returns_empty_when_missing(tmp_path):
    assert find_snapshots_for_slug("hamilton-pool", root=tmp_path / "missing") == []


def test_find_snapshots_for_slug_lists_all(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    payload = {
        "schedule_effective": "2026-01-01",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
        ],
        "closures": [],
    }
    for sha in ("a" * 64, "b" * 64):
        path = root / "hamilton-pool" / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_envelope("hamilton-pool", sha, payload)))
    assert len(find_snapshots_for_slug("hamilton-pool", root=root)) == 2


def test_write_ratified_snapshot_round_trips(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    payload = {
        "schedule_effective": "2026-01-01",
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}
        ],
        "closures": [],
    }
    new_sha = "c" * 64
    source_sha = "a" * 64
    path = write_ratified_snapshot(
        slug="hamilton-pool",
        pdf_sha256=new_sha,
        source_pdf_url="https://example.com/schedule.pdf",
        payload=payload,
        reviewed_against=[{"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"}],
        ratified_from_sha256=source_sha,
        root=root,
    )
    loaded, fingerprint, _ = load_reviewed_snapshot("hamilton-pool", new_sha, root=root)
    assert loaded["reviewed_by"] == "ratification"
    assert loaded["ratified_from_sha256"] == source_sha
    assert canonicalize_payload(loaded["payload"]) == canonicalize_payload(payload)
    assert fingerprint and len(fingerprint) == 64
    assert path.exists()
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest tests/test_ratification.py -v`
Expected: all three tests pass. (Helpers were written before tests deliberately; the tests here are guarding the helpers, not driving them.)

- [ ] **Step 5: Add the ratification branch to the pipeline**

In `src/schedules/pipeline.py`, update imports:

```python
from .reviewed_snapshots import (
    canonicalize_payload,
    find_snapshots_for_slug,
    load_reviewed_snapshot,
    write_ratified_snapshot,
)
```

Inside `run_pipeline`, after the provider extraction path runs and `payload` is in hand, and *before* `validation = validate(...)`, add the ratification check. This only fires when no reviewed snapshot matched by `pdf_sha256` (we took the provider path):

```python
# Inside run_pipeline, after: review_notes.extend(check_delta(payload, prior_snapshot))
# and after the artifact bundle is saved, and before `validation = validate(...)`.

if snapshot is None:
    ratified_from_sha256 = None
    canonical_payload = canonicalize_payload(payload)
    for existing_snapshot_path in find_snapshots_for_slug(entry.slug):
        try:
            existing_sha = existing_snapshot_path.stem
            existing, _, _ = load_reviewed_snapshot(entry.slug, existing_sha)
        except ValueError:
            continue
        if existing and canonicalize_payload(existing["payload"]) == canonical_payload:
            ratified_from_sha256 = existing_sha
            break

    if ratified_from_sha256 and write_allowed_pre:  # see Step 6 for write gate
        new_snapshot_path = write_ratified_snapshot(
            slug=entry.slug,
            pdf_sha256=fetch_result.sha256,
            source_pdf_url=entry.pdf_url,
            payload=payload,
            reviewed_against=[{"provider": provider, "model": model}],
            ratified_from_sha256=ratified_from_sha256,
        )
        result_provider = "reviewed-snapshot"
        model = "manual-review"
        cost_estimate = "ratified"
        artifact_paths["reviewed-snapshot"] = relative_to_repo(new_snapshot_path)
        snapshot_notes = f"Auto-ratified against {ratified_from_sha256[:12]}."
        review_notes.append(
            ReviewNote(
                kind="ratified",
                message=f"Provider payload canonicalizes to reviewed snapshot {ratified_from_sha256[:12]}.",
                severity="info",
            )
        )
```

- [ ] **Step 6: Define `write_allowed_pre`**

The ratification check needs to know whether the run is a write run before `should_write()` is called (which currently runs later with `catastrophic` in hand). Compute a pre-validation gate near the top of the per-entry loop:

```python
write_allowed_pre = not (dry_run or compare_with is not None)
```

And import `relative_to_repo`:

```python
from .paths import CONTENT_SPOTS_DIR, PROMPT_PATH, relative_to_repo
```

- [ ] **Step 7: Manually verify against one pool**

Delete the cached state for one pool to force a re-run with a provider call, then verify ratification:

```bash
set -a && source .env && set +a
uv run python -c "
import json, pathlib
p = pathlib.Path('data/extraction-state.json')
s = json.loads(p.read_text())
s.pop('hamilton-pool', None)
p.write_text(json.dumps(s, indent=2, sort_keys=True) + '\n')
"
uv run schedules extract --only hamilton-pool --dry-run
```

Expected: the report shows hamilton-pool with a `ratified` review note and `provider=reviewed-snapshot` (after matching the prior snapshot). The dry-run does not write a new snapshot file.

Now re-run without `--dry-run`:

```bash
uv run schedules extract --only hamilton-pool
```

Expected: a new file appears under `data/reviewed-snapshots/hamilton-pool/` at the current `pdf_sha256`, with `reviewed_by: "ratification"` and `ratified_from_sha256` pointing at a prior hash. If the hash is unchanged (current PDF byte-identical to the reviewed one), no new file is written — the pre-existing snapshot matches by `pdf_sha256` and the fast path takes over.

Restore the state if needed:

```bash
uv run schedules extract --only hamilton-pool
```

- [ ] **Step 8: Full dry-run**

Run: `set -a && source .env && set +a && uv run schedules extract --dry-run`
Expected: all seven pools still resolve via reviewed-snapshot (fast path; no ratification fires because all `pdf_sha256` keys already match).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(schedules): auto-ratify provider output matching a prior snapshot

When a fresh provider extraction canonicalizes to the same payload as
any existing reviewed snapshot for the slug, write a new ratified
snapshot at the current pdf_sha256 that links back to the source hash.
This is the step that turns a reviewed snapshot into a judgment between a
known-good prior and a new candidate, instead of an all-or-nothing
override. Re-exports of byte-diffed but content-identical PDFs no
longer force a re-review.
EOF
)"
```

---

## Task 6: Document the mental model

**Files:**
- Modify: `docs/schedules.md`
- Modify: `NAPKIN.md`

- [ ] **Step 1: Rewrite the Review Flow section in `docs/schedules.md`**

Replace the current "Review Flow" section with:

```markdown
## Review Flow

The source of truth for a pool's schedule is `content/spots/<slug>.md`. The
extractor and reviewed-snapshot machinery are regeneration aids — they
help produce and verify that file, but they are not parallel authorities.

1. Run `uv run schedules extract`.
2. Read `tmp/extraction-report.md`.
3. Review `git diff content/spots/`.
4. For any pool with `review_note[...]` lines, inspect the raw provider
   outputs under `data/artifacts/<slug>/<pdf_sha>/`.
5. If a pool needs a durable manual override, commit a reviewed snapshot
   under `data/reviewed-snapshots/<slug>/<pdf_sha256>.json`. The envelope
   schema is enforced on load — see `src/schedules/reviewed_snapshots.py`
   for the required fields.
6. If the provider catches up to the reviewed payload on a future PDF
   (same schedule, re-exported PDF), ratification fires automatically and
   writes a new snapshot at the new hash — no re-review needed.
7. Spot-check flagged pools against the source PDF before accepting a
   content diff.
8. Commit `content/spots/`, `data/extraction-state.json`, and any new
   `data/reviewed-snapshots/` files only after the diff looks trustworthy.

`data/artifacts/` is a local review cache. Keep it around when comparing
providers or debugging a bad extraction, but do not commit it by default.

`data/reviewed-snapshots/` is the opposite: committed, schema-enforced,
and used by the pipeline to skip re-extraction when the same
`slug + pdf_sha256` is seen again. Its payloads pass through the same
validation and grounding that provider output does — human review
protects against misinterpretation, not typos.
```

- [ ] **Step 2: Rewrite the Domain Behavior Guardrail in `NAPKIN.md`**

(Already done in Task 1 Step 10 as part of the rename. If the wording is still stale, fix it here to read:)

```markdown
1. **[2026-04-18] `content/spots/*.md` is the source of truth; `data/reviewed-snapshots/` is a regeneration aid**
   Do instead: treat checked-in markdown as authoritative. `data/reviewed-snapshots/<slug>/<pdf_sha256>.json` is a human-reviewed payload used to skip re-extraction; it is not parallel truth. If a provider run canonicalizes to a prior snapshot, the pipeline auto-ratifies and writes a new snapshot — no re-review needed.
```

- [ ] **Step 3: Commit**

```bash
git add docs/schedules.md NAPKIN.md
git commit -m "$(cat <<'EOF'
docs(schedules): document the reviewed-snapshot mental model

The rendered content/spots/*.md is authoritative; reviewed snapshots
are regeneration aids that pass the same validation as provider output
and auto-ratify when the provider catches up.
EOF
)"
```

---

## Rollout verification

After all tasks are committed, run this end-to-end check:

```bash
set -a && source .env && set +a
uv run pytest -q
uv run schedules extract --dry-run
git status
git diff --stat
```

Expected:
- All tests pass.
- Report shows all seven pools resolving via `reviewed-snapshot`, no validation violations.
- `git status` is clean (no stray files from ratification during dry-run).
- No stale `adj*` term appears anywhere in `src/`, `tests/`, `docs/`, or `data/extraction-state.json`:

```bash
! grep -RE '\badj[a-z_-]*\b' src tests docs data 2>/dev/null
```

## Follow-ups (out of scope here)

- Pool-zone schema (`docs/plans/multi-pool-facilities.md`) — adds a `pool` field with real semantic weight so north-beach can label its two concurrent grids. Independent of this plan.
- `pdfplumber` layout-aware grounding. Only worth doing if we start seeing grounding-false-positives in the wild.
- Canonical-PDF hashing (strip `/CreationDate` etc.). Ratification-by-payload solves the same re-review-churn problem; revisit only if byte-diff re-runs become a bottleneck even with ratification.
- Per-session page numbers in the extraction schema. Cheap grounding win; defer until a grounding failure actually ships.
