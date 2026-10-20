import json

from schedules.metrics import run_metrics


def test_metrics_separate_cache_failure_hold_and_confirmed_publication(tmp_path):
    directory = tmp_path / "build-1"
    directory.mkdir()
    (directory / "extraction-report-openai.json").write_text(json.dumps({"results": [
        {"slug": "paired", "status": "success", "cached": True},
        {"slug": "paired", "status": "failed", "cached": False},
        {"slug": "updated", "status": "success", "cached": False},
    ]}))
    state = {"run_id": "123-1", "status": "published", "published_slugs": ["updated"],
             "builds": [{"decisions": {"flagged_set": ["paired:missing_component"]}}]}
    metrics = run_metrics(tmp_path, state)
    paired, updated = metrics["pools"]
    assert paired["result_count"] == 2
    assert paired["failed_results"] == paired["cached_results"] == 1
    assert paired["review_reasons"] == ["missing_component"]
    assert not paired["published_live"]
    assert updated["published_live"]
    assert metrics["operator_minutes"] is None


def test_failed_deployment_never_counts_as_live_publication(tmp_path):
    metrics = run_metrics(tmp_path, {"status": "failed", "published_slugs": ["pool"], "builds": []})
    assert metrics["pools"] == []
    assert metrics["observed_reports"] == 0


def test_malformed_reports_are_visible_and_not_counted_as_success(tmp_path):
    directory = tmp_path / "build-1"
    directory.mkdir()
    (directory / "extraction-report-direct.json").write_text('{"results": "invalid"}')
    metrics = run_metrics(tmp_path, {"status": "failed", "builds": [{}]})
    assert metrics["unreadable_reports"] == ["extraction-report-direct.json"]
    assert metrics["observed_reports"] == 0


def test_rebuild_metrics_use_final_attempt_not_abandoned_candidate(tmp_path):
    old = tmp_path / "build-1"
    old.mkdir()
    (old / "extraction-report-openai.json").write_text('{"results": [{"slug": "old"}]}')
    assert run_metrics(tmp_path, {"builds": [{}, {}]})["pools"] == []
