# Local Reviewer Tool — Design (ARCHIVED)

Date: 2026-04-18
Status: **Archived 2026-04-19.** Superseded by the CLI-based reviewer spec at `docs/superpowers/specs/2026-04-19-reviewer-cli-design.md`.

## Why this was archived

This spec proposed a loopback HTTP server + Zola draft page + vanilla-JS browser UI with ETag concurrency, atomic write + rollback, read-back verification, delta-warning flow, and 14+ test files. A magi council review found 3 high-severity issues (silent drop of post-write verification, wrong `prior_sessions_count` into `validate()`, TOCTOU on concurrent saves) that were all consequences of the architectural choice to be a stateful concurrent server. The tool only has one user on one machine and is used maybe once a month — that architecture doesn't earn its complexity.

The replacement design uses: helix (with a JSON-schema-aware LSP) in one terminal pane, macOS Preview in another window, a ~80-line `schedules review` CLI that seeds drafts from existing provider artifacts and moves approved drafts into the tracked `reviewed-snapshots/` tree. No server, no browser, no queue file — the filesystem is the state machine.

---

Depends on: `2026-04-18-pdf-layout-and-vocabulary-migration-design.md` (lands first).

## Purpose

Give one developer a fast, local, browser-based way to manually correct extracted pool-schedule data against the source PDF. Produces checked-in `(PDF, per-provider LLM outputs, reviewed truth)` triples that seed a future eval system used to improve the extraction pipeline.

## Non-goals (v1)

- Any code that ships in the Worker or the published Zola site.
- Month-calendar projection of recurring sessions. Week grid only.
- Multi-pool editing on one screen.
- Price fields beyond the existing `cost` enum.
- Drag/resize calendar library. CSS-only grid first.
- Automatic extraction re-run on save.
- Per-session `~changed` detection in the provider-diff panel (no stable session ID; added/removed only).

## Architecture overview

Three cooperating pieces:

1. **Zola draft page** at `content/_admin/review.md` (`draft = true`). Rendered by `zola serve --drafts` during local use; excluded automatically from `zola build`. Provides the UI (HTML + vanilla ES-module JS).
2. **Local review server** — a ~150-LOC Python stdlib module (`src/schedules/review_server.py`) built on `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`. Binds `127.0.0.1` only. Exposes JSON endpoints that serve reads, validate writes, and project the reviewed data to both `reviewed-snapshots` and `content/spots/<slug>.md` using a new `review_project.py` helper (adjacent to `merge.py`). **All disk I/O — both reads and writes — flows through this server.** The browser never touches disk.
3. **Launch**: a single `devenv up admin` process group starts both `zola serve --drafts :1111` and `schedules review :4317`. Developers run one command in one terminal.

No Flask, no FastAPI, no Node at runtime, no build step. Only stdlib Python on the server and hand-written ES modules on the client.

### devenv integration

Add to `devenv.nix`:

- A new `admin` process group (a second, distinct value passed to `devenv up`). Members:
  - `zola serve --drafts --interface 127.0.0.1 --port 1111`
  - `uv run schedules review --host 127.0.0.1 --port 4317`
- Leave the existing default process group (zola build + wrangler) unchanged — production-parity previewing stays clean.
- Add `devenv.scripts` entries for common one-shot commands that today require manual env-sourcing (see NAPKIN: `schedules` CLI does not autoload `.env`). Initial set:
  - `extract` → `set -a && source .env && set +a && uv run schedules extract "$@"`
  - `bakeoff` → `set -a && source .env && set +a && uv run schedules debug bakeoff "$@"`
  - `project` → `uv run schedules project "$@"`
  - `migrate-pdf-layout` → `uv run python scripts/migrate_pdf_layout.py`

NAPKIN's first-item "use `devenv up`" rule still holds; this spec just adds a second process group alongside the default.

## Isolation guarantees

- `draft = true` keeps the page out of `zola build`. `config.toml:build_search_index = false` means no search-index leak.
- `tests/test_reviewer_isolation.py` reuses the `zola build` fixture from `tests/test_site_render.py` and asserts no file under `public/` contains any of: `_admin`, `/review/`, `review_server`.
- `review_server.py` imports nothing from `worker/` and is never imported by `pipeline.py` or `cli.py`'s production-path commands. A unit test verifies the import graph.
- The review server binds to `127.0.0.1` explicitly — not `0.0.0.0`. This is the real security boundary.
- CORS allow-list is a loopback regex: `^https?://(127\.0\.0\.1|localhost)(:\d+)?$`. Origin is reflected back in `Access-Control-Allow-Origin`. Zola port falling back from 1111 to 1112 does not break the tool. Chrome's Private Network Access does not preflight loopback-to-loopback, so standard CORS suffices.
- No `SWIMFRANCISCO_REVIEW_ALLOW` env flag. The loopback bind + CLI entry point is the control. Belt-and-suspenders env gates on the same process are theater.

