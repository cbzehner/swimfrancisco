import json
from pathlib import Path

from click.testing import CliRunner

from schedules.cli import cli


def _write_artifact(root: Path, slug: str, pdf_sha256: str) -> None:
    artifact_dir = root / slug / pdf_sha256[:12]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "gemini-model.json").write_text(json.dumps({
        "slug": slug,
        "provider": "gemini",
        "model": "model",
        "pdf_url": "https://example.com/x.pdf",
        "source_pdf_url": "https://example.com/x.pdf",
        "pdf_sha256": pdf_sha256,
        "payload": {
            "schedule_effective": "2026-03-17",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00"}
                for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            "closures": [],
        },
    }))


def _write_pdf(root: Path, slug: str, date: str, pdf_sha256: str) -> None:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / f"{date}-{pdf_sha256[:12]}.pdf").write_bytes(b"%PDF-fake")


def _seed_content_md(content_dir: Path, slug: str) -> None:
    content_dir.mkdir(parents=True, exist_ok=True)
    (content_dir / f"{slug}.md").write_text("+++\ntitle = \"X\"\n\n[extra]\n+++\n")


def _patch_dirs(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "reviewed-snapshots"
    data = tmp_path / "data"
    pdfs = tmp_path / "pdfs"
    content = tmp_path / "content" / "spots"
    artifacts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("schedules.cli.ARTIFACTS_DIR", artifacts)
    monkeypatch.setattr("schedules.cli.REVIEWED_SNAPSHOTS_DIR", snapshots)
    monkeypatch.setattr("schedules.cli.DATA_DIR", data)
    monkeypatch.setattr("schedules.cli.PDF_CACHE_DIR", pdfs)
    monkeypatch.setattr("schedules.cli.CONTENT_SPOTS_DIR", content)
    return artifacts, snapshots, data, pdfs, content


def test_cli_review_reports_nothing_to_review(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0
    assert "nothing to review" in result.output


def test_cli_review_hints_extract_when_artifacts_missing(tmp_path, monkeypatch):
    # Patch paths then remove the artifacts directory.
    artifacts, *_ = _patch_dirs(monkeypatch, tmp_path)
    import shutil
    shutil.rmtree(artifacts)
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0
    assert "schedules extract" in result.output


def test_cli_review_end_to_end_with_editor_noop(tmp_path, monkeypatch):
    artifacts, snapshots, data, pdfs, content = _patch_dirs(monkeypatch, tmp_path)
    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_content_md(content, "hamilton-pool")

    # Replace subprocess.run with no-ops: PDF open + editor both succeed immediately.
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        class R: returncode = 0
        return R()
    monkeypatch.setattr("schedules.cli.subprocess.run", fake_run)
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0, result.output
    reviewed_dir = data / "hamilton-pool"
    assert any(reviewed_dir.glob("*/reviewed.json"))  # reviewed.json was written
    assert "Wrote" in result.output
    # Editor and `open` were both invoked.
    assert any(call[0] == "open" for call in calls)
    assert any(call[0] in {"hx", "$EDITOR"} or call[0].endswith("hx") for call in calls)


def test_cli_review_splits_multi_word_editor(tmp_path, monkeypatch):
    artifacts, snapshots, data, pdfs, content = _patch_dirs(monkeypatch, tmp_path)
    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _seed_content_md(content, "hamilton-pool")

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        class R: returncode = 0
        return R()

    monkeypatch.setattr("schedules.cli.subprocess.run", fake_run)
    monkeypatch.setenv("EDITOR", "code --wait")

    runner = CliRunner()
    result = runner.invoke(cli, ["review"])
    assert result.exit_code == 0, result.output
    editor_calls = [call for call in calls if call and call[0] == "code"]
    assert editor_calls, f"expected `code` invocation, got {calls}"
    assert editor_calls[0][1] == "--wait"


def test_cli_review_filters_by_slug(tmp_path, monkeypatch):
    artifacts, snapshots, data, pdfs, content = _patch_dirs(monkeypatch, tmp_path)
    _write_artifact(artifacts, "hamilton-pool", "a" * 64)
    _write_artifact(artifacts, "balboa-pool", "b" * 64)
    _write_pdf(pdfs, "hamilton-pool", "2026-04-01", "a" * 64)
    _write_pdf(pdfs, "balboa-pool", "2026-04-01", "b" * 64)
    _seed_content_md(content, "balboa-pool")

    monkeypatch.setattr("schedules.cli.subprocess.run", lambda *a, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setenv("EDITOR", "hx")

    runner = CliRunner()
    result = runner.invoke(cli, ["review", "--slug", "balboa-pool"])
    assert result.exit_code == 0, result.output
    assert (data / "balboa-pool").exists()
    assert not (data / "hamilton-pool").exists()
