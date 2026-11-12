"""US slate date.

The game date on lineups, daily picks, and the events list is the calendar
date in America/New_York. UTC midnight is still the previous evening in
the US, so a UTC ``today`` string fetches the next slate. Real timestamps
(fetched_at, snapshot_at) stay in UTC and do not use this module.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# US slate clock. odds_line_snapshots.date and the lineup/picks date
# query params are the Eastern game date.
NBA_SLATE_TZ = ZoneInfo("America/New_York")


def nba_slate_date(now: datetime | None = None) -> tuple[str, int]:
    """US game date and the Eastern UTC offset in minutes at ``now``.

    ``now`` defaults to the current UTC time. A naive datetime is read as
    UTC. The returned date is the calendar date in America/New_York. The
    offset is minutes east of UTC, so Eastern Standard Time is -300 and
    Eastern Daylight Time is -240. ``take_snapshot`` uses both so the
    events query covers that Eastern day. Callers that only need the
    date string use ``nba_slate_date()[0]``.

    Args:
        now: Instant to convert. None means the current time.

    Returns:
        ``(YYYY-MM-DD, offset_minutes)``.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    eastern = moment.astimezone(NBA_SLATE_TZ)
    offset = eastern.utcoffset()
    if offset is None:
        raise RuntimeError("America/New_York did not provide a UTC offset")
    return eastern.date().isoformat(), int(offset.total_seconds() // 60)


def offset_for_us_game_date(date: str) -> int:
    """Eastern offset in minutes at noon on a US game date.

    Noon is after the 02:00 DST transition, which is when NBA games are
    played. A date string is not itself a timezone. This picks the offset
    that ``_get_events`` needs to turn that Eastern date into a UTC window.

    Args:
        date: ``YYYY-MM-DD`` US game date.

    Returns:
        Minutes east of UTC. -300 in January, -240 in July.
    """
    day = datetime.strptime(date, "%Y-%m-%d").date()
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=NBA_SLATE_TZ)
    _slate_date, offset = nba_slate_date(noon)
    return offset
