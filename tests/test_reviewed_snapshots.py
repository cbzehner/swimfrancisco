import json

from schedules.reviewed_snapshots import load_reviewed_snapshot


def test_load_reviewed_snapshot(tmp_path):
    root = tmp_path / "reviewed-snapshots"
    pdf_sha256 = "a" * 64
    file_path = root / "hamilton-pool" / f"{pdf_sha256}.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        json.dumps(
            {
                "slug": "hamilton-pool",
                "pdf_sha256": pdf_sha256,
                "summary": "manual review",
                "payload": {"schedule_effective": "2026-03-17", "sessions": [], "closures": []},
            }
        )
    )

    snapshot, fingerprint, relative_path = load_reviewed_snapshot("hamilton-pool", pdf_sha256, root=root)

    assert snapshot["summary"] == "manual review"
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert relative_path == str(file_path)
