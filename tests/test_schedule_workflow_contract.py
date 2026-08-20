from __future__ import annotations

import re
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "schedules-extract.yml"

_JOB_HEADER = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.M)
_STEP_HEADER = re.compile(r"^      - (?:name: (.+)|uses: (.+))", re.M)


def _workflow() -> str:
    return WORKFLOW.read_text()


def _header(workflow: str) -> str:
    return workflow.split("\njobs:", 1)[0]


def _jobs(workflow: str) -> dict[str, str]:
    _, jobs_text = workflow.split("\njobs:", 1)
    jobs_text = "jobs:" + jobs_text
    matches = list(_JOB_HEADER.finditer(jobs_text))
    blocks: dict[str, str] = {}
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(jobs_text)
        blocks[match.group(1)] = jobs_text[start:end]
    return blocks


def _steps(job: str) -> dict[str, str]:
    matches = list(_STEP_HEADER.finditer(job))
    steps: dict[str, str] = {}
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(job)
        name = (match.group(1) or match.group(2) or "").strip()
        steps[name] = job[start:end]
    return steps


def test_three_jobs_permissions_and_no_workflow_token_scopes() -> None:
    workflow = _workflow()
    header = _header(workflow)
    jobs = _jobs(workflow)

    assert "permissions:" not in header
    assert set(jobs) == {"ensure-labels", "extract", "page-schedules-extract"}

    ensure = jobs["ensure-labels"]
    assert "issues: write" in ensure
    assert "actions/checkout" not in ensure
    assert "contents:" not in ensure
    assert "pull-requests:" not in ensure

    page = jobs["page-schedules-extract"]
    assert "issues: write" in page
    assert re.search(r"^    if: always\(\)\s*$", page, re.M)
    assert "actions/checkout" not in page
    assert "contents:" not in page
    assert "pull-requests:" not in page

    extract = jobs["extract"]
    assert "issues: write" not in extract
    assert "contents: write" in extract
    assert "pull-requests: write" in extract


def test_github_token_only_in_pager_jobs() -> None:
    jobs = _jobs(_workflow())
    workflow = _workflow()

    assert "secrets.GITHUB_TOKEN" not in workflow
    assert "github.token" in jobs["ensure-labels"]
    assert "github.token" in jobs["page-schedules-extract"]
    assert "github.token" not in jobs["extract"]
    assert "GH_TOKEN: ${{ github.token }}" in jobs["ensure-labels"]
    assert "GH_TOKEN: ${{ github.token }}" in jobs["page-schedules-extract"]
    assert "GH_TOKEN: ${{ github.token }}" not in jobs["extract"]


def test_no_checkout_pager_jobs_set_gh_repo() -> None:
    jobs = _jobs(_workflow())
    for name in ("ensure-labels", "page-schedules-extract"):
        assert "GH_REPO: ${{ github.repository }}" in jobs[name]
        assert "actions/checkout" not in jobs[name]


def test_checkout_and_pr_use_schedules_bot_token() -> None:
    workflow = _workflow()
    extract = _jobs(workflow)["extract"]
    steps = _steps(extract)
    checkout = steps["actions/checkout@v4"]
    pr = steps["Open or update PR"]

    assert "token: ${{ secrets.SCHEDULES_BOT_TOKEN }}" in checkout
    assert "GH_TOKEN: ${{ secrets.SCHEDULES_BOT_TOKEN }}" in pr
    assert "github.token" not in checkout
    assert "github.token" not in pr


def _extract_discover_invocations(workflow: str) -> list[str]:
    lines: list[str] = []
    for line in workflow.splitlines():
        stripped = line.strip()
        if not stripped.startswith("run:"):
            continue
        if "schedules extract" in stripped or "schedules discover" in stripped:
            lines.append(stripped)
    return lines


