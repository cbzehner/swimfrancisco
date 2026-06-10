from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ExtractedPayload = dict[str, Any]

DAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


ViolationCode = Literal[
    "sessions_dropped_to_zero",
    "too_few_weekly_sessions",
    "invalid_session_time_range",
    "invalid_access_exception_date",
    "invalid_access_exception_time_range",
    "invalid_schedule_basis",
    "invalid_closure_date_range",
    "incomplete_closure_time_range",
    "invalid_closure_time_range",
    "multi_day_closure_with_time_range",
    "invalid_schedule_effective_date",
]


ReviewNoteKind = Literal[
    "multi_grid_suspected",
    "provider_session_count_disagreement",
    "provider_session_diff",
    "provider_closure_diff",
    "provider_schedule_effective_diff",
    "delta_session_count_shift",
    "delta_session_types_missing",
    "delta_schedule_effective_regressed",
    "grounding_coverage_low",
    "compare_provider_failed",
    "direct_extractor_note",
]


Severity = Literal["info", "warning", "error"]


SourceStatus = Literal[
    "published",
    "access_hours_only",
    "closed_without_current_schedule",
    "missing_current_schedule",
]


SourceKind = Literal[
    "sfrecpark_pdf",
    "twenty_four_hour_fitness_html",
    "jccsf_html",
    "koret_google_sheet",
    "pomeroy_html",
    "city_sports_html",
    "equinox_html",
    "fitness_sf_html",
    "sfsu_aquatics_html",
    "ucsf_fitness_html",
    "ucsf_bakar_html",
    "ymca_location_html",
]


ScheduleBasis = Literal[
    "swim_schedule",
    "pool_hours",
    "facility_hours",
    "amenity_only",
    "temporarily_closed",
    "unknown",
]


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    message: str


@dataclass(frozen=True)
class PoolEntry:
    slug: str
    pdf_url: str
    official_page_url: str
    source_status: SourceStatus = "published"
    source_kind: SourceKind = "sfrecpark_pdf"
    notes: str | None = None


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    bytes: bytes
    from_cache: bool
    page_count: int


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    violations: list[Violation]
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
    kind: ReviewNoteKind
    message: str
    severity: Severity = "warning"


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
    source_status: SourceStatus


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
    effective_start: str
    schedule_basis: str | None = None
    review_notes: list[ReviewNote] = field(default_factory=list)
    cost_estimate: str = "unchanged"
    artifact_paths: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Extracted(PoolResultBase):
    """Fresh LLM extraction. Sits as a review candidate — the pipeline
    never writes content/spots/*.md directly; `schedules review` is the
    only path that lands an approved snapshot.

    `catastrophic=True` means catastrophic validation refused the payload
    (e.g. sessions_dropped_to_zero). The result still records what the LLM
    produced for the review report; the run exits non-zero. Non-catastrophic
    results may still carry advisory violations and review notes for the
    operator to skim before approving.
    """

    provider: str
    model: str
    pdf_sha256: str
    page_count: int
    sessions_count: int
    prior_sessions_count: int
    closures_count: int
    effective_start: str | None
    cost_estimate: str
    schedule_basis: str | None = None
    catastrophic: bool = False
    violations: list[Violation] = field(default_factory=list)
    review_notes: list[ReviewNote] = field(default_factory=list)
    artifact_paths: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Aborted(PoolResultBase):
    """Run aborted by an exception in fetch/extract/merge — no completed extraction."""

    error: str
    prior_sessions_count: int
    prior_closures_count: int
    prior_schedule_effective: str | None


PoolResult = Skipped | Unchanged | Extracted | Aborted


def needs_review(result: PoolResult) -> bool:
    if isinstance(result, Skipped):
        return result.source_status != "published"
    if isinstance(result, Unchanged):
        return bool(result.review_notes)
    if isinstance(result, Aborted):
        return True
    return bool(result.violations or result.review_notes or result.source_status != "published")
