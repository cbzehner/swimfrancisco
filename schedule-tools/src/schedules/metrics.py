"""Operational observations from receipts; never schedule authority."""
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path


def run_metrics(evidence: Path, state: dict) -> dict:
    builds = state.get("builds", [])
    latest = builds[-1] if builds else {}
    directory = evidence / f"build-{len(builds)}"
    pools = defaultdict(list)
    errors = []
    reports = 0
    for provider in ("direct", "openai"):
        path = directory / f"extraction-report-{provider}.json"
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text())
            results = report["results"]
            if not isinstance(results, list):
                raise ValueError("Invalid result list")
            for result in results:
                if not isinstance(result, dict) or not isinstance(result.get("slug"), str):
                    raise ValueError("Invalid pool result")
            for result in results:
                pools[result["slug"]].append(result)
            reports += 1
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(path.name)
    flags = defaultdict(list)
    for flag in latest.get("decisions", {}).get("flagged_set", []):
        slug, _, code = flag.partition(":")
        flags[slug].append(code)
    published = set(state.get("published_slugs", [])) if state.get("status") == "published" else set()
    rows = [{"slug": slug, "result_count": len(pools[slug]),
             "failed_results": sum(item.get("status") == "failed" for item in pools[slug]),
             "cached_results": sum(item.get("cached") is True for item in pools[slug]),
             "review_reasons": sorted(flags[slug]), "published_live": slug in published,
             "results": pools[slug]} for slug in sorted(pools.keys() | flags.keys() | published)]
    return {"run_id": state.get("run_id"), "status": state.get("status"),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "build_attempts": len(builds), "elapsed_seconds": state.get("elapsed_seconds"),
            "command_seconds": latest.get("command_seconds", {}),
            "observed_reports": reports, "unreadable_reports": errors,
            "operator_minutes": None, "pools": rows}


def write_run_metrics(evidence: Path, state: dict) -> None:
    """Observability must not replace a publication failure or its receipt."""
    try:
        metrics = run_metrics(evidence, state)
        (evidence / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            lines = ["", "### Pool schedule outcomes", "",
                     "| Pool | Results | Cached | Failed | Review holds | Confirmed live |",
                     "|---|---:|---:|---:|---|---|"]
            lines.extend(f"| {row['slug']} | {row['result_count']} | {row['cached_results']} | {row['failed_results']} | "
                         f"{', '.join(row['review_reasons']) or '—'} | {'yes' if row['published_live'] else 'no'} |"
                         for row in metrics["pools"])
            lines.append("\nOperator time is not measured. Missing reports are not successful results.\n")
            with Path(summary).open("a") as stream:
                stream.write("\n".join(lines))
    except (OSError, ValueError, TypeError, KeyError):
        return
