"""Backtest discover's PDF classifier against every reviewed Rec & Park PDF.

The band/persisted adopt path trusts page-1 text alone (no anchor, no
filename). These tests replay that path over the committed corpus so a
layout the classifier has never seen fails loudly here, not in cron.

Contract, per reviewed capture:

- A ``temporarily_closed`` payload's PDF must never classify ``session_grid``.
- A ``swim_schedule`` payload's PDF, when page 1 yields a window, must yield
  the reviewed ``effective_start``/``effective_end`` exactly. A wrong window
  is the one failure that could adopt or sequence the wrong file.
- Layouts that name the pool on page 1 (2026 summer onward) must classify
  ``session_grid`` with a confirmed grid header and a parsed window.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from schedules.discover import (
    DocumentLink,
    _first_page_text,
    _matches_pool,
    absolute_view_url,
    classify_pdf,
    rec_park_entries,
    view_id_from_url,
)
from schedules.registry import load_registry
from schedules.window_dates import parse_window_dates

ROOT = Path(__file__).resolve().parents[1]
REC_PARK = {entry.slug for entry in rec_park_entries(load_registry())}
CAPTURES = sorted(
    path.parent
    for path in ROOT.glob("data/*/*/reviewed.json")
    if path.parent.parent.name in REC_PARK and (path.parent / "source.pdf").exists()
)


def _capture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _load(capture: Path) -> tuple[str, dict, int, bytes]:
    envelope = json.loads((capture / "reviewed.json").read_text())
    slug = capture.parent.name
    view_id = view_id_from_url(envelope.get("source_pdf_url") or "") or 0
    return slug, envelope["payload"], view_id, (capture / "source.pdf").read_bytes()


def _classify(slug: str, view_id: int, pdf: bytes):
    link = DocumentLink(view_id, absolute_view_url(view_id), "")
    return classify_pdf(link, pool_slug=slug, pdf_bytes=pdf, filename=None, source="band")


@pytest.mark.parametrize("capture", CAPTURES, ids=_capture_id)
def test_page1_window_never_disagrees_with_reviewed_window(capture: Path) -> None:
    slug, payload, view_id, pdf = _load(capture)
    item = _classify(slug, view_id, pdf)
    if item.window_start is None:
        pytest.skip("no page-1 window in this layout")
    assert item.window_start == date.fromisoformat(payload["effective_start"])
    assert item.window_end == date.fromisoformat(payload["effective_end"])


@pytest.mark.parametrize("capture", CAPTURES, ids=_capture_id)
def test_closure_flyers_are_not_session_grids(capture: Path) -> None:
    slug, payload, view_id, pdf = _load(capture)
    if payload.get("schedule_basis") != "temporarily_closed":
        pytest.skip("not a closure payload")
    item = _classify(slug, view_id, pdf)
    assert item.kind != "session_grid"
    assert item.grid_confirmed is not True


@pytest.mark.parametrize("capture", CAPTURES, ids=_capture_id)
def test_named_grid_layouts_fully_classify(capture: Path) -> None:
    """Page 1 names the pool ⇒ the band path must be able to adopt it."""
    slug, payload, view_id, pdf = _load(capture)
    if payload.get("schedule_basis") != "swim_schedule":
        pytest.skip("not a swim schedule")
    if not _matches_pool(_first_page_text(pdf), slug):
        pytest.skip("pool name is not in page-1 text (image header or embedded font)")
    item = _classify(slug, view_id, pdf)
    assert item.kind == "session_grid"
    assert item.grid_confirmed is True
    assert item.window_start is not None and item.window_end is not None


def test_corpus_coverage_floor() -> None:
    """Guard against the corpus silently shrinking or every test skipping."""
    assert len(CAPTURES) >= 38
    parsed = 0
    for capture in CAPTURES:
        slug, payload, view_id, pdf = _load(capture)
        if payload.get("schedule_basis") != "swim_schedule":
            continue
        if _classify(slug, view_id, pdf).window_start is not None:
            parsed += 1
    assert parsed >= 30


def test_numeric_page1_window_parses() -> None:
    assert parse_window_dates(
        page_text="SPRING 2026\n05/12/2026 - 06/06/2026\nAdditional Information",
        anchor_text=None,
        filename=None,
        year_default=2026,
    ) == (date(2026, 5, 12), date(2026, 6, 6))
    # Two-digit years are closure notes, not windows.
    assert (
        parse_window_dates(
            page_text="Closed 6/6/26 9am - 1pm In-Service",
            anchor_text=None,
            filename=None,
            year_default=2026,
        )
        is None
    )
