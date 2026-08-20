from __future__ import annotations

import json
import re
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, replace
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import httpx

from ._time import pacific_today
from .direct_sources.http import BOT_USER_AGENT
from .models import PoolEntry
from .paths import REGISTRY_PATH, TMP_DIR
from .signals import _has_grid_header, extract_page_texts

CandidateKind = Literal["session_grid", "closure_notice", "split_part", "other"]
CandidateSource = Literal["table", "band", "persisted"]
RollAction = Literal["adopt", "unchanged", "flag"]

DOCUMENT_CENTER_BASE = "https://sfrecpark.org/DocumentCenter/View"
VIEW_ID_RE = re.compile(r"/DocumentCenter/View/(\d+)", re.IGNORECASE)
BAND_WINDOW = 40
BAND_DELAY_SECONDS = 0.2
PAGE_TIMEOUT_SECONDS = 30.0
PAGE_RETRIES = 2

POOL_TOKENS: dict[str, tuple[str, ...]] = {
    "balboa-pool": ("Balboa",),
    "coffman-pool": ("Coffman",),
    "garfield-pool": ("Garfield",),
    "hamilton-pool": ("Hamilton",),
    "martin-luther-king-jr-pool": ("MLK", "Martin Luther King"),
    "mission-community-pool": ("Mission",),
    "north-beach-pool": ("North Beach", "NB Pool"),
    "rossi-pool": ("Rossi",),
    "sava-pool": ("Sava",),
}

_CLOSURE_RE = re.compile(
    r"(?i)(?<![a-z])(?:maintenance|closure|closed|notice|repair|attention)(?![a-z])"
)
_SEASON_RE = re.compile(
    r"(?i)(?<![a-z])(?:schedule|fall|spring|summer|winter|interim)(?![a-z])"
)
_SPLIT_RE = re.compile(
    r"(?i)(?:cool\s+pool|warm\s+pool|(?<![a-z])(?:cool|warm)(?![a-z])|"
    r"(?<![a-z])pt\.?\s*[12](?![a-z0-9])|(?<![a-z])part\s+[12](?![a-z0-9]))"
)
_NON_PDF_NAME_RE = re.compile(r"(?i)\.(?:jpe?g|png|gif|webp|html?)\s*$")
_DISCOVER_LINE_RE = re.compile(r"^discover:\s+(\d{4}-\d{2}-\d{2})\s+(\S+)(?:\s+(.*))?$")
_ID_KIND_SOURCE_RE = re.compile(r"id=(\d+):([a-z_]+):(table|band|persisted)\b")
_BAND_SESSION_GRID_RE = re.compile(r"band_session_grid\s+id=(\d+)")
_FILENAME_QUOTED_RE = re.compile(r'filename\s*=\s*"([^"]+)"', re.IGNORECASE)
_FILENAME_STAR_RE = re.compile(
    r"filename\*\s*=\s*(?:UTF-8''|utf-8'')([^;]+)", re.IGNORECASE
)
_FILENAME_BARE_RE = re.compile(r"filename\s*=\s*([^;]+)", re.IGNORECASE)


class DiscoverError(RuntimeError):
    """Hard discover failure: every in-scope Rec & Park page failed, or a crash."""


@dataclass(frozen=True)
class DocumentLink:
    view_id: int
    href: str
    anchor_text: str


@dataclass(frozen=True)
class ClassifiedDocument:
    link: DocumentLink
    kind: CandidateKind
    filename: str | None
    source: CandidateSource


@dataclass(frozen=True)
class DiscoverDecision:
    slug: str
    action: RollAction
    old_url: str
    new_url: str | None
    kind: CandidateKind | None
    reason: str
    candidates: tuple[ClassifiedDocument, ...]
    extra_candidates: tuple[ClassifiedDocument, ...]
    blocking: bool


@dataclass(frozen=True)
class _ViewFetch:
    view_id: int
    status_code: int
    content_type: str
    filename: str | None
    content: bytes
    is_pdf: bool


def rec_park_entries(entries: list[PoolEntry]) -> list[PoolEntry]:
    selected: list[PoolEntry] = []
    for entry in entries:
        if entry.source_kind != "sfrecpark_pdf":
            continue
        host = (urlparse(entry.official_page_url).hostname or "").lower()
        if host != "sfrecpark.org":
            continue
        selected.append(entry)
    return selected


