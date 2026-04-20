# Reviewer CLI — Design

Date: 2026-04-19
Status: Draft for review
Supersedes: `docs/superpowers/specs/archived/2026-04-18-local-reviewer-design.md`

## Purpose

Let a single developer approve pipeline-extracted pool schedules by editing JSON next to the source PDF. Each approval produces a checked-in `(PDF, per-provider LLM outputs, reviewed truth)` triple, seeding a future eval system for extraction-pipeline improvements.

## Non-goals

- No web UI, no HTTP server, no browser
- No multi-user coordination (ETag, locks, concurrency control)
- No read-back verification or rollback (`os.rename` is atomic; `pytest` is the safety net)
- No pipeline changes — the extraction side already writes `data/artifacts/<slug>/<hash>/<provider>-<model>.json`; reviewer is a pure consumer
- No queue file — the filesystem is the queue

## Architecture

**The filesystem is the state machine for review.** Three directories encode everything the reviewer CLI cares about:

```
data/
├── artifacts/                             # gitignored, produced by `schedules extract`
│   └── <slug>/<pdf-hash>/<provider>-<model>.json
├── reviewed-snapshots/                    # git-tracked, reviewer approves (exists today)
│   └── <slug>/<reviewed_at>-<prefix>.json
└── reviewed-snapshot-drafts/              # gitignored, ephemeral WIP
    └── <slug>/<reviewed_at>-<prefix>.json
```

`data/artifacts/` is in `.gitignore` and is only created once `schedules extract` has been run locally. A clean checkout has no artifacts → an empty review queue is the expected initial state, not an error. `schedules review` prints "nothing to review (run `schedules extract` first?)" when it finds no artifact directories.

`data/extraction-state.json` is the pipeline's own checkpoint log (which providers ran, last extraction time, grounding stats). It is **not** consulted by the reviewer CLI — the reviewer trusts only the filesystem layout above. If extraction-state.json disagrees with the on-disk snapshots (e.g. state file stale), the filesystem wins. This keeps the reviewer's state model single-sourced; the pipeline can continue to use extraction-state.json for its own purposes.

**Review-status detector:** for each `(slug, hash)` under `data/artifacts/`, check whether any `data/reviewed-snapshots/<slug>/*.json` has `pdf_sha256 == hash`. If not → needs review. PDF changed → new hash → new artifact dir → no matching snapshot → automatically re-enters the queue.

**Review order:** ascending by the date prefix embedded in the cached PDF filename (`data/pdfs/<slug>/<date>-<prefix>.pdf`), oldest first. Ties broken by slug alphabetically.

**Draft seeding:** on first `schedules review` for a `(slug, hash)` pair, wrap a chosen provider artifact in the reviewed-snapshot envelope (adding `slug`, `pdf_sha256`, `reviewed_at=today_pacific`, `source_pdf_url`, `reviewed_against` roster, `summary="(draft)"`, `payload` from artifact) and write it to the draft tree. Provider preference: gemini → anthropic → whatever's latest by mtime. (Only those two providers ship today; the mtime fallback handles future additions without a spec change.)

**Finalization order (commit before project).** The snapshot rename is the commit point; `project()` runs after and is idempotent:

1. Editor exits.
2. Reload draft. Schema-validate. Run `schedules validate` invariants.
3. Compute destination `<slug>/<reviewed_at>-<pdf_sha256[:12]>.json`. If it already exists, abort — reviewer resolves manually.
4. `os.rename` draft → reviewed-snapshots. **This is the commit.**
5. Run `schedules project <slug>` against the committed snapshot. On failure (tomlkit error, disk full), re-running `schedules project <slug>` finishes the job.

