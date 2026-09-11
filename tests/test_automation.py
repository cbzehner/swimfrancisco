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
    controls = {"stale": 0, "changed": True, "failure": None, "dirty": False, "verified": [], "closure_reviews": {}}

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
        if "extract" in arguments:
            provider = "direct" if "--direct" in arguments else "openai"
            (cwd / "tmp").mkdir(exist_ok=True)
            (cwd / f"tmp/extraction-report-{provider}.json").write_text(json.dumps(
                {"closure_reviews": controls["closure_reviews"].get(provider, [])}))
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


@pytest.mark.parametrize("failure, report", [("openai", "openai"), ("--direct", "direct")])
def test_pool_extraction_failure_keeps_other_pools_eligible_and_records_failure(runner, failure, report):
    _, _, controls, run = runner
    controls["failure"] = failure
    result = run()
    assert result["status"] == "published"
    assert result["builds"][0]["commands"][report] == 1


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
    source_name = "source.pdf"
    previous, current = tmp_path / "previous", tmp_path / "current"
    capture = Path("data/test-pool/2026-09-02-67f2a420e8fc")
    (previous / capture).mkdir(parents=True)
    (current / capture).mkdir(parents=True)
    for name in ("reviewed.json", source_name, "openai-gpt-6-2027-01-30.json"):
        (previous / capture / name).write_text("cached")
    (current / capture / source_name).write_text("concurrent edit")
    def command(args, root, **kwargs):
        return subprocess.CompletedProcess(args, 0, source_name if args[-1].endswith(source_name) else "", "")
    copy_extraction_cache(previous, current, "a" * 40, command)
    assert not (current / capture / "reviewed.json").exists()
    assert (current / capture / source_name).read_text() == "concurrent edit"
    assert (current / capture / "openai-gpt-6-2027-01-30.json").read_text() == "cached"


def test_live_verification_retries_then_succeeds_and_checks_browsers(tmp_path):
    calls, clock = [], [0]
    def command(args, root, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0 if len(calls) == 2 else 1, "", "")
    wait_for_deployment(tmp_path, "a" * 40, command, sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0])
    assert len(calls) == 2
    assert "--browser" in calls[0]


def test_production_provider_artifact_is_allowed_retained_and_reused(tmp_path):
    from schedules.paths import artifact_path
    from schedules.providers.openai_provider import API_MODEL
    from schedules.automation import save_evidence
    root, evidence, cache = (tmp_path / name for name in ("root", "evidence", "cache"))
    artifact = artifact_path("north-beach-pool", "2026-09-06", "a" * 64, "openai", API_MODEL, root=root / "data")
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"provider":"openai"}')
    relative = artifact.relative_to(root)
    result = subprocess.run(
        ["node", "--input-type=module", "-e", "import {generatedSchedulePath} from './scripts/check-build-ci.mjs'; if (!generatedSchedulePath(process.argv[1])) process.exit(1)", relative.as_posix()],
        check=False, capture_output=True,
    )
    assert result.returncode == 0
    save_evidence(root, evidence)
    assert (evidence / relative).read_bytes() == artifact.read_bytes()
    copy_extraction_cache(root, cache, "a" * 40, lambda args, cwd, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    assert (cache / relative).read_bytes() == artifact.read_bytes()


def test_live_verification_timeout_never_succeeds(tmp_path):
    clock = [0]
    def command(args, root, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "")
    with pytest.raises(RuntimeError, match="not reported as published"):
        wait_for_deployment(tmp_path, "a" * 40, command, sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0])
    assert clock[0] == 1200


