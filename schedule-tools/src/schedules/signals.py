from __future__ import annotations

import re
from dataclasses import dataclass, replace
from io import BytesIO

import pdfplumber
from pypdf import PdfReader

from .models import ReviewNote

DAY_TOKEN_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)

_PROGRAM_RE = re.compile(
    r"\b(?:swim|senior|family|exercise|aerobics|rentals?|lessons?|sfusd|synchro|hockey|piranha|parent|preschool|masters?)\b",
    re.IGNORECASE,
)
_CLOCK = r"(?:\d{1,2}(?::\d{2})?\s*(?:[ap](?:\.?m\.?)?)?|noon|midnight)"
TIME_RANGE_RE = re.compile(rf"(?<![\d/:])(?P<start>{_CLOCK})\s*[-–—]\s*(?P<end>{_CLOCK})(?![\d/])", re.IGNORECASE)
CLOSURE_TOKEN_RE = re.compile(r"\b(?:closed|closures?|closing|cancel\w*|unavailable|training\w*|maintenance|holidays?)\b", re.IGNORECASE)
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 12
MAX_PAGE_POINTS = 2000


@dataclass(frozen=True)
class SourceCell:
    id: str
    page: int
    day: str
    text: str
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class SourceNotice:
    id: str
    text: str
    facility: bool
    page: int = 1
    bounds: tuple[float, float, float, float] | None = None
    physical_pool: str | None = None
    session_cell: str | None = None


@dataclass(frozen=True)
class PdfSource:
    text: str
    cells: tuple[SourceCell, ...]
    issues: tuple[str, ...]
    page_count: int
    notices: tuple[SourceNotice, ...]



def north_beach_pool_identity(text: str) -> str | None:
    title = text.split("TUESDAY", 1)[0]
    identities = re.findall(r"NORTH\s+BEACH\s+POOL\s*\((COOL|WARM)\)\s+(?:FALL|WINTER|SPRING|SUMMER|INTERIM)\s+20\d{2}\s+SCHEDULE", title, re.IGNORECASE)
    return identities[0].lower() if len(identities) == 1 else None


def program_types(text: str) -> tuple[str, ...]:
    value = text.lower()
    for word in ("senior", "family", "recreation", "rec", "lap", "swim"):
        value = re.sub(r"\b" + r"\s*".join(word) + r"\b", word, value)
    value = re.sub(r"\b(?:senior|family|lap)\s+swim\s+(?:team|lessons?)\b", "", value)
    types = []
    if re.search(r"\bsenior\b", value):
        types.append("senior_swim")
        value = re.sub(r"\bsenior\s+lap\s+swim\b", "", value)
    if re.search(r"\b(?:family|recreation|rec)\b", value):
        types.append("family_swim")
    if re.search(r"\blap\b", value):
        types.append("lap_swim")
    return tuple(types)


def _weekday_header(page) -> list[dict]:
    words = [word for word in page.extract_words()
             if DAY_TOKEN_RE.fullmatch(word["text"])]
    groups = []
    for word in words:
        group = next((group for group in groups if abs(group[0]["top"] - word["top"]) < 6), None)
        if group is None:
            groups.append([word])
        else:
            group.append(word)
    headers = [group for group in groups if len({normalize_day_token(word["text"]) for word in group}) >= 3]
    if len(headers) != 1:
        return []
    return sorted(headers[0], key=lambda word: word["x0"])


