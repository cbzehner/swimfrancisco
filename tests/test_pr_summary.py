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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decisions) + "\n")


def _candidate(
    view_id: int,
    *,
    kind: str,
    source: str,
    filename: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict:
    return {
        "view_id": view_id,
        "href": f"https://sfrecpark.org/DocumentCenter/View/{view_id}",
        "anchor_text": filename or "",
        "kind": kind,
        "filename": filename,
        "source": source,
        "window_start": window_start,
        "window_end": window_end,
    }


def _write_provider_json(
    path: Path,
    *,
    effective_start: str,
    effective_end: str,
    source_pdf_url: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "provider": "gemini",
        "payload": {
            "effective_start": effective_start,
            "effective_end": effective_end,
            "sessions": [],
        },
    }
    if source_pdf_url is not None:
        payload["source_pdf_url"] = source_pdf_url
    path.write_text(json.dumps(payload) + "\n")


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
    assert "needs a human review" not in text
    assert "attestation was carried" not in text
    assert "This PR auto-merges once checks pass" in text
    assert "`garfield-pool`" in text
    assert "flyer 29808" in text
    assert "29799" in text
    assert "band-flagged" in text
    assert "unverified projection" not in text
    assert "Next Monday" not in text
    assert "The live site updates when this PR merges." in text
    assert "informational" in text
    assert "schedules flagged" in text
    for item in CHECKLIST:
        assert item not in text


def test_sava_lead_names_table_and_off_table_windows(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "sava-pool"\n')
    _write_decisions(
        repo,
        [
            {
                "slug": "sava-pool",
                "action": "unchanged",
                "old_url": "https://sfrecpark.org/DocumentCenter/View/29815",
                "new_url": "https://sfrecpark.org/DocumentCenter/View/29815",
                "kind": "session_grid",
                "reason": "sequential_windows",
                "blocking": False,
                "candidates": [
                    _candidate(
                        29815,
                        kind="session_grid",
                        source="table",
                        filename="Sava_Pool_Fall12026_Aug18toDec26_.pdf",
                        window_start="2026-08-18",
                        window_end="2026-08-28",
                    ),
                    _candidate(
                        29805,
                        kind="session_grid",
                        source="band",
                        filename="Sava_Pool_Fall2_2026.pdf",
                        window_start="2026-08-29",
                        window_end="2026-12-12",
                    ),
                ],
                "extra_candidates": [],
            }
        ],
    )

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    assert "Nothing to review" not in text
    assert "needs a human review" not in text
    assert "This PR auto-merges once checks pass" in text
    line = next(row for row in text.splitlines() if row.startswith("- `sava-pool`:"))
    assert "29815" in line
    assert "29805" in line
    assert "sequential_windows" in line
    assert "multiple_windows" not in line
    assert "off-table 29805" in line
    assert "Sava_Pool_Fall2_2026.pdf" in line
    assert "29805" in line.split("extra", 1)[0]
    assert "2026-08-18–2026-08-28" in line
    assert "2026-08-29–2026-12-12" in line


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


def test_registry_only_adopt_does_not_claim_carried_attestation(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "coffman-pool"\n')
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

    assert "Nothing to review" not in text
    assert "attestation was carried" not in text
    assert "identical to its last human-reviewed" not in text
    assert "needs a human review" not in text
    assert "auto-merges" in text
    assert "29563 → 29798" in text


def test_ci_attested_reviewed_json_is_auto_published(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "hamilton-pool"\n')
    run = repo / "data" / "hamilton-pool" / "2026-08-19-aaaaaaaaaaaa"
    _write_provider_json(
        run / "gemini-gemini-3-1-flash-lite-preview.json",
        effective_start="2026-08-18",
        effective_end="2026-12-12",
    )
    (run / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": "a" * 64,
                "reviewed_at": "2026-08-20",
                "attested_by": "ci",
                "source_pdf_url": "https://sfrecpark.org/DocumentCenter/View/29800",
                "payload": {
                    "effective_start": "2026-08-18",
                    "effective_end": "2026-12-12",
                    "sessions": [{"day": "monday", "type": "lap_swim", "start": "07:00", "end": "08:00"}],
                    "closures": [],
                },
            }
        )
        + "\n"
    )
    _git(repo, "add", "data")
    _write_decisions(
        repo,
        [
            {
                "slug": "hamilton-pool",
                "action": "adopt",
                "old_url": "https://sfrecpark.org/DocumentCenter/View/29599",
                "new_url": "https://sfrecpark.org/DocumentCenter/View/29800",
                "kind": "session_grid",
                "reason": "session_grid",
                "blocking": False,
                "candidates": [
                    _candidate(
                        29800,
                        kind="session_grid",
                        source="table",
                        filename="Hamilton Pool Fall 2026.pdf",
                    )
                ],
                "extra_candidates": [],
            }
        ],
    )
    (repo / "tmp" / "publish-pending.json").write_text(
        json.dumps({"published": ["hamilton-pool"], "refused": [], "closure": []}) + "\n"
    )

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    assert "Published 1 Rec & Park pool." in text
    assert "This PR auto-merges once checks pass" in text
    assert "The live site updates when this PR merges." in text
    assert "needs a human review" not in text
    assert "auto-published (`attested_by: ci`)" in text
    for item in CHECKLIST:
        assert item not in text


def test_sequential_publish_lists_per_window_dates_from_publish_pending(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "sava-pool"\n')
    fall1 = repo / "data" / "sava-pool" / "2026-08-20-aaaaaaaaaaaa"
    fall2 = repo / "data" / "sava-pool" / "2026-08-20-bbbbbbbbbbbb"
    _write_provider_json(
        fall1 / "gemini-gemini-3-1-flash-lite-preview.json",
        effective_start="2026-08-18",
        effective_end="2026-08-28",
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29815",
    )
    (fall1 / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "sava-pool",
                "pdf_sha256": "a" * 64,
                "reviewed_at": "2026-08-20",
                "attested_by": "ci",
                "source_pdf_url": "https://sfrecpark.org/DocumentCenter/View/29815",
                "payload": {
                    "effective_start": "2026-08-18",
                    "effective_end": "2026-08-28",
                    "sessions": [],
                    "closures": [],
                },
            }
        )
        + "\n"
    )
    _write_provider_json(
        fall2 / "gemini-gemini-3-1-flash-lite-preview.json",
        effective_start="2026-08-29",
        effective_end="2026-12-12",
        source_pdf_url="https://sfrecpark.org/DocumentCenter/View/29805",
    )
    (fall2 / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "sava-pool",
                "pdf_sha256": "b" * 64,
                "reviewed_at": "2026-08-20",
                "attested_by": "ci",
                "source_pdf_url": "https://sfrecpark.org/DocumentCenter/View/29805",
                "payload": {
                    "effective_start": "2026-08-29",
                    "effective_end": "2026-12-12",
                    "sessions": [],
                    "closures": [],
                },
            }
        )
        + "\n"
    )
    _git(repo, "add", "data")
    _write_decisions(
        repo,
        [
            {
                "slug": "sava-pool",
                "action": "unchanged",
                "old_url": "https://sfrecpark.org/DocumentCenter/View/29815",
                "new_url": "https://sfrecpark.org/DocumentCenter/View/29815",
                "kind": "session_grid",
                "reason": "sequential_windows",
                "blocking": False,
                "candidates": [
                    _candidate(
                        29815,
                        kind="session_grid",
                        source="table",
                        filename="Sava_Pool_Fall12026_Aug18toDec26_.pdf",
                        window_start="2026-08-18",
                        window_end="2026-08-28",
                    ),
                    _candidate(
                        29805,
                        kind="session_grid",
                        source="band",
                        filename="Sava_Pool_Fall2_2026.pdf",
                        window_start="2026-08-29",
                        window_end="2026-12-12",
                    ),
                ],
                "extra_candidates": [],
            }
        ],
    )
    (repo / "tmp" / "publish-pending.json").write_text(
        json.dumps(
            {
                "published": ["sava-pool"],
                "refused": [],
                "closure": [],
                "windows": [
                    {
                        "slug": "sava-pool",
                        "effective_start": "2026-08-18",
                        "effective_end": "2026-08-28",
                        "view_id": 29815,
                    },
                    {
                        "slug": "sava-pool",
                        "effective_start": "2026-08-29",
                        "effective_end": "2026-12-12",
                        "view_id": 29805,
                    },
                ],
            }
        )
        + "\n"
    )

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    assert "Published 1 Rec & Park pool." in text
    assert "schedules flagged" not in text.split("\n", 1)[0]
    line = next(row for row in text.splitlines() if row.startswith("- `sava-pool`:"))
    assert "sequential_windows" in line
    assert "table 29815" in line
    assert "off-table 29805" in line
    assert "2026-08-18–2026-08-28" in line
    assert "2026-08-29–2026-12-12" in line
    assert line.index("2026-08-18–2026-08-28") < line.index("2026-08-29–2026-12-12")
    assert "; auto" in line
    for item in CHECKLIST:
        assert item not in text


def test_carried_reviewed_json_keeps_carried_line(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage_registry(repo, 'slug = "hamilton-pool"\n')
    run = repo / "data" / "hamilton-pool" / "2026-08-19-aaaaaaaaaaaa"
    _write_provider_json(
        run / "gemini-gemini-3-1-flash-lite-preview.json",
        effective_start="2026-08-18",
        effective_end="2026-12-12",
    )
    (run / "reviewed.json").write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": "a" * 64,
                "reviewed_at": "2026-07-02",
                "attested_by": "human",
                "carried_from": "data/hamilton-pool/2026-07-02-bbbbbbbbbbbb/reviewed.json",
                "source_pdf_url": "https://example.com/x.pdf",
                "payload": {
                    "effective_start": "2026-08-18",
                    "effective_end": "2026-12-12",
                    "sessions": [],
                    "closures": [],
                },
            }
        )
        + "\n"
    )
    _git(repo, "add", "data")

    text = render_pr_body(repo_root=repo, data_root=repo / "data")

    assert "attestation was carried forward" in text
    assert "auto-published (`attested_by: ci`)" not in text
    assert "attestation carried forward." in text
    assert "needs a human review" not in text
    for item in CHECKLIST:
        assert item not in text
