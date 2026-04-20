from __future__ import annotations

from datetime import date

import pytest

from schedules import paths


def test_pdf_dir_is_under_data_dir():
    assert paths.pdf_dir("hamilton-pool") == paths.DATA_DIR / "pdfs" / "hamilton-pool"


def test_reviewed_snapshot_dir_is_under_data_dir():
    assert paths.reviewed_snapshot_dir("hamilton-pool") == paths.DATA_DIR / "reviewed-snapshots" / "hamilton-pool"


def test_pdf_filename_is_date_dash_prefix():
    sha = "a" * 64
    assert paths.pdf_filename("2026-04-17", sha) == "2026-04-17-aaaaaaaaaaaa.pdf"


def test_snapshot_filename_is_date_dash_prefix():
    sha = "a" * 64
    assert paths.snapshot_filename("2026-04-17", sha) == "2026-04-17-aaaaaaaaaaaa.json"


def test_latest_pdf_returns_none_when_dir_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    assert paths.latest_pdf("hamilton-pool") is None


def test_latest_pdf_picks_highest_date(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    slug_dir = tmp_path / "pdfs" / "hamilton-pool"
    slug_dir.mkdir(parents=True)
    older = slug_dir / "2026-01-01-aaaaaaaaaaaa.pdf"
    newer = slug_dir / "2026-04-17-bbbbbbbbbbbb.pdf"
    older.write_bytes(b"x")
    newer.write_bytes(b"y")
    assert paths.latest_pdf("hamilton-pool") == newer


def test_latest_reviewed_snapshot_picks_highest_date(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    slug_dir = tmp_path / "reviewed-snapshots" / "hamilton-pool"
    slug_dir.mkdir(parents=True)
    older = slug_dir / "2026-01-01-aaaaaaaaaaaa.json"
    newer = slug_dir / "2026-04-17-bbbbbbbbbbbb.json"
    older.write_text("{}")
    newer.write_text("{}")
    assert paths.latest_reviewed_snapshot("hamilton-pool") == newer


def test_reviewed_snapshot_drafts_dir_is_in_data():
    from schedules.paths import DATA_DIR, REVIEWED_SNAPSHOT_DRAFTS_DIR
    assert REVIEWED_SNAPSHOT_DRAFTS_DIR == DATA_DIR / "reviewed-snapshot-drafts"


# Consolidated-layout helpers (Task 2): data/<slug>/<date>-<sha12>/

def test_review_dir_shape(tmp_path):
    p = paths.review_dir("hamilton-pool", "2026-04-19", "a" * 64, root=tmp_path)
    assert p.name == "2026-04-19-aaaaaaaaaaaa"
    assert p.parent.name == "hamilton-pool"
    assert p.parent.parent == tmp_path


def test_pdf_path_is_source_pdf(tmp_path):
    p = paths.pdf_path("hamilton-pool", "2026-04-19", "a" * 64, root=tmp_path)
    assert p.name == "source.pdf"
    assert p.parent.name == "2026-04-19-aaaaaaaaaaaa"


def test_artifact_path_includes_provider_and_model(tmp_path):
    p = paths.artifact_path(
        "hamilton-pool",
        "2026-04-19",
        "a" * 64,
        "gemini",
        "gemini-3.1-flash-lite-preview",
        root=tmp_path,
    )
    assert p.name == "gemini-gemini-3-1-flash-lite-preview.json"
    assert p.parent.name == "2026-04-19-aaaaaaaaaaaa"


def test_reviewed_path_is_reviewed_json(tmp_path):
    p = paths.reviewed_path("hamilton-pool", "2026-04-19", "a" * 64, root=tmp_path)
    assert p.name == "reviewed.json"
    assert p.parent.name == "2026-04-19-aaaaaaaaaaaa"


def test_all_review_dirs_returns_empty_for_missing_slug(tmp_path):
    assert paths.all_review_dirs("ghost-pool", root=tmp_path) == []


def test_all_review_dirs_sorts_ascending(tmp_path):
    slug_dir = tmp_path / "hamilton-pool"
    slug_dir.mkdir()
    older = slug_dir / "2026-04-01-aaaaaaaaaaaa"
    newer = slug_dir / "2026-04-19-bbbbbbbbbbbb"
    older.mkdir()
    newer.mkdir()
    assert paths.all_review_dirs("hamilton-pool", root=tmp_path) == [older, newer]


def test_latest_review_dir_returns_newest(tmp_path):
    slug_dir = tmp_path / "hamilton-pool"
    slug_dir.mkdir()
    (slug_dir / "2026-04-01-aaaaaaaaaaaa").mkdir()
    newest = slug_dir / "2026-04-19-bbbbbbbbbbbb"
    newest.mkdir()
    assert paths.latest_review_dir("hamilton-pool", root=tmp_path) == newest


def test_latest_review_dir_returns_none_when_empty(tmp_path):
    assert paths.latest_review_dir("ghost-pool", root=tmp_path) is None
