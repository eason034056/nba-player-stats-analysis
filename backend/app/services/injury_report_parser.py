"""Turn one official NBA injury-report PDF into rows.

``parse_pdf`` is the function to call. Pass the PDF bytes. It returns
a ``ParsedReport`` (``tag="ok"``) or a ``ParseFailure`` (``tag="failed"``).
It does not open a database and it does not look at the clock. The
report time comes from the title line. ``last_modified`` and ``filename``
are only used when the title is missing.

Three layouts, from the PDF Producer and the header row:

- ``ReportLayout.A`` — iText, with Category and Previous Status columns.
- ``ReportLayout.B`` — iText, status and reason.
- ``ReportLayout.C`` — GemBox, status and reason.

Rows are assembled from word positions. A reason line that sits within
16 points of a player line joins that player. A reason line at the top
of a page with no player nearby joins the last row of the previous page.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal
from zoneinfo import ZoneInfo

import pdfplumber

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc

# pdfplumber word boxes. The research pass used these three settings.
_WORD_X_TOLERANCE = 1.5
_WORD_Y_TOLERANCE = 2
# Words whose tops differ by at most this many points are one line.
_LINE_TOP_TOLERANCE = 2.5
# A word belongs to the rightmost header whose x0 is at most this far left.
_COLUMN_X_SLACK = 3.0
# A reason-only line joins an anchor at most this far away on the same page.
_REASON_ATTACH_PT = 16.0

STATUSES = frozenset({"Out", "Questionable", "Doubtful", "Probable", "Available"})

# Full names as the PDFs print them. "LA Clippers" and "Los Angeles Clippers"
# are the same club. The value set is the 30 NBA abbreviations.
OFFICIAL_TEAM_ABBR: dict[str, str] = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}
NBA_TEAM_ABBRS = frozenset(OFFICIAL_TEAM_ABBR.values())
_TEAM_BY_FOLD = {name.casefold(): abbr for name, abbr in OFFICIAL_TEAM_ABBR.items()}

# Longest first so "G League - Two-Way" wins over a shorter prefix.
CATEGORY_PREFIXES: tuple[str, ...] = (
    "Return to Competition Reconditioning",
    "Health and Safety Protocols",
    "G League - On Assignment",
    "Concussion Protocol",
    "G League - Two-Way",
    "League Suspension",
    "Coach's Decision",
    "Coach’s Decision",
    "Personal Reasons",
    "Team Suspension",
    "Injury/Illness",
    "Not With Team",
    "G League Team",
    "Rest",
)

_LABELS: tuple[tuple[str, frozenset[str]], ...] = (
    ("game_date", frozenset({"game date"})),
    ("game_time", frozenset({"game time"})),
    ("matchup", frozenset({"matchup"})),
    ("team", frozenset({"team"})),
    ("player", frozenset({"player name"})),
    ("category", frozenset({"category"})),
    ("reason", frozenset({"reason"})),
    ("status", frozenset({"current status", "status"})),
    ("previous_status", frozenset({"previous status"})),
)
_CARRY_KEYS = ("game_date", "game_time", "matchup", "team")
_TITLE = re.compile(
    r"Injury Report:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)
_PAGE = re.compile(r"^page\s+\d+\s+of\s+\d+$", re.IGNORECASE)
_GAME_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_MATCHUP = re.compile(r"\b([A-Z]{2,4}@[A-Z]{2,4})\b")
_FILENAME = re.compile(
    r"Injury-Report_(\d{4})-(\d{2})-(\d{2})_(\d{2})(?:_(\d{2}))?(AM|PM)\.pdf$",
    re.IGNORECASE,
)
_NYS = "NOT YET SUBMITTED"
_ALL = "ALL PLAYERS AVAILABLE"


class ReportLayout(Enum):
    """Which injury-report table shape this PDF uses.

    ``A`` has a Category column and a Previous Status column.
    ``B`` and ``C`` have current status and a reason. ``C`` is the
    GemBox files. Callers read ``ParsedReport.layout``.
    """

    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True)
class InjuryRow:
    """One parsed line that is a player or a team-level note.

    ``player_raw`` is ``Last, First`` as printed. It is ``""`` when the
    line is ``NOT YET SUBMITTED`` or ``ALL PLAYERS AVAILABLE``.
    ``team_abbr`` is the PDF abbreviation for ``team_name`` (``BOS``,
    ``LAL``). It is ``""`` when the name is not one of the 30 clubs.
    ``previous_status`` is set only on layout A.
    """

    game_date: date
    game_time_et: str | None
    matchup: str
    team_name: str
    team_abbr: str
    player_raw: str
    status: str | None
    reason: str | None
    category: str | None
    not_yet_submitted: bool
    all_players_available: bool
    previous_status: str | None = None


@dataclass(frozen=True)
class ParsedReport:
    """A PDF that parsed. ``tag`` is ``"ok"``.

    ``report_at`` is an aware UTC instant. ``report_at_source`` says
    where it came from: ``title``, ``last_modified``, or ``filename``.
    ``pagebreak_joins`` counts reason lines that continued onto the
    next page. ``player_rows`` counts rows that name a player.
    ``nys_rows`` counts NOT YET SUBMITTED rows.
    """

    tag: Literal["ok"]
    layout: ReportLayout
    report_at: datetime
    report_at_source: str
    rows: tuple[InjuryRow, ...]
    pagebreak_joins: int
    unattached_reasons: int

    @property
    def player_rows(self) -> int:
        """How many rows name a player. Team notes are not included."""
        return sum(1 for row in self.rows if row.player_raw)

    @property
    def nys_rows(self) -> int:
        """How many rows are NOT YET SUBMITTED."""
        return sum(1 for row in self.rows if row.not_yet_submitted)


@dataclass(frozen=True)
class ParseFailure:
    """The PDF could not be read. ``tag`` is ``"failed"``.

    ``error`` is a short message. It does not include the PDF bytes.
    ``report_at`` is set when a fallback time was available, so the
    caller can still record the failure against that instant.
    """

    tag: Literal["failed"]
    error: str
    report_at: datetime | None = None
    report_at_source: str | None = None


ParseResult = ParsedReport | ParseFailure


@dataclass(frozen=True)
class _Column:
    name: str
    x0: float


@dataclass(frozen=True)
class _Line:
    page: int
    top: float
    cells: dict[str, str]
    raw: str


def parse_pdf(
    data: bytes,
    *,
    last_modified: datetime | None = None,
    filename: str | None = None,
) -> ParseResult:
    """Parse one injury-report PDF.

    ``parse_pdf`` reads ``data`` and returns rows. It does not touch
    the network, the disk, or a database.

    The title line ``Injury Report: MM/DD/YY HH:MM AM/PM`` wins. That
    clock is Eastern and is stored as UTC at that minute. Last-Modified
    is a few seconds later (the file write) and would miss a decision
    at the labeled minute, so it is used only when the title is absent.
    An hour-format filename (``05PM``) means 5:30 PM, the same rule as
    the slot map, and is used only when both of the others are absent.

    Args:
        data: The PDF bytes.
        last_modified: Aware instant from the stored Last-Modified
            header. Naive values are ignored.
        filename: ``Injury-Report_....pdf``, used only as a last time source.

    Returns:
        ``ParsedReport`` or ``ParseFailure``. Match on ``tag``.
    """
    try:
        return _parse_pdf(data, last_modified=last_modified, filename=filename)
    except Exception as exc:
        logger.warning("injury report parse failed (%s)", type(exc).__name__)
        report_at, source = _fallback_time(None, last_modified, filename)
        return ParseFailure(tag="failed", error=_short(exc), report_at=report_at, report_at_source=source)


def category_from_reason(reason: str | None) -> str | None:
    """The category prefix of a reason, or None.

    ``Injury/Illness - Left Ankle; Sprain`` returns ``Injury/Illness``.
    ``Rest`` returns ``Rest``. A free-text reason with no known prefix
    returns None. Layout A passes the Category column instead.
    """
    if not reason:
        return None
    for prefix in CATEGORY_PREFIXES:
        if reason == prefix or reason.startswith(prefix + " ") or reason.startswith(prefix + "-"):
            return prefix
    return None


def team_abbreviation(name: str) -> str:
    """PDF team name to its abbreviation. Unknown names return ``""``."""
    cleaned = _clean(name)
    if not cleaned:
        return ""
    return OFFICIAL_TEAM_ABBR.get(cleaned) or _TEAM_BY_FOLD.get(cleaned.casefold(), "")


def _parse_pdf(
    data: bytes,
    *,
    last_modified: datetime | None,
    filename: str | None,
) -> ParseResult:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        producer = ""
        if pdf.metadata:
            producer = str(pdf.metadata.get("Producer") or "")
        pages = [_page_lines(pdf.pages[0], 0)] if pdf.pages else []
        header = _find_header(pages[0] if pages else [])
        if header is None:
            report_at, source = _fallback_time(None, last_modified, filename)
            return ParseFailure(
                tag="failed",
                error="header row not found",
                report_at=report_at,
                report_at_source=source,
            )
        columns = _columns_from_header(header)
        names = {column.name for column in columns}
        if not {"matchup", "team", "player"} <= names:
            report_at, source = _fallback_time(None, last_modified, filename)
            return ParseFailure(
                tag="failed",
                error="header row is missing matchup, team, or player name",
                report_at=report_at,
                report_at_source=source,
            )
        layout = _layout(producer, names)
        title_text = _first_title(pages[0])
        content: list[_Line] = []
        for index, page in enumerate(pdf.pages):
            raw_lines = pages[0] if index == 0 else _page_lines(page, index)
            if index == 0 and title_text is None:
                title_text = _first_title(raw_lines)
            for line_words in raw_lines:
                raw = _raw(line_words)
                if not raw or _is_skippable(raw):
                    continue
                content.append(
                    _Line(
                        page=index,
                        top=float(line_words[0]["top"]),
                        cells=_cells(line_words, columns),
                        raw=raw,
                    )
                )
    title_at = _title_instant(title_text or "")
    report_at, source = _fallback_time(title_at, last_modified, filename)
    if report_at is None or source is None:
        return ParseFailure(tag="failed", error="report time not found")
    rows, joins, unattached = _assemble(content)
    return ParsedReport(
        tag="ok",
        layout=layout,
        report_at=report_at,
        report_at_source=source,
        rows=tuple(rows),
        pagebreak_joins=joins,
        unattached_reasons=unattached,
    )


def _page_lines(page: object, page_index: int) -> list[list[dict[str, object]]]:
    """Group one page's words into lines. ``page_index`` is unused; the caller tracks it."""
    del page_index
    words = page.extract_words(  # type: ignore[attr-defined]
        x_tolerance=_WORD_X_TOLERANCE,
        y_tolerance=_WORD_Y_TOLERANCE,
        keep_blank_chars=True,
    )
    ordered = sorted(words, key=lambda word: (float(word["top"]), float(word["x0"])))
    lines: list[list[dict[str, object]]] = []
    for word in ordered:
        top = float(word["top"])
        if lines and abs(top - float(lines[-1][0]["top"])) <= _LINE_TOP_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda word: float(word["x0"]))
    return lines


