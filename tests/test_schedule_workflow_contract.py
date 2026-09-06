from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github/workflows/schedules-extract.yml").read_text()


def test_weekly_disabled_by_default_and_serialized():
    assert "cron: '0 16 * * 1'" in WORKFLOW
    assert "vars.SCHEDULES_AUTOMATION_ENABLED == 'true'" in WORKFLOW
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW
    assert "default: extract-only" in WORKFLOW
    assert "pull_request_target" not in WORKFLOW


def test_split_permissions_without_pr_publication():
    extract, report = WORKFLOW.split("\n  report:", 1)
    assert "permissions: {}" in extract
    assert "contents: write" in extract
    assert "actions: read" in extract
    assert "issues: write" not in extract
    assert "issues: write" in report
    assert "contents: write" not in report
    assert "actions/checkout" not in report
    assert "pull-requests:" not in WORKFLOW
    assert "gh pr" not in WORKFLOW
    assert "--force" not in WORKFLOW
    assert "token: ${{ secrets.SCHEDULES_BOT_TOKEN }}" in extract


def test_budget_reserved_before_runner_and_always_settled():
    assert WORKFLOW.index("schedules budget reserve") < WORKFLOW.index("schedules automate")
    assert "SCHEDULES_API_BUDGET_FILE=" in WORKFLOW
    assert "SCHEDULES_API_BUDGET_USD=" in WORKFLOW
    assert "SCHEDULES_MONTHLY_BUDGET_USD:" in WORKFLOW
    assert "always() && steps.reserve.outcome == 'success'" in WORKFLOW
    assert "schedules budget settle" in WORKFLOW
    assert "budget initialize" not in WORKFLOW
    assert "OPENAI_API_KEY:" in WORKFLOW
    assert "GOOGLE_API_KEY" not in WORKFLOW


def test_evidence_and_live_browser_dependencies():
    assert "install --with-deps webkit chromium" in WORKFLOW
    assert "retention-days: 90" in WORKFLOW
    assert "tmp/automation/" in WORKFLOW
    assert "tmp/api-budget/budget.json" in WORKFLOW
    assert "tmp/api-budget/reservation.json" in WORKFLOW
    assert "path: tmp/" not in WORKFLOW


def test_operator_issue_is_deduplicated_and_requires_live_confirmation():
    assert "issues.listForRepo" in WORKFLOW
    assert "issue?.body?.includes(statusMarker)" in WORKFLOW
    assert "result.status === 'published' ? result.published_slugs" in WORKFLOW
    assert "commandFailures" in WORKFLOW
    assert "needs.extract.result != 'skipped'" in WORKFLOW
