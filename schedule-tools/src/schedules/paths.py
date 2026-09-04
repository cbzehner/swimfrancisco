import re
from datetime import date
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = SRC_ROOT.parent
REPO_ROOT = PROJECT_ROOT.parent

CONTENT_SPOTS_DIR = REPO_ROOT / "content" / "spots"
DATA_DIR = REPO_ROOT / "data"
TMP_DIR = REPO_ROOT / "tmp"
REPORT_PATHS = {
    "direct": TMP_DIR / "extraction-report-direct.md",
    "gemini": TMP_DIR / "extraction-report-gemini.md",
    "anthropic": TMP_DIR / "extraction-report-anthropic.md",
}
REGISTRY_PATH = PACKAGE_ROOT / "registry.toml"
PROMPT_PATH = PACKAGE_ROOT / "prompts" / "extract.txt"


def relative_to_repo(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


# Consolidated per-review layout: data/<slug>/<date>-<pdf_sha256[:12]>/

REVIEW_DIR_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{12})$")


def parse_review_dir_name(name: str) -> tuple[str, str] | None:
    match = REVIEW_DIR_NAME.fullmatch(name)
    if match is None:
        return None
    iso, sha12 = match.group(1), match.group(2)
    try:
        date.fromisoformat(iso)
    except ValueError:
        return None
    return iso, sha12


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
    return sorted(
        d for d in slug_dir.iterdir() if d.is_dir() and parse_review_dir_name(d.name)
    )


def latest_review_dir(slug: str, *, root: Path = DATA_DIR) -> Path | None:
    dirs = all_review_dirs(slug, root=root)
    return dirs[-1] if dirs else None


def latest_reviewed_dir(slug: str, *, root: Path = DATA_DIR) -> Path | None:
    dirs = [
        review_dir
        for review_dir in all_review_dirs(slug, root=root)
        if (review_dir / "reviewed.json").is_file()
    ]
    return dirs[-1] if dirs else None