def view_id_from_url(url: str) -> int | None:
    match = VIEW_ID_RE.search(url)
    return int(match.group(1)) if match else None


def absolute_view_url(view_id: int) -> str:
    return f"{DOCUMENT_CENTER_BASE}/{view_id}"


def discover_facility_documents(html: str) -> list[DocumentLink]:
    parser = _DocumentsParser()
    parser.feed(html)
    parser.close()
    seen: set[int] = set()
    out: list[DocumentLink] = []
    for link in parser.links:
        if link.view_id in seen:
            continue
        seen.add(link.view_id)
        out.append(link)
    return out


def classify_pdf(
    link: DocumentLink,
    *,
    pool_slug: str,
    pdf_bytes: bytes | None,
    filename: str | None,
    source: CandidateSource = "table",
) -> ClassifiedDocument:
    title = link.anchor_text or ""
    name = filename or ""
    primary = f"{title} {name}".strip()
    kind = _classify_kind(
        primary, pool_slug=pool_slug, pdf_bytes=pdf_bytes, filename=filename
    )
    if kind == "closure_notice":
        # Page-1 day tokens must not demote a flyer.
        if pdf_bytes:
            _page_has_grid(pdf_bytes)
        return ClassifiedDocument(
            link=link, kind=kind, filename=filename, source=source
        )
    if kind == "other" and pdf_bytes:
        page_text = _first_page_text(pdf_bytes)
        if page_text:
            kind = _classify_kind(
                f"{primary} {page_text}",
                pool_slug=pool_slug,
                pdf_bytes=None,
                filename=filename,
            )
            if _CLOSURE_RE.search(primary):
                kind = "closure_notice"
    if kind == "session_grid" and pdf_bytes:
        _page_has_grid(pdf_bytes)
    return ClassifiedDocument(link=link, kind=kind, filename=filename, source=source)


def choose_roll(
    entry: PoolEntry, classified: list[ClassifiedDocument]
) -> DiscoverDecision:
    candidates = tuple(classified)
    old_url = entry.pdf_url
    current_id = view_id_from_url(old_url)
    session_grids = [item for item in classified if item.kind == "session_grid"]
    table_grids = [item for item in session_grids if item.source == "table"]
    table_grid_ids = {item.link.view_id for item in table_grids}
    all_grid_ids = {item.link.view_id for item in session_grids}
    band_only_ids = all_grid_ids - table_grid_ids
    table_splits = [
        item
        for item in classified
        if item.kind == "split_part" and item.source == "table"
    ]
    table_notices = [
        item
        for item in classified
        if item.kind == "closure_notice" and item.source == "table"
    ]
    non_grid = tuple(item for item in classified if item.kind != "session_grid")

    def decide(
        action: RollAction,
        reason: str,
        *,
        kind: CandidateKind | None,
        new_url: str | None = None,
        blocking: bool,
        extra: tuple[ClassifiedDocument, ...] = (),
    ) -> DiscoverDecision:
        return DiscoverDecision(
            slug=entry.slug,
            action=action,
            old_url=old_url,
            new_url=new_url,
            kind=kind,
            reason=reason,
            candidates=candidates,
            extra_candidates=extra,
            blocking=blocking,
        )

    if entry.source_status != "published":
        reason = "split_part" if table_splits else "unpublished"
        kind: CandidateKind | None = "split_part" if table_splits else None
        if table_notices and not table_splits:
            reason = "closure_notice"
            kind = "closure_notice"
        return decide("flag", reason, kind=kind, blocking=True)

    if current_id is not None and current_id in all_grid_ids:
        return decide(
            "unchanged",
            "current_session_grid",
            kind="session_grid",
            new_url=old_url,
            blocking=False,
            extra=non_grid,
        )

    if len(all_grid_ids) >= 2:
        return decide("flag", "multiple_windows", kind="session_grid", blocking=True)

    if table_splits:
        return decide("flag", "split_part", kind="split_part", blocking=True)

    if len(table_grid_ids) == 1 and not band_only_ids:
        only = table_grids[0]
        if only.link.view_id != current_id:
            return decide(
                "adopt",
                "session_grid",
                kind="session_grid",
                new_url=only.link.href,
                blocking=False,
                extra=non_grid,
            )
        return decide(
            "unchanged",
            "same_id",
            kind="session_grid",
            new_url=old_url,
            blocking=False,
            extra=non_grid,
        )

    if not table_grid_ids and session_grids:
        return decide("flag", "band_session_grid", kind="session_grid", blocking=True)

    if table_notices and not session_grids:
        return decide("flag", "closure_notice", kind="closure_notice", blocking=True)

    if not classified:
        return decide("flag", "empty_table", kind=None, blocking=True)

    return decide("flag", "no_session_grid", kind=None, blocking=True)


