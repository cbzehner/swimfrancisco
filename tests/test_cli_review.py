import json
from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli


def _review_dir(data_root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    return data_root / slug / f"{date}-{pdf_sha256[:12]}"


def _seed_review_dir(data_root: Path, slug: str, date: str, pdf_sha256: str) -> Path:
    review_dir = _review_dir(data_root, slug, date, pdf_sha256)
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "gemini-model.json").write_text(json.dumps({
        "provider": "gemini",
        "model": "model",
        "source_pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "effective_start": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))
    (review_dir / "source.pdf").write_bytes(b"%PDF-fake")
    return review_dir


def _seed_content_md(content_dir: Path, slug: str) -> None:
    content_dir.mkdir(parents=True, exist_ok=True)
    (content_dir / f"{slug}.md").write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")


def _patch_dirs(monkeypatch, tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("schedules.cli.DATA_DIR", data)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)
    return data, content


def test_cli_review_reports_nothing_to_review(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0
    assert "nothing to review" in result.output


def test_cli_review_hints_extract_when_data_missing(tmp_path, monkeypatch):
    data, _ = _patch_dirs(monkeypatch, tmp_path)
    import shutil
    shutil.rmtree(data)
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0
    assert "schedules extract" in result.output


def _editing_fake_run(calls: list[list[str]], data_root: Path, slug: str, sha12: str):
    """Fake subprocess.run that simulates an editor making a real edit.

    The byte-identical guard in finalize_draft refuses to mark a review
    complete when the saved payload still byte-equals the provider seed,
    so test runs that mock the editor have to mutate something.
    """
    reviewed_path = data_root / slug / f"2026-04-01-{sha12}" / "reviewed.json"

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if reviewed_path.exists() and any(str(reviewed_path) == part for part in cmd):
            envelope = json.loads(reviewed_path.read_text())
            envelope["payload"]["sessions"][0]["notes"] = "verified"
            reviewed_path.write_text(json.dumps(envelope, indent=2))

        class R:
            returncode = 0

        return R()

    return fake_run


def test_cli_review_end_to_end_with_editor_edit(tmp_path, monkeypatch):
    data, content = _patch_dirs(monkeypatch, tmp_path)
    _seed_review_dir(data, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_content_md(content, "hamilton-pool")

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "schedules.cli.subprocess.run",
        _editing_fake_run(calls, data, "hamilton-pool", "a" * 12),
    )
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0, result.output
    reviewed_file = data / "hamilton-pool" / "2026-04-01-aaaaaaaaaaaa" / "reviewed.json"
    assert reviewed_file.exists()
    assert "Wrote" in result.output
    assert any(call[0] == "open" for call in calls)
    assert any(call[0] in {"hx", "$EDITOR"} or call[0].endswith("hx") for call in calls)


def test_cli_review_rejects_unedited_payload(tmp_path, monkeypatch):
    data, content = _patch_dirs(monkeypatch, tmp_path)
    _seed_review_dir(data, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_content_md(content, "hamilton-pool")

    def fake_run(cmd, *args, **kwargs):
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr("schedules.cli.subprocess.run", fake_run)
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code != 0
    assert "byte-identical" in result.output


def test_cli_review_splits_multi_word_editor(tmp_path, monkeypatch):
    data, content = _patch_dirs(monkeypatch, tmp_path)
    _seed_review_dir(data, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_content_md(content, "hamilton-pool")

    calls: list[list[str]] = []
    fake_run = _editing_fake_run(calls, data, "hamilton-pool", "a" * 12)

    monkeypatch.setattr("schedules.cli.subprocess.run", fake_run)
    monkeypatch.setenv("EDITOR", "code --wait")

    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0, result.output
    editor_calls = [call for call in calls if call and call[0] == "code"]
    assert editor_calls, f"expected `code` invocation, got {calls}"
    assert editor_calls[0][1] == "--wait"


def test_cli_review_filters_by_slug(tmp_path, monkeypatch):
    data, content = _patch_dirs(monkeypatch, tmp_path)
    _seed_review_dir(data, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_review_dir(data, "balboa-pool", "2026-04-01", "b" * 64)
    _seed_content_md(content, "balboa-pool")

    monkeypatch.setattr(
        "schedules.cli.subprocess.run",
        _editing_fake_run([], data, "balboa-pool", "b" * 12),
    )
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review", "--slug", "balboa-pool"])
    assert result.exit_code == 0, result.output
    assert (data / "balboa-pool" / "2026-04-01-bbbbbbbbbbbb" / "reviewed.json").exists()
    assert not (data / "hamilton-pool" / "2026-04-01-aaaaaaaaaaaa" / "reviewed.json").exists()
