"""Retention for captured snapshots: what each clause of the rule protects.

Every snapshot dir the automation writes is committed, so without a rule the
tree grows on every run. These cover the five ways a dir earns its place.
"""

from __future__ import annotations

import json

import pytest

from schedules.prune import plan_prune, prune


def snapshot(data_root, slug, name, **files):
    directory = data_root / slug / name
    directory.mkdir(parents=True)
    for filename, content in files.items():
        (directory / filename).write_text(content if isinstance(content, str) else json.dumps(content))
    return directory


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path


def test_keeps_only_the_newest_reviewed_snapshot(repo):
    data = repo / "data"
    older = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                     **{"source.html": "old", "reviewed.json": {"slug": "sava-pool"}})
    newest = snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
                      **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    assert plan_prune(data, repo) == [older]
    assert newest.is_dir()


def test_keeps_a_snapshot_pending_review(repo):
    data = repo / "data"
    snapshot(data, "sava-pool", "2026-08-21-cccccccccccc",
             **{"source.html": "pending", "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
             **{"source.html": "reviewed", "reviewed.json": {"slug": "sava-pool"}})
    assert plan_prune(data, repo) == []


def test_deletes_a_reviewed_snapshot_that_kept_its_provider_artifact(repo):
    data = repo / "data"
    stale = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                     **{"source.html": "old", "openai-gpt-5-5-2026-04-23.json": {"provider": "openai"},
                        "reviewed.json": {"slug": "sava-pool"}})
    snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
             **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    assert plan_prune(data, repo) == [stale]


def test_keeps_a_snapshot_another_review_was_carried_from(repo):
    data = repo / "data"
    prior = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                     **{"source.html": "old", "reviewed.json": {"slug": "sava-pool"}})
    snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb", **{
        "source.html": "new",
        "reviewed.json": {"slug": "sava-pool",
                          "carried_from": "data/sava-pool/2026-08-19-aaaaaaaaaaaa/reviewed.json"}})
    assert plan_prune(data, repo) == []
    assert prior.is_dir()


def test_deletes_a_carry_chain_left_behind_by_its_own_review(repo):
    """A deleted review carries nothing forward, so its source goes with it."""
    data = repo / "data"
    oldest = snapshot(data, "sava-pool", "2026-08-18-cccccccccccc",
                      **{"source.html": "oldest", "reviewed.json": {"slug": "sava-pool"}})
    carrier = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa", **{
        "source.html": "old",
        "reviewed.json": {"slug": "sava-pool",
                          "carried_from": "data/sava-pool/2026-08-18-cccccccccccc/reviewed.json"}})
    newest = snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
                      **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    assert plan_prune(data, repo) == [oldest, carrier]
    assert prune(data, repo, dry_run=False) == [oldest, carrier]
    assert plan_prune(data, repo) == []
    assert newest.is_dir()


def test_keeps_every_pdf_snapshot_for_the_backtest_corpus(repo):
    data = repo / "data"
    snapshot(data, "hamilton-pool", "2026-08-19-aaaaaaaaaaaa",
             **{"source.pdf": "%PDF old", "reviewed.json": {"slug": "hamilton-pool"}})
    snapshot(data, "hamilton-pool", "2026-08-20-bbbbbbbbbbbb",
             **{"source.pdf": "%PDF new", "reviewed.json": {"slug": "hamilton-pool"}})
    assert plan_prune(data, repo) == []


def test_deletes_a_workbook_snapshot_even_though_it_renders_a_pdf(repo):
    data = repo / "data"
    stale = snapshot(data, "koret-center", "2026-08-19-aaaaaaaaaaaa",
                     **{"source.xlsx": "PK old", "source.pdf": "%PDF rendered",
                        "reviewed.json": {"slug": "koret-center"}})
    snapshot(data, "koret-center", "2026-08-20-bbbbbbbbbbbb",
             **{"source.xlsx": "PK new", "source.pdf": "%PDF rendered",
                "reviewed.json": {"slug": "koret-center"}})
    assert plan_prune(data, repo) == [stale]


def test_keeps_a_snapshot_a_test_or_document_names(repo):
    data = repo / "data"
    snapshot(data, "sava-pool", "2026-08-17-dddddddddddd",
             **{"source.html": "fixture", "reviewed.json": {"slug": "sava-pool"}})
    snapshot(data, "sava-pool", "2026-08-18-eeeeeeeeeeee",
             **{"source.html": "documented", "reviewed.json": {"slug": "sava-pool"}})
    unnamed = snapshot(data, "sava-pool", "2026-08-19-ffffffffffff",
                       **{"source.html": "orphan", "reviewed.json": {"slug": "sava-pool"}})
    snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
             **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    (repo / "tests" / "test_frozen.py").write_text(
        'CAPTURE = "data/sava-pool/2026-08-17-dddddddddddd/source.html"\n')
    (repo / "docs" / "schedules.md").write_text("The 2026-08-18-eeeeeeeeeeee capture shows this.\n")
    assert plan_prune(data, repo) == [unnamed]


def test_prune_removes_whole_dirs_only_when_it_is_not_a_dry_run(repo):
    data = repo / "data"
    stale = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                     **{"source.html": "old", "reviewed.json": {"slug": "sava-pool"}})
    kept = snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
                    **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    assert prune(data, repo, dry_run=True) == [stale]
    assert stale.is_dir()
    assert prune(data, repo, dry_run=False) == [stale]
    assert not stale.exists()
    assert kept.is_dir() and (kept / "source.html").read_text() == "new"
    assert prune(data, repo, dry_run=False) == []


def test_prune_never_follows_a_symlinked_snapshot(repo):
    data = repo / "data"
    real = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                    **{"source.html": "old", "reviewed.json": {"slug": "sava-pool"}})
    snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
             **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    link = data / "sava-pool" / "2026-08-18-cccccccccccc"
    link.symlink_to(real, target_is_directory=True)
    assert prune(data, repo, dry_run=False) == [real]
    assert link.is_symlink()


def test_prune_ignores_paths_that_are_not_snapshots(repo):
    data = repo / "data"
    (data / "bulletin.json").write_text("{}")
    (data / "i18n").mkdir()
    (data / "i18n" / "en.json").write_text("{}")
    (data / "sava-pool").mkdir()
    (data / "sava-pool" / "notes").mkdir()
    assert plan_prune(data, repo) == []
    assert (data / "sava-pool" / "notes").is_dir()