## Data flow

```
            Zola :1111                            Python :4317
 ┌─────────────────────────────┐      ┌────────────────────────────────┐
 │ /_admin/review/             │──────▶│ GET  /pools             (list) │
 │   roster + pool page        │      │ GET  /pools/<slug>      (bundle)│
 │   week grid + PDF pane      │      │ GET  /pdfs/<slug>/<fn>  (binary)│
 │   provider-diff summary     │      │ GET  /artifacts/<slug>/<hash>/…│
 │                             │◀─────│ POST /pools/<slug>/save        │
 └─────────────────────────────┘      └────────────────────────────────┘
                                                   │
                                                   ▼
                                   content/spots/<slug>.md
                                   data/reviewed-snapshots/<slug>/<date>-<hash>.json
```

The browser issues fetches to `http://127.0.0.1:4317/...`; Zola only serves static HTML + JS. Every byte of schedule data crosses the Python process.

### Reads

- `GET /pools` → `[{slug, latest_pdf: {date, hash_prefix, rel_path}, latest_reviewed: {date, hash_prefix, rel_path, etag}, pending_review}, …]`.
- `GET /pools/<slug>` → `{metadata, sessions, closures, pdf: {rel_path, page_hints}, artifacts: [...], etag}`.
  - `metadata` is the parsed TOML frontmatter dict of `content/spots/<slug>.md`.
  - `sessions` + `closures` come from the latest reviewed snapshot if present, else from an extractor artifact if present, else empty.
  - `etag` is sha256 of `(content/spots/<slug>.md bytes || latest reviewed snapshot bytes)` — used for stale-save detection.
  - `artifacts` is the per-provider diff summary (see below).
  - `page_hints` read from `data/reviewed-snapshots/<slug>/<date>-<prefix>.pages.json` if present; `null` if absent.
- `GET /pdfs/<slug>/<filename>` → streams PDF bytes. Path guard: slug must match `^[a-z0-9][a-z0-9-]*$`, filename must match `^\d{4}-\d{2}-\d{2}-[0-9a-f]{12}\.pdf$`, and the resolved path must be inside `data/pdfs/<slug>/` (no traversal).
- `GET /artifacts/<slug>/<hash>/<provider>.json` → file if present, 404 if absent. Fresh-clone empty state handled client-side.

### Provider-diff panel (added / removed only)

Sessions and closures are compared as multisets using the full canonical tuple. For sessions the tuple is `(day, type, start, end, pool)` — exactly `_SESSION_COMPARE_KEYS` from `reviewed_snapshots.py`. For closures: `(start, end, reason)`. No `~changed` category. The panel reports:

```json
{
  "anthropic": { "sessions": { "added": [...], "removed": [...] },
                 "closures": { "added": [...], "removed": [...] } },
  "gemini":    { ... }
}
```

### Write (POST /pools/<slug>/save)

Request body:

```json
{
  "etag": "sha256hex...",
  "metadata": {
    "title": "...",
    "subtype": "indoor",
    "website": "...",
    "schedule_effective": "2026-03-17",
    "schedule_effective_end": "2026-06-06"
  },
  "sessions": [ {"day": "tuesday", "type": "lap_swim", "start": "07:00", "end": "08:00"}, ... ],
  "closures": [ {"start": "2026-03-19", "end": "2026-03-19", "reason": "In Service Training"}, ... ],
  "summary":  "Shortened Tuesday afternoon to end at 15:30.",
  "fully_verified": false,
  "save_anyway": false
}
```

Server pipeline (all-or-nothing, in order):