def persisted_band_ids(notes: str | None) -> frozenset[int]:
    line = _discover_machine_line(notes)
    if line is None:
        return frozenset()
    match = _DISCOVER_LINE_RE.match(line)
    if match is None or match.group(2) != "flag":
        return frozenset()
    ids: set[int] = set()
    for token in _BAND_SESSION_GRID_RE.finditer(line):
        ids.add(int(token.group(1)))
    for token in _ID_KIND_SOURCE_RE.finditer(line):
        view_id, kind, source = int(token.group(1)), token.group(2), token.group(3)
        if kind == "session_grid" and source in {"band", "persisted"}:
            ids.add(view_id)
    return frozenset(ids)


def rewrite_registry_pdf_url(path: Path, slug: str, url: str) -> None:
    text = path.read_text()
    start, end = _pool_block_span(text, slug)
    block = text[start:end]
    updated = _replace_quoted_field(block, "pdf_url", url)
    if updated == block:
        return
    path.write_text(text[:start] + updated + text[end:])


def apply_discover_decision(path: Path, decision: DiscoverDecision) -> None:
    text = path.read_text()
    start, end = _pool_block_span(text, slug=decision.slug)
    block = text[start:end]
    updated = _apply_decision_to_block(block, decision)
    if updated == block:
        return
    path.write_text(text[:start] + updated + text[end:])