def _find_header(lines: list[list[dict[str, object]]]) -> list[dict[str, object]] | None:
    for line in lines:
        raw = _raw(line).casefold()
        if "matchup" in raw and "team" in raw and "player" in raw and "name" in raw:
            return line
    return None


def _first_title(lines: list[list[dict[str, object]]]) -> str | None:
    for line in lines:
        raw = _raw(line)
        if "injury report:" in raw.casefold():
            return raw
    return None


def _columns_from_header(words: list[dict[str, object]]) -> list[_Column]:
    columns: list[_Column] = []
    used: set[str] = set()
    index = 0
    while index < len(words):
        matched = _longest_label(words, index, used)
        if matched is None:
            index += 1
            continue
        key, length = matched
        used.add(key)
        columns.append(_Column(key, float(words[index]["x0"])))
        index += length
    columns.sort(key=lambda column: column.x0)
    return columns


def _longest_label(
    words: list[dict[str, object]], index: int, used: set[str]
) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for length in range(1, 5):
        if index + length > len(words):
            break
        phrase = _clean(" ".join(_word_text(word) for word in words[index : index + length])).casefold()
        for key, aliases in _LABELS:
            if key in used or phrase not in aliases:
                continue
            best = (key, length)
    return best


def _layout(producer: str, names: set[str]) -> ReportLayout:
    """A when the header has both extra columns, else C for GemBox, else B."""
    if "category" in names and "previous_status" in names:
        return ReportLayout.A
    if "gembox" in producer.casefold():
        return ReportLayout.C
    return ReportLayout.B


