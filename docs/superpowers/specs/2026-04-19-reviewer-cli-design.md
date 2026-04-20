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
- No pipeline changes — artifacts already exist
- No queue file — the filesystem is the queue

## Architecture

**The filesystem is the state machine.** Three directories encode everything:

```
data/
├── artifacts/                             # git-tracked, pipeline writes (already exists)
│   └── <slug>/<pdf-hash>/<provider>-<model>.json
├── reviewed-snapshots/                    # git-tracked, reviewer approves (already exists)
│   └── <slug>/<reviewed_at>-<prefix>.json
└── reviewed-snapshot-drafts/              # gitignored, ephemeral WIP
    └── <slug>/<reviewed_at>-<prefix>.json
```

**Review-status detector:** for each `(slug, hash)` under `data/artifacts/`, check whether any `data/reviewed-snapshots/<slug>/*.json` has `pdf_sha256 == hash`. If not → needs review. PDF changed → new hash → new artifact dir → no matching snapshot → automatically re-enters the queue.

**Review order:** ascending by the date prefix embedded in the cached PDF filename (`data/pdfs/<slug>/<date>-<prefix>.pdf`), oldest first. Ties broken by slug alphabetically.

**Draft seeding:** on first `schedules review` for a `(slug, hash)` pair, wrap a chosen provider artifact in the reviewed-snapshot envelope (adding `slug`, `pdf_sha256`, `reviewed_at=today_pacific`, `source_pdf_url`, `reviewed_against` roster, `summary="(draft)"`, `payload` from artifact) and write it to the draft tree. Provider preference: gemini → openai → whatever's latest by mtime.

**Finalization:** editor exit → reload draft → schema-validate → `schedules validate` invariants → run `schedules project <slug>` → `os.rename` draft into the reviewed-snapshots tree at `<slug>/<reviewed_at>-<pdf_sha256[:12]>.json` (filename derived from envelope contents, not from the draft filename, so a stale draft picks up the current `reviewed_at`). Any failure leaves the draft in place and exits nonzero with the reason.

Pools only reach the review queue because auto-ratification refused them (grounding flagged something, validate failed, or extraction failed). So a seeded draft usually needs real edits before it validates. If a draft happens to be validate-clean already (e.g., validate passed but grounding didn't), exiting the editor without changes IS a legitimate "reviewer confirms" no-op approval — and the spec accepts that.

## CLI surface

### `schedules review [--slug <slug>]`

1. Scan for the next review candidate (oldest-PDF-first, or the provided `--slug`).
2. If no candidate → print "nothing to review" and exit 0.
3. If a draft already exists for the candidate, resume it; else seed a fresh one from the chosen artifact.
4. `subprocess.run(["open", pdf_path])` — non-blocking; Preview opens in its own window.
5. `subprocess.run([$EDITOR or "hx", draft_path])` — blocking; returns when editor exits.
6. Reload draft and:
   - If JSON is malformed → print location, leave draft, exit nonzero.
   - If schema-invalid → print violations, leave draft, exit nonzero.
   - If `validate(payload)` fails → print violations, leave draft, exit nonzero.
   - Else → run `project(slug)`, `os.rename` draft into reviewed-snapshots tree, print success, exit 0.

### `schedules project <slug>`

1. Load the latest reviewed snapshot for `slug` (rejects if file is still in the draft tree).
2. Canonicalize the payload (existing `canonicalize_payload`; strips evidence/notes, sorts).
3. Re-validate canonicalized payload.
4. Project into `content/spots/<slug>.md` via tomlkit round-trip (mirrors the pattern in `src/schedules/merge.py`).
5. Atomic write via `os.replace`.

## Failure modes & edge cases

| Scenario | Behavior |
|---|---|
| Editor exits without saving | Validate runs anyway. Usually fails (drafts enter the queue because auto-ratify refused them), draft stays. If it happens to pass, the reviewer approved-by-inaction — acceptable. |
| Pool has no published PDF (e.g. `mission-community-pool`) | No artifact ever written → never appears in the review queue. |
| Reviewer edits but leaves JSON malformed | Validate fails, draft stays; reviewer re-runs `schedules review` to resume |
| Reviewer forgets to bump `reviewed_at` | Field is required by schema and set by the seeder to today; stale date is a reviewer judgment call, not a correctness issue |
| Two concurrent `schedules review` invocations | Both may rename the same path; `os.rename` is atomic, last-write-wins. Acceptable for single-user. |
| Crash between schema-validate and `os.rename` | Draft still in place; re-run resumes cleanly |
| Provider artifact missing (deleted by hand) | Pipeline invariant violated; `schedules review` prints a clear error naming the missing path and exits. No silent fallback. |
| Reviewer deletes a reviewed snapshot | `(slug, hash)` re-enters the queue; draft seeded afresh |
| `open` command absent (non-macOS dev) | Print a warning with the PDF path and continue — reviewer opens it manually |

## Contracts

- **Draft envelope must be schema-valid after editing.** The pipeline seeds a schema-valid envelope, and the schema permits the raw provider shape. If the reviewer breaks it, finalize fails loudly.
- **`os.rename` is atomic across `data/reviewed-snapshot-drafts/` and `data/reviewed-snapshots/`.** Enforced by both trees living on the same filesystem (same `data/` parent).
- **`schedules project` never writes a spot .md from a draft.** Guarded by path check at the start of `project()`.
- **Finalization is all-or-nothing per pool.** Validate, project, and rename all succeed, or the draft stays untouched.

## Open questions (intentionally deferred)

None blocking. Candidates for later:
- Bulk-review mode (`schedules review --all` auto-advancing on success) — wait until we know the single-pool flow is ergonomic.
- Preferred-provider as a config knob — hardcode `gemini → openai → latest` for now.
- Abandoned-draft GC — rely on manual `rm` until it becomes annoying.

## What this costs

- New code: ~160 lines across `src/schedules/review.py` + `src/schedules/project.py` + two CLI hooks in `cli.py`
- New tests: ~6 test files (`test_review_seed.py`, `test_review_finalize.py`, `test_review_scan.py`, `test_project.py`, + integration)
- Documentation: update `docs/schedules.md` with the review workflow; add `.gitignore` entry
- Devenv: nothing new (`vscode-langservers-extracted` already landed)

## Dependencies already shipped

- `data/reviewed-snapshots/schema.json` — JSON Schema draft 2020-12, validated against all 7 current snapshots
- `devenv.nix` — `vscode-langservers-extracted` provides `vscode-json-language-server` for editor-side autocomplete
- `data/pdfs/<slug>/<date>-<prefix>.pdf` layout — date-prefix ordering enables the review queue
- `src/schedules/reviewed_snapshots.py` — `load_reviewed_snapshot_from_path`, `reviewed_snapshot_path`, `find_snapshots_for_slug`, `canonicalize_payload`, `REVIEWED_SNAPSHOT_VERSION`
- `src/schedules/merge.py` — tomlkit round-trip pattern to mirror in `project.py`
- `src/schedules/validate.py` — catastrophic-zero + ≥5-sessions invariants
- `src/schedules/cli.py` — Click CLI to extend with `review` and `project` subcommands
