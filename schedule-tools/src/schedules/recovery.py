"""Safe operator guidance; raw exception text stays in retained evidence."""
import httpx

from .fetch import http_failure_code


RECOVERY_ACTIONS = {
    "source_unavailable": "Temporary source failure: bounded retries were exhausted or deferred; retry extraction after the source recovers.",
    "source_missing": "Source removed: inspect the official facility page and discovery report for a replacement document.",
    "source_access_denied": "Source denied access: inspect the capture method and credentials before retrying.",
    "source_request_failed": "Source request failed: inspect the retained HTTP error before retrying.",
    "source_format_changed": "Source format changed: compare the retained document with the parser; repair or review the extraction.",
    "source_coverage_failed": "Source facts disagree: compare dates, closures, sessions, and physical pools with the retained document; use schedules-review.",
    "closure_review": "Closure needs review: inspect the closure review evidence and establish its dates and affected pool before publishing.",
    "extraction_failed": "Extraction failed: inspect the retained error and provider artifact; repair the cause before retrying.",
}


def failure_code(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return http_failure_code(error.response.status_code)
    if isinstance(error, httpx.TransportError):
        return "source_unavailable"
    code = getattr(error, "failure_code", None)
    if code in RECOVERY_ACTIONS:
        return code
    if isinstance(error.__cause__, Exception):
        return failure_code(error.__cause__)
    return "extraction_failed"
