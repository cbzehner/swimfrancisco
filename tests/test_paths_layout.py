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