def discover_all(
    entries: list[PoolEntry],
    *,
    dry_run: bool = False,
    delay: float = BAND_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    registry_path: Path = REGISTRY_PATH,
    report_dir: Path = TMP_DIR,
    slugs: list[str] | None = None,
    adopt: tuple[str, int] | None = None,
) -> list[DiscoverDecision]:
    rec_park = rec_park_entries(entries)
    if slugs is not None:
        wanted = set(slugs)
        selected = [entry for entry in rec_park if entry.slug in wanted]
        missing = sorted(wanted - {entry.slug for entry in selected})
        if missing:
            raise DiscoverError(
                f"Unknown or non-Rec & Park slug(s) for discover: {', '.join(missing)}"
            )
    else:
        selected = list(rec_park)
    selected_slugs = {entry.slug for entry in selected}

    if adopt is not None and adopt[0] not in {entry.slug for entry in rec_park}:
        raise DiscoverError(f"Unknown or non-Rec & Park slug for --adopt: {adopt[0]}")

    max_id = _max_pdf_view_id(rec_park)
    persisted_by_slug = {
        entry.slug: persisted_band_ids(entry.notes) for entry in rec_park
    }
    all_persisted = (
        set().union(*persisted_by_slug.values()) if persisted_by_slug else set()
    )
    probe: set[int] = set(all_persisted)
    if max_id is not None:
        probe.update(range(max_id + 1, max_id + 1 + BAND_WINDOW))

    headers = {
        "User-Agent": BOT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    }
    table_links: dict[str, list[DocumentLink]] = {}
    fetch_errors: set[str] = set()
    views: dict[int, _ViewFetch] = {}

    with httpx.Client(
        follow_redirects=True, timeout=PAGE_TIMEOUT_SECONDS, headers=headers
    ) as client:
        for entry in selected:
            try:
                page = _get_with_retries(client, entry.official_page_url, sleep=sleep)
                page.raise_for_status()
                table_links[entry.slug] = discover_facility_documents(page.text)
            except Exception:  # noqa: BLE001
                fetch_errors.add(entry.slug)
                table_links[entry.slug] = []

        table_ids = {link.view_id for links in table_links.values() for link in links}
        current_ids = {
            view_id
            for entry in selected
            if (view_id := view_id_from_url(entry.pdf_url)) is not None
        }
        if adopt is not None and adopt[0] in selected_slugs:
            current_ids.add(adopt[1])
        immediate_ids = sorted(table_ids | current_ids)
        for view_id in immediate_ids:
            views[view_id] = _fetch_view(client, view_id)

        remaining = sorted(view_id for view_id in probe if view_id not in views)
        for index, view_id in enumerate(remaining):
            if index and delay:
                sleep(delay)
            views[view_id] = _fetch_view(client, view_id)

    dropped_persisted = {
        view_id
        for view_id in all_persisted
        if (fetched := views.get(view_id)) is not None and fetched.status_code == 404
    }

    classified_by_slug: dict[str, list[ClassifiedDocument]] = {
        entry.slug: [] for entry in selected
    }
    seen_ids: dict[str, set[int]] = {entry.slug: set() for entry in selected}

    def add_classified(slug: str, item: ClassifiedDocument) -> None:
        if item.link.view_id in seen_ids[slug]:
            return
        seen_ids[slug].add(item.link.view_id)
        classified_by_slug[slug].append(item)

    for entry in selected:
        for link in table_links.get(entry.slug, []):
            fetched = views.get(link.view_id)
            item = classify_pdf(
                link,
                pool_slug=entry.slug,
                pdf_bytes=fetched.content if fetched and fetched.is_pdf else None,
                filename=_filename_for_link(link, fetched),
                source="table",
            )
            add_classified(entry.slug, item)

    for view_id in probe:
        if view_id in dropped_persisted:
            continue
        fetched = views.get(view_id)
        if fetched is None or not fetched.is_pdf:
            continue
        source: CandidateSource = (
            "persisted"
            if view_id in all_persisted and (max_id is None or view_id <= max_id)
            else "band"
        )
        haystack = " ".join(
            part
            for part in (
                fetched.filename or "",
                _first_page_text(fetched.content) if fetched.is_pdf else "",
            )
            if part
        )
        matches = [
            slug
            for slug in POOL_TOKENS
            if slug in selected_slugs and _matches_pool(haystack, slug)
        ]
        if len(matches) != 1:
            continue
        slug = matches[0]
        if view_id in seen_ids[slug]:
            continue
        link = DocumentLink(
            view_id=view_id,
            href=absolute_view_url(view_id),
            anchor_text=fetched.filename or "",
        )
        item = classify_pdf(
            link,
            pool_slug=slug,
            pdf_bytes=fetched.content,
            filename=fetched.filename,
            source=source,
        )
        add_classified(slug, item)

    decisions: list[DiscoverDecision] = []
    for entry in selected:
        if entry.slug in fetch_errors:
            decisions.append(
                DiscoverDecision(
                    slug=entry.slug,
                    action="flag",
                    old_url=entry.pdf_url,
                    new_url=None,
                    kind=None,
                    reason="fetch_error",
                    candidates=tuple(classified_by_slug[entry.slug]),
                    extra_candidates=(),
                    blocking=True,
                )
            )
            continue
        classified = classified_by_slug[entry.slug]
        decision = choose_roll(entry, classified)
        if adopt is not None and adopt[0] == entry.slug:
            decision = _operator_adopt_decision(entry, classified, views, adopt[1])
        if decision.action == "flag":
            decision = _with_persisted_survivors(
                decision,
                persisted_by_slug.get(entry.slug, frozenset()),
                dropped_persisted,
                views,
            )
        decisions.append(decision)

    if not dry_run:
        for decision in decisions:
            apply_discover_decision(registry_path, decision)

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "discovery-report.md"
    decisions_path = report_dir / "discovery-decisions.json"
    report_path.write_text(_render_report(decisions, persisted_by_slug))
    decisions_path.write_text(
        json.dumps([_decision_to_json(item) for item in decisions], indent=2) + "\n"
    )

    if selected and fetch_errors and set(fetch_errors) == selected_slugs:
        raise DiscoverError("every Rec & Park facility page failed to fetch")
    return decisions


