"""Read NBA tip times and game days from Postgres.

The backfill uses ``tip_times_for_season``. The scheduler uses
``is_nba_game_day``, which is true when ``games.date`` equals the
Eastern slate date and the game is not postponed. Neither function
calls the NBA CDN.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import asyncpg

from app.services.slate_date import nba_slate_date

logger = logging.getLogger(__name__)

# One row when this Eastern date has a game that is still on the schedule.
GAME_DAY_SQL = """
SELECT 1 AS present
FROM games
WHERE league = 'nba'
  AND date = $1
  AND COALESCE(postponed, false) = false
LIMIT 1
"""

# Tips for one season start year. Null tips and postponed games are dropped.
# 2021 is 2021-22. The caller refuses a year before 2021.
TIPS_SQL = """
SELECT datetime_utc
FROM games
WHERE league = 'nba'
  AND season = $1
  AND datetime_utc IS NOT NULL
  AND COALESCE(postponed, false) = false
ORDER BY datetime_utc, bdl_game_id
"""


async def has_nba_game_on(conn: asyncpg.Connection, on: date) -> bool:
    """True when ``on`` has a non-postponed NBA game.

    Args:
        conn: An open asyncpg connection. The caller owns it.
        on: The Eastern game date, matching ``games.date``.

    Returns:
        True when the query returns a row.
    """
    row = await conn.fetchrow(GAME_DAY_SQL, on)
    return row is not None


async def tip_times_for_season(
    conn: asyncpg.Connection, season_start_year: int
) -> list[datetime]:
    """Aware tip instants for one NBA season.

    Args:
        conn: An open asyncpg connection.
        season_start_year: 2021 means the 2021-22 season.

    Returns:
        ``datetime_utc`` values, oldest first. Games that share a tip
        are repeated. ``slots_for_tips`` collapses them.
    """
    rows = await conn.fetch(TIPS_SQL, season_start_year)
    return [row["datetime_utc"] for row in rows]


async def is_nba_game_day(now: datetime) -> bool:
    """True when the Eastern date of ``now`` has a non-postponed NBA game.

    Uses the process database pool. A pool that is not open is not a
    game day, and this function does not open one. The scheduler then
    skips the CDN.

    Args:
        now: Aware or naive. A naive value is read as UTC, same as
            ``nba_slate_date``.

    Returns:
        True when ``has_nba_game_on`` would be true for today's slate date.
    """
    from app.services.db import db_service

    if not db_service.is_connected:
        logger.info("injury pdf game-day check skipped; database is not connected")
        return False
    slate = date.fromisoformat(nba_slate_date(now)[0])
    row = await db_service.fetchrow(GAME_DAY_SQL, slate)
    return row is not None
