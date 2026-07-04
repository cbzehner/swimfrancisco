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
            "effective_start": "2026-03-17",
            "schedule_basis": "swim_schedule",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00", "evidence": "Lap Swim 7-8am"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }


def _seed_review_dir(data_root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    review_dir = data_root / slug / f"{date}-{pdf_sha256[:12]}"
    review_dir.mkdir(parents=True)
    (review_dir / "reviewed.json").write_text(
        json.dumps(_valid_envelope(slug, pdf_sha256))
    )
    return review_dir


def test_cli_project_happy_path(tmp_path, monkeypatch):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_review_dir(data, "hamilton-pool", "2026-04-18", "a" * 64)
    content.mkdir(parents=True)
    (content / "hamilton-pool.md").write_text("+++\ntitle = \"Hamilton\"\n\n[extra]\n+++\n")

    monkeypatch.setattr("schedules.cli.DATA_DIR", data)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)

    runner = CliRunner()
    result = runner.invoke(cli, ["project", "hamilton-pool"])
    assert result.exit_code == 0, result.output
    assert "hamilton-pool.md" in result.output


def test_cli_project_missing_slug_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("schedules.cli.DATA_DIR", tmp_path / "data")
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", tmp_path / "content" / "spots")
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "ghost-pool"])
    assert result.exit_code != 0
    assert "no review dir" in result.output