1. **Stale-save check**: recompute current etag from disk. If it differs from the request's etag, return **409 Conflict** with the current state. Client must re-read and merge.
2. **Bind context**: resolve `latest_pdf(slug)` → `pdf_sha256` (full 64-char), today's date in Pacific via `nowInPacific()`-equivalent in Python (`ZoneInfo("America/Los_Angeles")`).
3. **Capture rollback state**: for both `content/spots/<slug>.md` and `data/reviewed-snapshots/<slug>/<date>-<prefix>.json`, read current bytes into memory if the file exists; record `(exists: bool, bytes: bytes | None)` for each. This is the restore source if step 7 fails.
4. **Validate**: `validate.validate()` — catastrophic-zero, ≥5 sessions, session time ranges, closure date ranges, required metadata. Any violation → 422 with the violations list and no writes.
5. **Delta check**: `delta.check_delta()` against the prior reviewed snapshot. >20% session swing or disappearing types produce **warnings**. If any warning and `save_anyway` is false, return **200 with `{warnings: [...], written: false}`** — client must re-submit with `save_anyway: true`. First-time save has no prior; delta skipped. Also runs a first-save sanity check: sessions ≥ 5 and every enum type valid (already enforced by validate, kept here as a named assertion).
6. **Atomic write, both files**:
   - For each of `<snapshot_path>` and `<md_path>`:
     - Open `tempfile.NamedTemporaryFile(dir=target.parent, delete=False, mode="wb")`.
     - Write content (snapshot = reviewed JSON envelope, md = `review_project.project(...)` output — see below).
     - `f.flush(); os.fsync(f.fileno()); f.close()`.
     - `os.replace(tmp.name, target)`.
   - Write snapshot **before** MD. If the process crashes between the two replaces, the snapshot is updated and the MD is not — loud divergence surfaced on the next pipeline run, not silent data loss of authoritative MD state.
7. **Read back from disk** and re-parse both files. Verify:
   - snapshot payload's sessions/closures/schedule_effective equal the projected MD's sessions/closures/schedule_effective.
   - metadata fields (`title`, `subtype`, `website`, `schedule_effective`, `schedule_effective_end`) match what was sent.
   - If `fully_verified: true`, MD's `last_verified_at` equals today's Pacific date.
8. **On any mismatch at step 7, restore both files** from the rollback state captured at step 3:
   - If the previous `(exists, bytes)` had `exists=False`, `os.unlink(target)`.
   - Else write `bytes` back via the same tempfile + `os.replace` dance.
   - Return **500** with a diff.
9. **Success response**: `{ ok: true, reviewed_path, md_path, warnings: [...], new_etag }`.

### `last_verified_at` semantics

The spec explicitly does NOT auto-bump `last_verified_at` on every save. That field's contract, per `docs/plans/schedules.md:254`, is "human has verified this data against the current PDF." Auto-bumping on partial/checkpoint saves would poison freshness history.

Instead:

- The save bar has a checkbox: **☐ I have verified this against the PDF**.
- Checkbox sends `fully_verified: true`. Server bumps `last_verified_at` to today's Pacific date during projection.
- Checkbox unchecked (default): `last_verified_at` in the MD stays at whatever it was. Sessions/closures/metadata still save.

The roster view shows the current `last_verified_at` per pool so the reviewer sees which pools are behind.

### `review_project.py`

New module adjacent to `merge.py`. `merge.py`'s `merge()` only projects `extra.sessions`, `extra.closures`, `extra.schedule_effective`, `extra.schedule_effective_end`. The reviewer also needs to project metadata fields and (conditionally) `last_verified_at`. Rather than overload `merge.merge()`, add:

```python
def project(
    pool_md_path: Path,
    *,
    metadata: dict,            # title, subtype, website, schedule_effective, schedule_effective_end
    sessions: list[dict],
    closures: list[dict],
    last_verified_at: str | None,  # None = don't touch the existing value
) -> bytes:                    # returns the new file contents as bytes (caller does atomic write)
```

Uses the same `tomlkit.parse` + `extra.setdefault` pattern as `merge.merge()`. Explicitly sets each metadata key when present. Leaves any non-managed keys and all comments untouched.

