from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .publish import pager_job_payload


def run_command(arguments: list[str], root: Path, *, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, cwd=root, capture_output=True, text=True, timeout=timeout, check=False)


def checked(arguments: list[str], root: Path, command=run_command, *, timeout: int = 900) -> str:
    result = command(arguments, root, timeout=timeout)
    if result.returncode:
        # Do not copy subprocess output into public reports: it can include credentials.
        raise RuntimeError(f"{arguments[0]} command failed (exit {result.returncode})")
    return result.stdout.strip()


def copy_extraction_cache(previous: Path, current: Path, previous_base: str, command=run_command) -> None:
    """Reuse source captures, never prior publication decisions or concurrent edits."""
    for source in (previous / "data").glob("*/*/*"):
        if source.is_symlink() or not source.is_file():
            continue
        if not re.fullmatch(r"source\.(pdf|sha256)|openai-gpt-5\.5-2026-04-23\.json", source.name):
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
    for name in ("discovery-decisions.json", "discovery-report.md", "publish-pending.json", "publish-pending-report.md",
                 "extraction-report-direct.md", "extraction-report-openai.md"):
        source = root / "tmp" / name
        if source.is_file():
            shutil.copyfile(source, destination / name)
    for source in (root / "data").glob("*/*/*"):
        if source.is_symlink() or not source.is_file():
            continue
        if not re.fullmatch(r"source\.(pdf|html|csv|xlsx|sha256)|reviewed\.json|openai-gpt-5\.5-2026-04-23\.json|direct-[a-z0-9-]+\.json", source.name):
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
    state: dict = {"run_id": run_id, "mode": mode, "status": "running", "builds": [], "published_slugs": []}
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
                    ("discover", ["discover"], True),
                    ("direct", ["extract", "--direct"], False),
                    ("openai", ["extract", "--provider", "openai", "--no-discover"], False),
                ):
                    result = command(schedules + arguments, worktree, timeout=1800)
                    build["commands"][name] = result.returncode
                    if required and result.returncode:
                        raise RuntimeError(f"{name} failed; no publication is allowed")
                if mode == "extract-only":
                    state["status"] = "extracted"
                    return state
                checked(schedules + ["publish-pending"], worktree, command)
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