def _cells(words: list[dict[str, object]], columns: list[_Column]) -> dict[str, str]:
    buckets: dict[str, list[str]] = {column.name: [] for column in columns}
    for word in words:
        text = _word_text(word)
        if not text:
            continue
        name = _column_for(float(word["x0"]), columns)
        if name is None:
            continue
        buckets[name].append(text)
    return {name: _clean(" ".join(parts)) for name, parts in buckets.items()}


def _column_for(x0: float, columns: list[_Column]) -> str | None:
    chosen: str | None = None
    for column in columns:
        if column.x0 - _COLUMN_X_SLACK <= x0:
            chosen = column.name
        else:
            break
    return chosen


def _assemble(lines: list[_Line]) -> tuple[list[InjuryRow], int, int]:
    pending: dict[str, str] = {}
    anchors: list[_Line] = []
    reason_lines: list[_Line] = []
    for line in lines:
        if _is_reason_only(line):
            reason_lines.append(line)
            continue
        if _is_anchor(line):
            anchors.append(_merge_pending(line, pending))
            pending = {}
            continue
        for key in _CARRY_KEYS:
            value = _clean(line.cells.get(key, ""))
            if value and value != "-":
                pending[key] = value

    extras: dict[int, list[_Line]] = {index: [] for index in range(len(anchors))}
    joins = 0
    unattached = 0
    for line in reason_lines:
        same_page = [index for index, anchor in enumerate(anchors) if anchor.page == line.page]
        nearby = [
            index
            for index in same_page
            if abs(anchors[index].top - line.top) <= _REASON_ATTACH_PT
        ]
        if nearby:
            best = min(nearby, key=lambda index: (abs(anchors[index].top - line.top), anchors[index].top))
            extras[best].append(line)
            continue
        above_first = not same_page or line.top < min(anchors[index].top for index in same_page)
        if above_first:
            earlier = [
                index
                for index, anchor in enumerate(anchors)
                if (anchor.page, anchor.top) < (line.page, line.top)
            ]
            if earlier:
                extras[earlier[-1]].append(line)
                joins += 1
                continue
        unattached += 1

    rows: list[InjuryRow] = []
    carry: dict[str, object] = {
        "game_date": None,
        "game_time_et": None,
        "matchup": None,
        "team_name": None,
    }
    for index, anchor in enumerate(anchors):
        row = _row_from(anchor, extras[index], carry)
        if row is None:
            continue
        carry = {
            "game_date": row.game_date,
            "game_time_et": row.game_time_et,
            "matchup": row.matchup,
            "team_name": row.team_name,
        }
        rows.append(row)
    if unattached:
        logger.warning("injury report left %s reason lines unattached", unattached)
    return rows, joins, unattached


