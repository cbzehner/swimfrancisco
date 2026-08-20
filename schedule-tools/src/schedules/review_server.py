from __future__ import annotations

import csv
import html
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from io import StringIO
from urllib.parse import unquote, urlparse

from .paths import CONTENT_SPOTS_DIR, DATA_DIR, reviewed_path
from .direct_sources import DirectSourceError, extract_direct
from .fetch import FetchError, fetch_pdf
from .pipeline import SourceMode, parse_provider, run_pipeline
from .registry import load_registry
from .review import FinalizeError, draft_envelope, finalize_draft, find_review_candidates


UI_DIR = Path(__file__).resolve().parent / "review_ui"
REPO_ROOT = Path(__file__).resolve().parents[3]
BRAND_DIR = REPO_ROOT / "static"
MAX_BODY_BYTES = 1_000_000


class ReviewApp:
    def __init__(self, *, data_root: Path = DATA_DIR, content_spots_dir: Path = CONTENT_SPOTS_DIR):
        self.data_root = data_root
        self.content_spots_dir = content_spots_dir

    def candidates(self):
        candidates = find_review_candidates(data_root=self.data_root)
        if self.data_root.resolve() == DATA_DIR.resolve():
            changed_dirs = _changed_review_dirs()
            candidates = [candidate for candidate in candidates if candidate.review_dir.resolve() in changed_dirs]
        latest_by_slug = {
            candidate.slug: candidate
            for candidate in sorted(candidates, key=lambda candidate: (candidate.fetch_date, candidate.review_dir.name))
        }
        priority = {"koret-center": 0, "pomeroy-pool": 1}
        return sorted(latest_by_slug.values(), key=lambda candidate: (priority.get(candidate.slug, 2), candidate.fetch_date, candidate.slug))

    def candidate(self, slug: str):
        return next((candidate for candidate in self.candidates() if candidate.slug == slug), None)

    def list_reviews(self) -> list[dict]:
        return [
            {
                "slug": candidate.slug,
                "fetch_date": candidate.fetch_date,
                "source_kind": candidate.source_path.suffix.removeprefix("."),
            }
            for candidate in self.candidates()
        ]

    def review(self, slug: str) -> dict:
        candidate = self.candidate(slug)
        if candidate is None:
            raise LookupError(f"No pending review for {slug}.")
        return {
            "candidate": {
                **asdict(candidate),
                "review_dir": str(candidate.review_dir),
                "source_path": str(candidate.source_path),
                "source_kind": candidate.source_path.suffix.removeprefix("."),
            },
            "envelope": draft_envelope(candidate=candidate),
        }

    def check_source(self, slug: str) -> dict:
        candidate = self.candidate(slug)
        if candidate is None:
            raise LookupError(f"No pending review for {slug}.")
        identity = current_source_identity(slug)
        return {
            "status": "current" if identity == candidate.pdf_sha256 else "changed",
            "source_identity": identity,
        }

    def refresh(self, slug: str) -> dict:
        candidate = self.candidate(slug)
        if candidate is None:
            raise LookupError(f"No pending review for {slug}.")
        if current_source_identity(slug) == candidate.pdf_sha256:
            return self.review(slug)
        entry = next((entry for entry in load_registry() if entry.slug == slug), None)
        if entry is None:
            raise LookupError(f"Unknown registry slug: {slug}.")
        source_mode: SourceMode = "direct"
        if entry.source_kind == "sfrecpark_pdf":
            source_mode = parse_provider(os.getenv("SCHEDULES_PROVIDER", "gemini"))
        exit_code, _, results = run_pipeline(
            slugs=[slug],
            source_mode=source_mode,
            compare_with=None,
            force=True,
        )
        if exit_code != 0:
            raise RuntimeError(str(results[0]))
        return self.review(slug)

    def save(self, slug: str, envelope: dict, source_identity: str) -> Path:
        candidate = self.candidate(slug)
        if candidate is None:
            raise LookupError(f"No pending review for {slug}.")
        if envelope.get("slug") != slug or envelope.get("pdf_sha256") != candidate.pdf_sha256:
            raise FinalizeError("Review identity does not match the pending source.")
        if source_identity != candidate.pdf_sha256 or current_source_identity(slug) != source_identity:
            raise FinalizeError("Official source changed after this review opened. Refresh before saving.")

        target = reviewed_path(
            candidate.slug,
            candidate.fetch_date,
            candidate.pdf_sha256,
            root=self.data_root,
        )
        envelope = {**envelope, "attested_by": "human"}
        target.write_text(json.dumps(envelope, indent=2) + "\n")
        try:
            return finalize_draft(
                reviewed_json_path=target,
                content_spots_dir=self.content_spots_dir,
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise


def make_handler(app: ReviewApp):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/api/reviews":
                    self._json(200, {"reviews": app.list_reviews()})
                elif path.startswith("/api/reviews/"):
                    self._json(200, app.review(path.removeprefix("/api/reviews/")))
                elif path.startswith("/source/"):
                    slug = path.removeprefix("/source/")
                    candidate = app.candidate(slug)
                    if candidate is None:
                        self._json(404, {"error": "Pending review not found."})
                    elif candidate.source_path.suffix == ".csv":
                        self._csv_schedule(candidate.source_path)
                    elif candidate.source_path.suffix == ".html":
                        review = app.review(slug)
                        source_url = review["envelope"]["source_pdf_url"]
                        self._html_page(candidate.source_path.read_text(), source_url, "Captured source", review["envelope"]["payload"])
                    else:
                        self._file(candidate.source_path)
                elif path.startswith("/brand/"):
                    self._file(BRAND_DIR / path.removeprefix("/brand/"), root=BRAND_DIR)
                elif path.startswith("/fonts/"):
                    self._file(BRAND_DIR / path.removeprefix("/"), root=BRAND_DIR)
                elif path in {"/", "/index.html"}:
                    self._file(UI_DIR / "index.html", root=UI_DIR)
                elif path in {"/review.css", "/review.js"}:
                    self._file(UI_DIR / path.removeprefix("/"), root=UI_DIR)
                else:
                    self._json(404, {"error": "Not found."})
            except LookupError as exc:
                self._json(404, {"error": str(exc)})

        def do_POST(self) -> None:
            path = unquote(urlparse(self.path).path)
            if not path.startswith("/api/reviews/"):
                self._json(404, {"error": "Not found."})
                return
            try:
                slug_and_action = path.removeprefix("/api/reviews/")
                if slug_and_action.endswith("/check-source"):
                    self._json(200, app.check_source(slug_and_action.removesuffix("/check-source")))
                    return
                if slug_and_action.endswith("/refresh"):
                    review = app.refresh(slug_and_action.removesuffix("/refresh"))
                    self._json(200, review)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise ValueError("Review body must be between 1 byte and 1 MB.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or not isinstance(body.get("envelope"), dict):
                    raise ValueError("Review body must contain an envelope object.")
                if not body.get("attested"):
                    raise ValueError("Confirm that every source cell was checked before saving.")
                source_identity = body.get("source_identity")
                if not isinstance(source_identity, str):
                    raise ValueError("Review body must contain a verified source identity.")
                app.save(slug_and_action, body.get("envelope"), source_identity)
                self._json(200, {"ok": True})
            except (DirectSourceError, FetchError, FinalizeError, LookupError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def _json(self, status: int, value: dict) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, *, root: Path | None = None) -> None:
            resolved = path.resolve()
            if root is not None and not resolved.is_relative_to(root.resolve()):
                self._json(404, {"error": "Not found."})
                return
            try:
                body = resolved.read_bytes()
            except OSError:
                self._json(404, {"error": "File not found."})
                return
            self.send_response(200)
            content_type = "text/plain; charset=utf-8" if resolved.suffix == ".csv" else (mimetypes.guess_type(resolved.name)[0] or "application/octet-stream")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _csv_schedule(self, path: Path) -> None:
            try:
                source = path.read_text()
            except OSError:
                self._json(404, {"error": "File not found."})
                return
            sections = _csv_sections(source)
            tables = []
            for name, rows in sections:
                body = "".join(
                    "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
                    for row in rows
                )
                tables.append(
                    f'<section id="{html.escape(name.lower())}"><h2>{html.escape(name)}</h2>'
                    f'<div class="table-scroll"><table>{body}</table></div></section>'
                )
            document = f"""<!doctype html><html><head><meta charset="utf-8"><style>
                :root {{ color-scheme: light; --paper:#f8f1de; --ink:#1a1812; --teal:#14535f; --rule:#8a7a52; }}
                * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }}
                body {{ margin:0; padding:16px; background:var(--paper); color:var(--ink); font:13px ui-monospace,SFMono-Regular,Menlo,monospace; }}
                section {{ margin:0 0 28px; scroll-margin-top:12px; }}
                h2 {{ display:inline-block; position:sticky; left:0; margin:0; padding:8px 12px; background:var(--teal); color:white; font:700 14px system-ui,sans-serif; text-transform:uppercase; letter-spacing:.08em; }}
                .table-scroll {{ overflow-x:auto; border:2px solid var(--ink); background:white; }}
                table {{ border-collapse:separate; border-spacing:0; min-width:max-content; }}
                td {{ min-width:92px; max-width:220px; height:38px; padding:7px 9px; border-right:1px solid var(--rule); border-bottom:1px solid var(--rule); white-space:pre-wrap; vertical-align:top; }}
                tr:first-child td {{ position:sticky; top:0; z-index:2; background:#c2d6db; font-weight:700; }}
                td:first-child {{ position:sticky; left:0; z-index:1; min-width:118px; background:#ede0c4; font-weight:700; }}
                tr:first-child td:first-child {{ z-index:3; background:#d39b2a; }}
            </style></head><body>{''.join(tables)}</body></html>"""
            body = document.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "script-src 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _html_page(self, source: str, source_url: str, label: str, payload: dict) -> None:
            if "24hourfitness.com" in source_url:
                self._24_hour_page(source, source_url, label)
                return
            if "ucsf.edu" in source_url:
                self._evidence_page(source, source_url, label, payload)
                return
            source = re.sub(r"<script\b[^>]*>.*?</script>", "", source, flags=re.IGNORECASE | re.DOTALL)
            source = re.sub(r"<meta\b[^>]*http-equiv=[\"']?content-security-policy[^>]*>", "", source, flags=re.IGNORECASE)
            base = f'<base href="{html.escape(source_url, quote=True)}">'
            banner = (
                '<div style="position:sticky;top:0;z-index:2147483647;padding:10px 14px;'
                'background:#d39b2a;color:#1a1812;border-bottom:2px solid #1a1812;'
                'font:700 13px system-ui,sans-serif">'
                f'{html.escape(label)}</div>'
            )
            if re.search(r"<head\b[^>]*>", source, flags=re.IGNORECASE):
                source = re.sub(r"(<head\b[^>]*>)", rf"\1{base}", source, count=1, flags=re.IGNORECASE)
            else:
                source = base + source
            if re.search(r"<body\b[^>]*>", source, flags=re.IGNORECASE):
                source = re.sub(r"(<body\b[^>]*>)", rf"\1{banner}", source, count=1, flags=re.IGNORECASE)
            else:
                source = banner + source
            body = source.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "script-src 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _evidence_page(self, source: str, source_url: str, label: str, payload: dict) -> None:
            title_match = re.search(r"<title>(.*?)</title>", source, flags=re.IGNORECASE | re.DOTALL)
            title = html.unescape(title_match.group(1)).strip() if title_match else "Official source"
            source_text = html.unescape(re.sub(r"<[^>]+>", " ", source))
            source_text = re.sub(r"\s+", " ", source_text)
            evidence = []
            for collection in ("sessions", "access_hours", "access_exceptions"):
                for row in payload.get(collection, []):
                    value = row.get("evidence")
                    if value and value not in evidence:
                        evidence.append(value)
            cards = "".join(
                '<article><p class="eyebrow">Captured text</p>'
                f'<blockquote>{html.escape(value)}</blockquote>'
                f'<p class="match">{"✓ Found in captured source" if value in source_text or value.removeprefix("Facility Hours: ") in source_text else "Needs manual confirmation"}</p></article>'
                for value in evidence
            )
            document = f"""<!doctype html><html><head><meta charset="utf-8"><style>
                :root {{ --paper:#f8f1de; --ink:#1a1812; --teal:#14535f; --ochre:#d39b2a; --rule:#8a7a52; }}
                * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px system-ui,sans-serif; }}
                .status {{ padding:10px 16px; background:var(--ochre); border-bottom:2px solid var(--ink); font-weight:700; }}
                main {{ max-width:760px; margin:0 auto; padding:clamp(22px,5vw,64px); }}
                .eyebrow {{ margin:0 0 8px; font:700 11px ui-monospace,monospace; letter-spacing:.14em; text-transform:uppercase; }}
                h1 {{ margin:0 0 34px; font-size:clamp(30px,5vw,58px); line-height:1; text-transform:uppercase; }}
                article {{ margin:0 0 22px; padding:22px; border-top:8px solid var(--teal); background:white; }}
                blockquote {{ margin:0; font-size:22px; font-weight:700; line-height:1.35; }}
                .match {{ margin:16px 0 0; color:var(--teal); font-weight:700; }}
                a {{ display:inline-block; margin-top:16px; color:var(--teal); font-weight:700; }}
            </style></head><body><div class="status">{html.escape(label)}</div><main>
                <p class="eyebrow">Official source evidence</p><h1>{html.escape(title)}</h1>{cards}
                <a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noreferrer">Open complete official page →</a>
            </main></body></html>"""
            body = document.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "script-src 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _24_hour_page(self, source: str, source_url: str, label: str) -> None:
            title_match = re.search(r"<title>(.*?)</title>", source, flags=re.IGNORECASE | re.DOTALL)
            title = html.unescape(title_match.group(1)).split("|")[0].strip() if title_match else "24 Hour Fitness"
            hours = [
                (html.unescape(day.strip()), html.unescape(hour.strip()))
                for day, hour in re.findall(
                    r'<span class="ih-days">([^<]+)</span>\s*<span class="ih-hours">([^<]+)</span>',
                    source,
                    flags=re.IGNORECASE,
                )
            ]
            hours_rows = "".join(
                f"<tr><th>{html.escape(day)}</th><td>{html.escape(hour)}</td></tr>"
                for day, hour in hours
            )
            pool = "Indoor Lap Pool" if re.search(r"Indoor\s+Lap\s+Pool", source, flags=re.IGNORECASE) else "Pool amenity not found"
            document = f"""<!doctype html><html><head><meta charset="utf-8"><style>
                :root {{ --paper:#f8f1de; --ink:#1a1812; --teal:#14535f; --ochre:#d39b2a; --rule:#8a7a52; }}
                * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px system-ui,sans-serif; }}
                .status {{ padding:10px 16px; background:var(--ochre); border-bottom:2px solid var(--ink); font-weight:700; }}
                main {{ max-width:760px; margin:0 auto; padding:clamp(22px,5vw,64px); }}
                .eyebrow {{ margin:0 0 8px; font:700 11px ui-monospace,monospace; letter-spacing:.14em; text-transform:uppercase; }}
                h1 {{ margin:0 0 38px; font-size:clamp(34px,6vw,68px); line-height:.95; text-transform:uppercase; }}
                section {{ margin:0 0 34px; border-top:8px solid var(--teal); }}
                h2 {{ margin:0; padding:14px 0 8px; font-size:22px; text-transform:uppercase; }}
                table {{ width:100%; border-collapse:collapse; background:white; }}
                th,td {{ padding:15px; border:1px solid var(--rule); text-align:left; }} th {{ width:48%; }}
                .amenity {{ padding:20px; background:#c2d6db; border:1px solid var(--teal); font-size:24px; font-weight:700; }}
                a {{ display:inline-block; margin-top:18px; color:var(--teal); font-weight:700; }}
            </style></head><body><div class="status">{html.escape(label)}</div><main>
                <p class="eyebrow">Official source evidence</p><h1>{html.escape(title)}</h1>
                <section id="club-hours"><h2>Gym hours</h2><table>{hours_rows}</table></section>
                <section><h2>Pool amenity</h2><div class="amenity">{html.escape(pool)}</div></section>
                <a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noreferrer">Open complete official page →</a>
            </main></body></html>"""
            body = document.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "script-src 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def _csv_sections(source: str) -> list[tuple[str, list[list[str]]]]:
    sections: list[tuple[str, list[list[str]]]] = []
    name: str | None = None
    lines: list[str] = []
    for line in source.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if name is not None:
                sections.append((name, list(csv.reader(StringIO("\n".join(lines))))))
            name = line[4:-4]
            lines = []
        elif name is not None:
            lines.append(line)
    if name is not None:
        sections.append((name, list(csv.reader(StringIO("\n".join(lines))))))
    return sections


def _changed_review_dirs() -> set[Path]:
    commands = (
        ["git", "diff", "--name-only", "origin/main...HEAD", "--", "data"],
        ["git", "diff", "--name-only", "--", "data"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "data"],
    )
    paths: set[Path] = set()
    for command in commands:
        result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            paths.update((REPO_ROOT / line).parent.resolve() for line in result.stdout.splitlines() if line)
    return paths


def current_source_identity(slug: str) -> str:
    entry = next((entry for entry in load_registry() if entry.slug == slug), None)
    if entry is None:
        raise LookupError(f"Unknown registry slug: {slug}.")
    with tempfile.TemporaryDirectory(prefix="swimfrancisco-source-check-") as directory:
        cache_root = Path(directory)
        if entry.source_kind == "sfrecpark_pdf":
            return fetch_pdf(entry.slug, entry.pdf_url, cache_root=cache_root).sha256
        return extract_direct(entry, cache_root=cache_root).fetch_result.sha256


def serve_review_app(*, host: str = "127.0.0.1", port: int = 0, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(ReviewApp()))
    url = f"http://{host}:{server.server_port}"
    print(f"Schedule reviewer: {url}")
    print("Press Ctrl-C to stop.")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
