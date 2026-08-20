from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli
from schedules.discover import DiscoverError


def test_extract_requires_exactly_one_source_mode() -> None:
    runner = CliRunner()

    neither = runner.invoke(cli, ["extract"])
    both = runner.invoke(
        cli, ["extract", "--direct", "--provider", "gemini"]
    )

    assert neither.exit_code != 0
    assert both.exit_code != 0
    assert "exactly one of --direct or --provider is required" in neither.output
    assert "exactly one of --direct or --provider is required" in both.output


def _capture_run_pipeline(monkeypatch) -> dict:
    captured: dict = {}

    def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return 0, Path("report.md"), []

    monkeypatch.setattr("schedules.cli.run_pipeline", fake_run_pipeline)
    return captured


def test_extract_provider_applies_discover(monkeypatch) -> None:
    captured = _capture_run_pipeline(monkeypatch)
    result = CliRunner().invoke(cli, ["extract", "--provider", "gemini"])
    assert result.exit_code == 0
    assert captured["apply_discover"] is True
    assert captured["override_url"] is None
    assert captured["compare_with"] is None


def test_extract_no_discover_disables_discover(monkeypatch) -> None:
    captured = _capture_run_pipeline(monkeypatch)
    result = CliRunner().invoke(
        cli, ["extract", "--provider", "gemini", "--no-discover"]
    )
    assert result.exit_code == 0
    assert captured["apply_discover"] is False


def test_extract_direct_never_applies_discover(monkeypatch) -> None:
    captured = _capture_run_pipeline(monkeypatch)
    result = CliRunner().invoke(cli, ["extract", "--direct"])
    assert result.exit_code == 0
    assert captured["apply_discover"] is False


def test_extract_force_still_applies_discover(monkeypatch) -> None:
    captured = _capture_run_pipeline(monkeypatch)
    result = CliRunner().invoke(
        cli, ["extract", "--provider", "gemini", "--force"]
    )
    assert result.exit_code == 0
    assert captured["apply_discover"] is True
    assert captured["force"] is True


def test_extract_url_requires_exactly_one_only_slug() -> None:
    runner = CliRunner()
    missing = runner.invoke(
        cli,
        ["extract", "--provider", "gemini", "--url", "https://example.test/notice.pdf"],
    )
    many = runner.invoke(
        cli,
        [
            "extract",
            "--provider",
            "gemini",
            "--only",
            "hamilton-pool,sava-pool",
            "--url",
            "https://example.test/notice.pdf",
        ],
    )
    assert missing.exit_code != 0
    assert many.exit_code != 0
    assert "--url requires --only with exactly one slug" in missing.output
    assert "--url requires --only with exactly one slug" in many.output


def test_extract_url_incompatible_with_direct() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "extract",
            "--direct",
            "--only",
            "hamilton-pool",
            "--url",
            "https://example.test/notice.pdf",
        ],
    )
    assert result.exit_code != 0
    assert "--url is incompatible with --direct" in result.output


def test_extract_url_skips_discover_and_passes_override(monkeypatch) -> None:
    captured = _capture_run_pipeline(monkeypatch)
    url = "https://sfrecpark.org/DocumentCenter/View/29808"
    result = CliRunner().invoke(
        cli,
        [
            "extract",
            "--provider",
            "gemini",
            "--only",
            "garfield-pool",
            "--url",
            url,
        ],
    )
    assert result.exit_code == 0
    assert captured["apply_discover"] is False
    assert captured["override_url"] == url
    assert captured["slugs"] == ["garfield-pool"]


def test_bakeoff_does_not_apply_discover(monkeypatch) -> None:
    captured = _capture_run_pipeline(monkeypatch)
    result = CliRunner().invoke(
        cli,
        [
            "debug",
            "bakeoff",
            "--only",
            "hamilton-pool",
            "--provider",
            "gemini",
            "--compare-with",
            "anthropic",
        ],
    )
    assert result.exit_code == 0
    assert captured["apply_discover"] is False
    assert captured["compare_with"] == "anthropic"


def test_extract_prints_discover_error(monkeypatch) -> None:
    def boom(**_kwargs):
        raise DiscoverError("every Rec & Park facility page failed to fetch")

    monkeypatch.setattr("schedules.cli.run_pipeline", boom)
    result = CliRunner().invoke(cli, ["extract", "--provider", "gemini"])
    assert result.exit_code == 1
    assert "every Rec & Park facility page failed to fetch" in result.output
    assert "0 pools processed" not in result.output
