from click.testing import CliRunner

from schedules.cli import cli


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
