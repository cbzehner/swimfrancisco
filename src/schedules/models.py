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


@dataclass(frozen=True)
class DeltaResult:
    flags: list[str]
    hard_block: bool


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
class ReviewFlag:
    kind: str
    message: str
    severity: str = "warning"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfSignals:
    page_count: int
    text_sha256: str
    grid_header_pages: list[int]
    timed_lesson_line_count: int


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


@dataclass
class PoolResult:
    slug: str
    status: str
    official_page_url: str
    pdf_url: str
    source_status: str
    provider: str | None = None
    model: str | None = None
    pdf_sha256: str | None = None
    page_count: int | None = None
    sessions_count: int | None = None
    prior_sessions_count: int | None = None
    closures_count: int | None = None
    schedule_effective: str | None = None
    invariants_passed: bool | None = None
    violations: list[str] = field(default_factory=list)
    review_flags: list[ReviewFlag] = field(default_factory=list)
    hard_block: bool = False
    cost_estimate: str | None = None
    error: str | None = None
    written: bool = False
    notes: str | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)
    pdf_text_sha256: str | None = None

    @property
    def needs_review(self) -> bool:
        return bool(self.violations or self.review_flags or self.source_status != "published")

    @property
    def flag_messages(self) -> list[str]:
        return [flag.message for flag in self.review_flags]