def _column_cells(page, header: list[dict]) -> list[SourceCell]:
    centers = [(word["x0"] + word["x1"]) / 2 for word in header]
    boundaries = [max(0, centers[0] - (centers[1] - centers[0]) / 2),
                  *[(left + right) / 2 for left, right in zip(centers, centers[1:])],
                  min(page.width, centers[-1] + (centers[-1] - centers[-2]) / 2)]
    cells = []
    for column, word in enumerate(header):
        day = normalize_day_token(word["text"])
        bounds = (boundaries[column], word["bottom"] + 2, boundaries[column + 1], page.height)
        lines = page.crop(bounds).extract_text_lines(return_chars=False)
        blocks: list[list[dict]] = []
        current: list[dict] = []
        for line in lines:
            if (_PROGRAM_RE.search(line["text"]) or re.match(r"(?:Pool CLOSED|All city pools will be)", line["text"], re.IGNORECASE)) and any(TIME_RANGE_RE.search(item["text"]) for item in current):
                blocks.append(current)
                current = []
            current.append(line)
        if current:
            blocks.append(current)
        for block in blocks:
            text = "\n".join(line["text"] for line in block).strip()
            if not TIME_RANGE_RE.search(text):
                continue
            cells.append(SourceCell(
                id=f"p{page.page_number}-c{column + 1}-b{len(cells) + 1}",
                page=page.page_number, day=day, text=text,
                bounds=(bounds[0], block[0]["top"], bounds[2], block[-1]["bottom"]),
            ))
    return cells


