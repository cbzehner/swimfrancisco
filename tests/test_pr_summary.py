"""PR body for auto-extract: honest lead, off-table siblings, operator checklist."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from schedules.pr_summary import render_pr_body


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    return repo


def _stage_registry(repo: Path, text: str = 'slug = "garfield-pool"\n') -> None:
    path = repo / "schedule-tools" / "src" / "schedules" / "registry.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    _git(repo, "add", "schedule-tools/src/schedules/registry.toml")


def _write_decisions(repo: Path, decisions: list[dict]) -> None:
    path = repo / "tmp" / "discovery-decisions.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(decisions) + "\n")


def _candidate(
    view_id: int,
    *,
    kind: str,
    source: str,
    filename: str | None = None,
) -> dict:
    return {
        "view_id": view_id,
        "href": f"https://sfrecpark.org/DocumentCenter/View/{view_id}",
        "anchor_text": filename or "",
        "kind": kind,
        "filename": filename,
        "source": source,
    }


def _write_provider_json(
    path: Path,
    *,
    effective_start: str,
    effective_end: str,
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "provider": "gemini",
                "payload": {
                    "effective_start": effective_start,
                    "effective_end": effective_end,
                    "sessions": [],
                },
            }
        )
        + "\n"
    )


CHECKLIST = [
    "- [ ] git fetch origin && git checkout auto/schedules-extract",
    "- [ ] just schedules-review  (work the queue)",
    "- [ ] just release           (bulletin only if reviewed payloads changed)",
    "- [ ] commit content/spots, data, registry.toml",
    "- [ ] merge this PR; do not open a second one",
]


def test_flag_only_pr_names_garfield_off_table_sibling(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo)
    _write_decisions(
        repo,
        [
            {
                "slug": "garfield-pool",
                "action": "flag",
                "old_url": "https://sfrecpark.org/DocumentCenter/View/29564",
                "new_url": None,
                "kind": "session_grid",
                "reason": "band_session_grid",
                "blocking": True,
                "candidates": [
                    _candidate(
                        29808,
                        kind="closure_notice",
                        source="table",
                        filename="Garfield Pool Maintenance Closure 8-14_9-7 2026.pdf",
                    ),
                    _candidate(
                        29799,
                        kind="session_grid",
                        source="band",
                        filename="Garfield Pool Fall 2026.pdf",
                    ),
                ],
                "extra_candidates": [],
            }
        ],
    )

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    assert "Nothing to review" not in text
    assert "`garfield-pool`" in text
    assert "flyer 29808" in text
    assert "29799" in text
    assert "band-flagged" in text
    assert "unverified projection" not in text
    assert "Next Monday" not in text
    assert "The live site stays on the last reviewed window until this PR merges." in text
    assert "Daily extract will refresh this PR" in text
    for item in CHECKLIST:
        assert item in text


def test_sava_lead_names_table_and_off_table_windows(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "sava-pool"\n')
    _write_decisions(
        repo,
        [
            {
                "slug": "sava-pool",
                "action": "flag",
                "old_url": "https://sfrecpark.org/DocumentCenter/View/29571",
                "new_url": None,
                "kind": "session_grid",
                "reason": "multiple_windows",
                "blocking": True,
                "candidates": [
                    _candidate(
                        29815,
                        kind="session_grid",
                        source="table",
                        filename="Sava_Pool_Fall12026_Aug18toDec26_.pdf",
                    ),
                    _candidate(
                        29805,
                        kind="session_grid",
                        source="band",
                        filename="Sava_Pool_Fall2_2026.pdf",
                    ),
                ],
                "extra_candidates": [],
            }
        ],
    )

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    assert "Nothing to review" not in text
    line = next(row for row in text.splitlines() if row.startswith("- `sava-pool`:"))
    assert "29815" in line
    assert "29805" in line
    assert "multiple_windows" in line
    assert "off-table 29805" in line
    assert "Sava_Pool_Fall2_2026.pdf" in line
    assert "29805" in line.split("extra", 1)[0]


def test_adopt_line_includes_old_new_filename_kind_and_window(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "coffman-pool"\n')
    run = repo / "data" / "coffman-pool" / "2026-08-19-aaaaaaaaaaaa"
    _write_provider_json(
        run / "gemini-gemini-3-1-flash-lite-preview.json",
        effective_start="2026-08-18",
        effective_end="2026-12-12",
    )
    _git(repo, "add", "data")
    _write_decisions(
        repo,
        [
            {
                "slug": "coffman-pool",
                "action": "adopt",
                "old_url": "https://sfrecpark.org/DocumentCenter/View/29563",
                "new_url": "https://sfrecpark.org/DocumentCenter/View/29798",
                "kind": "session_grid",
                "reason": "session_grid",
                "blocking": False,
                "candidates": [
                    _candidate(
                        29798,
                        kind="session_grid",
                        source="table",
                        filename="Coffman Pool Fall 2026 Aug18_Dec12.pdf",
                    )
                ],
                "extra_candidates": [],
            }
        ],
    )

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    line = next(row for row in text.splitlines() if row.startswith("- `coffman-pool`:"))
    assert "29563 → 29798" in line
    assert "Coffman Pool Fall 2026 Aug18_Dec12.pdf" in line
    assert "session_grid" in line
    assert "2026-08-18–2026-12-12" in line
    assert "Nothing to review" not in text


def test_empty_diff_without_decisions_still_says_nothing_to_review(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    text = render_pr_body(repo_root=repo, data_root=repo / "data")
    assert text.startswith("Nothing to review.")
    assert "unverified projection" not in text
    assert "Next Monday" not in text
