"""Map a decision time to one official NBA injury-report PDF URL.

The public CDN is ``https://ak-static.cms.nba.com/referee/injury/``.
Times in the filename are US Eastern wall-clock times.

Two filename patterns:

- Hour files, through the morning of 2025-12-22. ``HHAM`` / ``HHPM`` is the
  report published at HH:30. ``03PM`` is the 3:30 PM report.
- Minute files, from 2025-12-22 09:00 ET. ``HH_MMAM`` / ``HH_MMPM`` is that
  exact quarter hour. A file stamped at exactly T is a few seconds late,
  so a decision at 4:00 PM uses ``03_45PM``.

``report_slot`` is pure. It does not touch the network or the clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc

# First instant that uses the minute filename. A decision at this instant
# still uses the hour file: the 09:00 file is the first minute-format file
# and, like every file stamped at exactly T, is a few seconds late.
MINUTE_FORMAT_START = datetime(2025, 12, 22, 9, 0, tzinfo=EASTERN)

CDN_BASE = "https://ak-static.cms.nba.com/referee/injury/"

# 2018-19 through 2020-21 are out of scope. 2021 is the 2021-22 season.
EARLIEST_SEASON_START_YEAR = 2021

_SEASON = re.compile(r"(\d{4})(?:-(\d{2}|\d{4}))?")
_HOUR_MARKS = frozenset({30})
_MINUTE_MARKS = frozenset({0, 15, 30, 45})


@dataclass(frozen=True)
class SlotKey:
    """One injury-report file.

    ``instant`` is the report's nominal Eastern publish time (HH:30 for an
    hour file, the quarter hour for a minute file). ``format_name`` is
    ``hour`` or ``minute``. ``filename`` is the CDN object name.
    ``url`` is ``CDN_BASE`` plus that name.

    Call ``report_slot`` to build one. Do not assemble the filename by hand.
    """

    instant: datetime
    format_name: str
    filename: str
    url: str


def _as_eastern(moment: datetime) -> datetime:
    """Eastern wall time of an aware instant.

    A naive datetime is refused. Callers pass ``games.datetime_utc`` or
    ``datetime.now(timezone.utc)``.
    """
    if moment.tzinfo is None:
        raise ValueError("decision time must be timezone-aware")
    return moment.astimezone(EASTERN)


def _latest_mark(moment: datetime, marks: frozenset[int], *, inclusive: bool) -> datetime:
    """Latest Eastern minute in ``marks`` at or before ``moment``.

    ``inclusive`` false steps one microsecond back first, so a decision
    that lands on a mark does not select that mark. The walk is in UTC.
    Subtracting a minute from an Eastern datetime inside the spring-forward
    gap produces a wall clock of 2:30 whose UTC instant is later, not
    earlier. UTC instants do not land on that missing 2:30, and both
    fall-back 1:30s stay distinct.
    """
    cursor = _as_eastern(moment).astimezone(UTC)
    if not inclusive:
        cursor -= timedelta(microseconds=1)
    cursor = cursor.replace(second=0, microsecond=0)
    for _ in range(180):
        local = cursor.astimezone(EASTERN)
        if local.minute in marks:
            return local
        cursor -= timedelta(minutes=1)
    raise RuntimeError("no injury-report slot within 3 hours of the decision time")


def _clock_token(slot: datetime, *, with_minute: bool) -> str:
    """12-hour token. Midnight is ``12AM``. Noon is ``12PM``. Hours are zero-padded."""
    suffix = "AM" if slot.hour < 12 else "PM"
    hour12 = slot.hour % 12 or 12
    if with_minute:
        return f"{hour12:02d}_{slot.minute:02d}{suffix}"
    return f"{hour12:02d}{suffix}"


def report_slot(moment: datetime) -> SlotKey:
    """The injury-report file that is already posted at ``moment``.

    Hour files apply when ``moment`` is at or before
    ``MINUTE_FORMAT_START`` (2025-12-22 09:00 ET). The file is the latest
    HH:30 at or before ``moment``. ``moment`` of 4:00 PM ET is ``03PM``.

    Minute files apply after that instant. The file is the latest
    15-minute mark strictly before ``moment``, because the file stamped
    at exactly ``moment`` is a few seconds late. ``moment`` of 4:00 PM ET
    is ``03_45PM``.

    Args:
        moment: Aware decision time. UTC and Eastern both work.

    Returns:
        The ``SlotKey`` for that file.

    Raises:
        ValueError: ``moment`` has no timezone.
    """
    local = _as_eastern(moment)
    if local <= MINUTE_FORMAT_START:
        slot = _latest_mark(local, _HOUR_MARKS, inclusive=True)
        format_name = "hour"
    else:
        slot = _latest_mark(local, _MINUTE_MARKS, inclusive=False)
        if slot < MINUTE_FORMAT_START:
            slot = _latest_mark(local, _HOUR_MARKS, inclusive=True)
            format_name = "hour"
        else:
            format_name = "minute"
    filename = (
        f"Injury-Report_{slot.strftime('%Y-%m-%d')}_"
        f"{_clock_token(slot, with_minute=format_name == 'minute')}.pdf"
    )
    return SlotKey(
        instant=slot,
        format_name=format_name,
        filename=filename,
        url=f"{CDN_BASE}{filename}",
    )


def decision_time(tip_utc: datetime) -> datetime:
    """T for one tip: ``tip_utc`` minus 3 hours.

    This is the same subtraction as ``game_as_of`` in migration 005
    (``datetime_utc - 3 hours``). A null tip is not passed here. The SQL
    that reads ``games`` drops those rows.

    Args:
        tip_utc: Aware tip instant from ``games.datetime_utc``.

    Returns:
        The aware UTC instant three hours earlier.

    Raises:
        ValueError: ``tip_utc`` has no timezone.
    """
    if tip_utc.tzinfo is None:
        raise ValueError("tip must be timezone-aware")
    return tip_utc.astimezone(UTC) - timedelta(hours=3)


def slots_for_tips(tips: list[datetime] | tuple[datetime, ...]) -> list[SlotKey]:
    """One slot per distinct URL, sorted by URL.

    Several games that tip together share one T and one file. The caller
    fetches the returned list once. Order is the URL so a dry run is stable.

    Args:
        tips: Aware tip instants. Empty is allowed.

    Returns:
        Deduplicated slots, URL order.
    """
    by_url: dict[str, SlotKey] = {}
    for tip in tips:
        slot = report_slot(decision_time(tip))
        by_url.setdefault(slot.url, slot)
    return [by_url[url] for url in sorted(by_url)]


def parse_season_start_year(text: str) -> int:
    """Start year of a season label.

    ``2021-22`` and ``2021`` are both the 2021-22 season. A label whose
    second year is not the next year is refused. A start year before
    ``EARLIEST_SEASON_START_YEAR`` (2021) is refused. 2018-19 through
    2020-21 are out of scope.

    Args:
        text: ``YYYY`` or ``YYYY-YY`` or ``YYYY-YYYY``.

    Returns:
        The season start year, such as 2021.

    Raises:
        ValueError: the text is not a season, or the season is too early.
    """
    match = _SEASON.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"season must look like 2021-22, got {text!r}")
    year = int(match.group(1))
    end = match.group(2)
    if end is not None:
        if len(end) == 2:
            end_year = (year // 100) * 100 + int(end)
            if end_year < year:
                end_year += 100
        else:
            end_year = int(end)
        if end_year != year + 1:
            raise ValueError(f"season span must be one year, got {text!r}")
    if year < EARLIEST_SEASON_START_YEAR:
        raise ValueError(
            f"seasons before {EARLIEST_SEASON_START_YEAR}-"
            f"{(EARLIEST_SEASON_START_YEAR + 1) % 100:02d} are out of scope"
        )
    return year