def _merge_pending(line: _Line, pending: dict[str, str]) -> _Line:
    if not pending:
        return line
    cells = dict(line.cells)
    for key, value in pending.items():
        if not _clean(cells.get(key, "")) or _clean(cells.get(key, "")) == "-":
            cells[key] = value
    return _Line(page=line.page, top=line.top, cells=cells, raw=line.raw)


def _is_anchor(line: _Line) -> bool:
    if _NYS in line.raw or _ALL in line.raw:
        return True
    player = _clean(line.cells.get("player", ""))
    if player and player != "-":
        return True
    return _clean(line.cells.get("status", "")) in STATUSES


def _is_reason_only(line: _Line) -> bool:
    if _NYS in line.raw or _ALL in line.raw:
        return False
    filled = [
        key
        for key, value in line.cells.items()
        if _clean(value) and _clean(value) != "-"
    ]
    return filled == ["reason"]


def _row_from(anchor: _Line, extra_lines: list[_Line], carry: dict[str, object]) -> InjuryRow | None:
    nys = _NYS in anchor.raw
    all_available = _ALL in anchor.raw
    player = ""
    if not nys and not all_available:
        player = _clean(anchor.cells.get("player", ""))
        if player == "-":
            player = ""
    status: str | None
    if nys or all_available:
        status = None
    else:
        raw_status = _clean(anchor.cells.get("status", ""))
        status = None if raw_status in {"", "-"} else raw_status
    if not player and not nys and not all_available:
        return None

    reason = _joined_reason(anchor, extra_lines, keep=not nys and not all_available)
    column_category = _clean(anchor.cells.get("category", ""))
    if column_category in {"", "-", _NYS, _ALL}:
        column_category = ""
    category = column_category or category_from_reason(reason)
    previous = _clean(anchor.cells.get("previous_status", ""))
    previous_status = None if previous in {"", "-"} else previous

    parsed_date = _parse_game_date(anchor.cells.get("game_date", ""))
    game_date = parsed_date or carry["game_date"]
    game_time = _clean(anchor.cells.get("game_time", ""))
    if game_time == "-":
        game_time = ""
    game_time_et = game_time or carry["game_time_et"]
    matchup = _parse_matchup(anchor.cells.get("matchup", "")) or carry["matchup"]
    team_name = _clean(anchor.cells.get("team", ""))
    if team_name == "-":
        team_name = ""
    team_name = team_name or carry["team_name"]
    if not isinstance(game_date, date) or not isinstance(matchup, str) or not isinstance(team_name, str):
        return None
    if not matchup or not team_name:
        return None
    time_text = game_time_et if isinstance(game_time_et, str) and game_time_et else None
    return InjuryRow(
        game_date=game_date,
        game_time_et=time_text,
        matchup=matchup,
        team_name=team_name,
        team_abbr=team_abbreviation(team_name),
        player_raw=player,
        status=status,
        reason=reason,
        category=category,
        not_yet_submitted=nys,
        all_players_available=all_available,
        previous_status=previous_status,
    )


