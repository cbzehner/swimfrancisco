# Local Reviewer Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-developer, browser-based review tool that lets the reviewer correct extracted pool-schedule data against the source PDF, writing checked-in `(PDF, per-provider LLM outputs, reviewed truth)` triples.

**Architecture:** Three cooperating pieces — a Zola draft page (`content/_admin/review.md`), a ~150-LOC Python stdlib HTTP server (`src/schedules/review_server.py`) that owns all disk I/O and binds to `127.0.0.1:4317`, and a `devenv up admin` process group that launches both. A separate `review_project.py` module projects reviewed data into both `reviewed-snapshots/<slug>/<date>-<prefix>.json` and `content/spots/<slug>.md` via tomlkit (mirroring `merge.py`'s comment-preserving pattern). Two-PR rollout: PR1 lands projection + CLI (usable immediately); PR2 lands the server + UI as one atomic unit.

**Tech Stack:** Python 3.13 (stdlib `http.server.ThreadingHTTPServer`, `tomlkit`, Click), pytest, vanilla ES-module JS (no bundler, no framework), Zola (with `draft = true`), devenv.nix.

---

## File Structure

**PR 1 — projection:**
- Create: `src/schedules/review_project.py`
- Create: `tests/test_review_project.py`
- Modify: `src/schedules/cli.py` (add `schedules project` subcommand)
- Create: `tests/test_cli_project.py`

**PR 2 — server + UI:**
- Create: `src/schedules/review_server.py` (handler, routes, graceful shutdown)
- Modify: `src/schedules/cli.py` (add `schedules review` subcommand)
- Create: `content/_admin/review.md` (Zola draft page host)
- Create: `static/js/review/index.mjs` (roster controller)
- Create: `static/js/review/pool.mjs` (editor controller; owns etag)
- Create: `static/js/review/api.mjs` (fetch wrappers + 409 handling)
- Create: `static/js/review/schema.mjs` (shared enums, mirrors `schedule/schema.py`)
- Create: `static/js/review/grid.mjs` (week grid + modals)
- Create: `static/js/review/closures.mjs` (closures list)
- Create: `static/js/review/pdf.mjs` (PDF pane)
- Create: `static/js/review/diff.mjs` (provider-diff panel)
- Create: `static/js/review/store.mjs` (in-memory editor state)
- Create: `static/js/review/time.mjs` (re-exports `nowInPacific`)
- Modify: `static/js/helpers/board.mjs` (add `nowInPacific()` — does not exist yet)
- Modify: `devenv.nix` (add `admin` process group + `devenv.scripts`)
- Create: `tests/test_review_server_routes.py`
- Create: `tests/test_review_save_pipeline.py`
- Create: `tests/test_review_etag.py`
- Create: `tests/test_review_rollback.py`
- Create: `tests/test_review_validate.py`
- Create: `tests/test_review_delta.py`
- Create: `tests/test_review_metadata.py`
- Create: `tests/test_review_pacific_midnight.py`
- Create: `tests/test_review_corrupt_frontmatter.py`
- Create: `tests/test_review_missing_pdf.py`
- Create: `tests/test_review_disk_full.py`
- Create: `tests/test_review_cors.py`
- Create: `tests/test_reviewer_isolation.py`
- Create: `tests/test_review_import_graph.py`

---

# PR 1 — review_project.py + CLI

## Task 1: `review_project.py` — TOML projection helper

Mirrors `merge.merge()`'s tomlkit pattern but also projects metadata and (conditionally) `last_verified_at`. Returns bytes; caller does atomic write.

**Files:**
- Create: `src/schedules/review_project.py`
- Create: `tests/test_review_project.py`

- [ ] **Step 1: Write the failing test — round-trip preserves comments and non-managed keys**

```python
# tests/test_review_project.py
from pathlib import Path

import pytest

from schedules.review_project import project


FIXTURE = """+++
title = "Hamilton Pool"
subtype = "indoor"
website = "https://sfrecpark.org/hamilton"
last_verified_at = "2026-04-10"

# Comment above schedule_effective — must survive round-trip
[extra]
schedule_effective = "2026-03-17"
schedule_effective_end = "2026-06-06"

# comment between the two AoTs — must survive
[[extra.sessions]]
day = "monday"
type = "lap_swim"
start = "07:30"
end = "08:30"

[[extra.closures]]
start = "2026-05-25"
end = "2026-05-25"
reason = "Memorial Day"
+++

Body content here.
"""


def test_project_preserves_comments_and_non_managed_keys(tmp_path):
    md = tmp_path / "hamilton-pool.md"
    md.write_text(FIXTURE)

    new_bytes = project(
        md,
        metadata={
            "title": "Hamilton Pool",
            "subtype": "indoor",
            "website": "https://sfrecpark.org/hamilton",
            "schedule_effective": "2026-03-17",
            "schedule_effective_end": "2026-06-06",
        },
        sessions=[
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "tuesday", "type": "lap_swim", "start": "12:30", "end": "15:00"},
        ],
        closures=[
            {"start": "2026-05-25", "end": "2026-05-25", "reason": "Memorial Day"},
        ],
        last_verified_at=None,
    )

    text = new_bytes.decode("utf-8")
    assert "# Comment above schedule_effective" in text
    assert "# comment between the two AoTs" in text
    assert 'last_verified_at = "2026-04-10"' in text  # untouched because last_verified_at=None
    assert text.startswith("+++\n")
    assert text.endswith("\nBody content here.\n")
    assert 'day = "monday"' in text
    assert 'day = "tuesday"' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_project.py::test_project_preserves_comments_and_non_managed_keys -v`
Expected: FAIL with `ImportError` / module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# src/schedules/review_project.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit

from .merge import _build_closures_value, _build_sessions_value, _split_frontmatter


_METADATA_KEYS = ("title", "subtype", "website")


def project(
    pool_md_path: Path,
    *,
    metadata: dict[str, Any],
    sessions: list[dict[str, Any]],
    closures: list[dict[str, Any]],
    last_verified_at: str | None,
) -> bytes:
    """Project reviewed data back into a spot MD.

    Returns the new file contents as bytes. Caller is responsible for atomic
    write. Preserves all comments and any non-managed frontmatter keys.
    Mirrors ``merge.merge()``'s tomlkit pattern.
    """
    original_text = pool_md_path.read_text()
    frontmatter_text, body = _split_frontmatter(original_text)
    document = tomlkit.parse(frontmatter_text)

    for key in _METADATA_KEYS:
        if key in metadata and metadata[key] is not None:
            document[key] = metadata[key]

    if last_verified_at is not None:
        document["last_verified_at"] = last_verified_at

    extra = document.setdefault("extra", tomlkit.table())
    if "schedule_effective" in metadata and metadata["schedule_effective"] is not None:
        extra["schedule_effective"] = metadata["schedule_effective"]
    if "schedule_effective_end" in metadata and metadata["schedule_effective_end"] is not None:
        extra["schedule_effective_end"] = metadata["schedule_effective_end"]
    elif "schedule_effective_end" in extra and metadata.get("schedule_effective_end") is None:
        del extra["schedule_effective_end"]

    extra["sessions"] = _build_sessions_value(sessions)
    extra["closures"] = _build_closures_value(closures)

    updated = tomlkit.dumps(document).rstrip("\n")
    return f"+++\n{updated}\n+++\n{body}".encode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_review_project.py -v`
Expected: PASS.

- [ ] **Step 5: Add metadata-update test**

```python
# append to tests/test_review_project.py

def test_project_updates_metadata_and_bumps_last_verified(tmp_path):
    md = tmp_path / "hamilton-pool.md"
    md.write_text(FIXTURE)

    new_bytes = project(
        md,
        metadata={
            "title": "Hamilton Rec Pool",
            "subtype": "outdoor",
            "website": "https://example.com",
            "schedule_effective": "2026-04-01",
            "schedule_effective_end": None,
        },
        sessions=[{"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}],
        closures=[],
        last_verified_at="2026-04-18",
    )
    text = new_bytes.decode("utf-8")
    assert 'title = "Hamilton Rec Pool"' in text
    assert 'subtype = "outdoor"' in text
    assert 'last_verified_at = "2026-04-18"' in text
    assert "schedule_effective_end" not in text
```

- [ ] **Step 6: Verify the new test passes**

Run: `uv run pytest tests/test_review_project.py -v`
Expected: both tests PASS.

- [ ] **Step 7: Add inter-AoT-comment invariant test (documenting the limitation)**

```python
# append to tests/test_review_project.py

def test_project_loses_comment_inside_aot_block(tmp_path):
    """Document the tomlkit limitation: comments inside [[extra.sessions]] are lost.
    This is not a regression — it is a known invariant. If this test starts failing
    (comment now survives), update the spec to allow inter-AoT comments."""
    md = tmp_path / "pool.md"
    md.write_text("""+++
title = "X"
[extra]
schedule_effective = "2026-03-17"

[[extra.sessions]]
# this comment will be lost
day = "monday"
type = "lap_swim"
start = "07:30"
end = "08:30"
+++

""")
    new_bytes = project(
        md,
        metadata={"title": "X", "schedule_effective": "2026-03-17"},
        sessions=[{"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}],
        closures=[],
        last_verified_at=None,
    )
    assert b"this comment will be lost" not in new_bytes
```

- [ ] **Step 8: Run all projection tests**

Run: `uv run pytest tests/test_review_project.py -v`
Expected: all three tests PASS.

- [ ] **Step 9: Commit**

```bash
git add src/schedules/review_project.py tests/test_review_project.py
git commit -m "feat(review): add review_project module for TOML projection"
```

## Task 2: `schedules project <slug>` CLI subcommand

Standalone CLI that runs `review_project.project()` using the latest reviewed snapshot for a slug.

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


def _write_spot_md(path: Path) -> None:
    path.write_text("""+++
title = "Hamilton Pool"
subtype = "indoor"
website = "https://example.com"

[extra]
schedule_effective = "2026-03-17"

[[extra.sessions]]
day = "monday"
type = "lap_swim"
start = "07:30"
end = "08:30"
+++

""")


def _write_snapshot(root: Path, slug: str, pdf_sha256: str, sessions: list[dict]) -> None:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True)
    (slug_dir / f"2026-04-18-{pdf_sha256[:12]}.json").write_text(json.dumps({
        "version": 1,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/x.pdf",
        "reviewed_against": [{"provider": "gemini", "model": "gemini-3.1"}],
        "summary": "manual review",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": sessions,
            "closures": [],
        },
    }))


def test_schedules_project_writes_md(tmp_path, monkeypatch):
    content_dir = tmp_path / "content" / "spots"
    content_dir.mkdir(parents=True)
    md = content_dir / "hamilton-pool.md"
    _write_spot_md(md)

    snapshots_root = tmp_path / "data" / "reviewed-snapshots"
    sha = "a" * 64
    _write_snapshot(snapshots_root, "hamilton-pool", sha, [
        {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        {"day": "tuesday", "type": "lap_swim", "start": "12:30", "end": "15:00"},
    ])

    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["project", "hamilton-pool"])
    assert result.exit_code == 0, result.output
    text = md.read_text()
    assert 'day = "tuesday"' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_project.py -v`
Expected: FAIL — no `project` subcommand.

- [ ] **Step 3: Implement the subcommand**

Append to `src/schedules/cli.py`:

```python
@cli.command()
@click.argument("slug")
def project(slug: str) -> None:
    """Regenerate content/spots/<slug>.md from the latest reviewed snapshot."""
    from pathlib import Path
    from .paths import CONTENT_SPOTS_DIR
    from .review_project import project as project_fn
    from .reviewed_snapshots import find_snapshots_for_slug, load_reviewed_snapshot_from_path

    snapshots = find_snapshots_for_slug(slug)
    if not snapshots:
        raise click.ClickException(f"No reviewed snapshots for slug={slug}")
    latest = snapshots[-1]
    envelope, _, _ = load_reviewed_snapshot_from_path(latest, expected_slug=slug)
    payload = envelope["payload"]

    md_path = CONTENT_SPOTS_DIR / f"{slug}.md"
    if not md_path.exists():
        raise click.ClickException(f"{md_path} does not exist")

    new_bytes = project_fn(
        md_path,
        metadata={
            "schedule_effective": payload.get("schedule_effective"),
            "schedule_effective_end": payload.get("schedule_effective_end"),
        },
        sessions=payload.get("sessions") or [],
        closures=payload.get("closures") or [],
        last_verified_at=None,
    )
    md_path.write_bytes(new_bytes)
    click.echo(f"Projected {latest.name} -> {md_path}")
```

Check that `src/schedules/paths.py` exports `CONTENT_SPOTS_DIR`. If not, add a minimal constant (this is not the place to restructure paths).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_project.py -v`
Expected: PASS.

- [ ] **Step 5: Full-test smoke**

Run: `uv run pytest -q`
Expected: whole suite PASS.

- [ ] **Step 6: Commit**

```bash
git add src/schedules/cli.py tests/test_cli_project.py src/schedules/paths.py
git commit -m "feat(cli): add 'schedules project' subcommand for regenerating spot MDs"
```

---

**↑ PR 1 ends here. Open PR, land on main. PR 2 builds on top. ↑**

---

# PR 2 — review_server.py + UI + devenv

## Task 3: Add `nowInPacific()` to `board.mjs`

The spec assumes this helper exists. Grep confirms it does not. Add it now — it has exactly one caller initially (`static/js/review/time.mjs`), but it belongs in `board.mjs` alongside the other time helpers.

**Files:**
- Modify: `static/js/helpers/board.mjs`

- [ ] **Step 1: Implement**

Append to `static/js/helpers/board.mjs`:

```javascript
/**
 * Returns today's date string in Pacific Time (America/Los_Angeles) as YYYY-MM-DD.
 * Used by both the public board and the local reviewer tool to avoid UTC drift.
 */
export function nowInPacific() {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(new Date());
}
```

- [ ] **Step 2: Manual smoke — import it in a Node REPL**

Run: `node --input-type=module -e "import('./static/js/helpers/board.mjs').then(m => console.log(m.nowInPacific()))"`
Expected: a YYYY-MM-DD string matching today's Pacific date.

- [ ] **Step 3: Commit**

```bash
git add static/js/helpers/board.mjs
git commit -m "feat(helpers): add nowInPacific() for Pacific-timezone date strings"
```

## Task 4: `review_server.py` skeleton — `/health`, CORS, graceful shutdown

Start with the handler scaffolding. No data routes yet.

**Files:**
- Create: `src/schedules/review_server.py`
- Create: `tests/test_review_server_routes.py`
- Create: `tests/test_review_cors.py`

- [ ] **Step 1: Write the failing test for `/health`**

```python
# tests/test_review_server_routes.py
import threading
import time
import urllib.request

import pytest

from schedules.review_server import ReviewServer, make_handler


@pytest.fixture
def server(tmp_path):
    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_health_endpoint(server):
    _, port = server
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health")
    assert resp.status == 200
    assert resp.read() == b'{"ok":true}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_server_routes.py::test_health_endpoint -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the skeleton**

```python
# src/schedules/review_server.py
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable


_CORS_ORIGIN_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    block_on_close = False


def make_handler(*, repo_root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        # Suppress the default access-log chatter; keep stderr clean for devenv tailing.
        def log_message(self, *args, **kwargs) -> None:  # noqa: ARG002
            return

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin", "")
            if _CORS_ORIGIN_RE.match(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, status: int, body: dict | list) -> None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"ok": True})
                return
            self._json(404, {"error": "not found", "path": self.path})

    Handler.repo_root = repo_root  # type: ignore[attr-defined]
    return Handler
```

Note: `json.dumps({"ok": True}, separators=(",", ":"))` produces `{"ok":true}` — matching the test's exact bytes.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_review_server_routes.py::test_health_endpoint -v`
Expected: PASS.

- [ ] **Step 5: Write the CORS test**

```python
# tests/test_review_cors.py
import threading
import urllib.request

import pytest

from schedules.review_server import ReviewServer, make_handler


@pytest.fixture
def server(tmp_path):
    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_cors_allows_loopback(server):
    port = server
    req = urllib.request.Request(f"http://127.0.0.1:{port}/health",
                                 headers={"Origin": "http://localhost:1111"})
    resp = urllib.request.urlopen(req)
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:1111"


def test_cors_denies_non_loopback(server):
    port = server
    req = urllib.request.Request(f"http://127.0.0.1:{port}/health",
                                 headers={"Origin": "https://evil.example.com"})
    resp = urllib.request.urlopen(req)
    assert resp.headers.get("Access-Control-Allow-Origin") is None
```

- [ ] **Step 6: Run CORS tests**

Run: `uv run pytest tests/test_review_cors.py -v`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add src/schedules/review_server.py tests/test_review_server_routes.py tests/test_review_cors.py
git commit -m "feat(review): add review_server skeleton with /health and CORS"
```

## Task 5: Read endpoints — `GET /pools`, `GET /pools/<slug>`

**Files:**
- Modify: `src/schedules/review_server.py`
- Modify: `tests/test_review_server_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_review_server_routes.py
import json

def test_list_pools_empty(server, tmp_path):
    _, port = server
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/pools")
    body = json.loads(resp.read())
    assert body == []


def test_get_pool_bundle(server, tmp_path):
    _, port = server
    content = tmp_path / "content" / "spots"
    content.mkdir(parents=True)
    (content / "hamilton-pool.md").write_text("""+++
title = "Hamilton Pool"
subtype = "indoor"
website = "https://example.com"

[extra]
schedule_effective = "2026-03-17"

[[extra.sessions]]
day = "monday"
type = "lap_swim"
start = "07:30"
end = "08:30"
+++

""")

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/pools/hamilton-pool")
    body = json.loads(resp.read())
    assert body["metadata"]["title"] == "Hamilton Pool"
    assert body["sessions"][0]["day"] == "monday"
    assert isinstance(body["etag"], str) and len(body["etag"]) == 64
    assert body["artifacts"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_server_routes.py -v`
Expected: FAIL — new routes not implemented.

- [ ] **Step 3: Implement the routes**

Extend `do_GET` in `review_server.py`:

```python
# inside make_handler, replace do_GET with:
import hashlib
from .merge import read_schedule_snapshot, _split_frontmatter
import tomlkit

        def do_GET(self) -> None:
            root: Path = self.__class__.repo_root  # type: ignore[attr-defined]
            if self.path == "/health":
                self._json(200, {"ok": True})
                return
            if self.path == "/pools":
                self._json(200, _list_pools(root))
                return
            if self.path.startswith("/pools/"):
                slug = self.path[len("/pools/"):]
                if not re.match(r"^[a-z0-9][a-z0-9-]*$", slug):
                    self._json(400, {"error": "bad slug"})
                    return
                bundle = _pool_bundle(root, slug)
                if bundle is None:
                    self._json(404, {"error": "no such pool"})
                    return
                self._json(200, bundle)
                return
            self._json(404, {"error": "not found", "path": self.path})
```

Add helpers to the module (outside `make_handler`):

```python
def _list_pools(root: Path) -> list[dict]:
    spots = root / "content" / "spots"
    if not spots.is_dir():
        return []
    pools: list[dict] = []
    for md in sorted(spots.glob("*.md")):
        pools.append({"slug": md.stem})
    return pools


def _pool_bundle(root: Path, slug: str) -> dict | None:
    md = root / "content" / "spots" / f"{slug}.md"
    if not md.exists():
        return None
    frontmatter_text, _ = _split_frontmatter(md.read_text())
    document = tomlkit.parse(frontmatter_text)
    snapshot = read_schedule_snapshot(md)
    metadata = {k: document.get(k) for k in ("title", "subtype", "website", "last_verified_at")}
    metadata["schedule_effective"] = snapshot.get("schedule_effective")
    metadata["schedule_effective_end"] = snapshot.get("schedule_effective_end")
    etag = hashlib.sha256(md.read_bytes()).hexdigest()
    return {
        "metadata": metadata,
        "sessions": snapshot["sessions"],
        "closures": snapshot["closures"],
        "pdf": None,
        "artifacts": [],
        "etag": etag,
    }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_review_server_routes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/review_server.py tests/test_review_server_routes.py
git commit -m "feat(review): add /pools and /pools/<slug> read endpoints"
```

## Task 6: Binary endpoints — `GET /pdfs/...`, `GET /artifacts/...`

**Files:**
- Modify: `src/schedules/review_server.py`
- Create: `tests/test_review_missing_pdf.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_missing_pdf.py
import threading
import urllib.error
import urllib.request

import pytest

from schedules.review_server import ReviewServer, make_handler


@pytest.fixture
def server(tmp_path):
    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield tmp_path, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_missing_pdf_returns_404(server):
    _, port = server
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/pdfs/hamilton-pool/2026-04-18-abcabcabcabc.pdf")
    assert ei.value.code == 404


def test_existing_pdf_streams_bytes(server):
    root, port = server
    pdf_dir = root / "data" / "pdfs" / "hamilton-pool"
    pdf_dir.mkdir(parents=True)
    fn = "2026-04-18-abcabcabcabc.pdf"
    (pdf_dir / fn).write_bytes(b"%PDF-1.4 fake")

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/pdfs/hamilton-pool/{fn}")
    assert resp.status == 200
    assert resp.read() == b"%PDF-1.4 fake"
    assert resp.headers["Content-Type"] == "application/pdf"


def test_pdf_path_traversal_rejected(server):
    _, port = server
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/pdfs/hamilton-pool/..%2Fsecret.pdf")
    assert ei.value.code in (400, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_missing_pdf.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `review_server.py`:

```python
_PDF_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{12}\.pdf$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _serve_pdf(handler: BaseHTTPRequestHandler, root: Path, slug: str, filename: str) -> None:
    if not _SLUG_RE.match(slug) or not _PDF_FILENAME_RE.match(filename):
        handler.send_response(400); handler.end_headers(); return
    pdf_root = (root / "data" / "pdfs" / slug).resolve()
    target = (pdf_root / filename).resolve()
    if pdf_root not in target.parents:
        handler.send_response(400); handler.end_headers(); return
    if not target.is_file():
        handler.send_response(404); handler.end_headers(); return
    data = target.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/pdf")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
```

In `do_GET`, dispatch `/pdfs/<slug>/<filename>` to `_serve_pdf`. Likewise add `/artifacts/<slug>/<hash>/<provider>.json` dispatch (404 if missing; the reviewer UI handles empty state).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_review_missing_pdf.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/review_server.py tests/test_review_missing_pdf.py
git commit -m "feat(review): add /pdfs and /artifacts binary endpoints with traversal guard"
```

## Task 7: `POST /pools/<slug>/save` — happy path (etag + validate + atomic write)

**Files:**
- Modify: `src/schedules/review_server.py`
- Create: `tests/test_review_save_pipeline.py`
- Create: `tests/test_review_etag.py`
- Create: `tests/test_review_validate.py`

- [ ] **Step 1: Write the failing happy-path test**

```python
# tests/test_review_save_pipeline.py
import json
import threading
import urllib.request

import pytest

from schedules.review_server import ReviewServer, make_handler


@pytest.fixture
def env(tmp_path):
    (tmp_path / "content" / "spots").mkdir(parents=True)
    (tmp_path / "content" / "spots" / "hamilton-pool.md").write_text("""+++
title = "Hamilton Pool"
subtype = "indoor"
website = "https://example.com"

[extra]
schedule_effective = "2026-03-17"

[[extra.sessions]]
day = "monday"
type = "lap_swim"
start = "07:30"
end = "08:30"
+++

""")
    (tmp_path / "data" / "pdfs" / "hamilton-pool").mkdir(parents=True)
    sha = "a" * 64
    (tmp_path / "data" / "pdfs" / "hamilton-pool" / f"2026-04-18-{sha[:12]}.pdf").write_bytes(b"%PDF")

    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield tmp_path, srv.server_address[1], sha
    srv.shutdown()
    srv.server_close()


def _post(port: int, slug: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/pools/{slug}/save",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:  # type: ignore[name-defined]
        return e.code, json.loads(e.read())


def test_save_happy_path(env):
    root, port, _ = env
    # Fetch current etag first.
    bundle = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/pools/hamilton-pool").read())
    status, body = _post(port, "hamilton-pool", {
        "etag": bundle["etag"],
        "metadata": {
            "title": "Hamilton Pool",
            "subtype": "indoor",
            "website": "https://example.com",
            "schedule_effective": "2026-03-17",
            "schedule_effective_end": None,
        },
        "sessions": [
            {"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "tuesday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "wednesday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "thursday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
            {"day": "friday", "type": "lap_swim", "start": "07:30", "end": "08:30"},
        ],
        "closures": [],
        "summary": "test",
        "fully_verified": False,
        "save_anyway": False,
    })
    assert status == 200, body
    assert body["ok"] is True

    md = (root / "content" / "spots" / "hamilton-pool.md").read_text()
    assert 'day = "friday"' in md
    snapshots = list((root / "data" / "reviewed-snapshots" / "hamilton-pool").glob("*.json"))
    assert len(snapshots) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_review_save_pipeline.py::test_save_happy_path -v`
Expected: FAIL — `/save` route doesn't exist.

- [ ] **Step 3: Implement `do_POST` + save pipeline**

In `review_server.py`, add:

```python
import hashlib
import json
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from .review_project import project as project_fn
from .reviewed_snapshots import REVIEWED_SNAPSHOT_VERSION, reviewed_snapshot_path
from .validate import validate


def _today_pacific() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _latest_pdf_for_slug(root: Path, slug: str) -> tuple[str, str] | None:
    pdf_dir = root / "data" / "pdfs" / slug
    if not pdf_dir.is_dir():
        return None
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        return None
    latest = pdfs[-1]
    # For a full sha we would need to re-hash the bytes; for reviewer purposes
    # the 12-char prefix from the filename is the authoritative cache key.
    # We hash the bytes to get a real sha256 for the envelope.
    full_sha = hashlib.sha256(latest.read_bytes()).hexdigest()
    return full_sha, latest.name


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(dir=target.parent, delete=False, mode="wb")
    try:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, target)
    except Exception:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
        raise


def _save(root: Path, slug: str, body: dict) -> tuple[int, dict]:
    md_path = root / "content" / "spots" / f"{slug}.md"
    if not md_path.exists():
        return 404, {"error": "no such pool"}

    current_etag = hashlib.sha256(md_path.read_bytes()).hexdigest()
    if body.get("etag") != current_etag:
        return 409, {"error": "stale etag", "current_etag": current_etag}

    pdf = _latest_pdf_for_slug(root, slug)
    if pdf is None:
        return 422, {"error": "no PDF cached for slug"}
    pdf_sha256, _pdf_name = pdf

    sessions = body.get("sessions") or []
    closures = body.get("closures") or []
    metadata = body.get("metadata") or {}

    result = validate({"sessions": sessions, "closures": closures,
                       "schedule_effective": metadata.get("schedule_effective")},
                      prior_sessions_count=len(sessions))
    if not result.ok:
        return 422, {"error": "validation failed", "violations": [str(v) for v in result.violations]}

    snap_path = reviewed_snapshot_path(slug, pdf_sha256, root=root / "data" / "reviewed-snapshots")

    md_prior = md_path.read_bytes() if md_path.exists() else None
    snap_prior = snap_path.read_bytes() if snap_path.exists() else None

    envelope = {
        "version": REVIEWED_SNAPSHOT_VERSION,
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": _today_pacific(),
        "source_pdf_url": metadata.get("source_pdf_url", ""),
        "reviewed_against": [],
        "summary": body.get("summary", ""),
        "payload": {
            "schedule_effective": metadata.get("schedule_effective"),
            "schedule_effective_end": metadata.get("schedule_effective_end"),
            "sessions": sessions,
            "closures": closures,
        },
    }
    snap_bytes = (json.dumps(envelope, indent=2) + "\n").encode("utf-8")

    new_md_bytes = project_fn(
        md_path,
        metadata=metadata,
        sessions=sessions,
        closures=closures,
        last_verified_at=_today_pacific() if body.get("fully_verified") else None,
    )

    try:
        _atomic_write(snap_path, snap_bytes)
        _atomic_write(md_path, new_md_bytes)
    except Exception as exc:
        _restore(md_path, md_prior)
        _restore(snap_path, snap_prior)
        return 500, {"error": "write failed", "detail": str(exc)}

    new_etag = hashlib.sha256(md_path.read_bytes()).hexdigest()
    return 200, {
        "ok": True,
        "reviewed_path": str(snap_path.relative_to(root)),
        "md_path": str(md_path.relative_to(root)),
        "warnings": [],
        "new_etag": new_etag,
    }


def _restore(path: Path, prior: bytes | None) -> None:
    if prior is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    else:
        _atomic_write(path, prior)
```

In `make_handler`, add `do_POST`:

```python
        def do_POST(self) -> None:
            root: Path = self.__class__.repo_root  # type: ignore[attr-defined]
            m = re.match(r"^/pools/([a-z0-9][a-z0-9-]*)/save$", self.path)
            if not m:
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            status, resp = _save(root, m.group(1), body)
            self._json(status, resp)
```

- [ ] **Step 4: Run the happy-path test**

Run: `uv run pytest tests/test_review_save_pipeline.py::test_save_happy_path -v`
Expected: PASS.

- [ ] **Step 5: Add the 409 stale-etag test**

```python
# tests/test_review_etag.py
import json
import threading
import urllib.error
import urllib.request

import pytest

from schedules.review_server import ReviewServer, make_handler


# Reuse the same env fixture pattern as test_review_save_pipeline.py
# (import or duplicate — for clarity, duplicate here).


def _setup(tmp_path):
    (tmp_path / "content" / "spots").mkdir(parents=True)
    (tmp_path / "content" / "spots" / "hamilton-pool.md").write_text(
        '+++\ntitle = "X"\nsubtype = "indoor"\nwebsite = "https://x"\n\n'
        '[extra]\nschedule_effective = "2026-03-17"\n\n'
        '[[extra.sessions]]\nday = "monday"\ntype = "lap_swim"\nstart = "07:30"\nend = "08:30"\n+++\n\n'
    )
    (tmp_path / "data" / "pdfs" / "hamilton-pool").mkdir(parents=True)
    sha = "a" * 64
    (tmp_path / "data" / "pdfs" / "hamilton-pool" / f"2026-04-18-{sha[:12]}.pdf").write_bytes(b"%PDF")


@pytest.fixture
def port(tmp_path):
    _setup(tmp_path)
    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_stale_etag_returns_409(port):
    # Don't fetch current etag — send an obviously-wrong one.
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/pools/hamilton-pool/save",
        data=json.dumps({
            "etag": "0" * 64,
            "metadata": {"title": "X", "subtype": "indoor", "website": "https://x",
                         "schedule_effective": "2026-03-17"},
            "sessions": [{"day": d, "type": "lap_swim", "start": "07:30", "end": "08:30"}
                         for d in ("monday", "tuesday", "wednesday", "thursday", "friday")],
            "closures": [],
            "summary": "",
            "fully_verified": False,
            "save_anyway": False,
        }).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req)
    assert ei.value.code == 409
```

- [ ] **Step 6: Add the 422 validation test**

```python
# tests/test_review_validate.py — similar _setup/fixture, then:

def test_fewer_than_five_sessions_returns_422(port):
    bundle = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/pools/hamilton-pool").read())
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/pools/hamilton-pool/save",
        data=json.dumps({
            "etag": bundle["etag"],
            "metadata": {"title": "X", "subtype": "indoor", "website": "https://x",
                         "schedule_effective": "2026-03-17"},
            "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:30", "end": "08:30"}],
            "closures": [],
            "summary": "",
            "fully_verified": False,
            "save_anyway": False,
        }).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req)
    assert ei.value.code == 422
```

- [ ] **Step 7: Run all the new tests**

Run: `uv run pytest tests/test_review_save_pipeline.py tests/test_review_etag.py tests/test_review_validate.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/schedules/review_server.py tests/test_review_save_pipeline.py tests/test_review_etag.py tests/test_review_validate.py
git commit -m "feat(review): add POST /pools/<slug>/save with etag + validate + atomic writes"
```

## Task 8: Rollback + read-back verification

Verify both files parse back to what was written; restore prior bytes if not.

**Files:**
- Modify: `src/schedules/review_server.py`
- Create: `tests/test_review_rollback.py`
- Create: `tests/test_review_disk_full.py`

- [ ] **Step 1: Write the rollback test**

```python
# tests/test_review_rollback.py
import json
import threading
from unittest.mock import patch
import urllib.request

import pytest

from schedules.review_server import ReviewServer, make_handler


def _setup(tmp_path):
    (tmp_path / "content" / "spots").mkdir(parents=True)
    md = tmp_path / "content" / "spots" / "hamilton-pool.md"
    md.write_text(
        '+++\ntitle = "X"\nsubtype = "indoor"\nwebsite = "https://x"\n\n'
        '[extra]\nschedule_effective = "2026-03-17"\n\n'
        '[[extra.sessions]]\nday = "monday"\ntype = "lap_swim"\nstart = "07:30"\nend = "08:30"\n+++\n\n'
    )
    (tmp_path / "data" / "pdfs" / "hamilton-pool").mkdir(parents=True)
    sha = "a" * 64
    (tmp_path / "data" / "pdfs" / "hamilton-pool" / f"2026-04-18-{sha[:12]}.pdf").write_bytes(b"%PDF")
    return md


def test_disk_full_on_second_replace_rolls_back_first(tmp_path):
    md = _setup(tmp_path)
    original_bytes = md.read_bytes()

    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    port = srv.server_address[1]
    try:
        bundle = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/pools/hamilton-pool").read())

        # Patch os.replace to fail only the SECOND call (the MD write).
        from schedules import review_server as rs
        call_count = {"n": 0}
        real_replace = rs.os.replace

        def flaky_replace(src, dst):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("disk full")
            return real_replace(src, dst)

        with patch.object(rs.os, "replace", side_effect=flaky_replace):
            import urllib.error
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/pools/hamilton-pool/save",
                data=json.dumps({
                    "etag": bundle["etag"],
                    "metadata": {"title": "Y", "subtype": "indoor", "website": "https://x",
                                 "schedule_effective": "2026-03-17"},
                    "sessions": [{"day": d, "type": "lap_swim", "start": "07:30", "end": "08:30"}
                                 for d in ("monday", "tuesday", "wednesday", "thursday", "friday")],
                    "closures": [],
                    "summary": "",
                    "fully_verified": False,
                    "save_anyway": False,
                }).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(urllib.error.HTTPError) as ei:
                urllib.request.urlopen(req)
            assert ei.value.code == 500

        # MD must be back to its original contents; snapshot must not exist.
        assert md.read_bytes() == original_bytes
        snapshots = list((tmp_path / "data" / "reviewed-snapshots" / "hamilton-pool").glob("*.json"))
        assert snapshots == []
    finally:
        srv.shutdown()
        srv.server_close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_rollback.py -v`
Expected: FAIL — current rollback only restores bytes but doesn't unlink a newly-created snapshot.

- [ ] **Step 3: Verify `_restore(snap_path, snap_prior=None)` unlinks**

Confirm by re-reading the implementation in Task 7 — `_restore` calls `os.unlink` when `prior is None`. If the test still fails, it's because the first `_atomic_write` succeeded: the snapshot exists, then we try to roll it back to "prior=None" which means unlink. Verify the unlink path runs.

If needed, tighten the rollback ordering:

```python
# inside _save, replace the write block:
    try:
        _atomic_write(snap_path, snap_bytes)
    except Exception as exc:
        return 500, {"error": "snapshot write failed", "detail": str(exc)}
    try:
        _atomic_write(md_path, new_md_bytes)
    except Exception as exc:
        _restore(snap_path, snap_prior)  # undoes the snapshot we just wrote
        return 500, {"error": "md write failed", "detail": str(exc)}
```

- [ ] **Step 4: Run the rollback test**

Run: `uv run pytest tests/test_review_rollback.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/review_server.py tests/test_review_rollback.py
git commit -m "fix(review): roll back snapshot write when MD write fails"
```

## Task 9: `schedules review` CLI + SIGINT/SIGTERM graceful shutdown

**Files:**
- Modify: `src/schedules/cli.py`

- [ ] **Step 1: Write the failing test (start + /health + shutdown)**

```python
# tests/test_cli_review_signal.py
import subprocess
import sys
import time
import urllib.request

import pytest


@pytest.mark.slow
def test_review_cli_serves_and_shuts_down_on_sigint(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "schedules", "review", "--host", "127.0.0.1", "--port", "0"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Read the "listening on 127.0.0.1:<port>" line from stdout.
    line = proc.stdout.readline().decode("utf-8")
    assert "listening on 127.0.0.1:" in line
    port = int(line.rsplit(":", 1)[-1].strip())

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
    assert resp.status == 200

    proc.send_signal(subprocess.signal.SIGINT)
    proc.wait(timeout=5)
    assert proc.returncode == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_review_signal.py -v`
Expected: FAIL — no `schedules review` subcommand, no `__main__` entry point.

- [ ] **Step 3: Implement the subcommand**

Append to `src/schedules/cli.py`:

```python
@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=4317, show_default=True, type=int)
def review(host: str, port: int) -> None:
    """Run the local review server."""
    import signal
    import sys
    from pathlib import Path
    from .review_server import ReviewServer, make_handler

    if host != "127.0.0.1" and host != "localhost":
        raise click.ClickException(f"Refusing to bind to {host}; reviewer is loopback-only.")

    server = ReviewServer((host, port), make_handler(repo_root=Path.cwd()))
    actual_port = server.server_address[1]
    click.echo(f"listening on {host}:{actual_port}", nl=True)
    sys.stdout.flush()

    def _stop(*_args):
        # server.shutdown() must be called from a different thread than serve_forever.
        import threading
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        server.serve_forever()
    finally:
        server.server_close()
```

Ensure `src/schedules/__main__.py` exists and calls `cli()`; add if missing.

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_cli_review_signal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schedules/cli.py src/schedules/__main__.py tests/test_cli_review_signal.py
git commit -m "feat(cli): add 'schedules review' subcommand with graceful shutdown"
```

## Task 10: `devenv.nix` — `admin` process group + scripts

**Files:**
- Modify: `devenv.nix`

- [ ] **Step 1: Add the admin process group and scripts**

Read the current `devenv.nix` structure (it uses flat `processes.<name>.exec`). Add:

```nix
# in the appropriate location in devenv.nix

processes.zola-admin = {
  exec = "zola serve --drafts --interface 127.0.0.1 --port 1111";
  process-compose = {
    availability.restart = "on_failure";
    # Put this in a non-default group via process-compose namespace:
  };
};

processes.schedules-review = {
  exec = "uv run schedules review --host 127.0.0.1 --port 4317";
};

scripts.extract.exec = ''
  set -a && source .env && set +a
  uv run schedules extract "$@"
'';

scripts.bakeoff.exec = ''
  set -a && source .env && set +a
  uv run schedules debug bakeoff "$@"
'';

scripts.project.exec = "uv run schedules project \"$@\"";

scripts.migrate-pdf-layout.exec = "uv run python scripts/migrate_pdf_layout.py";
```

Verify against the actual `devenv.nix` conventions (flat `processes.<name>.exec`) and use whatever grouping mechanism the file already uses. If devenv does not support named groups natively on this version, use an `admin = true` attribute on the processes or gate them via a `dev.enable` flag toggled by `devenv up admin`.

- [ ] **Step 2: Smoke test**

Run: `devenv up admin` (or the equivalent group invocation). Confirm both `zola serve` and `schedules review` start. Hit `http://127.0.0.1:4317/health` and `http://127.0.0.1:1111/`. Stop with Ctrl+C — both must exit cleanly.

- [ ] **Step 3: Commit**

```bash
git add devenv.nix
git commit -m "feat(devenv): add 'admin' process group and schedules scripts"
```

## Task 11: `content/_admin/review.md` + static HTML shell

Zola draft page that loads the ES module entry point.

**Files:**
- Create: `content/_admin/review.md`
- Create: `static/review/index.html` (optional) or inline into the MD page

- [ ] **Step 1: Create the draft page**

```markdown
+++
title = "Schedule Reviewer"
draft = true
template = "admin/review.html"
path = "/_admin/review/"
+++
```

- [ ] **Step 2: Create the template**

Create `templates/admin/review.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Schedule Reviewer</title>
  <link rel="stylesheet" href="/css/admin/review.css">
</head>
<body>
  <header id="review-header"></header>
  <main id="review-main"></main>
  <script type="module" src="/js/review/index.mjs"></script>
</body>
</html>
```

- [ ] **Step 3: Add the CSS skeleton**

Create `static/css/admin/review.css`:

```css
body { font-family: system-ui, sans-serif; margin: 0; padding: 1rem; }
#review-header { padding: 0.5rem 1rem; background: #f4f4f4; border-bottom: 1px solid #ddd; }
.week-grid { display: grid; grid-template-columns: 4rem repeat(7, 1fr); gap: 1px; background: #ddd; }
.week-grid .cell { background: white; min-height: 2rem; }
.session-block { position: absolute; background: #4a90e2; color: white; border-radius: 4px; padding: 2px 4px; font-size: 0.8rem; }
.banner-error { background: #fee; border: 1px solid #c33; padding: 0.5rem; margin: 0.5rem 0; }
```

- [ ] **Step 4: Smoke test — Zola build excludes the page**

Run: `zola build` (from repo root).
Expected: succeeds. `public/` contains no `_admin` directory.

Run: `zola serve --drafts`, open `http://127.0.0.1:1111/_admin/review/`.
Expected: page loads (even if JS 404s for now — that's the next task).

- [ ] **Step 5: Commit**

```bash
git add content/_admin/review.md templates/admin/review.html static/css/admin/review.css
git commit -m "feat(admin): add Zola draft page for schedule reviewer"
```

## Task 12: Client foundation — `api.mjs`, `schema.mjs`, `time.mjs`, `store.mjs`

**Files:**
- Create: `static/js/review/api.mjs`
- Create: `static/js/review/schema.mjs`
- Create: `static/js/review/time.mjs`
- Create: `static/js/review/store.mjs`

- [ ] **Step 1: Write `api.mjs`**

```javascript
// static/js/review/api.mjs
const BASE = "http://127.0.0.1:4317";

export async function getPools() {
  const r = await fetch(`${BASE}/pools`);
  if (!r.ok) throw new Error(`pools: ${r.status}`);
  return r.json();
}

export async function getPool(slug) {
  const r = await fetch(`${BASE}/pools/${slug}`);
  if (!r.ok) throw new Error(`pool ${slug}: ${r.status}`);
  return r.json();
}

export async function savePool(slug, body) {
  const r = await fetch(`${BASE}/pools/${slug}/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await r.json().catch(() => ({}));
  return { status: r.status, body: json };
}

export async function getHealth() {
  try {
    const r = await fetch(`${BASE}/health`);
    return r.ok;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: Write `schema.mjs`**

```javascript
// static/js/review/schema.mjs — mirrors src/schedules/schema.py
export const SESSION_TYPES = ["lap_swim", "family_swim", "senior_swim", "lessons"];
export const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

export function validSession(s) {
  if (!DAYS.includes(s.day)) return "bad day";
  if (!SESSION_TYPES.includes(s.type)) return "bad type";
  if (!/^\d{2}:\d{2}$/.test(s.start)) return "bad start";
  if (!/^\d{2}:\d{2}$/.test(s.end)) return "bad end";
  if (s.end <= s.start) return "end must be after start";
  return null;
}
```

- [ ] **Step 3: Write `time.mjs`**

```javascript
// static/js/review/time.mjs
export { nowInPacific } from "/js/helpers/board.mjs";
```

- [ ] **Step 4: Write `store.mjs`**

```javascript
// static/js/review/store.mjs — minimal pub-sub for the editor
export function createStore(initial) {
  let state = initial;
  const subs = new Set();
  return {
    get: () => state,
    set: (next) => { state = typeof next === "function" ? next(state) : next; subs.forEach(fn => fn(state)); },
    subscribe: (fn) => { subs.add(fn); return () => subs.delete(fn); },
  };
}
```

- [ ] **Step 5: Smoke test**

Run: `node --input-type=module -e "import('./static/js/review/schema.mjs').then(m => console.log(m.validSession({day:'monday',type:'lap_swim',start:'07:30',end:'08:30'})))"`
Expected: `null`.

- [ ] **Step 6: Commit**

```bash
git add static/js/review/api.mjs static/js/review/schema.mjs static/js/review/time.mjs static/js/review/store.mjs
git commit -m "feat(review): add client foundation modules (api, schema, time, store)"
```

## Task 13: Roster — `index.mjs`

**Files:**
- Create: `static/js/review/index.mjs`

- [ ] **Step 1: Implement**

```javascript
// static/js/review/index.mjs
import { getHealth, getPools } from "./api.mjs";

async function render() {
  const header = document.getElementById("review-header");
  const main = document.getElementById("review-main");

  const healthy = await getHealth();
  header.innerHTML = healthy
    ? `<span style="color:green">Review server: ok</span>`
    : `<div class="banner-error">Review server unreachable. Run <code>devenv up admin</code> in a terminal.</div>`;

  if (!healthy) return;

  // If query string has ?slug= route to the pool editor; otherwise show roster.
  const params = new URLSearchParams(window.location.search);
  const slug = params.get("slug");
  if (slug) {
    const { renderPool } = await import("./pool.mjs");
    return renderPool(slug, main);
  }

  const pools = await getPools();
  main.innerHTML = `
    <h1>Pools</h1>
    <table>
      <thead><tr><th>slug</th><th></th></tr></thead>
      <tbody>
        ${pools.map(p => `<tr><td>${p.slug}</td><td><a href="?slug=${p.slug}">edit</a></td></tr>`).join("")}
      </tbody>
    </table>`;
}

render();
```

- [ ] **Step 2: Manual smoke**

Open `http://127.0.0.1:1111/_admin/review/` with `devenv up admin` running. Expected: health banner green, table of pool slugs.

- [ ] **Step 3: Commit**

```bash
git add static/js/review/index.mjs
git commit -m "feat(review): add roster page with health banner"
```

## Task 14: Pool editor — `pool.mjs` + `grid.mjs` + `closures.mjs`

**Files:**
- Create: `static/js/review/pool.mjs`
- Create: `static/js/review/grid.mjs`
- Create: `static/js/review/closures.mjs`

- [ ] **Step 1: `grid.mjs` — pure render of a week grid**

```javascript
// static/js/review/grid.mjs
import { DAYS } from "./schema.mjs";

export function renderGrid(sessions, onClickBlock, onClickCell) {
  const container = document.createElement("div");
  container.className = "week-grid-wrap";
  container.style.position = "relative";

  const grid = document.createElement("div");
  grid.className = "week-grid";
  const hours = [];
  for (let h = 6; h <= 22; h++) hours.push(h);

  // header row
  grid.appendChild(headerCell(""));
  for (const day of DAYS.slice(0, 7)) grid.appendChild(headerCell(day.slice(0, 3)));
  for (const h of hours) {
    grid.appendChild(headerCell(`${String(h).padStart(2, "0")}:00`));
    for (const day of DAYS.slice(0, 7)) {
      const cell = document.createElement("div");
      cell.className = "cell";
      cell.dataset.day = day;
      cell.dataset.hour = h;
      cell.addEventListener("click", () => onClickCell(day, h));
      grid.appendChild(cell);
    }
  }
  container.appendChild(grid);

  for (const s of sessions) {
    const block = sessionBlock(s);
    block.addEventListener("click", (e) => { e.stopPropagation(); onClickBlock(s); });
    container.appendChild(block);
  }
  return container;
}

function headerCell(text) {
  const d = document.createElement("div");
  d.className = "cell header";
  d.textContent = text;
  return d;
}

function sessionBlock(s) {
  const [sh, sm] = s.start.split(":").map(Number);
  const [eh, em] = s.end.split(":").map(Number);
  const topPct = ((sh - 6) * 60 + sm) / ((22 - 6) * 60) * 100;
  const heightPct = ((eh - sh) * 60 + (em - sm)) / ((22 - 6) * 60) * 100;
  const dayIdx = DAYS.indexOf(s.day);
  const block = document.createElement("div");
  block.className = "session-block";
  block.style.top = `calc(${topPct}% + 1.5rem)`;
  block.style.left = `calc(4rem + ${dayIdx} * ((100% - 4rem) / 7))`;
  block.style.width = `calc((100% - 4rem) / 7 - 2px)`;
  block.style.height = `${heightPct}%`;
  block.textContent = `${s.type} ${s.start}–${s.end}`;
  return block;
}
```

- [ ] **Step 2: `closures.mjs` — list with add/remove**

```javascript
// static/js/review/closures.mjs
export function renderClosures(closures, onChange) {
  const wrap = document.createElement("div");
  wrap.innerHTML = `<h3>Closures</h3><div class="closures-list"></div>
    <button class="add-closure">+ add closure</button>`;
  const list = wrap.querySelector(".closures-list");
  closures.forEach((c, i) => {
    const row = document.createElement("div");
    row.innerHTML = `
      <input value="${c.start}" data-field="start">
      <input value="${c.end}" data-field="end">
      <input value="${c.reason}" data-field="reason">
      <button data-i="${i}">x</button>`;
    row.querySelectorAll("input").forEach(input => {
      input.addEventListener("change", () => {
        closures[i][input.dataset.field] = input.value;
        onChange(closures);
      });
    });
    row.querySelector("button").addEventListener("click", () => {
      closures.splice(i, 1);
      onChange(closures);
    });
    list.appendChild(row);
  });
  wrap.querySelector(".add-closure").addEventListener("click", () => {
    closures.push({ start: "2026-01-01", end: "2026-01-01", reason: "" });
    onChange(closures);
  });
  return wrap;
}
```

- [ ] **Step 3: `pool.mjs` — assembles grid + closures + save bar; owns etag**

```javascript
// static/js/review/pool.mjs
import { getPool, savePool } from "./api.mjs";
import { renderGrid } from "./grid.mjs";
import { renderClosures } from "./closures.mjs";
import { createStore } from "./store.mjs";
import { validSession } from "./schema.mjs";

export async function renderPool(slug, main) {
  const bundle = await getPool(slug);
  const store = createStore({
    metadata: bundle.metadata,
    sessions: [...bundle.sessions],
    closures: [...bundle.closures],
    etag: bundle.etag,
    fullyVerified: false,
    summary: "",
  });

  main.innerHTML = `
    <h1>${slug}</h1>
    <div class="metadata-strip"></div>
    <div class="grid-wrap"></div>
    <div class="closures-wrap"></div>
    <div class="save-bar">
      <label><input type="checkbox" id="verify"> I have verified this against the PDF</label>
      <button id="save">Save</button>
      <span id="status"></span>
    </div>`;

  const gridWrap = main.querySelector(".grid-wrap");
  const closuresWrap = main.querySelector(".closures-wrap");

  function redraw() {
    const { sessions, closures } = store.get();
    gridWrap.innerHTML = "";
    gridWrap.appendChild(renderGrid(
      sessions,
      (s) => editSession(s),
      (day, hour) => addSession(day, hour),
    ));
    closuresWrap.innerHTML = "";
    closuresWrap.appendChild(renderClosures(closures, (next) => {
      store.set(prev => ({ ...prev, closures: [...next] }));
    }));
  }

  function addSession(day, hour) {
    const start = `${String(hour).padStart(2, "0")}:00`;
    const end = `${String(hour + 1).padStart(2, "0")}:00`;
    const s = { day, type: "lap_swim", start, end };
    store.set(prev => ({ ...prev, sessions: [...prev.sessions, s] }));
  }

  function editSession(s) {
    const newEnd = prompt(`End time for ${s.day} ${s.start}?`, s.end);
    if (!newEnd) return;
    store.set(prev => ({
      ...prev,
      sessions: prev.sessions.map(x => x === s ? { ...x, end: newEnd } : x),
    }));
  }

  store.subscribe(redraw);
  redraw();

  main.querySelector("#save").addEventListener("click", async () => {
    const state = store.get();
    for (const s of state.sessions) {
      const err = validSession(s);
      if (err) { main.querySelector("#status").textContent = `invalid session: ${err}`; return; }
    }
    const { status, body } = await savePool(slug, {
      etag: state.etag,
      metadata: state.metadata,
      sessions: state.sessions,
      closures: state.closures,
      summary: state.summary,
      fully_verified: main.querySelector("#verify").checked,
      save_anyway: false,
    });
    if (status === 409) {
      main.querySelector("#status").innerHTML = `Stale — <button id="reload">reload</button>`;
      main.querySelector("#reload").addEventListener("click", () => window.location.reload());
      return;
    }
    if (status !== 200) {
      main.querySelector("#status").textContent = `error ${status}: ${JSON.stringify(body)}`;
      return;
    }
    main.querySelector("#status").textContent = "saved";
    store.set(prev => ({ ...prev, etag: body.new_etag }));
  });
}
```

- [ ] **Step 4: Manual smoke**

Open `http://127.0.0.1:1111/_admin/review/?slug=hamilton-pool`. Expected: grid renders sessions; clicking empty cell adds a session; clicking a session edits end time; save works.

- [ ] **Step 5: Commit**

```bash
git add static/js/review/pool.mjs static/js/review/grid.mjs static/js/review/closures.mjs
git commit -m "feat(review): add pool editor with week grid and closures list"
```

## Task 15: PDF pane + provider diff — `pdf.mjs`, `diff.mjs`

**Files:**
- Create: `static/js/review/pdf.mjs`
- Create: `static/js/review/diff.mjs`
- Modify: `static/js/review/pool.mjs` (wire them in)

- [ ] **Step 1: `pdf.mjs`**

```javascript
// static/js/review/pdf.mjs
export function renderPdfPane(slug, pdfInfo) {
  const wrap = document.createElement("div");
  if (!pdfInfo) {
    wrap.innerHTML = `<em>No PDF cached for ${slug}.</em>`;
    return wrap;
  }
  wrap.innerHTML = `
    <embed src="http://127.0.0.1:4317/pdfs/${slug}/${pdfInfo.filename}"
           type="application/pdf" width="100%" height="600">`;
  return wrap;
}
```

- [ ] **Step 2: `diff.mjs` (added/removed only; no `~changed`)**

```javascript
// static/js/review/diff.mjs
const SESSION_KEYS = ["day", "type", "start", "end", "pool"];
const CLOSURE_KEYS = ["start", "end", "reason"];

function keyOf(obj, keys) {
  return keys.map(k => obj[k] ?? "").join("|");
}

export function diff(reviewed, extracted, keys) {
  const rSet = new Set(reviewed.map(s => keyOf(s, keys)));
  const eSet = new Set(extracted.map(s => keyOf(s, keys)));
  const added = extracted.filter(s => !rSet.has(keyOf(s, keys)));
  const removed = reviewed.filter(s => !eSet.has(keyOf(s, keys)));
  return { added, removed };
}

export function renderDiff(reviewedSessions, reviewedClosures, providerArtifacts) {
  const wrap = document.createElement("div");
  wrap.innerHTML = "<h3>Provider diff</h3>";
  if (!providerArtifacts || Object.keys(providerArtifacts).length === 0) {
    wrap.innerHTML += `<em>No local LLM artifacts — run <code>devenv run extract --only &lt;slug&gt;</code>.</em>`;
    return wrap;
  }
  for (const [provider, payload] of Object.entries(providerArtifacts)) {
    const ses = diff(reviewedSessions, payload.sessions || [], SESSION_KEYS);
    const clo = diff(reviewedClosures, payload.closures || [], CLOSURE_KEYS);
    const row = document.createElement("div");
    row.innerHTML = `<strong>${provider}</strong>
      sessions: +${ses.added.length} added / -${ses.removed.length} removed ·
      closures: +${clo.added.length} added / -${clo.removed.length} removed`;
    wrap.appendChild(row);
  }
  return wrap;
}
```

- [ ] **Step 3: Wire into `pool.mjs`**

Add `<div class="pdf-wrap"></div>` and `<div class="diff-wrap"></div>` to the `main.innerHTML`. In `redraw()`:

```javascript
import { renderPdfPane } from "./pdf.mjs";
import { renderDiff } from "./diff.mjs";

// inside redraw():
main.querySelector(".pdf-wrap").innerHTML = "";
main.querySelector(".pdf-wrap").appendChild(renderPdfPane(slug, bundle.pdf));
main.querySelector(".diff-wrap").innerHTML = "";
main.querySelector(".diff-wrap").appendChild(
  renderDiff(store.get().sessions, store.get().closures, bundle.artifacts_by_provider || {})
);
```

- [ ] **Step 4: Node smoke for `diff.mjs`**

```bash
node --input-type=module -e "
import('./static/js/review/diff.mjs').then(m => {
  console.log(m.diff(
    [{day:'monday',type:'lap_swim',start:'07:30',end:'08:30'}],
    [{day:'monday',type:'lap_swim',start:'07:30',end:'08:30'},
     {day:'tuesday',type:'lap_swim',start:'07:30',end:'08:30'}],
    ['day','type','start','end','pool']
  ));
});"
```

Expected: `{ added: [ {...tuesday...} ], removed: [] }`.

- [ ] **Step 5: Commit**

```bash
git add static/js/review/pdf.mjs static/js/review/diff.mjs static/js/review/pool.mjs
git commit -m "feat(review): add PDF pane and provider-diff panel"
```

## Task 16: Isolation + import-graph tests

**Files:**
- Create: `tests/test_reviewer_isolation.py`
- Create: `tests/test_review_import_graph.py`

- [ ] **Step 1: Write isolation test**

```python
# tests/test_reviewer_isolation.py
import shutil
import subprocess
from pathlib import Path


def test_zola_build_excludes_admin(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    work = tmp_path / "site"
    shutil.copytree(repo, work, ignore=shutil.ignore_patterns(".git", "target", "node_modules", "public"))
    subprocess.run(["zola", "build"], cwd=work, check=True)
    public = work / "public"
    for path in public.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore") if path.suffix in (".html", ".js", ".css", ".xml") else ""
        for token in ("_admin", "/review/", "review_server"):
            assert token not in text, f"{path} leaks '{token}'"
```

- [ ] **Step 2: Write import-graph test**

```python
# tests/test_review_import_graph.py
import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            for n in node.names:
                out.add(n.name)
    return out


def test_worker_does_not_import_review_modules():
    root = Path(__file__).resolve().parents[1]
    for py in (root / "worker").rglob("*.py"):
        imports = _imports(py)
        assert "schedules.review_server" not in imports, py
        assert "schedules.review_project" not in imports, py


def test_pipeline_does_not_import_review_modules():
    root = Path(__file__).resolve().parents[1]
    imports = _imports(root / "src" / "schedules" / "pipeline.py")
    assert "schedules.review_server" not in imports
    assert "review_server" not in imports
    assert ".review_server" not in imports
```

- [ ] **Step 3: Run both tests**

Run: `uv run pytest tests/test_reviewer_isolation.py tests/test_review_import_graph.py -v`
Expected: PASS.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_reviewer_isolation.py tests/test_review_import_graph.py
git commit -m "test(review): enforce Zola build isolation and import-graph separation"
```

---

# Remaining tests (bundle with PR 2)

The following tests are listed in the spec's **Testing** section; fold them in as one additional commit once the main feature is working. Each follows the same `_setup` + fixture pattern as prior tests.

## Task 17: Delta, metadata, Pacific-midnight, corrupt-frontmatter tests

**Files:**
- Create: `tests/conftest_reviewer.py` (shared helper; imported explicitly by each test)
- Create: `tests/test_review_delta.py`
- Create: `tests/test_review_metadata.py`
- Create: `tests/test_review_pacific_midnight.py`
- Create: `tests/test_review_corrupt_frontmatter.py`

- [ ] **Step 0: Write the shared setup helper (extract the duplicated fixture)**

```python
# tests/conftest_reviewer.py
import json
import threading
import urllib.request
from pathlib import Path

from schedules.review_server import ReviewServer, make_handler


VALID_WEEK = [
    {"day": d, "type": "lap_swim", "start": "07:30", "end": "08:30"}
    for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
]


def seed_repo(tmp_path: Path) -> Path:
    (tmp_path / "content" / "spots").mkdir(parents=True)
    (tmp_path / "content" / "spots" / "hamilton-pool.md").write_text(
        '+++\ntitle = "Hamilton Pool"\nsubtype = "indoor"\nwebsite = "https://example.com"\n\n'
        '[extra]\nschedule_effective = "2026-03-17"\n\n'
        '[[extra.sessions]]\nday = "monday"\ntype = "lap_swim"\nstart = "07:30"\nend = "08:30"\n+++\n\n'
    )
    (tmp_path / "data" / "pdfs" / "hamilton-pool").mkdir(parents=True)
    sha = "a" * 64
    (tmp_path / "data" / "pdfs" / "hamilton-pool" / f"2026-04-18-{sha[:12]}.pdf").write_bytes(b"%PDF")
    return tmp_path


def start_server(tmp_path: Path) -> tuple[ReviewServer, int]:
    srv = ReviewServer(("127.0.0.1", 0), make_handler(repo_root=tmp_path))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def get_bundle(port: int, slug: str) -> dict:
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/pools/{slug}").read())


def save(port: int, slug: str, body: dict) -> tuple[int, dict]:
    import urllib.error
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/pools/{slug}/save",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
```

- [ ] **Step 1: Delta test — >20% session swing**

```python
# tests/test_review_delta.py
from tests.conftest_reviewer import VALID_WEEK, get_bundle, save, seed_repo, start_server


def test_shrinking_to_two_sessions_warns_then_save_anyway(tmp_path):
    seed_repo(tmp_path)
    srv, port = start_server(tmp_path)
    try:
        etag = get_bundle(port, "hamilton-pool")["etag"]
        status, body = save(port, "hamilton-pool", {
            "etag": etag,
            "metadata": {"title": "Hamilton Pool", "subtype": "indoor",
                         "website": "https://example.com", "schedule_effective": "2026-03-17"},
            "sessions": VALID_WEEK,
            "closures": [],
            "summary": "",
            "fully_verified": False,
            "save_anyway": False,
        })
        assert status == 200
        etag = body["new_etag"]

        status, body = save(port, "hamilton-pool", {
            "etag": etag,
            "metadata": {"title": "Hamilton Pool", "subtype": "indoor",
                         "website": "https://example.com", "schedule_effective": "2026-03-17"},
            "sessions": VALID_WEEK[:2],  # shrink from 5 → 2 → >50% swing
            "closures": [],
            "summary": "",
            "fully_verified": False,
            "save_anyway": False,
        })
        assert status == 200
        assert body.get("written") is False
        assert body.get("warnings")

        status, body = save(port, "hamilton-pool", {
            "etag": etag,
            "metadata": {"title": "Hamilton Pool", "subtype": "indoor",
                         "website": "https://example.com", "schedule_effective": "2026-03-17"},
            "sessions": VALID_WEEK[:2],
            "closures": [],
            "summary": "",
            "fully_verified": False,
            "save_anyway": True,
        })
        assert status == 200
        assert body.get("ok") is True
    finally:
        srv.shutdown(); srv.server_close()
```

This test will require implementing the delta-warning branch in `_save` using `src/schedules/delta.py`. If not already wired, add a call after validate that returns `{warnings, written: False}` when thresholds fire and `save_anyway` is false.

- [ ] **Step 2: Metadata test — `fully_verified` gates `last_verified_at`**

```python
# tests/test_review_metadata.py
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.conftest_reviewer import VALID_WEEK, get_bundle, save, seed_repo, start_server


def test_last_verified_at_only_bumps_when_fully_verified(tmp_path):
    seed_repo(tmp_path)
    srv, port = start_server(tmp_path)
    try:
        etag = get_bundle(port, "hamilton-pool")["etag"]
        meta = {"title": "Hamilton Pool", "subtype": "indoor",
                "website": "https://example.com", "schedule_effective": "2026-03-17"}
        status, body = save(port, "hamilton-pool", {
            "etag": etag, "metadata": meta, "sessions": VALID_WEEK, "closures": [],
            "summary": "", "fully_verified": False, "save_anyway": True,
        })
        assert status == 200
        md = (tmp_path / "content" / "spots" / "hamilton-pool.md").read_text()
        assert "last_verified_at" not in md

        etag = body["new_etag"]
        status, body = save(port, "hamilton-pool", {
            "etag": etag, "metadata": meta, "sessions": VALID_WEEK, "closures": [],
            "summary": "", "fully_verified": True, "save_anyway": True,
        })
        assert status == 200
        md = (tmp_path / "content" / "spots" / "hamilton-pool.md").read_text()
        today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        assert f'last_verified_at = "{today}"' in md
    finally:
        srv.shutdown(); srv.server_close()
```

- [ ] **Step 3: Pacific-midnight test**

```python
# tests/test_review_pacific_midnight.py
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tests.conftest_reviewer import VALID_WEEK, get_bundle, save, seed_repo, start_server


def test_save_at_2359_pacific_uses_pacific_date_not_utc(tmp_path):
    seed_repo(tmp_path)
    srv, port = start_server(tmp_path)
    try:
        etag = get_bundle(port, "hamilton-pool")["etag"]
        fixed = datetime(2026, 4, 18, 23, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
        with patch("schedules.review_server.datetime") as m:
            m.now.return_value = fixed
            status, body = save(port, "hamilton-pool", {
                "etag": etag,
                "metadata": {"title": "Hamilton Pool", "subtype": "indoor",
                             "website": "https://example.com", "schedule_effective": "2026-03-17"},
                "sessions": VALID_WEEK, "closures": [],
                "summary": "", "fully_verified": True, "save_anyway": True,
            })
            assert status == 200
        snaps = list((tmp_path / "data" / "reviewed-snapshots" / "hamilton-pool").glob("*.json"))
        assert len(snaps) == 1
        import json as _json
        env = _json.loads(snaps[0].read_text())
        assert env["reviewed_at"] == "2026-04-18"
    finally:
        srv.shutdown(); srv.server_close()
```

If the `_today_pacific` helper in `review_server.py` uses `datetime.now(...)` directly, the patch above works. If it imports `datetime` differently, adjust the patch target accordingly.

- [ ] **Step 4: Corrupt-frontmatter test**

```python
# tests/test_review_corrupt_frontmatter.py
import urllib.error
import urllib.request

from tests.conftest_reviewer import seed_repo, start_server


def test_missing_closing_frontmatter_delimiter_returns_error(tmp_path):
    seed_repo(tmp_path)
    # Corrupt the MD: open delimiter, no close.
    md = tmp_path / "content" / "spots" / "hamilton-pool.md"
    md.write_text('+++\ntitle = "X"\n[extra]\nschedule_effective = "2026-03-17"\n')

    srv, port = start_server(tmp_path)
    try:
        import pytest
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/pools/hamilton-pool")
        assert ei.value.code >= 500
    finally:
        srv.shutdown(); srv.server_close()
```

Implement handler-side error handling in `_pool_bundle` to catch `ValueError` from `_split_frontmatter` and return 500 with a clear message.

- [ ] **Step 5: Run all four test files**

Run: `uv run pytest tests/test_review_delta.py tests/test_review_metadata.py tests/test_review_pacific_midnight.py tests/test_review_corrupt_frontmatter.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_review_delta.py tests/test_review_metadata.py tests/test_review_pacific_midnight.py tests/test_review_corrupt_frontmatter.py
git commit -m "test(review): delta, metadata, Pacific midnight, corrupt-frontmatter coverage"
```

## Task 18: JS unit tests (via Node)

Spec lists `tests/js/test_schema.mjs`, `test_grid.mjs`, `test_diff.mjs`, `test_409.mjs`. Keep them tiny — pure-function checks, no DOM.

**Files:**
- Create: `tests/js/test_schema.mjs`
- Create: `tests/js/test_diff.mjs`
- Create: `tests/js/run.sh`

- [ ] **Step 1: `test_schema.mjs`**

```javascript
// tests/js/test_schema.mjs
import { validSession } from "../../static/js/review/schema.mjs";
import assert from "node:assert/strict";

assert.equal(validSession({day:"monday",type:"lap_swim",start:"07:30",end:"08:30"}), null);
assert.equal(validSession({day:"funday",type:"lap_swim",start:"07:30",end:"08:30"}), "bad day");
assert.equal(validSession({day:"monday",type:"laps",start:"07:30",end:"08:30"}), "bad type");
assert.equal(validSession({day:"monday",type:"lap_swim",start:"08:30",end:"07:30"}), "end must be after start");
console.log("test_schema ok");
```

- [ ] **Step 2: `test_diff.mjs`**

```javascript
// tests/js/test_diff.mjs
import { diff } from "../../static/js/review/diff.mjs";
import assert from "node:assert/strict";

const keys = ["day","type","start","end","pool"];
const r = diff(
  [{day:"monday",type:"lap_swim",start:"07:30",end:"08:30"}],
  [{day:"monday",type:"lap_swim",start:"07:30",end:"08:30"},
   {day:"tuesday",type:"lap_swim",start:"07:30",end:"08:30"}],
  keys,
);
assert.equal(r.added.length, 1);
assert.equal(r.added[0].day, "tuesday");
assert.equal(r.removed.length, 0);
console.log("test_diff ok");
```

- [ ] **Step 3: `run.sh`**

```bash
#!/usr/bin/env bash
# tests/js/run.sh
set -euo pipefail
for f in tests/js/test_*.mjs; do
  node "$f"
done
```

Mark executable: `chmod +x tests/js/run.sh`.

- [ ] **Step 4: Run**

Run: `bash tests/js/run.sh`
Expected: both tests print `ok` and exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/js/ static/js/review/
git commit -m "test(review): add Node unit tests for schema and diff modules"
```

---

# Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Manual smoke per spec §Testing → Manual smoke test**

1. `devenv up admin`
2. Open `http://127.0.0.1:1111/_admin/review/`
3. Pick a pool. Shift a session by 15 minutes. Leave checkbox unchecked. Save.
4. Verify: MD updated, snapshot created, `last_verified_at` unchanged.
5. Check verify box. Save. Confirm `last_verified_at` bumped to today Pacific.
6. Revert edit. Save. Confirm files revert, comments preserved.
7. `devenv up` (default group); `zola build`; confirm `public/` has no `_admin`.

- [ ] **Step 3: Commit final state**

```bash
git status
# if clean, proceed; if any uncommitted smoke changes, commit or discard explicitly
```
