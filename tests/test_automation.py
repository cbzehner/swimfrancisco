from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from schedules.automation import automate, copy_extraction_cache, wait_for_deployment


@pytest.fixture
def runner(tmp_path, monkeypatch):
    ledger = tmp_path / "budget.json"
    ledger.write_text("{}")
    monkeypatch.setenv("SCHEDULES_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(ledger))
    monkeypatch.delenv("SCHEDULES_AUTO_PROJECT", raising=False)
    monkeypatch.setattr("schedules.automation.tempfile.mkdtemp", lambda **_: str(tmp_path / f"work-{len(calls)}"))
    root = tmp_path / "repo"
    root.mkdir()
    calls = []
    controls = {"stale": 0, "changed": True, "failure": None, "dirty": False, "verified": []}

    def command(arguments, cwd, **kwargs):
        calls.append(arguments)
        output = ""
        code = 0
        if arguments[:3] == ["git", "status", "--porcelain"]:
            output = " M user.txt" if controls["dirty"] else ""
        elif arguments[:2] == ["git", "rev-parse"]:
            output = "a" * 40
        elif arguments[:3] == ["git", "worktree", "add"]:
            Path(arguments[-2]).mkdir(parents=True)
        elif arguments[-1] == "stage":
            output = json.dumps({"changed": controls["changed"], "paths": ["content/spots/test-pool.md"]})
        elif "promote" in arguments:
            if controls["stale"]:
                controls["stale"] -= 1
                output, code = '{"status":"stale"}', 2
            else:
                output = json.dumps({"status": "promoted", "commit": "b" * 40})
        elif arguments[-1] == "publish-pending":
            (cwd / "tmp").mkdir(exist_ok=True)
            (cwd / "tmp/publish-pending.json").write_text('{"published":["test-pool"],"refused":[]}')
        if controls["failure"] and controls["failure"] in arguments:
            code = 1
        return subprocess.CompletedProcess(arguments, code, output, "")

    def verify(worktree, commit, command):
        receipt = json.loads((root / "tmp/automation/result.json").read_text())
        assert receipt["status"] == "promoted"
        assert receipt["published_slugs"] == []
        controls["verified"].append(commit)

    def run(mode="publish"):
        return automate(root, mode=mode, run_id="123-1", command=command, verify=verify)

    return root, calls, controls, run


def test_publish_orders_extraction_gate_commit_promotion_and_live_check(runner):
    root, calls, controls, run = runner
    result = run()
    assert result["status"] == "published"
    assert result["published_slugs"] == ["test-pool"]
    assert controls["verified"] == ["b" * 40]
    positions = [next(i for i, args in enumerate(calls) if token in args) for token in
                 ("discover", "--direct", "openai", "publish-pending", "stage", "commit", "promote")]
    assert positions == sorted(positions)
    assert json.loads((root / "tmp/automation/result.json").read_text()) == result


def test_extract_only_never_projects_commits_or_pushes(runner):
    _, calls, controls, run = runner
    assert run("extract-only")["status"] == "extracted"
    assert not controls["verified"]
    assert not any(token in args for args in calls for token in ("publish-pending", "commit", "promote", "stage"))


def test_unchanged_does_not_commit_or_call_live_checks(runner):
    _, calls, controls, run = runner
    controls["changed"] = False
    assert run()["status"] == "unchanged"
    assert not controls["verified"]
    assert not any("commit" in args or "promote" in args for args in calls)


@pytest.mark.parametrize("failure", ["discover", "publish-pending", "stage", "promote"])
def test_required_failure_never_reports_publication(runner, failure):
    root, _, controls, run = runner
    controls["failure"] = failure
    with pytest.raises(RuntimeError):
        run()
    result = json.loads((root / "tmp/automation/result.json").read_text())
    assert result["status"] == "failed"
    assert result["published_slugs"] == []
    assert not controls["verified"]


def test_pool_extraction_failure_keeps_other_pools_eligible_and_records_failure(runner):
    _, _, controls, run = runner
    controls["failure"] = "openai"
    result = run()
    assert result["status"] == "published"
    assert result["builds"][0]["commands"]["openai"] == 1


def test_main_movement_rebuilds_once_and_rechecks(runner):
    _, calls, controls, run = runner
    controls["stale"] = 1
    result = run()
    assert [build["branch"] for build in result["builds"]] == ["auto/schedules/123-1-1", "auto/schedules/123-1-2"]
    assert sum("discover" in args for args in calls) == 2
    assert sum("promote" in args for args in calls) == 2
    assert len(controls["verified"]) == 1


def test_repeated_main_movement_stops_after_two_attempts(runner):
    root, calls, controls, run = runner
    controls["stale"] = 2
    with pytest.raises(RuntimeError, match="both checked builds"):
        run()
    assert sum("promote" in args for args in calls) == 2
    assert json.loads((root / "tmp/automation/result.json").read_text())["published_slugs"] == []


def test_dirty_checkout_is_preserved_without_worktree_or_git_writes(runner):
    _, calls, controls, run = runner
    controls["dirty"] = True
    with pytest.raises(ValueError, match="clean checkout"):
        run()
    assert calls == [["git", "status", "--porcelain"]]


def test_kill_switch_stops_before_commands(runner, monkeypatch):
    _, calls, _, run = runner
    monkeypatch.setenv("SCHEDULES_AUTOMATION_ENABLED", "false")
    with pytest.raises(ValueError, match="disabled"):
        run()
    assert not calls


def test_cache_never_copies_reviewed_decisions_or_overwrites_concurrent_source_edits(tmp_path):
    previous, current = tmp_path / "previous", tmp_path / "current"
    capture = Path("data/test-pool/2026-09-02-67f2a420e8fc")
    (previous / capture).mkdir(parents=True)
    (current / capture).mkdir(parents=True)
    for name in ("reviewed.json", "source.pdf", "openai-gpt-5.5-2026-04-23.json"):
        (previous / capture / name).write_text("cached")
    (current / capture / "source.pdf").write_text("concurrent edit")
    def command(args, root, **kwargs):
        return subprocess.CompletedProcess(args, 0, "source.pdf" if args[-1].endswith("source.pdf") else "", "")
    copy_extraction_cache(previous, current, "a" * 40, command)
    assert not (current / capture / "reviewed.json").exists()
    assert (current / capture / "source.pdf").read_text() == "concurrent edit"
    assert (current / capture / "openai-gpt-5.5-2026-04-23.json").read_text() == "cached"


def test_live_verification_retries_then_succeeds_and_checks_browsers(tmp_path):
    calls, clock = [], [0]
    def command(args, root, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0 if len(calls) == 2 else 1, "", "")
    wait_for_deployment(tmp_path, "a" * 40, command, sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0])
    assert len(calls) == 2
    assert "--browser" in calls[0]


def test_live_verification_timeout_never_succeeds(tmp_path):
    clock = [0]
    def command(args, root, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "")
    with pytest.raises(RuntimeError, match="not reported as published"):
        wait_for_deployment(tmp_path, "a" * 40, command, sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0])
    assert clock[0] == 1200