Pools only reach the review queue because auto-ratification refused them (grounding flagged something, validate failed, or extraction failed). So a seeded draft usually needs real edits before it validates. If a draft happens to be validate-clean already (e.g., validate passed but grounding didn't), exiting the editor without changes IS a legitimate "reviewer confirms" no-op approval — and the spec accepts that.

## CLI surface

### `schedules review [--slug <slug>]`

1. Scan for the next review candidate (oldest-PDF-first, or the provided `--slug`).
2. If no candidate → print "nothing to review" (with the "run `schedules extract` first?" hint if `data/artifacts/` is missing) and exit 0.
3. If a draft already exists for the candidate, resume it; else seed a fresh one from the chosen artifact.
4. `subprocess.run(["open", pdf_path])` — non-blocking; Preview opens in its own window.
5. `subprocess.run([$EDITOR or "hx", draft_path])` — blocking; returns when editor exits.
6. Reload draft and, in order:
   - If JSON is malformed → print location, leave draft, exit nonzero.
   - If schema-invalid → print violations, leave draft, exit nonzero.
   - If `validate(payload)` fails → print violations, leave draft, exit nonzero.
   - If destination `<slug>/<reviewed_at>-<pdf_sha256[:12]>.json` already exists → print the conflict, leave draft, exit nonzero.
   - Else → `os.rename` draft into reviewed-snapshots tree (**commit point**), then run `project(slug)`, print success, exit 0.

### `schedules project <slug>`

1. Load the latest reviewed snapshot for `slug` (rejects if file is still in the draft tree).
2. Canonicalize the payload (existing `canonicalize_payload`; strips evidence/notes, sorts).
3. Re-validate canonicalized payload.
4. Project into `content/spots/<slug>.md` via tomlkit round-trip (mirrors the pattern in `src/schedules/merge.py`, including its plain `write_text`).

## Failure modes & edge cases

| Scenario | Behavior |
|---|---|
| Editor exits without saving | Validate runs anyway. Usually fails (drafts enter the queue because auto-ratify refused them), draft stays. If it happens to pass, the reviewer approved-by-inaction — acceptable. |
| Pool has no published PDF (e.g. `mission-community-pool`) | No artifact ever written → never appears in the review queue. |
| Reviewer edits but leaves JSON malformed | Validate fails, draft stays; reviewer re-runs `schedules review` to resume |
| Reviewer forgets to bump `reviewed_at` | Field is required by schema and set by the seeder to today; stale date is a reviewer judgment call, not a correctness issue |
| Two concurrent `schedules review` invocations | Both may rename the same path; `os.rename` is atomic, last-write-wins. Acceptable for single-user. |
| Destination snapshot already exists (stale draft, or reviewer re-ran after the snapshot was written by ratification) | Finalize aborts with a clear error; reviewer resolves by `rm` of either the stale draft or the conflicting snapshot |
| Crash between schema-validate and `os.rename` | Draft still in place; re-run resumes cleanly |
| Crash between `os.rename` and `project()` | Snapshot is committed; re-running `schedules project <slug>` updates the MD. Idempotent. |
| Provider artifact missing (deleted by hand) | Pipeline invariant violated; `schedules review` prints a clear error naming the missing path and exits. No silent fallback. |
| Reviewer deletes a reviewed snapshot | `(slug, hash)` re-enters the queue; draft seeded afresh |
| `open` command absent (non-macOS dev) | Print a warning with the PDF path and continue — reviewer opens it manually |

## Contracts

- **Draft envelope must be schema-valid after editing.** The pipeline seeds a schema-valid envelope, and the schema permits the raw provider shape. If the reviewer breaks it, finalize fails loudly.
- **`os.rename` is atomic across `data/reviewed-snapshot-drafts/` and `data/reviewed-snapshots/`.** Enforced by both trees living on the same filesystem (same `data/` parent).
- **`schedules project` never writes a spot .md from a draft.** Guarded by path check at the start of `project()`.
- **The reviewed snapshot is the commit point; `content/spots/<slug>.md` is a pure derivation.** Re-running `schedules project <slug>` is idempotent and always safe.

## Schema compatibility

Before shipping: extend `data/reviewed-snapshots/schema.json` with optional `reviewed_by` (string) and `ratified_from_sha256` (string, 64 hex chars) fields. The ratification writer (`reviewed_snapshots.py:148-174`) already emits these, and the schema's `additionalProperties: false` would otherwise reject them. Re-validate all existing snapshots after the schema update.

## Open questions (intentionally deferred)

None blocking. Candidates for later:
- Bulk-review mode (`schedules review --all` auto-advancing on success) — wait until we know the single-pool flow is ergonomic.
- Preferred-provider as a config knob — hardcode `gemini → anthropic → latest` for now.
- Abandoned-draft GC — rely on manual `rm` until it becomes annoying.

## What this costs

- New code: ~160 lines across `src/schedules/review.py` + `src/schedules/project.py` + two CLI hooks in `cli.py`
- Schema update: extend `data/reviewed-snapshots/schema.json` with `reviewed_by` and `ratified_from_sha256` optional fields; re-validate existing snapshots
- New tests: ~6 test files (`test_review_seed.py`, `test_review_finalize.py`, `test_review_scan.py`, `test_project.py`, + integration)
- Documentation: update `docs/schedules.md` with the review workflow; add `data/reviewed-snapshot-drafts/` to `.gitignore`
- Devenv: nothing new (`vscode-langservers-extracted` already landed)

## Dependencies already shipped

- `data/reviewed-snapshots/schema.json` — JSON Schema draft 2020-12, validated against all 7 current snapshots
- `devenv.nix` — `vscode-langservers-extracted` provides `vscode-json-language-server` for editor-side autocomplete
- `data/pdfs/<slug>/<date>-<prefix>.pdf` layout — date-prefix ordering enables the review queue
- `src/schedules/reviewed_snapshots.py` — `load_reviewed_snapshot_from_path`, `reviewed_snapshot_path`, `find_snapshots_for_slug`, `canonicalize_payload`, `REVIEWED_SNAPSHOT_VERSION`
- `src/schedules/merge.py` — tomlkit round-trip pattern to mirror in `project.py`
- `src/schedules/validate.py` — catastrophic-zero + ≥5-sessions invariants
- `src/schedules/cli.py` — Click CLI to extend with `review` and `project` subcommands