def _operator_adopt_decision(
    entry: PoolEntry,
    classified: list[ClassifiedDocument],
    views: dict[int, _ViewFetch],
    view_id: int,
) -> DiscoverDecision:
    match = next((item for item in classified if item.link.view_id == view_id), None)
    if match is None:
        fetched = views.get(view_id)
        link = DocumentLink(
            view_id=view_id,
            href=absolute_view_url(view_id),
            anchor_text=(fetched.filename if fetched else None) or "",
        )
        match = classify_pdf(
            link,
            pool_slug=entry.slug,
            pdf_bytes=fetched.content if fetched and fetched.is_pdf else None,
            filename=fetched.filename if fetched else None,
            source="persisted",
        )
        classified = [*classified, match]
    extras = tuple(
        item
        for item in classified
        if item.kind != "session_grid" and item.link.view_id != view_id
    )
    return DiscoverDecision(
        slug=entry.slug,
        action="adopt",
        old_url=entry.pdf_url,
        new_url=absolute_view_url(view_id),
        kind=match.kind,
        reason="operator_adopt",
        candidates=tuple(classified),
        extra_candidates=extras,
        blocking=False,
    )


def _with_persisted_survivors(
    decision: DiscoverDecision,
    previous: frozenset[int],
    dropped: set[int],
    views: dict[int, _ViewFetch],
) -> DiscoverDecision:
    current_ids = {item.link.view_id for item in decision.candidates}
    survivors: list[ClassifiedDocument] = []
    adopted_id = (
        view_id_from_url(decision.new_url or "") if decision.action == "adopt" else None
    )
    for view_id in sorted(previous):
        if view_id in dropped or view_id in current_ids or view_id == adopted_id:
            continue
        fetched = views.get(view_id)
        if fetched is None or not fetched.is_pdf:
            continue
        link = DocumentLink(
            view_id=view_id,
            href=absolute_view_url(view_id),
            anchor_text=fetched.filename or "",
        )
        survivors.append(
            ClassifiedDocument(
                link=link,
                kind="session_grid",
                filename=fetched.filename,
                source="persisted",
            )
        )
    if not survivors:
        return decision
    return replace(decision, candidates=decision.candidates + tuple(survivors))


def _classify_kind(
    haystack: str,
    *,
    pool_slug: str,
    pdf_bytes: bytes | None,
    filename: str | None,
) -> CandidateKind:
    if _is_non_pdf(filename, pdf_bytes):
        return "other"
    if _matches_other_pool(haystack, pool_slug) and not _matches_pool(
        haystack, pool_slug
    ):
        return "other"
    if _CLOSURE_RE.search(haystack):
        return "closure_notice"
    if _SPLIT_RE.search(haystack):
        return "split_part"
    if _matches_pool(haystack, pool_slug) and _SEASON_RE.search(haystack):
        return "session_grid"
    return "other"


def _is_non_pdf(filename: str | None, pdf_bytes: bytes | None) -> bool:
    if filename and _NON_PDF_NAME_RE.search(filename.strip()):
        return True
    if (
        pdf_bytes is not None
        and pdf_bytes != b""
        and not pdf_bytes.lstrip().startswith(b"%PDF")
    ):
        return True
    return False


def _matches_pool(text: str, slug: str) -> bool:
    for token in POOL_TOKENS.get(slug, ()):
        if _token_re(token).search(text):
            return True
    return False


def _matches_other_pool(text: str, slug: str) -> bool:
    return any(_matches_pool(text, other) for other in POOL_TOKENS if other != slug)


def _token_re(token: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in token.split() if part]
    body = r"\s+".join(parts)
    return re.compile(rf"(?i)(?<![a-z]){body}(?![a-z])")


def _first_page_text(pdf_bytes: bytes) -> str:
    try:
        pages = extract_page_texts(pdf_bytes)
    except Exception:  # noqa: BLE001
        return ""
    return pages[0] if pages else ""


def _page_has_grid(pdf_bytes: bytes) -> bool:
    text = _first_page_text(pdf_bytes)
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return _has_grid_header(lines)


def _filename_for_link(link: DocumentLink, fetched: _ViewFetch | None) -> str | None:
    if fetched is not None and fetched.filename:
        return fetched.filename
    if link.anchor_text:
        return None
    return fetched.filename if fetched else None


def _max_pdf_view_id(entries: list[PoolEntry]) -> int | None:
    ids = [
        view_id
        for entry in entries
        if (view_id := view_id_from_url(entry.pdf_url)) is not None
    ]
    return max(ids) if ids else None


