from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "schedules-extract.yml"


def test_schedule_workflow_has_one_partitioned_pass_per_extraction_mode() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("schedules extract --direct") == 1
    assert workflow.count("schedules extract --provider gemini") == 1
    assert workflow.count("schedules extract --provider anthropic") == 1
    assert workflow.index("schedules extract --direct") < workflow.index("schedules extract --provider gemini")
    assert workflow.index("schedules extract --provider gemini") < workflow.index("schedules extract --provider anthropic")
    assert workflow.count("continue-on-error: true") >= 3
    assert workflow.count("id: extract-direct") == 1
    assert workflow.count("id: extract-gemini") == 1
    assert workflow.count("id: extract-anthropic") == 1


def test_schedule_workflow_fails_closed_and_preserves_reports() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.index("Verify CI-capable publication token") < workflow.index("actions/checkout@v4")
    assert "token: ${{ secrets.SCHEDULES_BOT_TOKEN }}" in workflow
    assert "GH_TOKEN: ${{ secrets.SCHEDULES_BOT_TOKEN }}" in workflow
    assert "github.token" not in workflow
    assert "secrets.GITHUB_TOKEN" not in workflow
    assert "tmp/extraction-report-direct.md" in workflow
    assert "tmp/extraction-report-gemini.md" in workflow
    assert "tmp/extraction-report-anthropic.md" in workflow
    assert "actions/upload-artifact@v4" in workflow
    summary = workflow.index("name: Publish extraction evidence")
    artifact = workflow.index("name: Upload extraction reports")
    assert workflow.index("if: always()", summary) < artifact
    assert workflow.index("if: always()", artifact) < workflow.index("name: Run eval")
    assert "blocked before extraction" in workflow
    assert "partial success" in workflow
    outcome_bullets = workflow.index('echo "- ${pass}: ${outcome}"')
    assert workflow.index('echo "## Schedule extraction: success"') < outcome_bullets
    assert workflow.index('echo "## Schedule extraction: partial success"') < outcome_bullets
    assert workflow.index('echo "## Schedule extraction: blocked before extraction"') < outcome_bullets
