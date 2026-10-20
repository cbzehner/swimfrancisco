import hashlib
import json

from click.testing import CliRunner
import pytest

from schedules.jev_trial import MODEL, CRITERIA, load_cases, main, request_hash, score


def record(text, choice, confidence=1):
    return {"request_sha256": request_hash(text), "response": {
        "model": MODEL, "answers": {"document_kind": {
            "type": "choice", "choice": choice, "confidence": confidence,
            "probabilities": {key: int(key == choice) for key in CRITERIA},
        }},
    }}


def test_missed_closures_are_separate_from_safe_abstentions():
    cases = [{"id": str(i), "text": str(i), "split": "holdout", "expected": "closure_notice"} for i in range(3)]
    responses = {"0": record("0", "session_grid"), "1": record("1", "other", 0.2), "2": record("2", "closure_notice")}
    summary = score(cases, responses, 0.8)["summary"]["holdout"]
    assert summary == {"documents": 3, "abstentions": 1, "coverage": 2 / 3,
                       "classification_errors": 2, "accepted_errors": 1, "missed_closures": 1,
                       "closure_abstentions": 1, "reviews_avoided": None}


@pytest.mark.parametrize("mutation", ["source", "model", "nan", "probabilities", "extra"])
def test_invalid_or_unmatched_evidence_fails_closed(mutation):
    cases = [{"id": "a", "text": "closure", "split": "holdout", "expected": "closure_notice"}]
    responses = {"a": record("closure", "closure_notice")}
    if mutation == "source":
        responses["a"]["request_sha256"] = "stale"
    elif mutation == "model":
        responses["a"]["response"]["model"] = "latest"
    elif mutation == "nan":
        responses["a"]["response"]["answers"]["document_kind"]["confidence"] = float("nan")
    elif mutation == "probabilities":
        responses["a"]["response"]["answers"]["document_kind"]["probabilities"]["other"] = 1
    else:
        responses["unexpected"] = record("closure", "closure_notice")
    with pytest.raises(ValueError):
        score(cases, responses, 0.8)


def manifest_case(identifier, text, split, group):
    return f'''[[documents]]
id = "{identifier}"
text_path = "{identifier}.txt"
text_sha256 = "{hashlib.sha256(text.encode()).hexdigest()}"
expected = "closure_notice"
split = "{split}"
pool_season = "{group}"
review = "Synthetic test fixture only, not benchmark evidence"
'''


def test_pool_season_leakage_and_source_changes_rejected(tmp_path):
    path = tmp_path / "cases.toml"
    (tmp_path / "a.txt").write_text("Closed for repairs")
    (tmp_path / "b.txt").write_text("Closed for maintenance")
    path.write_text(manifest_case("a", "Closed for repairs", "development", "pool-fall")
                    + manifest_case("b", "Closed for maintenance", "holdout", "pool-fall"))
    with pytest.raises(ValueError, match="pool/season"):
        load_cases(path)
    path.write_text(manifest_case("a", "Old content", "development", "pool-fall"))
    with pytest.raises(ValueError, match="changed"):
        load_cases(path)


def test_cli_replays_without_credentials_or_network(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    source = "Closed for repairs"
    (tmp_path / "a.txt").write_text(source)
    manifest = tmp_path / "cases.toml"
    manifest.write_text(manifest_case("a", source, "holdout", "pool-fall"))
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps({"a": record(source, "closure_notice")}))
    output = tmp_path / "report.json"
    args = [str(manifest), "--responses", str(responses), "--output", str(output), "--threshold", "0.8"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text())["publication_authority"] is False
    output.unlink()
    result = CliRunner().invoke(main, [*args, "--request"])
    assert result.exit_code != 0
    assert "TYPESAFE_API_KEY" in result.output
    assert not output.exists()
