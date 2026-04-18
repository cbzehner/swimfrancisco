from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = SRC_ROOT.parent

CONTENT_SPOTS_DIR = REPO_ROOT / "content" / "spots"
DATA_DIR = REPO_ROOT / "data"
PDF_CACHE_DIR = DATA_DIR / "pdfs"
PDF_CACHE_INDEX_PATH = DATA_DIR / "pdf-cache-index.json"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
ADJUDICATIONS_DIR = DATA_DIR / "adjudications"
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