def _get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    sleep: Callable[[float], None],
    retries: int = PAGE_RETRIES,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return client.get(url)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= retries:
                break
            sleep(0.25 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _fetch_view(client: httpx.Client, view_id: int) -> _ViewFetch:
    url = absolute_view_url(view_id)
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return _ViewFetch(
            view_id=view_id,
            status_code=0,
            content_type="",
            filename=None,
            content=b"",
            is_pdf=False,
        )
    content_type = response.headers.get("content-type", "")
    filename = _filename_from_headers(response.headers)
    content = response.content or b""
    is_pdf = response.status_code == 200 and (
        "pdf" in content_type.lower() or content.lstrip().startswith(b"%PDF")
    )
    return _ViewFetch(
        view_id=view_id,
        status_code=response.status_code,
        content_type=content_type,
        filename=filename,
        content=content,
        is_pdf=is_pdf,
    )


def _filename_from_headers(headers: httpx.Headers) -> str | None:
    cd = headers.get("content-disposition")
    if not cd:
        return None
    star = _FILENAME_STAR_RE.search(cd)
    if star:
        return unquote(star.group(1).strip().strip('"'))
    quoted = _FILENAME_QUOTED_RE.search(cd)
    if quoted:
        return quoted.group(1)
    bare = _FILENAME_BARE_RE.search(cd)
    if bare:
        return bare.group(1).strip().strip('"')
    return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


class _DocumentsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[DocumentLink] = []
        self._table = 0
        self._in_tr = False
        self._in_th = False
        self._in_heading = False
        self._in_a = False
        self._heading_text: list[str] = []
        self._th_text: list[str] = []
        self._a_text: list[str] = []
        self._a_href: str | None = None
        self._row_links: list[tuple[str, str]] = []
        self._row_th_texts: list[str] = []
        self._collecting = False
        self._ignore_deck = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table":
            self._table += 1
            if self._table == 1:
                self._collecting = False
        elif tag == "tr" and self._table == 1:
            self._in_tr = True
            self._row_links = []
            self._row_th_texts = []
        elif tag == "th" and self._in_tr:
            self._in_th = True
            self._th_text = []
        elif tag in {"h1", "h2", "h3", "h4"}:
            self._in_heading = True
            self._heading_text = []
        elif tag == "a":
            self._in_a = True
            self._a_href = attrs_dict.get("href") or ""
            self._a_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4"} and self._in_heading:
            text = _squash("".join(self._heading_text))
            self._in_heading = False
            lowered = text.lower()
            if lowered in {"features", "facility and deck rules"}:
                self._collecting = False
            if lowered == "facility and deck rules":
                self._ignore_deck = True
            elif lowered != "features":
                self._ignore_deck = False
        elif tag == "th" and self._in_th:
            self._in_th = False
            self._row_th_texts.append(_squash("".join(self._th_text)))
        elif tag == "a" and self._in_a:
            href = self._a_href or ""
            text = _squash("".join(self._a_text))
            self._in_a = False
            self._a_href = None
            if self._in_tr and self._table == 1:
                self._row_links.append((href, text))
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            self._finish_row()
        elif tag == "table" and self._table:
            self._table -= 1
            if self._table == 0:
                self._collecting = False

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading_text.append(data)
        if self._in_th:
            self._th_text.append(data)
        if self._in_a:
            self._a_text.append(data)

    def _finish_row(self) -> None:
        if self._ignore_deck or self._table != 1:
            return
        th_texts = [text.strip() for text in self._row_th_texts]
        has_th = bool(th_texts)
        is_documents = any(text.lower() == "documents" for text in th_texts)
        if self._collecting and has_th and not is_documents:
            self._collecting = False
            return
        if is_documents:
            self._collecting = True
        if not self._collecting:
            return
        for href, text in self._row_links:
            match = VIEW_ID_RE.search(href)
            if match is None:
                continue
            view_id = int(match.group(1))
            self.links.append(
                DocumentLink(
                    view_id=view_id,
                    href=absolute_view_url(view_id),
                    anchor_text=text,
                )
            )


def _pool_block_span(text: str, slug: str) -> tuple[int, int]:
    needle = f'slug = "{slug}"'
    idx = text.find(needle)
    if idx == -1:
        raise DiscoverError(f"slug {slug!r} not found in registry")
    start = text.rfind("[[pool]]", 0, idx)
    if start == -1:
        raise DiscoverError(f"[[pool]] header missing for slug {slug!r}")
    nxt = text.find("[[pool]]", idx)
    end = nxt if nxt != -1 else len(text)
    return start, end


def _apply_decision_to_block(block: str, decision: DiscoverDecision) -> str:
    updated = block
    if decision.action == "adopt" and decision.new_url:
        updated = _replace_quoted_field(updated, "pdf_url", decision.new_url)
        if decision.kind == "session_grid":
            updated = _ensure_source_status(updated, "published", insert=False)
    if decision.action == "flag" and decision.kind == "split_part":
        updated = _ensure_source_status(
            updated, "missing_current_schedule", insert=True
        )

    existing_notes = _block_notes(updated)
    machine, human = _split_notes(existing_notes)
    desired = _desired_machine_line(decision)
    if (
        desired is not None
        and machine is not None
        and _machine_key(machine) == _machine_key(desired)
    ):
        desired = machine
    composed = _compose_notes(desired, human)
    return _replace_or_insert_notes(updated, composed)


def _desired_machine_line(decision: DiscoverDecision) -> str | None:
    date = pacific_today().isoformat()
    if decision.action in {"adopt", "unchanged"}:
        extras = [
            item for item in decision.extra_candidates if item.kind != "session_grid"
        ]
        if not extras:
            return None
        tokens = " ".join(_id_token(item) for item in extras)
        return f"discover: {date} extra {tokens}".rstrip()

    tokens = _flag_tokens(decision)
    reason = decision.reason
    return f"discover: {date} flag {reason}{tokens}".rstrip()


def _flag_tokens(decision: DiscoverDecision) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    for item in decision.candidates:
        if item.link.view_id in seen:
            continue
        seen.add(item.link.view_id)
        parts.append(_id_token(item, prefix_band=True))
    if not parts:
        return ""
    return " " + " ".join(parts)


def _id_token(item: ClassifiedDocument, *, prefix_band: bool = False) -> str:
    token = f"id={item.link.view_id}:{item.kind}:{item.source}"
    if (
        prefix_band
        and item.kind == "session_grid"
        and item.source in {"band", "persisted"}
    ):
        return f"band_session_grid {token}"
    return token


def _ensure_source_status(block: str, status: str, *, insert: bool) -> str:
    pattern = re.compile(r'^source_status\s*=\s*"(.*?)"', re.MULTILINE)
    match = pattern.search(block)
    if match:
        if match.group(1) == status:
            return block
        if status == "published" or insert or match.group(1) != status:
            return pattern.sub(f'source_status = "{status}"', block, count=1)
        return block
    if not insert:
        return block
    return _insert_field_after(block, "official_page_url", "source_status", status)


def _replace_quoted_field(block: str, field: str, value: str) -> str:
    pattern = re.compile(rf'^({re.escape(field)}\s*=\s*)".*?"', re.MULTILINE)
    if pattern.search(block) is None:
        return block
    return pattern.sub(rf'\1"{value}"', block, count=1)


def _insert_field_after(block: str, after_field: str, field: str, value: str) -> str:
    pattern = re.compile(
        rf'^({re.escape(after_field)}\s*=\s*".*?"[ \t]*)(\n)', re.MULTILINE
    )
    match = pattern.search(block)
    if match is None:
        return block.rstrip() + f'\n{field} = "{value}"\n'
    return block[: match.end()] + f'{field} = "{value}"\n' + block[match.end() :]


def _block_notes(block: str) -> str | None:
    try:
        parsed = tomllib.loads(block)
    except tomllib.TOMLDecodeError:
        return None
    pool = parsed.get("pool")
    raw = None
    if isinstance(pool, list) and pool:
        raw = pool[0].get("notes")
    elif isinstance(pool, dict):
        raw = pool.get("notes")
    return raw if isinstance(raw, str) else None


def _notes_span(block: str) -> tuple[int, int] | None:
    triple = re.search(r'^notes\s*=\s*"""', block, re.MULTILINE)
    if triple:
        close = block.find('"""', triple.end())
        if close == -1:
            raise DiscoverError("unterminated triple-quoted notes")
        return triple.start(), close + 3
    single = re.search(r'^notes\s*=\s*"(?:[^"\\]|\\.)*"', block, re.MULTILINE)
    if single:
        return single.start(), single.end()
    return None


def _replace_or_insert_notes(block: str, notes: str | None) -> str:
    span = _notes_span(block)
    if notes is None:
        if span is None:
            return block
        start, end = span
        if end < len(block) and block[end] == "\n":
            end += 1
        return block[:start] + block[end:]
    rendered = _render_notes_assignment(notes)
    if span is None:
        return _insert_notes(block, rendered)
    start, end = span
    return block[:start] + rendered + block[end:]


def _insert_notes(block: str, assignment: str) -> str:
    for field in ("source_status", "official_page_url"):
        match = re.search(
            rf'^({re.escape(field)}\s*=\s*".*?"[ \t]*)(\n)', block, re.MULTILINE
        )
        if match:
            return block[: match.end()] + assignment + "\n" + block[match.end() :]
    return block.rstrip() + "\n" + assignment + "\n"


def _render_notes_assignment(notes: str) -> str:
    if "\n" in notes or notes.startswith("discover:"):
        return f'notes = """\n{notes}\n"""'
    escaped = notes.replace("\\", "\\\\").replace('"', '\\"')
    return f'notes = "{escaped}"'


def _split_notes(notes: str | None) -> tuple[str | None, str]:
    if not notes:
        return None, ""
    lines = notes.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    machine: str | None = None
    if index < len(lines) and lines[index].lstrip().startswith("discover:"):
        machine = lines[index].strip()
        index += 1
        if index < len(lines) and not lines[index].strip():
            index += 1
    human = "\n".join(lines[index:]).strip("\n")
    return machine, human


def _compose_notes(machine: str | None, human: str) -> str | None:
    human = human.strip("\n")
    if machine and human:
        return f"{machine}\n\n{human}"
    if machine:
        return machine
    if human:
        return human
    return None


def _discover_machine_line(notes: str | None) -> str | None:
    machine, _human = _split_notes(notes)
    return machine


def _machine_key(line: str) -> str:
    return re.sub(r"^discover:\s+\d{4}-\d{2}-\d{2}\s+", "discover: ", line.strip())


def _decision_to_json(decision: DiscoverDecision) -> dict:
    return {
        "slug": decision.slug,
        "action": decision.action,
        "old_url": decision.old_url,
        "new_url": decision.new_url,
        "kind": decision.kind,
        "reason": decision.reason,
        "blocking": decision.blocking,
        "candidates": [_classified_to_json(item) for item in decision.candidates],
        "extra_candidates": [
            _classified_to_json(item) for item in decision.extra_candidates
        ],
    }


def _classified_to_json(item: ClassifiedDocument) -> dict:
    return {
        "view_id": item.link.view_id,
        "href": item.link.href,
        "anchor_text": item.link.anchor_text,
        "kind": item.kind,
        "filename": item.filename,
        "source": item.source,
    }


def _render_report(
    decisions: list[DiscoverDecision],
    persisted_by_slug: dict[str, frozenset[int]],
) -> str:
    lines = [
        "# Rec & Park PDF discovery",
        "",
        "| slug | action | blocking | reason | old | new |",
        "|---|---|---|---|---|---|",
    ]
    for decision in decisions:
        old_id = view_id_from_url(decision.old_url)
        new_id = view_id_from_url(decision.new_url or "")
        lines.append(
            f"| {decision.slug} | {decision.action} | "
            f"{'yes' if decision.blocking else 'no'} | {decision.reason} | "
            f"{old_id or ''} | {new_id or ''} |"
        )
    lines.append("")
    for decision in decisions:
        lines.append(f"## {decision.slug}")
        lines.append(f"- action: {decision.action}")
        lines.append(f"- reason: {decision.reason}")
        lines.append(f"- blocking: {decision.blocking}")
        if decision.candidates:
            listed = ", ".join(
                f"{item.link.view_id}:{item.kind}:{item.source}"
                for item in decision.candidates
            )
            lines.append(f"- candidates: {listed}")
        extra = [
            item for item in decision.extra_candidates if item.kind != "session_grid"
        ]
        if extra:
            listed = ", ".join(
                f"{item.link.view_id}:{item.kind}:{item.source}" for item in extra
            )
            lines.append(f"- extra: {listed}")
        persisted = persisted_by_slug.get(decision.slug) or frozenset()
        if persisted:
            lines.append(
                f"- persisted: {', '.join(str(view_id) for view_id in sorted(persisted))}"
            )
        lines.append("")
    return "\n".join(lines)
