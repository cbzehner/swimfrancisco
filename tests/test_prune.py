"""Retention for captured snapshots: what each clause of the rule protects.

Every snapshot dir the automation writes is committed, so without a rule the
tree grows on every run. These cover the ways a dir earns its place, and the
two ways it loses one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def test_keeps_a_snapshot_pending_review_from_the_newest_capture_date(repo):
    data = repo / "data"
    snapshot(data, "sava-pool", "2026-08-21-cccccccccccc",
             **{"source.html": "pending", "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    snapshot(data, "sava-pool", "2026-08-21-dddddddddddd",
             **{"source.html": "also pending", "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
             **{"source.html": "reviewed", "reviewed.json": {"slug": "sava-pool"}})
    assert plan_prune(data, repo) == []


def test_deletes_a_pending_extraction_a_later_review_superseded(repo):
    """A review of a later capture answers the question the older one asked."""
    data = repo / "data"
    superseded = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                          **{"source.html": "stale", "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    current = snapshot(data, "sava-pool", "2026-08-21-cccccccccccc",
                       **{"source.html": "reviewed", "reviewed.json": {"slug": "sava-pool"}})
    assert plan_prune(data, repo) == [superseded]
    assert current.is_dir()


def test_keeps_an_unreviewed_extraction_a_later_bare_capture_did_not_supersede(repo):
    """A failed extraction on the newer day reviews nothing, so both wait."""
    data = repo / "data"
    pending = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                       **{"source.html": "pending", "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    bare = snapshot(data, "sava-pool", "2026-08-21-cccccccccccc", **{"source.html": "captured"})
    assert plan_prune(data, repo) == []
    assert pending.is_dir() and bare.is_dir()


def test_keeps_a_bare_capture_on_the_newest_capture_date(repo):
    """Source bytes with no artifact yet are awaiting extraction or closure review."""
    data = repo / "data"
    bare = snapshot(data, "sava-pool", "2026-08-21-cccccccccccc",
                    **{"source.html": "captured", "source.sha256": hashlib.sha256(b"captured").hexdigest()})
    assert plan_prune(data, repo) == []
    assert bare.is_dir()


def test_deletes_a_bare_capture_a_newer_one_replaced(repo):
    """Nothing extracted it and a newer capture of the slug arrived; it is spent."""
    data = repo / "data"
    spent = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa", **{"source.html": "captured"})
    current = snapshot(data, "sava-pool", "2026-08-21-cccccccccccc", **{"source.html": "recaptured"})
    assert plan_prune(data, repo) == [spent]
    assert current.is_dir()


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


def test_deletes_a_capture_whose_bytes_disagree_with_its_own_sidecar(repo):
    """A capture that cannot prove its identity blocks every later fetch."""
    data = repo / "data"
    broken = snapshot(data, "sava-pool", "2026-08-21-ffffffffffff",
                      **{"source.html": "not what the sidecar says",
                         "source.sha256": hashlib.sha256(b"something else").hexdigest(),
                         "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    intact = snapshot(data, "sava-pool", "2026-08-21-cccccccccccc",
                      **{"source.html": "pending",
                         "source.sha256": hashlib.sha256(b"pending").hexdigest(),
                         "direct-pomeroy-html-v1.json": {"provider": "direct"}})
    assert plan_prune(data, repo) == [broken]
    assert intact.is_dir()


def test_keeps_a_mismatched_capture_the_backtest_corpus_needs(repo):
    data = repo / "data"
    snapshot(data, "hamilton-pool", "2026-08-21-ffffffffffff",
             **{"source.pdf": "%PDF", "source.sha256": hashlib.sha256(b"other").hexdigest()})
    assert plan_prune(data, repo) == []


def test_prune_never_follows_a_symlinked_snapshot(repo):
    """A symlink is neither deleted nor allowed to stand in for the newest review."""
    data = repo / "data"
    real = snapshot(data, "sava-pool", "2026-08-19-aaaaaaaaaaaa",
                    **{"source.html": "old", "reviewed.json": {"slug": "sava-pool"}})
    newest = snapshot(data, "sava-pool", "2026-08-20-bbbbbbbbbbbb",
                      **{"source.html": "new", "reviewed.json": {"slug": "sava-pool"}})
    link = data / "sava-pool" / "2026-08-21-cccccccccccc"
    link.symlink_to(real, target_is_directory=True)
    assert prune(data, repo, dry_run=False) == [real]
    assert link.is_symlink() and newest.is_dir()


def test_prune_ignores_paths_that_are_not_snapshots(repo):
    data = repo / "data"
    (data / "bulletin.json").write_text("{}")
    (data / "i18n").mkdir()
    (data / "i18n" / "en.json").write_text("{}")
    (data / "sava-pool").mkdir()
    (data / "sava-pool" / "notes").mkdir()
    assert plan_prune(data, repo) == []
    assert (data / "sava-pool" / "notes").is_dir()


def test_the_committed_capture_tree_needs_every_dir_it_holds():
    """Retention is a rule the repository already satisfies, not a pending sweep."""
    root = Path(__file__).parents[1]
    assert plan_prune(root / "data", root) == []
