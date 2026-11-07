"""Retained, conflicting Sava originals remain evidence, not new approval."""
from datetime import date
import hashlib
from pathlib import Path

import pytest

from schedules.discover import DocumentLink, choose_roll, classify_pdf
from schedules.grounding import source_window
from schedules.models import PoolEntry
from schedules.providers import openai_provider
from schedules.schema import EXTRACTION_SCHEMA
from schedules.signals import inspect_pdf_source

ROOT = Path(__file__).parents[1]
ORIGINALS = [
    (30037, "2026-09-09-4b1055669e1d", "4b1055669e1df46512c16b051b02b8de52d1b935f7cbfde2f27bfe38ff03009c",
     (date(2026, 8, 29), date(2026, 12, 12))),
    (30374, "2026-10-30-eb848200d8e2", "eb848200d8e2426c44e499731ccfa050dd3042cabf2dea3735447655cc97f1aa",
     (date(2026, 11, 3), date(2026, 12, 1))),
]


@pytest.mark.parametrize("view_id,capture,sha256,window", ORIGINALS)
def test_sava_original_keeps_its_window_and_unresolved_literal_notices(monkeypatch, view_id, capture, sha256, window):
    directory = ROOT / "data/sava-pool" / capture
    raw = (directory / "source.pdf").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha256
    assert (directory / "source.sha256").read_text().strip() == sha256
    assert source_window(inspect_pdf_source(raw)) == window
    # Existing source-specific human approval is not permission to correct
    # literal midnight or reinterpret notices in a different original.
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-real-key")

    def forbidden_transport(*args, **kwargs):
        pytest.fail("Unresolved Sava source reached paid transport")

    monkeypatch.setattr(openai_provider, "call_api", forbidden_transport)
    if view_id == 30037:
        with pytest.raises(ValueError, match="p1-c3-b15:unsupported_session_duration"):
            openai_provider.extract(raw, "synthetic preflight test", EXTRACTION_SCHEMA)
    else:
        with pytest.raises(openai_provider.ClosureReviewRequired) as error:
            openai_provider.extract(raw, "synthetic preflight test", EXTRACTION_SCHEMA)
        assert set(error.value.issues) == {
            "p1-c3-b17-notice:conflicting_recurring_closure_dates",
            "p1-c3-b14-notice:ambiguous_exclusion_date",
        }


def test_sava_overlapping_originals_do_not_imply_supersession(monkeypatch):
    monkeypatch.setattr("schedules.discover.pacific_today", lambda: date(2026, 11, 7))
    documents = []
    for view_id, capture, sha256, _ in ORIGINALS:
        raw = (ROOT / "data/sava-pool" / capture / "source.pdf").read_bytes()
        link = DocumentLink(view_id, f"https://sfrecpark.org/DocumentCenter/View/{view_id}", "Sava Pool Fall 2026")
        classified = classify_pdf(link, pool_slug="sava-pool", pdf_bytes=raw, filename=None)
        assert classified.pdf_sha256 == sha256
        assert classified.window_source == "page-1"
        documents.append(classified)
    # This is a frozen source-choice case, not a pin on future live registry
    # documents. A properly reviewed successor can legitimately replace it.
    entry = PoolEntry(slug="sava-pool", pdf_url=documents[0].link.href,
                      official_page_url="https://sfrecpark.org/facilities/facility/details/Sava-Pool-220")
    decision = choose_roll(entry, documents)
    assert decision.action == "flag"
    assert decision.reason == "overlapping_windows"
    assert decision.blocking
    assert decision.new_url is None