@pytest.fixture(params=[("test-pool", "pdf"), ("chinatown-ymca", "html"), ("ucsf-bakar", "html")])
def closure_repository(tmp_path, monkeypatch, request):
    slug, extension = request.param
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
    source_bytes = b"%PDF-test source" if extension == "pdf" else b"<html>Closed for maintenance</html>"
    digest = hashlib.sha256(source_bytes).hexdigest()
    path = f"data/{slug}/2026-09-06-{digest[:12]}/source.{extension}"
    source = evidence / "build-1" / path
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)
    review = {"slug": slug, "source_sha256": digest, "source_path": path,
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
            matching = existing if "--head" in arguments else [item for item in existing if item["state"] == "OPEN"]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(matching), "")
        if arguments[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(arguments, 0, "example/pools", "")
        if arguments[:3] == ["gh", "pr", "create"]:
            assert "--draft" in arguments
            body = Path(arguments[arguments.index("--body-file") + 1]).read_text()
            assert f"https://github.com/example/pools/blob/review/closures/{slug}-{digest[:12]}/{path}" in body
            existing.append({"url": "https://github.com/example/pools/pull/1", "state": "OPEN"})
            return subprocess.CompletedProcess(arguments, 0, existing[0]["url"], "")
        return subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)
    return root, remote, evidence, review, state, calls, existing, command, git


def test_closure_pr_contains_evidence_only_and_does_not_move_main(closure_repository):
    root, remote, evidence, review, _, calls, _, command, git = closure_repository
    main = git(remote, "rev-parse", "main")
    result = open_closure_review_prs(root, evidence, command)
    branch = f"review/closures/{review['slug']}-{review['source_sha256'][:12]}"
    assert git(remote, "rev-parse", "main") == main
    paths = git(remote, "diff", "--name-only", "main", branch).splitlines()
    assert set(paths) == {review["source_path"], str(Path(review["source_path"]).with_name("closure-review.md")),
                          str(Path(review["source_path"]).with_name("source.sha256"))}
    sidecar = str(Path(review["source_path"]).with_name("source.sha256"))
    assert git(remote, "show", f"{branch}:{sidecar}") == review["source_sha256"]
    stored_source = subprocess.check_output(["git", "show", f"{branch}:{review['source_path']}"], cwd=remote)
    assert hashlib.sha256(stored_source).hexdigest() == git(remote, "show", f"{branch}:{sidecar}")
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
    branch = f"review/closures/{review['slug']}-{review['source_sha256'][:12]}"
    git(root, "push", "origin", f"HEAD:refs/heads/{branch}")
    before = git(remote, "rev-parse", branch)
    with pytest.raises(RuntimeError, match="preserve"):
        open_closure_review_prs(root, evidence, command)
    assert git(remote, "rev-parse", branch) == before
    assert not any("push" in args for args in calls)


def test_browser_capture_runs_before_direct_and_again_after_stale_main(runner):
    _, calls, controls, run = runner
    controls['stale'] = 1
    assert run()['status'] == 'published'
    captures = [i for i, args in enumerate(calls) if args == ['node', 'scripts/capture-schedules.mjs']]
    direct = [i for i, args in enumerate(calls) if '--direct' in args]
    pdf = [i for i, args in enumerate(calls) if 'openai' in args]
    assert len(captures) == len(direct) == len(pdf) == 2
    assert captures[0] < direct[0] < pdf[0] < captures[1] < direct[1] < pdf[1]


def test_browser_failure_is_reported_without_blocking_independent_sources(runner):
    _, calls, controls, run = runner
    controls['failure'] = 'scripts/capture-schedules.mjs'
    result = run()
    assert result['builds'][0]['commands']['browser'] == 1
    assert any('--direct' in args for args in calls)
    assert result['status'] == 'published'


def test_browser_evidence_retained_with_narrow_filename_allowlist(tmp_path):
    from schedules.automation import save_evidence
    root = tmp_path / 'root'
    capture = root / 'tmp/browser-capture/jccsf'
    capture.mkdir(parents=True)
    (capture.parent / 'results.json').write_text('{}')
    for name in ['source.html', 'rendered.html', 'screenshot.png', 'capture.json', 'credentials.txt']:
        (capture / name).write_text('evidence')
    destination = tmp_path / 'evidence'
    save_evidence(root, destination)
    assert sorted(str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()) == [
        'browser-capture/jccsf/capture.json', 'browser-capture/jccsf/rendered.html',
        'browser-capture/jccsf/screenshot.png', 'browser-capture/jccsf/source.html',
        'browser-capture/results.json',
    ]


