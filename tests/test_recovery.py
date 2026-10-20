import httpx
import pytest

from schedules.direct_sources.errors import DirectSourceError
from schedules.recovery import failure_code


@pytest.mark.parametrize("status, code", [
    (404, "source_missing"), (410, "source_missing"), (403, "source_access_denied"),
    (429, "source_unavailable"), (503, "source_unavailable"),
])
def test_http_failure_is_classified_through_wrapping(status, code):
    request = httpx.Request("GET", "https://example.test/source")
    response = httpx.Response(status, request=request)
    try:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RuntimeError("fetch failed") from error
    except RuntimeError as error:
        assert failure_code(error) == code


def test_direct_errors_keep_safe_codes_without_original_http_exception():
    assert failure_code(DirectSourceError("sanitized", failure_code="source_access_denied")) == "source_access_denied"
    assert failure_code(DirectSourceError("layout changed")) == "source_format_changed"
    assert failure_code(ValueError("bad model response")) == "extraction_failed"
