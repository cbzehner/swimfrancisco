from __future__ import annotations

from schedules import paths


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


def test_parse_review_dir_name_accepts_canonical_shape():
    assert paths.parse_review_dir_name("2026-04-19-aaaaaaaaaaaa") == (
        "2026-04-19",
        "aaaaaaaaaaaa",
    )
    assert paths.parse_review_dir_name("2026-04-19-0123456789ab") == (
        "2026-04-19",
        "0123456789ab",
    )


def test_parse_review_dir_name_rejects_non_canonical():
    assert paths.parse_review_dir_name("2026-04-19-AAAAAAAAAAAA") is None
    assert paths.parse_review_dir_name("2026-04-19-aaaaaaaaaaa") is None
    assert paths.parse_review_dir_name("2026-04-19-aaaaaaaaaaaag") is None
    assert paths.parse_review_dir_name("2026-04-19") is None
    assert paths.parse_review_dir_name("notes") is None
    assert paths.parse_review_dir_name("2026-04-19-aaaaaaaaaaaa-extra") is None
    assert paths.parse_review_dir_name("2026-4-19-aaaaaaaaaaaa") is None
    assert paths.parse_review_dir_name("2026-99-99-aaaaaaaaaaaa") is None
    assert paths.parse_review_dir_name("2026-02-30-aaaaaaaaaaaa") is None


def test_all_review_dirs_sorts_ascending(tmp_path):
    slug_dir = tmp_path / "hamilton-pool"
    slug_dir.mkdir()
    older = slug_dir / "2026-04-01-aaaaaaaaaaaa"
    newer = slug_dir / "2026-04-19-bbbbbbbbbbbb"
    older.mkdir()
    newer.mkdir()
    assert paths.all_review_dirs("hamilton-pool", root=tmp_path) == [older, newer]


def test_all_review_dirs_ignores_non_matching_subdirs(tmp_path):
    slug_dir = tmp_path / "hamilton-pool"
    slug_dir.mkdir()
    kept = slug_dir / "2026-04-19-aaaaaaaaaaaa"
    kept.mkdir()
    (slug_dir / "notes").mkdir()
    (slug_dir / "2026-04-19").mkdir()
    (slug_dir / "2026-04-19-aaaaaaaaaaaag").mkdir()
    (slug_dir / "scratch.txt").write_text("nope\n")
    assert paths.all_review_dirs("hamilton-pool", root=tmp_path) == [kept]


def test_latest_review_dir_returns_newest(tmp_path):
    slug_dir = tmp_path / "hamilton-pool"
    slug_dir.mkdir()
    (slug_dir / "2026-04-01-aaaaaaaaaaaa").mkdir()
    newest = slug_dir / "2026-04-19-bbbbbbbbbbbb"
    newest.mkdir()
    assert paths.latest_review_dir("hamilton-pool", root=tmp_path) == newest


def test_latest_review_dir_returns_none_when_empty(tmp_path):
    assert paths.latest_review_dir("ghost-pool", root=tmp_path) is None


def test_latest_reviewed_dir_skips_newer_pending_capture(tmp_path):
    slug_dir = tmp_path / "hamilton-pool"
    slug_dir.mkdir()
    reviewed = slug_dir / "2026-04-18-aaaaaaaaaaaa"
    reviewed.mkdir()
    (reviewed / "reviewed.json").write_text("{}")
    (slug_dir / "2026-04-19-bbbbbbbbbbbb").mkdir()

    assert paths.latest_reviewed_dir("hamilton-pool", root=tmp_path) == reviewed