def _program_row_cells(page) -> list[SourceCell] | None:
    # Word processors draw single-line text boxes as rectangles too. They are
    # not schedule borders; keep the larger cell rectangles for row detection.
    sizes = sorted(char["size"] for char in page.chars if char["text"].strip())
    minimum_height = 1.5 * sizes[len(sizes) // 2] if sizes else 18
    borders = page.filter(lambda obj: obj["object_type"] != "rect" or obj["height"] > minimum_height)
    tables = [table for table in borders.find_tables()
              if any("PROGRAMS" == (value or "").strip().upper() for value in table.extract()[0])]
    if not tables:
        return None
    if len(tables) != 1:
        raise ValueError("multiple_program_tables")
    table = tables[0]
    rows = table.extract()
    days = [normalize_day_token((value or "").strip()) for value in rows[0]]
    cells = []
    for index, row in enumerate(rows[1:], start=1):
        label = row[0] or ""
        for column, day in enumerate(days):
            if day is None or not row[column]:
                continue
            bounds = table.rows[index].cells[column]
            if bounds is None:
                raise ValueError("merged_program_cell")
            for line in row[column].splitlines():
                if TIME_RANGE_RE.search(line):
                    cells.append(SourceCell(
                        id=f"p{page.page_number}-r{index}-c{column}-b{len(cells) + 1}",
                        page=page.page_number, day=day, text=f"{label}\n{line}", bounds=bounds,
                    ))
    return cells


def _closure_notices(page, header: list[dict], cells: list[SourceCell] | None = None) -> list[SourceNotice]:
    words = page.extract_words()
    markers = [word for word in words if CLOSURE_TOKEN_RE.search(word["text"])]
    if not markers:
        return []
    if not header:
        return [SourceNotice(f"p{page.page_number}-notice", page.extract_text() or "", True)]
    headings = [word for word in words if word["text"].lower() == "notes:"
                and word["x0"] > header[-1]["x1"]]
    if len(headings) != 1:
        return [SourceNotice(f"p{page.page_number}-unresolved-notice", page.extract_text() or "", False)]
    heading = headings[0]
    left, top = max(0, heading["x0"] - 4), heading["bottom"]
    text = page.crop((left, top, page.width, page.height)).extract_text() or ""
    blocks = re.split(r"[•●]|\bPool Info:|(?=Closed for annual maintenance)", text)
    notices = [SourceNotice(f"p{page.page_number}-notice-{index}", block.strip(), True)
               for index, block in enumerate(blocks) if CLOSURE_TOKEN_RE.search(block)]
    covered = []
    identity = north_beach_pool_identity(page.extract_text() or "")
    if identity:
        scoped = []
        for notice in notices:
            pools = re.findall(r"\b(cool|warm) pool will be closed\b", notice.text, re.IGNORECASE)
            scoped.append(replace(notice, physical_pool=pools[0].lower()) if len(pools) == 1 else notice)
        notices = scoped
    if cells is not None:
        for cell in cells:
            if not CLOSURE_TOKEN_RE.search(cell.text):
                continue
            facility = not program_types(cell.text) or bool(re.search(r"All city pools will be", cell.text, re.IGNORECASE))
            notices.append(SourceNotice(cell.id + "-notice", cell.text, facility, cell.page, cell.bounds,
                                        None if facility else identity, None if facility else cell.id))
            covered.append(cell.bounds)
    for index, word in enumerate(markers):
        if any(x0 <= word["x0"] < x1 and top <= word["top"] <= bottom for x0, top, x1, bottom in covered):
            continue
        if word["x0"] < left or word["top"] < top:
            notices.append(SourceNotice(f"p{page.page_number}-unresolved-{index}", word["text"], False))
    return notices


def inspect_pdf_source(pdf_bytes: bytes) -> PdfSource:
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 25 MiB source limit")
    cells = []
    issues = []
    page_texts = []
    notices = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as document:
        if not 1 <= len(document.pages) <= MAX_PDF_PAGES:
            raise ValueError("PDF must have between 1 and 12 pages")
        for page in document.pages:
            if not (0 < page.width <= MAX_PAGE_POINTS and 0 < page.height <= MAX_PAGE_POINTS):
                raise ValueError("PDF page exceeds the supported dimensions")
            text = page.extract_text() or ""
            page_texts.append(f"PAGE {page.page_number}\n{text}")
            if not text.strip():
                issues.append(f"page_{page.page_number}:no_text")
                continue
            header = _weekday_header(page)
            if not header:
                notices.extend(_closure_notices(page, header))
                if TIME_RANGE_RE.search(text) and program_types(text):
                    issues.append(f"page_{page.page_number}:unsupported_grid")
                continue
            row_cells = _program_row_cells(page)
            page_cells = row_cells if row_cells is not None else _column_cells(page, header)
            notices.extend(_closure_notices(page, header, page_cells))
            if not page_cells:
                issues.append(f"page_{page.page_number}:empty_grid")
            cells.extend(page_cells)
            for cell in page_cells:
                if cell.text.count("(") != cell.text.count(")"):
                    issues.append(f"{cell.id}:unbalanced_text")
                if any(notice.facility and notice.bounds == cell.bounds for notice in notices):
                    continue
                if not program_types(cell.text) and not re.search(
                    r"\b(?:lessons?|learn|exercise|aerobics|rentals?|masters?|team|sfusd|piranha|preschool|parent|synchro|hockey)\b",
                    cell.text, re.IGNORECASE,
                ):
                    issues.append(f"{cell.id}:unknown_program")
        return PdfSource("\n\n".join(page_texts), tuple(cells), tuple(issues), len(document.pages), tuple(notices))


def extract_page_texts(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


def analyze_page_texts(page_texts: list[str]) -> list[int]:
    """Return the 1-based page numbers that carry a day-grid header."""
    grid_header_pages: list[int] = []

    for page_index, text in enumerate(page_texts, start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if _has_grid_header(lines):
            grid_header_pages.append(page_index)

    return grid_header_pages


def source_notes_for_signals(grid_header_pages: list[int]) -> list[ReviewNote]:
    notes: list[ReviewNote] = []

    if len(grid_header_pages) >= 2:
        notes.append(
            ReviewNote(
                kind="multi_grid_suspected",
                message=(
                    f"PDF appears to contain repeated day-grid pages ({len(grid_header_pages)} pages with day headers)"
                ),
            )
        )

    return notes


def _has_grid_header(lines: list[str]) -> bool:
    for line in lines:
        day_tokens = {normalize_day_token(match.group(1)) for match in DAY_TOKEN_RE.finditer(line)}
        day_tokens.discard(None)
        if len(day_tokens) >= 3:
            return True
    return False


def normalize_day_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.lower()
    if token.startswith("mon"):
        return "monday"
    if token.startswith("tue"):
        return "tuesday"
    if token.startswith("wed"):
        return "wednesday"
    if token.startswith("thu"):
        return "thursday"
    if token.startswith("fri"):
        return "friday"
    if token.startswith("sat"):
        return "saturday"
    if token.startswith("sun"):
        return "sunday"
    return None
