"""
verify.py - check a walked season before its shards are marked done.

A ``done`` shard is never walked again, so a season is marked done only when
every check that a re-walk could fix passes. Those checks are what the
pipeline controls: each shard walked to its last page, each games type
stored as many games as BALLDONTLIE sent, every stats line stored, dropped,
or rejected exactly once, and no line refused. A refused line is a spelling
``normalize_stat_row`` cannot read yet; it is fixed in code and the season
re-walked.

Gaps in BALLDONTLIE's own data are listed in the report and do not block,
because a re-walk returns the same data: final games with no lines, lines
per game, final games where a team's player points differ from its score,
and final games where a team's minutes add to under 230. A team plays at
least 240 minutes; seasons that send whole minutes round a team's total to
231-239.

The full 2000-01 to 2026-27 walk lists 50 games, and fetching them again by
game id returns the same lines (``stats__game*_page1.json``):

- 30 games in 2005-06 and 2006-07: points match the score, the minutes
  field is wrong (37 points in ``"0"`` minutes).
- 5 games with four overtimes: the game object has ``ot1``-``ot3`` only and
  its score stops tied after the third; the player points are the final.
- 1 game in 2018-19: a team is 4 points short, a line left out.
- 14 games between 2024-02-01 and 2024-03-08: points short, minutes short,
  or both.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.backfill.walker import Shard, season_shards
from app.backfill.writer import GAME_TYPE_BY_SEASON_TYPE

logger = logging.getLogger(__name__)

_ERROR_TEXT_LIMIT = 500
_SHORT_TEAM_SECONDS = 230 * 60
_NOT_WALKED: Mapping[str, Any] = {
    "cursor": None, "pages_fetched": 0, "rows_fetched": 0, "rows_dropped": 0, "rows_rejected": 0,
}

_CHECKPOINTS = """
SELECT data_type, shard_key, cursor, pages_fetched, rows_fetched, rows_dropped, rows_rejected
FROM bdl_backfill_checkpoints
WHERE league = $1 AND season = $2 AND data_type IN ('games', 'stats')
"""
_GAMES_BY_TYPE = """
SELECT season_type, count(*) AS games FROM games
WHERE league = $1 AND season = $2
GROUP BY season_type
"""
_STAT_LINES = """
SELECT count(*) AS lines, count(*) FILTER (WHERE dnp) AS dnp FROM player_game_stats
WHERE league = $1 AND season = $2
"""
_FINAL_GAMES_WITHOUT_STATS = """
SELECT g.bdl_game_id FROM games g
WHERE g.league = $1 AND g.season = $2 AND g.status_state = 'final'
  AND NOT EXISTS (
      SELECT 1 FROM player_game_stats s
      WHERE s.league = g.league AND s.bdl_game_id = g.bdl_game_id
  )
ORDER BY g.bdl_game_id
"""
_LINES_PER_FINAL_GAME = """
SELECT min(lines) AS fewest, max(lines) AS most FROM (
    SELECT count(*) AS lines FROM player_game_stats s
    JOIN games g ON g.league = s.league AND g.bdl_game_id = s.bdl_game_id
    WHERE s.league = $1 AND s.season = $2 AND g.status_state = 'final'
    GROUP BY s.bdl_game_id
) per_game
"""
_TEAM_TOTALS = """
SELECT bdl_game_id,
       coalesce(home_points, 0) <> home_score OR coalesce(visitor_points, 0) <> visitor_score AS points_off,
       least(coalesce(home_seconds, 0), coalesce(visitor_seconds, 0)) < $3 AS minutes_short