def test_cache_copy_reuses_every_capture_kind_and_drops_old_browser_receipts(tmp_path):
    """A retry re-uses the captures it already paid for, whatever their kind."""
    previous, current = tmp_path / "previous", tmp_path / "current"
    capture = Path("data/jccsf/2026-09-08-67f2a420e8fc")
    (previous / capture).mkdir(parents=True)
    for name in ("source.html", "source.xlsx", "source.csv", "source.pdf", "source.sha256",
                 "openai-gpt-6-2027-01-30.json", "direct-jccsf-html-v1.json", "reviewed.json"):
        (previous / capture / name).write_text(name)
    browser = previous / "tmp/browser-capture/jccsf"
    browser.mkdir(parents=True)
    (browser / "capture.json").write_text("old receipt")
    copy_extraction_cache(previous, current, "a" * 40,
                          lambda args, cwd, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    assert sorted(path.name for path in (current / capture).iterdir()) == [
        "direct-jccsf-html-v1.json", "openai-gpt-6-2027-01-30.json", "source.csv", "source.html",
        "source.pdf", "source.sha256", "source.xlsx"]
    assert not (current / "tmp/browser-capture").exists()


def test_unapproved_html_source_cannot_open_closure_pr(closure_repository):
    root, _, evidence, review, state, calls, _, command, _ = closure_repository
    review["slug"] = "unapproved-pool"
    review["source_path"] = f"data/unapproved-pool/2026-09-06-{review['source_sha256'][:12]}/source.html"
    (evidence / "result.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="Invalid closure review evidence"):
        open_closure_review_prs(root, evidence, command)
    assert not calls


def test_closure_review_escapes_source_backtick_fences():
    from schedules.automation import closure_review_document
    review = {"slug": "chinatown-ymca", "source_path": "data/chinatown-ymca/source.html",
              "source_sha256": "a" * 64, "issues": ["conflict"], "notices": ["``` injection"]}
    document = closure_review_document(review)
    assert "[Source HTML](source.html)" in document
    assert "````json" in document
    assert document.endswith("````\n")


def test_city_and_html_closure_reviews_share_existing_review_report(runner):
    _, _, controls, run = runner
    controls["closure_reviews"] = {"openai": [{"slug": "balboa-pool"}],
                                    "direct": [{"slug": "chinatown-ymca"}]}
    result = run()
    assert result["builds"][0]["closure_reviews"] == [
        {"slug": "balboa-pool"}, {"slug": "chinatown-ymca"}]


@pytest.mark.parametrize("open_head, reused", [
    ("review/closures/chinatown-ymca-" + "a" * 12, True),
    ("review/closures/chinatown-ymca-other-" + "a" * 12, False),
    ("review/closures/chinatown-ymca-" + "g" * 12, False),
    ("review/closures/chinatown-ymca-" + "a" * 13, False),
])
def test_html_byte_churn_reuses_only_exact_slug_open_review(closure_repository, open_head, reused):
    root, remote, evidence, review, _, calls, _, original, git = closure_repository
    old_review = {"headRefName": open_head, "url": "https://example.invalid/existing", "state": "OPEN"}
    def command(args, cwd, **kwargs):
        if args[:3] == ["gh", "pr", "list"] and "--head" not in args:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, json.dumps([old_review]), "")
        return original(args, cwd, **kwargs)
    before = git(remote, "rev-parse", "main")
    result = open_closure_review_prs(root, evidence, command)
    should_reuse = reused and review["slug"] == "chinatown-ymca"
    assert (result[0]["url"] == old_review["url"]) == should_reuse
    assert any(args[:3] == ["gh", "pr", "create"] for args in calls) != should_reuse
    assert any("push" in args for args in calls) != should_reuse
    assert git(remote, "rev-parse", "main") == before
    assert (evidence / "build-1" / review["source_path"]).is_file()


def test_browser_source_cannot_disguise_closure_evidence_as_pdf(closure_repository):
    root, _, evidence, review, state, calls, _, command, _ = closure_repository
    review["slug"] = "chinatown-ymca"
    review["source_path"] = f"data/chinatown-ymca/2026-09-06-{review['source_sha256'][:12]}/source.pdf"
    (evidence / "result.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="Invalid closure review evidence"):
        open_closure_review_prs(root, evidence, command)
    assert not calls


def test_changed_html_capture_second_run_keeps_existing_review_and_new_evidence(closure_repository):
    root, _, evidence, review, state, calls, existing, original, _ = closure_repository
    if review["slug"] != "chinatown-ymca":
        return
    first = open_closure_review_prs(root, evidence, original)
    old_branch = f"review/closures/{review['slug']}-{review['source_sha256'][:12]}"
    source_bytes = b"<html>new markup; same maintenance closure</html>"
    digest = hashlib.sha256(source_bytes).hexdigest()
    review["source_sha256"] = digest
    review["source_path"] = f"data/{review['slug']}/2026-09-13-{digest[:12]}/source.html"
    source = evidence / "build-1" / review["source_path"]
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)
    (evidence / "result.json").write_text(json.dumps(state))
    calls.clear()
    def command(args, cwd, **kwargs):
        if args[:3] == ["gh", "pr", "list"]:
            calls.append(args)
            output = [] if "--head" in args else [existing[0] | {"headRefName": old_branch}]
            return subprocess.CompletedProcess(args, 0, json.dumps(output), "")
        return original(args, cwd, **kwargs)
    second = open_closure_review_prs(root, evidence, command)
    assert second[0]["url"] == first[0]["url"]
    assert second[0]["source_sha256"] == digest
    assert source.read_bytes() == source_bytes
    assert len(calls) == 2 and all(args[:3] == ["gh", "pr", "list"] for args in calls)


@pytest.mark.parametrize("existing_hash", ["wrong hash\n", "symlink"])
def test_closure_pr_preserves_conflicting_source_hash_before_push(closure_repository, existing_hash):
    root, remote, evidence, review, _, calls, _, command, git = closure_repository
    sidecar = root / Path(review["source_path"]).with_name("source.sha256")
    sidecar.parent.mkdir(parents=True)
    if existing_hash == "symlink":
        sidecar.symlink_to(root / "hours.txt")
    else:
        sidecar.write_text(existing_hash)
    git(root, "add", str(sidecar.relative_to(root)))
    git(root, "commit", "-m", "Preserve operator hash")
    git(root, "push", "origin", "main")
    before = git(remote, "rev-parse", "main")
    with pytest.raises(ValueError, match="Existing source hash differs"):
        open_closure_review_prs(root, evidence, command)
    assert git(remote, "rev-parse", "main") == before
    assert not any("push" in args for args in calls)
    assert sidecar.is_symlink() if existing_hash == "symlink" else sidecar.read_text() == existing_hash


def test_zero_model_allowance_still_captures_extracts_and_publishes_free_updates(runner, monkeypatch):
    root, calls, controls, run = runner
    ledger = root.parent / "budget.json"
    ledger.write_text(json.dumps({"limit_microusd": 0, "requests": []}))
    ledger.with_name("reservation.json").write_text(json.dumps({"status": "unavailable", "limit_microusd": 0}))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "0")
    controls["failure"] = "openai"
    result = run()
    assert result["status"] == "published"
    assert result["paid_budget_status"] == "unavailable"
    assert result["builds"][0]["commands"] == {"discover": 0, "browser": 0, "direct": 0, "openai": 1}
    assert any(args == ["node", "scripts/capture-schedules.mjs"] for args in calls)
    assert controls["verified"] == ["b" * 40]
    assert json.loads(ledger.read_text()) == {"limit_microusd": 0, "requests": []}
