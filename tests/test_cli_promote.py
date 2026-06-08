from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli


SAMPLE_SCHEDULE = """[[sessions]]
day = "monday"
type = "lap_swim"
start = "07:00"
end = "08:00"
"""


def _seed_spot(content_dir: Path, slug: str, *, current_end: str, upcoming_start: str | None = None) -> Path:
    """Write a minimal spot frontmatter with optional upcoming_schedule."""
    parts = [
        "+++",
        f'title = "{slug}"',
        "",
        "[extra]",
        'effective_start = "2026-01-01"',
        f'effective_end = "{current_end}"',
        SAMPLE_SCHEDULE.strip(),
    ]
    if upcoming_start:
        parts.extend([
            "",
            "[extra.upcoming_schedule]",
            f'effective_start = "{upcoming_start}"',
            'effective_end = "2026-12-31"',
            SAMPLE_SCHEDULE.strip(),
        ])
    parts.extend(["+++", ""])
    path = content_dir / f"{slug}.md"
    path.write_text("\n".join(parts))
    return path


def test_promote_command_walks_spots_skipping_index_and_locales(tmp_path, monkeypatch):
    content = tmp_path / "content" / "spots"
    content.mkdir(parents=True)

    # Eligible: today >= upcoming.start
    _seed_spot(content, "alpha", current_end="2026-06-06", upcoming_start="2026-06-09")
    # Not eligible: today < upcoming.start
    _seed_spot(content, "beta", current_end="2026-06-06", upcoming_start="2026-09-01")
    # No upcoming queued
    _seed_spot(content, "gamma", current_end="2026-12-31", upcoming_start=None)
    # Localized variant — must be skipped (would otherwise look eligible)
    _seed_spot(content, "alpha.es", current_end="2026-06-06", upcoming_start="2026-06-09")
    # Section index — must be skipped
    (content / "_index.md").write_text("+++\ntitle = \"Spots\"\n+++\n")

    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    runner = CliRunner()
    result = runner.invoke(cli, ["promote", "--as-of", "2026-06-09"])
    assert result.exit_code == 0, result.output
    assert "Promoted 1 pool(s): alpha" in result.output

    # alpha promoted: upcoming block gone, root effective_start advanced.
    alpha = (content / "alpha.md").read_text()
    assert "[extra.upcoming_schedule]" not in alpha
    assert 'effective_start = "2026-06-09"' in alpha

    # localized variant untouched (still has its upcoming block)
    alpha_es = (content / "alpha.es.md").read_text()
    assert "[extra.upcoming_schedule]" in alpha_es


def test_promote_command_dry_run_does_not_write(tmp_path, monkeypatch):
    content = tmp_path / "content" / "spots"
    content.mkdir(parents=True)
    path = _seed_spot(content, "alpha", current_end="2026-06-06", upcoming_start="2026-06-09")
    snapshot = path.read_text()

    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    runner = CliRunner()
    result = runner.invoke(cli, ["promote", "--as-of", "2026-06-09", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Would promote 1 pool(s): alpha" in result.output
    assert path.read_text() == snapshot


def test_promote_command_nothing_to_do(tmp_path, monkeypatch):
    content = tmp_path / "content" / "spots"
    content.mkdir(parents=True)
    _seed_spot(content, "alpha", current_end="2026-06-06", upcoming_start="2026-09-01")

    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    runner = CliRunner()
    result = runner.invoke(cli, ["promote", "--as-of", "2026-06-09"])
    assert result.exit_code == 0, result.output
    assert "Nothing to promote." in result.output


def test_promote_command_rejects_bad_as_of(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", tmp_path / "content" / "spots")
    runner = CliRunner()
    result = runner.invoke(cli, ["promote", "--as-of", "tomorrow"])
    assert result.exit_code != 0
    assert "must be YYYY-MM-DD" in result.output
