import json
from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli


def _valid_envelope(slug: str, pdf_sha256: str) -> dict:
    return {
        "slug": slug,
        "pdf_sha256": pdf_sha256,
        "reviewed_at": "2026-04-18",
        "source_pdf_url": "https://example.com/schedule.pdf",
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def test_cli_project_happy_path(tmp_path, monkeypatch):
    snapshots = tmp_path / "reviewed-snapshots"
    content = tmp_path / "content" / "spots"
    (snapshots / "hamilton-pool").mkdir(parents=True)
    (snapshots / "hamilton-pool" / "2026-04-18-aaaaaaaaaaaa.json").write_text(
        json.dumps(_valid_envelope("hamilton-pool", "a" * 64))
    )
    content.mkdir(parents=True)
    (content / "hamilton-pool.md").write_text("+++\ntitle = \"Hamilton\"\n\n[extra]\n+++\n")

    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOTS_DIR", snapshots)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    runner = CliRunner()
    result = runner.invoke(cli, ["project", "hamilton-pool"])
    assert result.exit_code == 0, result.output
    assert "hamilton-pool.md" in result.output


def test_cli_project_missing_slug_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOTS_DIR", tmp_path / "reviewed-snapshots")
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", tmp_path / "content" / "spots")
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "ghost-pool"])
    assert result.exit_code != 0
    assert "no reviewed snapshot" in result.output