def test_discover_before_gemini_no_discover_no_anthropic_no_url() -> None:
    workflow = _workflow()

    discover = "run: uv --project schedule-tools run schedules discover"
    gemini = "schedules extract --provider gemini --no-discover"
    direct = "schedules extract --direct"

    assert workflow.count(discover) == 1
    assert workflow.count(gemini) == 1
    assert workflow.count("schedules extract --provider gemini") == 1
    assert workflow.count(direct) == 1
    assert workflow.index(discover) < workflow.index(gemini)
    assert workflow.index(direct) < workflow.index(gemini)
    assert "schedules extract --provider anthropic" not in workflow
    assert "ANTHROPIC_API_KEY" not in workflow
    for line in _extract_discover_invocations(workflow):
        assert "--url" not in line
        assert "--adopt" not in line
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("run:") and "schedules review" in stripped:
            raise AssertionError("workflow must not run schedules review")


def test_gemini_fail_closed_direct_continues() -> None:
    steps = _steps(_jobs(_workflow())["extract"])
    discover = steps["Discover Rec & Park PDF URLs"]
    direct = steps["Extract direct sources (no content writes)"]
    gemini = steps["Extract PDF sources with Gemini (no content writes)"]

    assert "continue-on-error" not in discover
    assert "continue-on-error: true" in direct
    assert "continue-on-error" not in gemini
    assert "--no-discover" in gemini


def test_preflight_proves_pat_with_ls_remote() -> None:
    workflow = _workflow()
    extract = _jobs(workflow)["extract"]
    preflight = _steps(extract)["Verify CI-capable publication token"]

    assert workflow.index("Verify CI-capable publication token") < workflow.index("actions/checkout@v4")
    assert "git ls-remote" in preflight
    assert "SCHEDULES_BOT_TOKEN is empty." in preflight
    assert "preflight_outcome: ${{ steps.token-preflight.outcome }}" in extract


def test_detect_and_pr_if_always_preflight() -> None:
    steps = _steps(_jobs(_workflow())["extract"])
    detect = steps["Detect new or changed artifacts"]
    pr = steps["Open or update PR"]
    eval_step = steps["Run eval against committed reviewed.json"]
    bulletin = steps["Regenerate bulletin fingerprint"]
    i18n = steps["Regenerate i18n artifacts"]
    publish = steps["Publish extraction evidence"]
    upload = steps["Upload extraction reports"]

    assert "if: always() && steps.token-preflight.outcome == 'success'" in detect
    assert "steps.detect.outputs.changed" not in detect
    assert (
        "if: always() && steps.token-preflight.outcome == 'success'"
        " && steps.detect.outputs.changed == 'true'"
    ) in pr
    assert "if: always() && steps.token-preflight.outcome == 'success'" in eval_step
    assert "if: always() && steps.token-preflight.outcome == 'success'" in bulletin
    assert "if: always() && steps.token-preflight.outcome == 'success'" in i18n
    assert "node scripts/generate-i18n.mjs generate" in i18n
    assert re.search(r"^        if: always\(\)\s*$", publish, re.M)
    assert re.search(r"^        if: always\(\)\s*$", upload, re.M)


def test_git_add_includes_registry() -> None:
    detect = _steps(_jobs(_workflow())["extract"])["Detect new or changed artifacts"]
    assert (
        "git add data/ schedule-tools/src/schedules/registry.toml content/spots/ "
        "schedule-tools/src/schedules/quarantine.toml"
    ) in detect
    assert "grep -qE 'registry.toml|content/spots/|quarantine.toml'" in detect


def test_auto_merge_keys_on_publish_pending() -> None:
    pr = _steps(_jobs(_workflow())["extract"])["Open or update PR"]
    assert "steps.publish-pending.outcome" in pr
    assert '[ "${{ steps.publish-pending.outcome }}" = "success" ]' in pr
    assert "schedules pending-reviews" not in pr
    assert "schedules discover-blocking" not in pr
    assert 'gh pr edit "${PR_NUMBER}" --add-label "needs-schedule-review"' in pr
    assert "publish-pending did not succeed; not auto-merging." in pr
    assert "echo \"pr_number=${PR_NUMBER}\"" in pr or "pr_number=${PR_NUMBER}" in pr
    assert "flagged_set" not in pr


