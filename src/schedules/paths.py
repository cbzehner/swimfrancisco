import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = SRC_ROOT.parent

CONTENT_SPOTS_DIR = REPO_ROOT / "content" / "spots"
DATA_DIR = REPO_ROOT / "data"
PDF_CACHE_DIR = DATA_DIR / "pdfs"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
REVIEWED_SNAPSHOTS_DIR = DATA_DIR / "reviewed-snapshots"
STATE_PATH = DATA_DIR / "extraction-state.json"
TMP_DIR = REPO_ROOT / "tmp"
REPORT_PATH = TMP_DIR / "extraction-report.md"
REGISTRY_PATH = PACKAGE_ROOT / "registry.toml"
PROMPT_PATH = PACKAGE_ROOT / "prompts" / "extract.txt"


def relative_to_repo(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def pdf_dir(slug: str) -> Path:
    return DATA_DIR / "pdfs" / slug


def reviewed_snapshot_dir(slug: str) -> Path:
    return DATA_DIR / "reviewed-snapshots" / slug


def pdf_filename(date: str, pdf_sha256: str) -> str:
    return f"{date}-{pdf_sha256[:12]}.pdf"


def snapshot_filename(date: str, pdf_sha256: str) -> str:
    return f"{date}-{pdf_sha256[:12]}.json"


def latest_pdf(slug: str) -> Path | None:
    directory = pdf_dir(slug)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.pdf"))
    return files[-1] if files else None


def latest_reviewed_snapshot(slug: str) -> Path | None:
    directory = reviewed_snapshot_dir(slug)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.json"))
    return files[-1] if files else None


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


# Consolidated per-review layout: data/<slug>/<date>-<pdf_sha256[:12]>/


def review_dir(slug: str, date: str, pdf_sha256: str, *, root: Path = DATA_DIR) -> Path:
    return root / slug / f"{date}-{pdf_sha256[:12]}"


def pdf_path(slug: str, date: str, pdf_sha256: str, *, root: Path = DATA_DIR) -> Path:
    return review_dir(slug, date, pdf_sha256, root=root) / "source.pdf"


def artifact_path(
    slug: str,
    date: str,
    pdf_sha256: str,
    provider: str,
    model: str,
    *,
    root: Path = DATA_DIR,
) -> Path:
    return review_dir(slug, date, pdf_sha256, root=root) / f"{provider}-{slugify(model)}.json"


def reviewed_path(slug: str, date: str, pdf_sha256: str, *, root: Path = DATA_DIR) -> Path:
    return review_dir(slug, date, pdf_sha256, root=root) / "reviewed.json"


def all_review_dirs(slug: str, *, root: Path = DATA_DIR) -> list[Path]:
    slug_dir = root / slug
    if not slug_dir.is_dir():
        return []
    return sorted(d for d in slug_dir.iterdir() if d.is_dir())


def latest_review_dir(slug: str, *, root: Path = DATA_DIR) -> Path | None:
    dirs = all_review_dirs(slug, root=root)
    return dirs[-1] if dirs else None
