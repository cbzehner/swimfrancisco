from __future__ import annotations


class DirectSourceError(RuntimeError):
    """Raised when a non-PDF source cannot be fetched or parsed."""


class CapturedClosureReviewRequired(DirectSourceError):
    def __init__(self, *, slug: str, source_path: str, source_sha256: str,
                 issues: list[str], notices: list[dict]):
        self.review = {"slug": slug, "source_path": source_path, "source_sha256": source_sha256,
                       "issues": issues, "notices": notices}
        super().__init__("Unresolved HTML source closures: " + ", ".join(issues))
