import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from schedules.cli import cli
from schedules.review_server import ReviewApp, _csv_sections
from schedules.models import PoolEntry


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
            "schedule_basis": "swim_schedule",
            "sessions": [
                {"day": d, "type": "lap_swim", "start": "07:00", "end": "08:00", "evidence": "Lap Swim 7-8am"}
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


def test_cli_review_launches_local_site(tmp_path, monkeypatch):
    data, _ = _patch_dirs(monkeypatch, tmp_path)
    _seed_review_dir(data, "hamilton-pool", "2026-04-01", "a" * 64)
    calls = []
    monkeypatch.setattr("schedules.cli.serve_review_app", lambda **kwargs: calls.append(kwargs))

    runner = CliRunner()
    result = runner.invoke(cli, ["review", "--port", "4317", "--no-open"])
    assert result.exit_code == 0, result.output
    assert calls == [{"port": 4317, "open_browser": False}]


def test_review_app_lists_source_kind_and_seed_without_writing(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    review_dir = _seed_review_dir(data, "koret-center", "2026-04-01", "a" * 64)
    (review_dir / "source.pdf").rename(review_dir / "source.csv")
    app = ReviewApp(data_root=data, content_spots_dir=content)

    assert app.list_reviews() == [{
        "slug": "koret-center",
        "sha12": "a" * 12,
        "fetch_date": "2026-04-01",
        "source_kind": "csv",
        "sequential": False,
    }]
    assert app.review("koret-center")["envelope"]["slug"] == "koret-center"
    assert not (review_dir / "reviewed.json").exists()


def test_review_app_lists_only_latest_pending_capture_per_pool(tmp_path):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_review_dir(data, "koret-center", "2026-07-06", "a" * 64)
    latest = _seed_review_dir(data, "koret-center", "2026-07-10", "b" * 64)
    app = ReviewApp(data_root=data, content_spots_dir=content)

    assert app.list_reviews() == [{
        "slug": "koret-center",
        "sha12": "b" * 12,
        "fetch_date": "2026-07-10",
        "source_kind": "pdf",
        "sequential": False,
    }]
    assert app.candidate("koret-center").review_dir == latest


def test_csv_source_is_split_into_calendar_sections():
    source = '--- Monday ---\n"Monday Hours","Lane 1"\n"7:00 AM","Lap Swim"\n\n--- Tuesday ---\n"Tuesday Hours","Lane 1"'

    assert _csv_sections(source) == [
        ("Monday", [["Monday Hours", "Lane 1"], ["7:00 AM", "Lap Swim"]]),
        ("Tuesday", [["Tuesday Hours", "Lane 1"]]),
    ]


def test_review_app_saves_identical_attested_payload_and_projects(tmp_path, monkeypatch):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    review_dir = _seed_review_dir(data, "koret-center", "2026-04-01", "a" * 64)
    _seed_content_md(content, "koret-center")
    app = ReviewApp(data_root=data, content_spots_dir=content)
    envelope = app.review("koret-center")["envelope"]
    monkeypatch.setattr("schedules.review_server.current_source_identity", lambda slug: "a" * 64)

    result = app.save("koret-center", envelope, "a" * 64)

    assert result == review_dir / "reviewed.json"
    assert result.exists()
    assert "[[extra.schedules.sessions]]" in (content / "koret-center.md").read_text()


def test_review_app_rejects_save_when_source_changed(tmp_path, monkeypatch):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_review_dir(data, "koret-center", "2026-04-01", "a" * 64)
    _seed_content_md(content, "koret-center")
    app = ReviewApp(data_root=data, content_spots_dir=content)
    envelope = app.review("koret-center")["envelope"]
    monkeypatch.setattr("schedules.review_server.current_source_identity", lambda slug: "b" * 64)

    with pytest.raises(Exception, match="Official source changed"):
        app.save("koret-center", envelope, "a" * 64)


def test_review_app_reports_current_and_changed_source(tmp_path, monkeypatch):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_review_dir(data, "koret-center", "2026-04-01", "a" * 64)
    app = ReviewApp(data_root=data, content_spots_dir=content)

    monkeypatch.setattr("schedules.review_server.current_source_identity", lambda slug: "a" * 64)
    assert app.check_source("koret-center") == {"status": "current", "source_identity": "a" * 64}

    monkeypatch.setattr("schedules.review_server.current_source_identity", lambda slug: "b" * 64)
    assert app.check_source("koret-center") == {"status": "changed", "source_identity": "b" * 64}


@pytest.mark.parametrize("source_kind, configured_provider, expected_mode", [
    ("koret_google_sheet", "anthropic", "direct"),
    ("pomeroy_html", "gemini", "direct"),
    ("sfrecpark_pdf", "anthropic", "anthropic"),
])
def test_review_refresh_uses_registry_source_mode(tmp_path, monkeypatch, source_kind, configured_provider, expected_mode):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_review_dir(data, "koret-center", "2026-04-01", "a" * 64)
    app = ReviewApp(data_root=data, content_spots_dir=content)
    entry = PoolEntry(
        slug="koret-center",
        pdf_url="https://example.com/source.pdf",
        official_page_url="https://example.com/pool",
        source_kind=source_kind,
    )
    monkeypatch.setattr("schedules.review_server.load_registry", lambda: [entry])
    monkeypatch.setattr("schedules.review_server.current_source_identity", lambda slug: "b" * 64)
    monkeypatch.setenv("SCHEDULES_PROVIDER", configured_provider)
    calls = []
    monkeypatch.setattr(
        "schedules.review_server.run_pipeline",
        lambda **kwargs: (calls.append(kwargs) or (0, None, [object()])),
    )

    app.refresh("koret-center")

    assert calls[0]["source_mode"] == expected_mode


def test_review_refresh_rejects_invalid_pdf_provider(tmp_path, monkeypatch):
    data = tmp_path / "data"
    content = tmp_path / "content" / "spots"
    _seed_review_dir(data, "koret-center", "2026-04-01", "a" * 64)
    app = ReviewApp(data_root=data, content_spots_dir=content)
    entry = PoolEntry(
        slug="koret-center",
        pdf_url="https://example.com/source.pdf",
        official_page_url="https://example.com/pool",
        source_kind="sfrecpark_pdf",
    )
    monkeypatch.setattr("schedules.review_server.load_registry", lambda: [entry])
    monkeypatch.setattr("schedules.review_server.current_source_identity", lambda slug: "b" * 64)
    monkeypatch.setenv("SCHEDULES_PROVIDER", "direct")

    with pytest.raises(ValueError, match="Unsupported provider"):
        app.refresh("koret-center")
