import posixpath
import re
from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github/workflows/schedules-extract.yml").read_text()


def test_weekly_disabled_by_default_and_serialized():
    assert "cron: '0 16 * * 1'" in WORKFLOW
    assert "vars.SCHEDULES_AUTOMATION_ENABLED == 'true'" in WORKFLOW
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW
    assert "default: extract-only" in WORKFLOW
    assert "pull_request_target" not in WORKFLOW


def test_split_permissions_with_closure_only_review_job():
    extract, rest = WORKFLOW.split("\n  review-closures:", 1)
    reviews, report = rest.split("\n  report:", 1)
    assert "permissions: {}" in extract
    assert "contents: write" in extract
    assert "actions: read" in extract
    assert "issues: write" not in extract
    assert "issues: write" in report
    assert "contents: write" not in report
    assert "actions/checkout" not in report
    assert "pull-requests:" not in extract
    assert "pull-requests:" not in report
    assert "pull-requests: write" in reviews
    assert "schedules closure-prs" in reviews
    assert "OPENAI_API_KEY" not in reviews
    assert "needs: [extract, review-closures]" in report
    assert "--force" not in WORKFLOW
    assert "token: ${{ secrets.SCHEDULES_BOT_TOKEN }}" in extract


def test_no_spend_ledger_bounds_the_paid_model_calls():
    """The OpenAI project spend limit is the only cap; nothing reserves or settles."""
    assert "budget" not in WORKFLOW.lower()
    assert "allowance" not in WORKFLOW.lower()
    assert "OPENAI_API_KEY:" in WORKFLOW
    assert "GOOGLE_API_KEY" not in WORKFLOW


def _uploaded_evidence_paths() -> list[str]:
    """The extract job's upload-artifact search paths, in order."""
    extract = WORKFLOW.split("\n  review-closures:", 1)[0]
    block = extract.split("          path: |\n", 1)[1].split("\n          retention-days:", 1)[0]
    return [line.strip() for line in block.split("\n") if line.strip()]


def _artifact_root(paths: list[str]) -> str:
    """What upload-artifact@v4 strips: the least common ancestor of its search
    paths. A directory contributes itself, a file its parent."""
    roots = [path[:-1] if path.endswith("/") else posixpath.dirname(path) for path in paths]
    return roots[0] if len(roots) == 1 else posixpath.commonpath(roots)


def test_evidence_and_live_browser_dependencies():
    assert "install --with-deps webkit chromium" in WORKFLOW
    assert "retention-days: 90" in WORKFLOW
    assert _uploaded_evidence_paths() == ["tmp/automation/"]
    assert "path: tmp/" not in WORKFLOW


def test_downloaded_evidence_paths_start_at_the_stripped_artifact_root():
    """upload-artifact@v4 roots the artifact at the least common ancestor of its
    search paths, so that directory's own name is gone from the download. Every
    `evidence/...` consumer must name a path relative to it, not through it."""
    uploaded = _uploaded_evidence_paths()
    root = _artifact_root(uploaded)
    assert root == "tmp/automation"
    assert all(path.rstrip("/") == root or path.startswith(root + "/") for path in uploaded)

    stripped = posixpath.basename(root)
    consumers = set(re.findall(r"evidence(?:/[A-Za-z0-9_.*-]+)*", WORKFLOW))
    for reference in consumers:
        relative = reference[len("evidence"):].lstrip("/")
        assert relative.split("/", 1)[0] != stripped, (
            f"{reference} names the {stripped}/ directory that upload-artifact "
            f"strips when it roots the artifact at {root}"
        )
    assert {"evidence", "evidence/result.json", "evidence/closure-prs.json"} <= consumers


def test_operator_issue_is_deduplicated_and_requires_live_confirmation():
    assert "issues.listForRepo" in WORKFLOW
    assert "issue?.body?.includes(statusMarker)" in WORKFLOW
    assert "result.status === 'published' ? result.published_slugs" in WORKFLOW
    assert "commandFailures" in WORKFLOW
    assert "needs.extract.result != 'skipped'" in WORKFLOW


def test_browser_credentials_and_evidence_are_scoped_to_extraction():
    extract, rest = WORKFLOW.split('\n  review-closures:', 1)
    assert 'CLOUDFLARE_BROWSER_API_TOKEN: ${{ secrets.CLOUDFLARE_BROWSER_API_TOKEN }}' in extract
    assert 'CLOUDFLARE_ACCOUNT_ID: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}' in extract
    assert 'test -n "$CLOUDFLARE_BROWSER_API_TOKEN"' in extract
    assert 'CLOUDFLARE_BROWSER_API_TOKEN' not in rest


def test_missing_paid_credentials_do_not_block_free_updates():
    assert 'test -n "$OPENAI_API_KEY"' not in WORKFLOW


def test_ci_runs_on_the_automation_branches_promotion_waits_for():
    """`promoteScheduleCommit` pushes to `auto/schedules/<run>-<build>` and then
    polls for a push-event `ci.yml` run on that branch; without the pattern in
    the push trigger no run is ever created and promotion times out."""
    ci = (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text()
    assert "auto/schedules/**" in ci.split("\npermissions:", 1)[0]
