from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path

import pytest

from schedules.automation import automate, copy_extraction_cache, open_closure_review_prs, wait_for_deployment


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


@pytest.fixture
def closure_repository(tmp_path, monkeypatch):
    remote, root, evidence = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "evidence"
    def git(cwd, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=cwd, text=True, stderr=subprocess.PIPE).strip()
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "clone", str(remote), str(root))
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "hours.txt").write_text("Do not change these hours\n")
    git(root, "add", "hours.txt")
    git(root, "commit", "-m", "Baseline")
    git(root, "push", "origin", "main")
    digest = hashlib.sha256(b"%PDF-test source").hexdigest()
    path = f"data/test-pool/2026-09-06-{digest[:12]}/source.pdf"
    source = evidence / "build-1" / path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-test source")
    review = {"slug": "test-pool", "source_sha256": digest, "source_path": path,
              "issues": ["page_1:unresolved_closure_scope"],
              "notices": [{"id": "page_1", "text": "Closed for training; hours unclear", "facility": False}]}
    state = {"mode": "publish", "builds": [{"closure_reviews": [review]}]}
    (evidence / "result.json").write_text(json.dumps(state))
    calls, existing = [], []
    original = __import__("tempfile").mkdtemp
    monkeypatch.setattr("schedules.automation.tempfile.mkdtemp", lambda **kwargs: original(dir=tmp_path, **kwargs))
    def command(arguments, cwd, **kwargs):
        calls.append(arguments)
        if arguments[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(existing), "")
        if arguments[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(arguments, 0, "example/pools", "")
        if arguments[:3] == ["gh", "pr", "create"]:
            assert "--draft" in arguments
            body = Path(arguments[arguments.index("--body-file") + 1]).read_text()
            assert f"https://github.com/example/pools/blob/review/closures/test-pool-{digest[:12]}/{path}" in body
            existing.append({"url": "https://github.com/example/pools/pull/1", "state": "OPEN"})
            return subprocess.CompletedProcess(arguments, 0, existing[0]["url"], "")
        return subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)
    return root, remote, evidence, review, state, calls, existing, command, git


def test_closure_pr_contains_evidence_only_and_does_not_move_main(closure_repository):
    root, remote, evidence, review, _, calls, _, command, git = closure_repository
    main = git(remote, "rev-parse", "main")
    result = open_closure_review_prs(root, evidence, command)
    branch = f"review/closures/test-pool-{review['source_sha256'][:12]}"
    assert git(remote, "rev-parse", "main") == main
    paths = git(remote, "diff", "--name-only", "main", branch).splitlines()
    assert set(paths) == {review["source_path"], review["source_path"].replace("source.pdf", "closure-review.md")}
    assert git(remote, "show", f"{branch}:hours.txt") == "Do not change these hours"
    assert result[0]["state"] == "OPEN"
    assert not any("--force" in args or "--auto" in args or "merge" in args for args in calls)


@pytest.mark.parametrize("pr_state", ["OPEN", "CLOSED", "MERGED"])
def test_closure_pr_does_not_duplicate_or_overwrite_an_existing_review(closure_repository, pr_state):
    root, _, evidence, _, _, calls, existing, command, _ = closure_repository
    existing.append({"url": "https://github.com/example/pools/pull/1", "state": pr_state})
    assert open_closure_review_prs(root, evidence, command)[0]["state"] == pr_state
    assert len(calls) == 1
    assert calls[0][:3] == ["gh", "pr", "list"]


def test_closure_pr_second_run_reuses_same_hash_without_push(closure_repository):
    root, _, evidence, _, _, calls, _, command, _ = closure_repository
    first = open_closure_review_prs(root, evidence, command)
    calls.clear()
    assert open_closure_review_prs(root, evidence, command) == first
    assert len(calls) == 1


def test_extract_only_evidence_cannot_open_a_pr(closure_repository):
    root, _, evidence, _, state, calls, _, command, _ = closure_repository
    state["mode"] = "extract-only"
    (evidence / "result.json").write_text(json.dumps(state))
    assert open_closure_review_prs(root, evidence, command) == []
    assert calls == []


@pytest.mark.parametrize("problem", ["hash", "path", "symlink"])
def test_closure_pr_validates_evidence_before_any_remote_write(closure_repository, problem):
    root, _, evidence, review, state, calls, _, command, _ = closure_repository
    source = evidence / "build-1" / review["source_path"]
    if problem == "hash":
        source.write_bytes(b"tampered")
    elif problem == "path":
        review["source_path"] = "../../.env"
        (evidence / "result.json").write_text(json.dumps(state))
    else:
        source.unlink()
        source.symlink_to(root / "hours.txt")
    with pytest.raises(ValueError):
        open_closure_review_prs(root, evidence, command)
    assert not calls


def test_orphan_review_branch_is_preserved_not_force_pushed(closure_repository):
    root, remote, evidence, review, _, calls, _, command, git = closure_repository
    branch = f"review/closures/test-pool-{review['source_sha256'][:12]}"
    git(root, "push", "origin", f"HEAD:refs/heads/{branch}")
    before = git(remote, "rev-parse", branch)
    with pytest.raises(RuntimeError, match="preserve"):
        open_closure_review_prs(root, evidence, command)
    assert git(remote, "rev-parse", branch) == before
    assert not any("push" in args for args in calls)