def test_page_issue_on_preflight_failure_close_on_preflight_success() -> None:
    page = _jobs(_workflow())["page-schedules-extract"]
    steps = _steps(page)
    file_issue = steps["File schedules-extract blocked issue"]
    close_issue = steps["Close schedules-extract blocked issue"]

    assert "needs.extract.outputs.preflight_outcome == 'failure'" in file_issue
    assert "needs.extract.outputs.preflight_outcome == 'success'" in close_issue
    assert "success()" not in close_issue
    assert 'gh issue create --title "schedules-extract blocked"' in file_issue
    assert "--label schedules-extract-blocked" in file_issue
    assert "extract did not run." in file_issue
    assert "github-actions[bot]" in file_issue
    assert "github-actions[bot]" in close_issue
    assert "gh issue close" in close_issue


def test_ensure_labels_force_creates_review_and_pager_labels() -> None:
    ensure = _jobs(_workflow())["ensure-labels"]
    assert "gh label create needs-schedule-review --force" in ensure
    assert "gh label create schedules-extract-blocked --force" in ensure
    assert "gh label create schedules-published --force" in ensure
    assert "gh label create schedules-flagged --force" in ensure


def test_reports_drop_anthropic_and_upload_discovery() -> None:
    extract = _jobs(_workflow())["extract"]
    steps = _steps(extract)
    publish = steps["Publish extraction evidence"]
    upload = steps["Upload extraction reports"]

    assert "tmp/extraction-report-anthropic.md" not in publish
    assert "anthropic" not in publish.lower()
    assert "tmp/discovery-report.md" in publish
    assert "tmp/extraction-report-direct.md" in publish
    assert "tmp/extraction-report-gemini.md" in publish
    assert "tmp/discovery-report.md" in upload
    assert "tmp/publish-pending-report.md" in upload
    assert "actions/upload-artifact@v4" in upload


def test_publish_pending_before_eval_bulletin_and_upload() -> None:
    extract = _jobs(_workflow())["extract"]
    steps = _steps(extract)
    direct = steps["Extract direct sources (no content writes)"]
    gemini = steps["Extract PDF sources with Gemini (no content writes)"]
    publish = steps["Publish pending unique Rec & Park grids"]
    upload = steps["Upload extraction reports"]
    pager = steps["Set pager outputs"]

    assert "no content writes" in direct.split("\n", 1)[0] or "no content writes" in direct
    assert "no content writes" in gemini.split("\n", 1)[0] or "no content writes" in gemini
    assert "schedules publish-pending" not in "\n".join(
        line for line in direct.splitlines() if line.strip().startswith("run:")
    )
    assert "schedules publish-pending" not in "\n".join(
        line for line in gemini.splitlines() if line.strip().startswith("run:")
    )
    assert "run: uv --project schedule-tools run schedules publish-pending" in publish
    assert "id: publish-pending" in publish
    assert "always() && steps.token-preflight.outcome == 'success'" in publish
    assert "vars.SCHEDULES_AUTO_PROJECT != 'false'" in publish
    assert extract.index("schedules publish-pending") < extract.index(
        "Run eval against committed reviewed.json"
    )
    assert extract.index("Run eval against committed reviewed.json") < extract.index(
        "Regenerate bulletin fingerprint"
    )
    assert extract.index("Regenerate bulletin fingerprint") < extract.index(
        "Regenerate i18n artifacts"
    )
    assert extract.index("schedules publish-pending") < extract.index(
        "actions/upload-artifact@v4"
    )
    assert "tmp/publish-pending-report.md" in upload
    assert "if: always() && steps.token-preflight.outcome == 'success'" in pager
    assert "detect.outputs.changed" not in pager
    assert "flagged_computed" in pager
    assert "flagged_set" in pager
    header = _header(_workflow())
    assert "never edits" not in header
    assert "workflow never edits" not in extract.lower()


def test_header_does_not_forbid_content_spots_writes() -> None:
    header = _header(_workflow())
    assert "never edits" not in header
    assert "content/spots/" in header
    assert "auto_project" in header or "auto_project" in _workflow()


def test_public_repo_safety_schedule_and_dispatch_only() -> None:
    header = _header(_workflow())
    on_block = header.split("\non:", 1)[1].split("\nconcurrency:", 1)[0]
    assert "workflow_dispatch" in on_block
    assert "schedule:" in on_block
    assert "pull_request" not in on_block
    assert "cron: '0 16 * * *'" in on_block
