from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .publish import pager_job_payload
from .registry import BROWSER_SOURCES, HTTP_ACCESS_SOURCES


def run_command(arguments: list[str], root: Path, *, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, cwd=root, capture_output=True, text=True, timeout=timeout, check=False)


def checked(arguments: list[str], root: Path, command=run_command, *, timeout: int = 900) -> str:
    result = command(arguments, root, timeout=timeout)
    if result.returncode:
        # Do not copy subprocess output into public reports: it can include credentials.
        raise RuntimeError(f"{arguments[0]} command failed (exit {result.returncode})")
    return result.stdout.strip()


# Every file a build attempt captured or extracted, so a retry pays for none
# of it twice. reviewed.json is deliberately absent: a publication decision
# carried into the retry would take its slug out of the review queue and the
# retry would then never write its schedule page.
REUSABLE_CAPTURE = re.compile(r"source\.(pdf|html|xlsx|csv|sha256)|openai-[a-z0-9-]+\.json|direct-[a-z0-9-]+\.json")


def copy_extraction_cache(previous: Path, current: Path, previous_base: str, command=run_command) -> None:
    """Reuse source captures, never prior publication decisions or concurrent edits."""
    for source in (previous / "data").glob("*/*/*"):
        if source.is_symlink() or not source.is_file():
            continue
        if not REUSABLE_CAPTURE.fullmatch(source.name):
            continue
        relative = source.relative_to(previous)
        target = current / relative
        changed = checked(["git", "diff", "--name-only", previous_base, "HEAD", "--", relative.as_posix()], current, command)
        if changed or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def save_evidence(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    captures = root / "tmp/browser-capture"
    for source in captures.glob("**/*"):
        relative = source.relative_to(captures)
        if (source.is_symlink() or source.parent.is_symlink() or not source.is_file()
                or not re.fullmatch(r"results\.json|[a-z0-9-]+/(source\.html|rendered\.html|screenshot\.png|capture\.json)", relative.as_posix())):
            continue
        target = destination / "browser-capture" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for name in ("discovery-decisions.json", "discovery-report.md", "publish-pending.json", "publish-pending-report.md",
                 "extraction-report-direct.md", "extraction-report-direct.json", "extraction-report-openai.md", "extraction-report-openai.json"):
        source = root / "tmp" / name
        if source.is_file():
            shutil.copyfile(source, destination / name)
    for source in (root / "data").glob("*/*/*"):
        if source.is_symlink() or not source.is_file():
            continue
        if not re.fullmatch(r"source\.(pdf|html|csv|xlsx|sha256)|reviewed\.json|source-bundle\.json|openai-[a-z0-9-]+\.json|direct-[a-z0-9-]+\.json", source.name):
            continue
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def wait_for_deployment(root: Path, commit: str, command=run_command, *, sleep=time.sleep, now=time.monotonic) -> None:
    deadline = now() + 1200
    for _ in range(61):
        remaining = deadline - now()
        if remaining <= 0:
            break
        try:
            result = command(["node", "scripts/smoke-production.mjs", f"--expected-commit={commit}", "--browser"],
                             root, timeout=max(1, min(240, int(remaining))))
            if result.returncode == 0 and now() < deadline:
                return
        except subprocess.TimeoutExpired:
            pass
        remaining = deadline - now()
        if remaining > 0:
            sleep(min(20, remaining))
    raise RuntimeError("Live deployment did not verify within twenty minutes; commit is not reported as published")


def closure_review_document(review: dict) -> str:
    notices = json.dumps({"issues": review["issues"], "notices": review["notices"]}, ensure_ascii=False, indent=2)
    fence = "`" * (max([len(value) for value in re.findall(r"`+", notices)] + [2]) + 1)
    source_name = Path(review["source_path"]).name
    source_label = "Source HTML" if source_name == "source.html" else "Source PDF"
    return (
        f"# Closure review: {review['slug']}\n\n"
        f"Source SHA-256: `{review['source_sha256']}`\n\n"
        f"[{source_label}]({source_name})\n\n"
        "This draft contains evidence only. It does not change published hours.\n"
        "Merging this note alone does not approve or resolve the closure.\n\n"
        "- [ ] Confirm closure dates, times, and affected programs against the official source.\n"
        "- [ ] If unclear, obtain clarification; do not infer all-day or facility-wide closure.\n"
        "- [ ] Add a corrected human-reviewed snapshot and content changes, then run the full checks.\n"
        "- [ ] Verify the live result after merging, or close this PR with a reason.\n\n"
        f"## Source notices and unresolved checks\n\n{fence}json\n{notices}\n{fence}\n"
    )


def open_closure_review_prs(root: Path, evidence: Path, command=run_command) -> list[dict]:
    result = json.loads((evidence / "result.json").read_text())
    if result.get("mode") != "publish":
        return []
    builds = result.get("builds") or []
    if not builds:
        return []
    published: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for review in builds[-1].get("closure_reviews", []):
        slug, digest = review.get("slug", ""), review.get("source_sha256", "")
        relative = Path(review.get("source_path", ""))
        source_extension = "html" if slug in BROWSER_SOURCES | HTTP_ACCESS_SOURCES else "pdf"
        if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or not re.fullmatch(rf"data/{re.escape(slug)}/\d{{4}}-\d{{2}}-\d{{2}}-{digest[:12]}/source\.{source_extension}", relative.as_posix())
                or not isinstance(review.get("issues"), list) or not review["issues"]
                or not isinstance(review.get("notices"), list) or not review["notices"]):
            raise ValueError("Invalid closure review evidence")
        key = (slug, digest)
        if key in seen:
            continue
        seen.add(key)
        source = evidence / f"build-{len(builds)}" / relative
        if not source.resolve().is_relative_to(evidence.resolve()) or source.is_symlink():
            raise ValueError("Closure source escapes retained evidence")
        source_bytes = source.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != digest:
            raise ValueError("Closure source does not match its recorded hash")
        branch = f"review/closures/{slug}-{digest[:12]}"
        existing = json.loads(checked(["gh", "pr", "list", "--head", branch, "--base", "main", "--state", "all",
                                       "--json", "url,state"], root, command))
        if existing:
            published.append({"slug": slug, "source_sha256": digest, **existing[0]})
            continue
        if source_extension == "html":
            open_reviews = json.loads(checked([
                "gh", "pr", "list", "--base", "main", "--state", "open",
                "--json", "headRefName,url,state", "--limit", "1000"], root, command))
            matching = [item for item in open_reviews
                        if item.get("state") == "OPEN" and re.fullmatch(
                            rf"review/closures/{re.escape(slug)}-[a-f0-9]{{12}}", item.get("headRefName", ""))]
            if matching:
                existing_review = sorted(matching, key=lambda item: item["headRefName"])[0]
                published.append({"slug": slug, "source_sha256": digest,
                                  "url": existing_review["url"], "state": existing_review["state"]})
                continue
        remote = checked(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"], root, command)
        if remote:
            raise RuntimeError("Closure review branch exists without a PR; preserve it for operator recovery")
        checked(["git", "fetch", "--no-tags", "origin", "main"], root, command)
        base = checked(["git", "rev-parse", "FETCH_HEAD"], root, command)
        worktree = Path(tempfile.mkdtemp(prefix="swimfrancisco-closure-review-")) / "checkout"
        checked(["git", "worktree", "add", "--detach", str(worktree), base], root, command)
        target = worktree / relative
        if not target.resolve().is_relative_to(worktree.resolve()) or target.is_symlink():
            raise ValueError("Closure target escapes the review worktree")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source_bytes:
            raise ValueError("Existing source differs; refusing to overwrite it")
        sidecar = target.with_name("source.sha256")
        if sidecar.is_symlink() or (sidecar.exists() and sidecar.read_text() != f"{digest}\n"):
            raise ValueError("Existing source hash differs; preserve the operator's work")
        target.write_bytes(source_bytes)
        sidecar.write_text(f"{digest}\n")
        note = target.with_name("closure-review.md")
        if note.exists() or note.is_symlink():
            raise ValueError("Closure review note already exists; preserve the operator's work")
        note.write_text(closure_review_document(review))
        paths = [relative.as_posix(), sidecar.relative_to(worktree).as_posix(), note.relative_to(worktree).as_posix()]
        checked(["git", "add", "--", *paths], worktree, command)
        staged = checked(["git", "diff", "--cached", "--name-only"], worktree, command).splitlines()
        if not staged or not set(staged).issubset(paths):
            raise ValueError("Closure PR may contain only its source document, hash, and review note")
        checked(["git", "-c", "user.name=Schedule automation", "-c", "user.email=schedules@swimfrancisco.com",
                 "commit", "-m", f"Review unclear closure notice for {slug}"], worktree, command)
        checked(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], worktree, command)
        repository = checked(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], root, command)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository identity")
        body = worktree / "tmp/closure-pr-body.md"
        body.parent.mkdir(exist_ok=True)
        source_label = "Source HTML" if relative.name == "source.html" else "Source PDF"
        body.write_text(note.read_text().replace(f"[{source_label}]({relative.name})",
                        f"[{source_label}](https://github.com/{repository}/blob/{branch}/{relative.as_posix()})"))
        url = checked(["gh", "pr", "create", "--draft", "--base", "main", "--head", branch,
                       "--title", f"Review unclear closure notice: {slug}", "--body-file", str(body)], worktree, command)
        published.append({"slug": slug, "source_sha256": digest, "url": url, "state": "OPEN"})
    return published


