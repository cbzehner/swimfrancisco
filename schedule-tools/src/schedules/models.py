from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ExtractedPayload = dict[str, Any]


@dataclass(frozen=True)
class PoolEntry:
    slug: str
    pdf_url: str
    official_page_url: str
    source_status: str = "published"
    notes: str | None = None


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    bytes: bytes
    from_cache: bool
    page_count: int
    response_url: str


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    violations: list[str]
    stats: dict[str, int]
    catastrophic: bool = False


@dataclass(frozen=True)
class MergeResult:
    prior_sessions_count: int
    new_sessions_count: int
    prior_closures_count: int
    new_closures_count: int
    written: bool


@dataclass(frozen=True)
class ProviderResult:
    payload: ExtractedPayload
    model: str
    usage: dict[str, Any]
    cost_estimate: str


@dataclass(frozen=True)
class ReviewNote:
    kind: str
    message: str
    severity: str = "warning"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfSignals:
    page_count: int
    text_sha256: str
    grid_header_pages: list[int]


@dataclass(frozen=True)
class SessionGrounding:
    index: int
    grounded: bool
    missing_evidence: bool
    evidence_in_pdf: bool
    start_in_evidence: bool
    type_in_evidence: bool
    type_in_pdf_text: bool
    session: dict[str, Any]


@dataclass(frozen=True)
class GroundingResult:
    sessions: list[SessionGrounding]
    grounded_count: int
    total: int

    @property
    def ratio(self) -> float:
        return self.grounded_count / self.total if self.total else 1.0

    @property
    def ungrounded(self) -> list[SessionGrounding]:
        return [session for session in self.sessions if not session.grounded]


@dataclass(frozen=True)
class PoolResultBase:
    slug: str
    official_page_url: str
    pdf_url: str
    source_status: str


@dataclass(frozen=True)
class Skipped(PoolResultBase):
    """No extraction attempted (e.g., no current schedule PDF published)."""

    reason: str = ""
    notes: str | None = None


@dataclass(frozen=True)
class Unchanged(PoolResultBase):
    """PDF and reviewed snapshot both match the last successful run — no re-extraction."""

    provider: str
    model: str
    pdf_sha256: str
    page_count: int
    sessions_count: int
    closures_count: int
    schedule_effective: str
    invariants_passed: bool
    review_notes: list[ReviewNote] = field(default_factory=list)
    cost_estimate: str = "unchanged"
    artifact_paths: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Proposed(PoolResultBase):
    """Fresh extraction that validated cleanly. May or may not have been written."""

    provider: str
    model: str
    pdf_sha256: str
    page_count: int
    sessions_count: int
    prior_sessions_count: int
    closures_count: int
    schedule_effective: str | None
    invariants_passed: bool
    cost_estimate: str
    violations: list[str] = field(default_factory=list)
    review_notes: list[ReviewNote] = field(default_factory=list)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    written: bool = False


@dataclass(frozen=True)
class Failed(PoolResultBase):
    """Extraction failed — either by exception or by validation refusing the payload.

    Rich fields are populated if extraction got far enough to produce them.
    """

    error: str = ""
    provider: str | None = None
    model: str | None = None
    pdf_sha256: str | None = None
    page_count: int | None = None
    sessions_count: int | None = None
    prior_sessions_count: int | None = None
    closures_count: int | None = None
    schedule_effective: str | None = None
    violations: list[str] = field(default_factory=list)
    review_notes: list[ReviewNote] = field(default_factory=list)
    cost_estimate: str | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)


PoolResult = Skipped | Unchanged | Proposed | Failed


def needs_review(result: PoolResult) -> bool:
    if isinstance(result, Skipped):
        return result.source_status != "published"
    if isinstance(result, Unchanged):
        return bool(result.review_notes)
    return bool(result.violations or result.review_notes or result.source_status != "published")