FROM (
    SELECT g.bdl_game_id, g.home_score, g.visitor_score,
           sum(s.pts) FILTER (WHERE s.bdl_team_id = g.home_team_id) AS home_points,
           sum(s.pts) FILTER (WHERE s.bdl_team_id = g.visitor_team_id) AS visitor_points,
           sum(s.seconds_played) FILTER (WHERE s.bdl_team_id = g.home_team_id) AS home_seconds,
           sum(s.seconds_played) FILTER (WHERE s.bdl_team_id = g.visitor_team_id) AS visitor_seconds
    FROM games g
    JOIN player_game_stats s ON s.league = g.league AND s.bdl_game_id = g.bdl_game_id
    WHERE g.league = $1 AND g.season = $2 AND g.status_state = 'final'
    GROUP BY g.bdl_game_id, g.home_score, g.visitor_score
) per_game
ORDER BY bdl_game_id
"""
_MARK_DONE = """
UPDATE bdl_backfill_checkpoints SET status = 'done', last_error = NULL, updated_at = now()
WHERE league = $1 AND season = $2 AND data_type IN ('games', 'stats')
"""
_MARK_FAILED = """
UPDATE bdl_backfill_checkpoints SET status = 'error', last_error = $5, updated_at = now()
WHERE league = $1 AND data_type = $2 AND season = $3 AND shard_key = $4
"""


@dataclass(frozen=True)
class Problem:
    """A check that blocks ``done``, on the shard a re-walk would fix."""

    shard: Shard
    message: str


@dataclass(frozen=True)
class SeasonReport:
    """One season's verification.

    Attributes:
        problems: checks that failed. Any problem keeps the season from ``done``.
        games_by_type: games stored per product game type.
        stat_rows: stats lines stored for the season.
        dnp_rows: of those, did-not-play lines.
        rejected_rows: lines ``normalize_stat_row`` refused. Any blocks ``done``.
        final_games_without_stats: final games with no stored line. Listed,
            not blocking.
        stat_rows_per_final_game: fewest and most lines over final games that
            have lines, or ``None`` when none has.
        final_games_points_off_score: final games with lines where a team's
            player points differ from its score. Listed, not blocking.
        final_games_under_230_minutes: final games with lines where a team's
            minutes add to under 230. Listed, not blocking.
    """

    season: int
    problems: tuple[Problem, ...]
    games_by_type: Mapping[str, int]
    stat_rows: int
    dnp_rows: int
    rejected_rows: int
    final_games_without_stats: tuple[int, ...]
    stat_rows_per_final_game: tuple[int, int] | None
    final_games_points_off_score: tuple[int, ...]
    final_games_under_230_minutes: tuple[int, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


def _walk_problem(shard: Shard, checkpoint: Mapping[str, Any]) -> Problem | None:
    if checkpoint["pages_fetched"] == 0:
        return Problem(shard, "no page stored")
    if checkpoint["cursor"] is not None:
        return Problem(shard, f"not walked to the end; the next page is cursor {checkpoint['cursor']}")
    return None


async def verify_season(conn: asyncpg.Connection, *, league: str, season: int) -> SeasonReport:
    """Check ``season`` against its checkpoints. Reads only."""
    checkpoints = {
        (row["data_type"], row["shard_key"]): row for row in await conn.fetch(_CHECKPOINTS, league, season)
    }
    games_by_type = {row["season_type"]: row["games"] for row in await conn.fetch(_GAMES_BY_TYPE, league, season)}
    stat_lines = await conn.fetchrow(_STAT_LINES, league, season)

    problems: list[Problem] = []
    rejected = 0
    for shard in season_shards(season):
        checkpoint = checkpoints.get((shard.data_type, shard.shard_key), _NOT_WALKED)
        walk_problem = _walk_problem(shard, checkpoint)
        if walk_problem is not None:
            problems.append(walk_problem)
        fetched = checkpoint["rows_fetched"]
        if shard.data_type == "games":
            stored = games_by_type.get(GAME_TYPE_BY_SEASON_TYPE[shard.shard_key], 0)
            if stored != fetched:
                problems.append(Problem(shard, f"{stored} games stored, {fetched} fetched"))
            continue
        dropped, rejected = checkpoint["rows_dropped"], checkpoint["rows_rejected"]
        if dropped:
            problems.append(Problem(shard, f"{dropped} lines dropped because their game is not stored"))
        if rejected:
            problems.append(Problem(shard, f"{rejected} lines refused by normalize_stat_row"))
        if stat_lines["lines"] + dropped + rejected != fetched:
            problems.append(Problem(
                shard,
                f"{stat_lines['lines']} lines stored, {dropped} dropped, {rejected} rejected, {fetched} fetched",
            ))

    without_stats = await conn.fetch(_FINAL_GAMES_WITHOUT_STATS, league, season)
    per_game = await conn.fetchrow(_LINES_PER_FINAL_GAME, league, season)
    team_totals = await conn.fetch(_TEAM_TOTALS, league, season, _SHORT_TEAM_SECONDS)
    return SeasonReport(
        season=season,
        problems=tuple(problems),
        games_by_type=games_by_type,
        stat_rows=stat_lines["lines"],
        dnp_rows=stat_lines["dnp"],
        rejected_rows=rejected,
        final_games_without_stats=tuple(row["bdl_game_id"] for row in without_stats),
        stat_rows_per_final_game=None if per_game["fewest"] is None else (per_game["fewest"], per_game["most"]),
        final_games_points_off_score=tuple(row["bdl_game_id"] for row in team_totals if row["points_off"]),
        final_games_under_230_minutes=tuple(row["bdl_game_id"] for row in team_totals if row["minutes_short"]),
    )


async def finish_season(conn: asyncpg.Connection, *, league: str, season: int) -> SeasonReport:
    """Verify ``season`` and mark its games and stats shards.

    Passed: every shard of the season becomes ``done``. Failed: each shard
    with a problem becomes ``error`` with ``verification: <problems>`` and
    the others keep their status. A failed shard sends no request on the
    next run, because all its pages are stored; ``--restart-season``
    re-walks it.
    """
    async with conn.transaction():
        report = await verify_season(conn, league=league, season=season)
        if report.passed:
            await conn.execute(_MARK_DONE, league, season)
            logger.info("bdl_backfill_season_done season=%s", season)
            return report
        messages: dict[Shard, list[str]] = {}
        for problem in report.problems:
            messages.setdefault(problem.shard, []).append(problem.message)
        for shard, texts in messages.items():
            text = f"verification: {'; '.join(texts)}"[:_ERROR_TEXT_LIMIT]
            await conn.execute(_MARK_FAILED, league, shard.data_type, season, shard.shard_key, text)
            logger.warning("bdl_backfill_season_failed season=%s shard=%s %s", season, shard.label, text)
    return report
