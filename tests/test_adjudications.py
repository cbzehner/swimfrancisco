import json

from schedules.adjudications import load_adjudication


def test_load_adjudication(tmp_path):
    root = tmp_path / "adjudications"
    path = root / "hamilton-pool" / ("abc123" * 10 + "ab")[:64]  # unused, just keep shape obvious
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

    adjudication, fingerprint, relative_path = load_adjudication("hamilton-pool", pdf_sha256, root=root)

    assert adjudication["summary"] == "manual review"
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert relative_path == str(file_path)