**tomlkit comment-preservation invariant** (stated here so future edits don't violate it):

- **Preserved**: comments that appear before `[extra]`, between `[extra]` and its first key, between keys within `[extra]`, and before/after managed arrays-of-tables like `[[extra.sessions]]` and `[[extra.closures]]`.
- **Not preserved**: comments that appear *inside* a managed `[[extra.sessions]]` or `[[extra.closures]]` block (tomlkit re-emits these arrays when replaced).

All 7 current spot MDs fit the preserved pattern (comments at lines 16–17 sit before `schedule_effective_end`, outside any AoT). A test enforces the invariant (see Testing).

## UI

Single Zola-built page under `content/_admin/review/`:

- `/_admin/review/` — roster.
- `/_admin/review/pool/?slug=<slug>` — editor (query string keeps the page count at 2, static).

### Roster

- Banner showing review-server health (`GET http://127.0.0.1:4317/health`). If unreachable: "Run `devenv up admin` in a terminal."
- Table: slug, `last_verified_at`, latest reviewed date, latest PDF date, pending flag (PDF hash prefix ≠ reviewed hash prefix), open-link.

### Pool page

```
┌──────────────────────────────────────────────────────────────────────┐
│  [slug]   title  subtype  website  schedule_effective  …            │
├────────────────────────────┬─────────────────────────────────────────┤
│ Week grid                  │                                         │
│  Mon Tue Wed Thu Fri Sat Sun│     PDF                                │
│  [sessions as blocks]      │     <embed src="/pdfs/<slug>/…">        │
│                            │     [page-jump buttons if sidecar]      │
├────────────────────────────┤                                         │
│ Closures                   │                                         │
│  date range   reason   [x] │                                         │
│  [+ add closure]           │                                         │
├────────────────────────────┤                                         │
│ Provider diff              │                                         │
│  anthropic  +2 added -1 removed                                     │
│  gemini     +0 added -0 removed                                     │
├────────────────────────────┴─────────────────────────────────────────┤
│ ☐ I have verified this against the PDF                              │
│ [save]  [discard]   warnings: 0   last_verified_at: 2026-04-17      │
└──────────────────────────────────────────────────────────────────────┘
```

- **Metadata strip**: inline-editable `title`, `subtype`, `website`, `schedule_effective`, `schedule_effective_end`. Current `last_verified_at` is displayed next to the save bar; auto-bumps only when the verification checkbox is checked.
- **Week grid**: 7 columns × hourly rows, 06:00–22:00. Sessions as absolutely-positioned colored blocks. Click empty cell → create modal (day, type, start, end). Click block → edit modal. Types: `lap_swim`, `family_swim`, `senior_swim`, `lessons`.
- **Closures**: list of `{start, end, reason}` rows.
- **PDF pane**: `<embed>` of the current PDF. Page-jump buttons if `pages.json` sidecar exists (optional; absent is fine).
- **Provider diff**: per-provider `added` / `removed` counts; click to expand to the differing tuples. Empty state: "No local LLM artifacts for this PDF — run `devenv run extract --only <slug>` to populate."
- **Save bar**: verification checkbox, save/discard buttons, warnings count, current `last_verified_at`, a "save anyway (ignore delta warnings)" toggle that appears when warnings come back.

### Stale-save UX

When save returns 409: show an inline notice ("the data changed since you loaded it — reload to see the latest state") with a Reload button. No automatic clobber.

### Client module structure

```
static/js/review/
  index.mjs        # roster controller
  pool.mjs         # pool page controller; owns etag
  api.mjs          # thin fetch wrappers, 409 handling
  schema.mjs       # shared enums + shape validators (mirrors src/schedules/schema.py)
  grid.mjs         # week grid render + create/edit modals
  closures.mjs     # closures list
  pdf.mjs          # PDF pane + page-jump
  diff.mjs         # provider-diff panel (pure added/removed rendering)
  store.mjs        # in-memory editor state; no persistence
  time.mjs         # re-exports nowInPacific() from board.mjs
```

No TOML code in the browser. No File System Access API. No vendored JS libraries.

## Server module structure

```
src/schedules/review_server.py        # ~150 LOC: handler, routes, graceful shutdown
src/schedules/review_project.py       # ~80 LOC: TOML projection via tomlkit (adjacent to merge.py)
src/schedules/cli.py                  # + `schedules review` subcommand, + `schedules project` subcommand
```

### ThreadingHTTPServer configuration

Required knobs, explicit in code:

```python
class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True          # Ctrl+C does not hang on live browser tabs
    allow_reuse_address = True     # default on HTTPServer; made explicit for clarity
    block_on_close = False         # don't wait for in-flight requests on shutdown
```

`schedules review` sets a `SIGINT` + `SIGTERM` handler that calls `server.shutdown()` from a separate thread and exits cleanly.

`schedules project <slug>` — standalone CLI that runs the same projection pipeline without the server, useful for regenerating MDs from an externally-edited reviewed snapshot. Reuses `review_project.project()`.

## Testing

### Python unit

- `tests/test_review_server_routes.py` — each endpoint: happy path, 404, bad method, bad path.
- `tests/test_review_save_pipeline.py` — end-to-end save: valid payload writes both files; payload that fails validate → 422 + no writes; delta warning → 200 with `written=false`; `save_anyway=true` writes; read-back mismatch triggers rollback to original state.
- `tests/test_review_etag.py` — stale etag returns 409; freshly-fetched etag succeeds.
- `tests/test_review_rollback.py` — inject a read-back mismatch mid-pipeline; verify both files restored to exact prior bytes; verify snapshot file unlinked when it didn't exist before.
- `tests/test_review_concurrent.py` — two POSTs with the same starting etag, serial execution; second one 409s.
- `tests/test_review_validate.py` — invalid payloads return 422 with correct violations.
- `tests/test_review_delta.py` — >20% swing, disappearing types, `save_anyway` flow, first-save branch.
- `tests/test_review_project.py` — projection preserves all comments and non-managed keys in every `content/spots/*.md`. Fixtures diff against real files. Includes a negative test for the inter-AoT-comment invariant (synthetic fixture with a comment inside `[[extra.sessions]]` is expected to lose the comment — the test documents the limitation).
- `tests/test_review_metadata.py` — `last_verified_at` only bumps when `fully_verified=true`; other metadata edits always persist.
- `tests/test_review_pacific_midnight.py` — date boundary: request at 23:59 PT then 00:01 PT + 1d produces correct `reviewed_at` / `last_verified_at` values.
- `tests/test_review_corrupt_frontmatter.py` — spot MD with malformed TOML: reads/writes return a loud error, not silent corruption.
- `tests/test_review_missing_pdf.py` — `GET /pdfs/...` for an absent file returns 404 cleanly.
- `tests/test_review_disk_full.py` — simulate `OSError` on the second `os.replace`; verify rollback restores the first file.
- `tests/test_review_cors.py` — origins matching the loopback regex pass; anything else is denied.
- `tests/test_reviewer_isolation.py` — `zola build` in tmp dir; no admin leakage.
- `tests/test_review_import_graph.py` — `review_server` and `review_project` are not imported from `worker/`, `pipeline.py`, or production-path `cli.py` commands.

### JS (Node via devenv)

- `tests/js/test_schema.mjs` — shared shape checks match Python.
- `tests/js/test_grid.mjs` — grid renders N sessions correctly; conflict detection; time-range edits.
- `tests/js/test_diff.mjs` — added/removed counts correct for canned inputs; no `~changed` regression.
- `tests/js/test_409.mjs` — stale-save UX.

### Manual smoke test

1. `devenv up admin`
2. Open `http://127.0.0.1:1111/_admin/review/` in any browser.
3. Pick a pool. Shift a session by 15 minutes. Leave verification checkbox unchecked. Save.
4. Verify: `content/spots/<slug>.md` updated, reviewed snapshot updated, `last_verified_at` UNCHANGED.
5. Check the verification checkbox. Save again. Verify `last_verified_at` now bumped to today (Pacific).
6. Revert the edit. Save. Confirm files revert, comments preserved.
7. Stop the admin process group; `devenv up` (default); `zola build`; confirm `public/` has no `_admin`.

## Rollout sequence

Two PRs.

**PR 1**: `review_project.py` + `schedules project <slug>` CLI. Covered by projection + metadata tests. Usable immediately (regenerate MD from a reviewed snapshot). No UI dependency.

**PR 2**: `review_server.py` + `schedules review` CLI + Zola draft page + all client JS + devenv `admin` process group + `devenv.scripts` entries + all remaining tests. Ships together — the server is dead code without the page and vice versa.

Within PR 2, commits can be broken up (roster → week grid → closures → PDF pane → provider diff → save pipeline → rollback/etag → tests) for review ergonomics, but none land on `main` before the full feature.

## Open questions (deferred; not blockers)

- Whether future eval scoring considers per-session grounding (`evidence` + page hints). Current schema carries these; no change needed today.
- Whether the reviewer should eventually become the sole write path for `content/spots/*.md`. For v1, Helix hand-edits remain first-class; the server re-reads MD on each `GET /pools/<slug>`.
- `pages.json` sidecar generation — pipeline-side work; UI degrades gracefully when absent.

## Risks

- **tomlkit inter-AoT comment loss**: documented invariant + projection test. If a future spot MD puts a comment inside `[[extra.sessions]]`, the test fails before merge.
- **Delta warning fatigue**: >20% swings are common during initial review. `save_anyway` toggle mitigates; thresholds can soften later with real usage data.
- **Stale-save handling on refresh**: 409 shows a reload prompt. User must manually re-apply any in-flight edits — this is correct conservative behavior for a single-user tool; multi-tab work is not v1's use case.
- **Cross-file divergence on process crash between the two `os.replace` calls**: bounded. Snapshot-before-MD ordering means the repo never loses authoritative MD state. Divergence is loud on the next pipeline run.
- **Pacific-midnight date rollover during a long save**: captured once at request entry, used consistently throughout the request. Test enforces.
