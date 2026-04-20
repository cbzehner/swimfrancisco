#!/usr/bin/env python3
"""Migrate data/ from three-tree layout to per-review consolidated dirs.

Moves:
  data/pdfs/<slug>/<date>-<sha12>.pdf           → data/<slug>/<date>-<sha12>/source.pdf
  data/artifacts/<slug>/<sha12>/<provider>.json → data/<slug>/<date>-<sha12>/<provider>.json
                                                  (self-describing; meta.json folded in + deleted)
  data/reviewed-snapshots/<slug>/*.json         → data/<slug>/<date>-<sha12>/reviewed.json
                                                  (version/$schema/reviewed_by/reviewed_against stripped)

Idempotent. Exits 0 on success. Also deletes data/extraction-state.json,
data/pdf-cache-index.json, and the old root dirs once emptied.

Usage:
    python scripts/migrate_consolidated_layout.py [--data-dir data]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


STRIP_FIELDS_ENVELOPE = ("version", "$schema", "reviewed_by", "reviewed_against")
STRIP_FIELDS_PROVIDER = ("slug", "pdf_url", "pdf_page_count", "pdf_text_sha256")


@dataclass
class Summary:
    reviews_migrated: int = 0
    providers_migrated: int = 0
    pdfs_moved: int = 0
    meta_files_deleted: int = 0
    warnings: list[str] = field(default_factory=list)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _fallback_hashes(repo_root: Path) -> tuple[str | None, str | None]:
    """Compute fallback prompt/schema hashes from the current source tree."""
    prompt_path = repo_root / "src" / "schedules" / "prompts" / "extract.txt"
    prompt_sha = _sha256_text(prompt_path.read_text().strip()) if prompt_path.exists() else None

    schema_sha = None
    try:
        sys.path.insert(0, str(repo_root / "src"))
        from schedules.extraction import EXTRACTION_SCHEMA  # type: ignore

        schema_sha = _sha256_json(EXTRACTION_SCHEMA)
    except Exception:
        pass
    finally:
        try:
            sys.path.remove(str(repo_root / "src"))
        except ValueError:
            pass
    return prompt_sha, schema_sha


def _resolve_date(envelope: dict, pdfs_dir: Path, slug: str, sha12: str) -> str:
    matches = sorted(pdfs_dir.glob(f"{slug}/*-{sha12}.pdf"))
    if len(matches) == 1:
        return matches[0].name[:10]
    return envelope["reviewed_at"]


def _migrate_one_review(
    snapshot_path: Path,
    data_root: Path,
    prompt_sha_fallback: str | None,
    schema_sha_fallback: str | None,
    summary: Summary,
) -> None:
    envelope = json.loads(snapshot_path.read_text())
    slug = envelope["slug"]
    pdf_sha = envelope["pdf_sha256"]
    sha12 = pdf_sha[:12]

    pdfs_root = data_root / "pdfs"
    artifacts_src = data_root / "artifacts" / slug / sha12

    date = _resolve_date(envelope, pdfs_root, slug, sha12)
    target_dir = data_root / slug / f"{date}-{sha12}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Harvest old meta.json if present
    old_meta: dict = {}
    if artifacts_src.is_dir():
        meta_path = artifacts_src / "meta.json"
        if meta_path.exists():
            try:
                old_meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                old_meta = {}

    prompt_sha256 = (
        old_meta.get("prompt_sha256")
        or old_meta.get("prompt_hash")
        or prompt_sha_fallback
    )
    schema_sha256 = (
        old_meta.get("schema_sha256")
        or old_meta.get("schema_hash")
        or schema_sha_fallback
    )
    meta_extracted_at = old_meta.get("extracted_at") or old_meta.get("updated_at")

    # Move PDF
    pdf_matches = sorted(pdfs_root.glob(f"{slug}/*-{sha12}.pdf"))
    if pdf_matches:
        src_pdf = pdf_matches[0]
        dest_pdf = target_dir / "source.pdf"
        if not dest_pdf.exists():
            src_pdf.rename(dest_pdf)
            summary.pdfs_moved += 1
        else:
            src_pdf.unlink()
    else:
        summary.warnings.append(f"no PDF found for {slug}/{sha12}")

    # Move + trim provider JSONs
    if artifacts_src.is_dir():
        for provider_file in sorted(artifacts_src.iterdir()):
            if provider_file.name == "meta.json":
                provider_file.unlink()
                summary.meta_files_deleted += 1
                continue
            data = json.loads(provider_file.read_text())
            source_pdf_url = (
                data.get("source_pdf_url")
                or data.get("pdf_url")
                or old_meta.get("source_pdf_url")
                or envelope.get("source_pdf_url")
                or ""
            )
            pdf_sha256_val = data.get("pdf_sha256") or old_meta.get("pdf_sha256") or pdf_sha
            for key in STRIP_FIELDS_PROVIDER:
                data.pop(key, None)
            data["source_pdf_url"] = source_pdf_url
            data["pdf_sha256"] = pdf_sha256_val
            if prompt_sha256:
                data.setdefault("prompt_sha256", prompt_sha256)
            if schema_sha256:
                data.setdefault("schema_sha256", schema_sha256)
            if meta_extracted_at:
                data.setdefault("extracted_at", meta_extracted_at)
            dest = target_dir / provider_file.name
            dest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            provider_file.unlink()
            summary.providers_migrated += 1
        try:
            artifacts_src.rmdir()
        except OSError:
            pass

    # Move reviewed.json (stripped)
    for key in STRIP_FIELDS_ENVELOPE:
        envelope.pop(key, None)
    (target_dir / "reviewed.json").write_text(json.dumps(envelope, indent=2) + "\n")
    snapshot_path.unlink()
    summary.reviews_migrated += 1


def _cleanup_empty_dir(path: Path) -> None:
    """Recursively remove empty dirs rooted at `path`."""
    if not path.is_dir():
        return
    for child in list(path.iterdir()):
        if child.is_dir():
            _cleanup_empty_dir(child)
    try:
        path.rmdir()
    except OSError:
        pass


def main_fn(data_root: Path, repo_root: Path) -> Summary:
    summary = Summary()
    snapshots_root = data_root / "reviewed-snapshots"
    if not snapshots_root.is_dir():
        return summary

    prompt_sha, schema_sha = _fallback_hashes(repo_root)

    for slug_dir in sorted(snapshots_root.iterdir()):
        if not slug_dir.is_dir():
            continue
        for snapshot_path in sorted(slug_dir.glob("*.json")):
            _migrate_one_review(
                snapshot_path=snapshot_path,
                data_root=data_root,
                prompt_sha_fallback=prompt_sha,
                schema_sha_fallback=schema_sha,
                summary=summary,
            )

    # Cleanup old trees (only if emptied)
    _cleanup_empty_dir(data_root / "pdfs")
    _cleanup_empty_dir(data_root / "artifacts")
    _cleanup_empty_dir(data_root / "reviewed-snapshots")
    _cleanup_empty_dir(data_root / "reviewed-snapshot-drafts")

    state_path = data_root / "extraction-state.json"
    if state_path.exists():
        state_path.unlink()
    index_path = data_root / "pdf-cache-index.json"
    if index_path.exists():
        index_path.unlink()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    data_root = Path(args.data_dir).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    if not data_root.exists():
        print(f"error: {data_root} does not exist", file=sys.stderr)
        return 1

    summary = main_fn(data_root, repo_root)
    print(
        f"migrated: reviews={summary.reviews_migrated} providers={summary.providers_migrated} "
        f"pdfs={summary.pdfs_moved} meta_deleted={summary.meta_files_deleted}"
    )
    for warning in summary.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
