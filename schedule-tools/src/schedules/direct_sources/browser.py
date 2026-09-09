from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import PoolEntry
from ..paths import REPO_ROOT
from .errors import DirectSourceError
from .http import DirectTextResponse


def read_browser_capture(entry: PoolEntry, *, root: Path = REPO_ROOT) -> tuple[DirectTextResponse, dict]:
    directory = root / "tmp/browser-capture"
    try:
        manifest = json.loads((directory / "results.json").read_text())
        matches = [item for item in manifest["results"] if item["slug"] == entry.slug]
        if manifest.get("closed") is not True or len(matches) != 1 or matches[0]["status"] != "captured":
            raise ValueError("Capture was not completed and closed")
        capture_dir = directory / entry.slug
        paths = {"source": capture_dir / "source.html", "rendered": capture_dir / "rendered.html",
                 "screenshot": capture_dir / "screenshot.png", "receipt": capture_dir / "capture.json"}
        if directory.is_symlink() or capture_dir.is_symlink() or any(path.is_symlink() for path in paths.values()):
            raise ValueError("Capture paths must not be symlinks")
        receipt = json.loads(paths["receipt"].read_text())
        if (receipt["method"] != "cloudflare_browser" or receipt["status"] != 200
                or receipt["requested_url"] != entry.pdf_url or receipt["url"].rstrip("/") != entry.pdf_url.rstrip("/")):
            raise ValueError("Capture source identity changed")
        observed = datetime.fromisoformat(receipt["captured_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 900:
            raise ValueError("Capture is stale or future-dated")
        configuration = receipt["configuration"]
        script = root / "scripts/capture-schedules.mjs"
        package = root / "node_modules/playwright-core/package.json"
        if configuration != {"script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                             "playwright_version": json.loads(package.read_text())["version"]}:
            raise ValueError("Capture configuration changed")
        content = {}
        for name in ("source", "rendered", "screenshot"):
            content[name] = paths[name].read_bytes()
            if not content[name] or hashlib.sha256(content[name]).hexdigest() != receipt["hashes"][name]:
                raise ValueError("Capture evidence hash mismatch")
        if not content["screenshot"].startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Capture screenshot is not PNG")
        text = content["source"].decode("utf-8")
        if "<html" not in text.lower() or any(marker in text.lower() for marker in (
                "<title>just a moment", "<title>access denied", "<title>attention required")):
            raise ValueError("Capture is not a usable HTML document")
        return DirectTextResponse(text, content["source"], receipt["url"]), receipt
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise DirectSourceError(f"{entry.slug}: valid current Cloudflare capture required; run scripts/capture-schedules.mjs and inspect its receipts") from None