def _joined_reason(anchor: _Line, extra_lines: list[_Line], *, keep: bool) -> str | None:
    if not keep:
        return None
    parts: list[tuple[int, float, str]] = []
    own = _clean(anchor.cells.get("reason", ""))
    if own and own not in {"-", _NYS} and _ALL not in own:
        parts.append((anchor.page, anchor.top, own))
    for line in extra_lines:
        text = _clean(line.cells.get("reason", "")) or _clean(line.raw)
        if text and text != "-":
            parts.append((line.page, line.top, text))
    parts.sort()
    joined = _clean(" ".join(text for _page, _top, text in parts))
    if joined in {"", "-"}:
        return None
    return joined


def _parse_game_date(text: str) -> date | None:
    match = _GAME_DATE.search(text or "")
    if match is None:
        return None
    month, day, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_matchup(text: str) -> str | None:
    match = _MATCHUP.search(text or "")
    if match is None:
        return None
    return match.group(1)


def _title_instant(text: str) -> datetime | None:
    match = _TITLE.search(text or "")
    if match is None:
        return None
    month, day, year, hour, minute, ampm = match.groups()
    return _eastern_instant(int(year), int(month), int(day), int(hour), int(minute), ampm)


def instant_from_filename(filename: str | None) -> datetime | None:
    """Eastern publish time implied by an injury-report filename.

    ``Injury-Report_2024-01-15_05PM.pdf`` is 5:30 PM: an hour file is
    the HH:30 report. ``Injury-Report_2026-01-14_03_45PM.pdf`` is
    3:45 PM. Returns None when ``filename`` is not that shape.
    Used only when the PDF title and Last-Modified are both missing.
    """
    if not filename:
        return None
    match = _FILENAME.search(filename)
    if match is None:
        return None
    year, month, day, hour, minute, ampm = match.groups()
    minute_value = int(minute) if minute is not None else 30
    return _eastern_instant(int(year), int(month), int(day), int(hour), minute_value, ampm)


def _eastern_instant(year: int, month: int, day: int, hour: int, minute: int, ampm: str) -> datetime | None:
    if year < 100:
        year += 2000
    marker = ampm.upper()
    if marker == "PM" and hour != 12:
        hour += 12
    elif marker == "AM" and hour == 12:
        hour = 0
    try:
        local = datetime(year, month, day, hour, minute, tzinfo=EASTERN)
    except ValueError:
        return None
    return local.astimezone(UTC)


def _fallback_time(
    title_at: datetime | None,
    last_modified: datetime | None,
    filename: str | None,
) -> tuple[datetime | None, str | None]:
    """Title, then Last-Modified, then the filename. The first one wins."""
    if title_at is not None:
        return title_at, "title"
    if last_modified is not None and last_modified.tzinfo is not None:
        return last_modified.astimezone(UTC), "last_modified"
    named = instant_from_filename(filename)
    if named is not None:
        return named, "filename"
    return None, None


def _is_skippable(raw: str) -> bool:
    folded = raw.casefold()
    if "injury report:" in folded:
        return True
    if _PAGE.match(raw.strip()):
        return True
    return "matchup" in folded and "player" in folded and "name" in folded


def _word_text(word: dict[str, object]) -> str:
    return str(word.get("text") or "").strip()


def _raw(words: list[dict[str, object]]) -> str:
    return _clean(" ".join(_word_text(word) for word in words))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _short(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    message = message.replace("\n", " ")
    if len(message) > 500:
        return message[:500]
    return message