def automate(root: Path, *, mode: str, run_id: str, command=run_command, verify=wait_for_deployment) -> dict:
    if mode not in {"extract-only", "publish"} or not re.fullmatch(r"\d+-\d+", run_id):
        raise ValueError("Expected a supported mode and GitHub run-attempt identifier")
    if os.environ.get("SCHEDULES_AUTOMATION_ENABLED") != "true":
        raise ValueError("Automation is disabled; operator approval is required")
    if mode == "publish" and os.environ.get("SCHEDULES_AUTO_PROJECT") == "false":
        raise ValueError("Publication kill switch is active")
    ledger = Path(os.environ.get("SCHEDULES_API_BUDGET_FILE", ""))
    if not ledger.is_absolute() or not ledger.is_file():
        raise ValueError("Automation requires an existing absolute run budget ledger")
    if checked(["git", "status", "--porcelain"], root, command):
        raise ValueError("Automation requires a clean checkout")
    evidence = root / "tmp" / "automation"
    if evidence.exists():
        raise ValueError("Automation evidence directory already exists; use a fresh checkout")
    evidence.mkdir(parents=True)
    allowance = ledger.with_name("reservation.json")
    paid_budget_status = json.loads(allowance.read_text()).get("status", "unknown") if allowance.is_file() else "unknown"
    state: dict = {"run_id": run_id, "mode": mode, "status": "running", "builds": [], "published_slugs": [],
                   "paid_budget_status": paid_budget_status}
    def save_state() -> None:
        (evidence / "result.json").write_text(json.dumps(state, indent=2) + "\n")

    previous: Path | None = None
    previous_base = ""
    try:
        for build_number in (1, 2):
            checked(["git", "fetch", "--no-tags", "origin", "main"], root, command)
            base = checked(["git", "rev-parse", "FETCH_HEAD"], root, command)
            if not re.fullmatch(r"[a-f0-9]{40}", base):
                raise RuntimeError("Remote main did not resolve to an exact commit")
            worktree = Path(tempfile.mkdtemp(prefix="swimfrancisco-publication-")) / "checkout"
            checked(["git", "worktree", "add", "--detach", str(worktree), base], root, command)
            build: dict = {"base": base, "branch": f"auto/schedules/{run_id}-{build_number}", "commands": {}}
            state["builds"].append(build)
            save_state()
            try:
                if previous:
                    copy_extraction_cache(previous, worktree, previous_base, command)
                checked(["npm", "ci"], worktree, command)
                checked(["uv", "--project", "schedule-tools", "sync", "--locked"], worktree, command)
                schedules = ["uv", "--project", "schedule-tools", "run", "--locked", "schedules"]
                for name, arguments, required in (
                    ("discover", schedules + ["discover"], True),
                    ("browser", ["node", "scripts/capture-schedules.mjs"], False),
                    ("direct", schedules + ["extract", "--direct"], False),
                    ("openai", schedules + ["extract", "--provider", "openai", "--no-discover"], False),
                ):
                    result = command(arguments, worktree, timeout=160 if name == "browser" else 1800)
                    build["commands"][name] = result.returncode
                    if required and result.returncode:
                        raise RuntimeError(f"{name} failed; no publication is allowed")
                build["closure_reviews"] = []
                for provider in ("openai", "direct"):
                    closure_report = worktree / f"tmp/extraction-report-{provider}.json"
                    if closure_report.exists():
                        build["closure_reviews"].extend(json.loads(closure_report.read_text()).get("closure_reviews", []))
                save_state()
                if mode == "extract-only":
                    state["status"] = "extracted"
                    return state
                checked(schedules + ["publish-pending"], worktree, command)
                publication = json.loads((worktree / "tmp/publish-pending.json").read_text())
                build["closure_reviews"].extend(item["closure_review"] for item in publication.get("refused", []) if item.get("closure_review"))
                build["decisions"] = pager_job_payload(worktree / "tmp")
                checked(["node", "scripts/generate-bulletin.mjs"], worktree, command)
                checked(["node", "scripts/generate-i18n.mjs", "generate"], worktree, command)
                staged = json.loads(checked(["node", "scripts/check-build-ci.mjs", "stage"], worktree, command))
                build["paths"] = staged["paths"]
                if not staged["changed"]:
                    state["status"] = "unchanged"
                    return state
                checked(["git", "-c", "user.name=Schedule automation", "-c", "user.email=schedules@swimfrancisco.com",
                         "commit", "-m", "Refresh verified swimming schedules"], worktree, command)
                save_evidence(worktree, evidence / f"build-{build_number}")
                save_state()
                result = command(["node", "scripts/check-build-ci.mjs", "promote", base, build["branch"]], worktree, timeout=900)
                if result.returncode not in (0, 2):
                    raise RuntimeError("Exact-commit CI or main promotion failed")
                promotion = json.loads(result.stdout.strip().splitlines()[-1])
                build["promotion"] = promotion
                if result.returncode == 2 and promotion["status"] == "stale":
                    previous, previous_base = worktree, base
                    continue
                if promotion["status"] != "promoted" or not re.fullmatch(r"[a-f0-9]{40}", promotion.get("commit", "")):
                    raise RuntimeError("Invalid promotion receipt")
                state["status"] = "promoted"
                save_state()
                verify(worktree, promotion["commit"], command)
                state["status"] = "published"
                state["published_slugs"] = build["decisions"]["published_slugs"]
                state["deployment_url"] = "https://swimfrancisco.com/agent/build.json"
                return state
            finally:
                save_evidence(worktree, evidence / f"build-{build_number}")
        raise RuntimeError("Main moved during both checked builds; no stale update was pushed")
    except Exception as error:
        state["status"] = "failed"
        state["error_type"] = type(error).__name__
        raise
    finally:
        save_state()
