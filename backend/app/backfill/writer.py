"""
writer.py - store one BALLDONTLIE page and move its checkpoint in one transaction.

The walker fetches a page and hands its rows here. The rows and the
checkpoint that points past them commit together, so a crash leaves both or
neither: a resumed walk never skips a page, and every insert is an upsert on
the natural key, so a replayed page adds no rows.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

import asyncpg

from app.services.bdl_stats import BOX_STATS, SHOOTING_PCTS, BdlStatRowError, normalize_stat_row
from app.services.game_log_hygiene import (
    GAME_TYPE_CUP,
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_REGULAR,
)

logger = logging.getLogger(__name__)

# BALLDONTLIE's /v1/games season_type (bdl_client.SEASON_TYPES) to the product
# game type the games CHECK allows. The game object does not carry its type,
# so a game is stored under the type its page was requested with.
GAME_TYPE_BY_SEASON_TYPE: Mapping[str, str] = MappingProxyType({
    "regular": GAME_TYPE_REGULAR,
    "playoffs": GAME_TYPE_PLAYOFFS,
    "playin": GAME_TYPE_PLAY_IN,
    "ist": GAME_TYPE_CUP,
})

_SCORE_LINE = tuple(
    f"{side}_{part}"
    for side in ("home", "visitor")
    for part in ("q1", "q2", "q3", "q4", "ot1", "ot2", "ot3")
)
_GAME_COLUMNS = (
    "league", "bdl_game_id", "season", "date", "datetime_utc", "status", "status_state",
    "postponed", "season_type", "home_team_id", "visitor_team_id", "home_score",
    "visitor_score", *_SCORE_LINE, "period", "ist_stage",
)
_TEAM_FIELDS = ("abbreviation", "name", "full_name", "city", "conference", "division")
_TEAM_COLUMNS = ("league", "bdl_team_id", *_TEAM_FIELDS)
_PLAYER_COLUMNS = ("league", "bdl_player_id", "first_name", "last_name", "display_name", "position")
_LINE_VALUES = ("seconds_played", "dnp", *BOX_STATS, *SHOOTING_PCTS, "plus_minus")
_STAT_COLUMNS = (
    "league", "bdl_stat_id", "bdl_game_id", "bdl_player_id", "bdl_team_id", "season", "date",
    "min_raw", *_LINE_VALUES,
)


def _upsert(table: str, columns: Sequence[str], key: Sequence[str]) -> str:
    placeholders = ", ".join(f"${position}" for position in range(1, len(columns) + 1))
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column not in key)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}"
    )


_UPSERT_GAME = _upsert("games", _GAME_COLUMNS, ("league", "bdl_game_id"))
_UPSERT_TEAM = _upsert("teams", _TEAM_COLUMNS, ("league", "bdl_team_id"))
_UPSERT_PLAYER = _upsert("players", _PLAYER_COLUMNS, ("league", "bdl_player_id"))
_UPSERT_STAT = _upsert("player_game_stats", _STAT_COLUMNS, ("league", "bdl_game_id", "bdl_player_id"))
_STORED_GAME_IDS = """
SELECT bdl_game_id FROM games WHERE league = $1 AND bdl_game_id = ANY($2::bigint[])
"""
_COUNT_SEASON_STATS = """
SELECT count(*) FROM player_game_stats WHERE league = $1 AND season = $2
"""
_INSERT_SEASON = """
INSERT INTO seasons (league, season_start_year, label) VALUES ($1, $2, $3)
ON CONFLICT (league, season_start_year) DO NOTHING
"""
_COUNT_SHARD_GAMES = """
SELECT count(*) FROM games WHERE league = $1 AND season = $2 AND season_type = $3
"""
_UPSERT_CHECKPOINT = """
INSERT INTO bdl_backfill_checkpoints (
    league, data_type, season, shard_key, cursor, status, rows_written, pages_fetched,
    rows_fetched, rows_dropped, rows_rejected
)
VALUES ($1, $2, $3, $4, $5, 'in_progress', $6, 1, $7, $8, $9)
ON CONFLICT (league, data_type, season, shard_key) DO UPDATE SET
    cursor = EXCLUDED.cursor,
    status = 'in_progress',
    rows_written = EXCLUDED.rows_written,
    pages_fetched = bdl_backfill_checkpoints.pages_fetched + 1,
    rows_fetched = bdl_backfill_checkpoints.rows_fetched + EXCLUDED.rows_fetched,
    rows_dropped = bdl_backfill_checkpoints.rows_dropped + EXCLUDED.rows_dropped,
    rows_rejected = bdl_backfill_checkpoints.rows_rejected + EXCLUDED.rows_rejected,
    last_error = NULL,
    updated_at = now()
"""


class BackfillPageError(RuntimeError):
    """A page the writer refuses before any SQL runs.

    The walker records the message as the shard's ``last_error`` and stops
    that shard. Nothing from the page is stored.
    """


@dataclass(frozen=True)
class PageWrite:
    """What one page changed.

    Attributes:
        written: rows from the page that were upserted.
        shard_rows: rows stored for the shard after the page. This is the
            checkpoint's ``rows_written``.
        dropped: stats rows whose game is not in ``games``.
        rejected: stats rows ``normalize_stat_row`` refused.
    """

    written: int
    shard_rows: int
    dropped: int = 0
    rejected: int = 0


def season_label(season: int) -> str:
    """``2000`` is ``"2000-01"`` and ``1999`` is ``"1999-00"``."""
    return f"{season}-{(season + 1) % 100:02d}"


def _team_row(league: str, team: Mapping[str, Any]) -> tuple[Any, ...]:
    return (league, team["id"], *(team[field] for field in _TEAM_FIELDS))


def _parse_game(
    league: str, season: int, game_type: str, game: Mapping[str, Any]
) -> tuple[tuple[Any, ...], list[tuple[Any, ...]]]:
    """One ``/v1/games`` object as a games row and its two teams rows.

    Values are passed through as BALLDONTLIE sent them; the database checks
    their types. Only the shape is checked here.
    """
    try:
        game_season = game["season"]
        home, visitor = game["home_team"], game["visitor_team"]
        raw_datetime = game["datetime"]
        row = (
            league,
            game["id"],
            game_season,
            date.fromisoformat(game["date"]),
            datetime.fromisoformat(raw_datetime) if raw_datetime is not None else None,
            game["status"],
            game["status_state"],
            game["postponed"],
            game_type,
            home["id"],
            visitor["id"],
            game["home_team_score"],
            game["visitor_team_score"],
            *(game[column] for column in _SCORE_LINE),
            game["period"],
            game["ist_stage"],
        )
        teams = [_team_row(league, home), _team_row(league, visitor)]
    except (KeyError, TypeError, ValueError) as exc:
        raise BackfillPageError(f"game {game.get('id')!r} cannot be read: {exc!r}") from exc
    if game_season != season:
        raise BackfillPageError(
            f"game {game['id']} is season {game_season}, but the page was requested for {season}"
        )
    return row, teams


async def write_games_page(
    conn: asyncpg.Connection,
    *,
    league: str,
    season: int,
    season_type: str,
    games: Sequence[Mapping[str, Any]],
    next_cursor: int | None,
) -> PageWrite:
    """Upsert one ``/v1/games`` page and point the shard's checkpoint past it.

    The shard is ``(league, "games", season, season_type)``. ``season_type``
    is the BALLDONTLIE value the page was requested with; the games are
    stored under its product game type. Teams come from each game's nested
    ``home_team`` and ``visitor_team``. The checkpoint stays ``in_progress``
    with ``cursor`` set to ``next_cursor`` (``None`` after the last page).
    The walker marks the shard ``done`` once the season is verified.

    Raises:
        BackfillPageError: before any SQL, when ``season_type`` is not one
            the client requests, a game cannot be read, or a game belongs to
            another season.
        asyncpg.PostgresError: a value the database refuses. The page and its
            checkpoint roll back together.
    """
    game_type = GAME_TYPE_BY_SEASON_TYPE.get(season_type)
    if game_type is None:
        raise BackfillPageError(
            f"season_type {season_type!r} is not one of {tuple(GAME_TYPE_BY_SEASON_TYPE)}"
        )
    game_rows: list[tuple[Any, ...]] = []
    team_rows: dict[int, tuple[Any, ...]] = {}
    for game in games:
        row, teams = _parse_game(league, season, game_type, game)
        game_rows.append(row)
        team_rows.update((team[1], team) for team in teams)

    async with conn.transaction():
        if game_rows:
            await conn.execute(_INSERT_SEASON, league, season, season_label(season))
            await conn.executemany(_UPSERT_TEAM, list(team_rows.values()))
            await conn.executemany(_UPSERT_GAME, game_rows)
        shard_rows = await conn.fetchval(_COUNT_SHARD_GAMES, league, season, game_type)
        result = PageWrite(written=len(game_rows), shard_rows=shard_rows)
        await _move_checkpoint(conn, league, "games", season, season_type, next_cursor, len(games), result)
    return result


async def _move_checkpoint(
    conn: asyncpg.Connection,
    league: str,
    data_type: str,
    season: int,
    shard_key: str,
    next_cursor: int | None,
    fetched: int,
    result: PageWrite,
) -> None:
    cursor = None if next_cursor is None else str(next_cursor)
    await conn.execute(
        _UPSERT_CHECKPOINT,
        league,
        data_type,
        season,
        shard_key,
        cursor,
        result.shard_rows,
        fetched,
        result.dropped,
        result.rejected,
    )


@dataclass(frozen=True)
class _StatLine:
    game_id: int
    season: int
    stat_row: tuple[Any, ...]
    player_row: tuple[Any, ...]


def _parse_stat(league: str, row: Mapping[str, Any]) -> _StatLine:
    """One ``/v1/stats`` row as a player_game_stats row and its players row.

    Raises:
        BdlStatRowError: the row cannot be normalized or read. The caller
            skips and counts it.
    """
    line = normalize_stat_row(row)
    try:
        game, player = row["game"], row["player"]
        game_season = game["season"]
        game_date = date.fromisoformat(game["date"])
        first_name, last_name = player["first_name"], player["last_name"]
        display_name = " ".join(part for part in (first_name, last_name) if part)
        player_row = (league, line.player_id, first_name, last_name, display_name, player["position"])
        raw_minutes = row["min"]
    except (KeyError, TypeError, ValueError) as exc:
        raise BdlStatRowError(f"stats row {row.get('id')!r} cannot be read: {exc!r}") from exc
    stat_row = (
        league, line.stat_id, line.game_id, line.player_id, line.team_id, game_season, game_date,
        raw_minutes, *(getattr(line, name) for name in _LINE_VALUES),
    )
    return _StatLine(line.game_id, game_season, stat_row, player_row)


async def write_stats_page(
    conn: asyncpg.Connection,
    *,
    league: str,
    season: int,
    rows: Sequence[Mapping[str, Any]],
    next_cursor: int | None,
) -> PageWrite:
    """Upsert one ``/v1/stats`` page and point the season's checkpoint past it.

    The shard is ``(league, "stats", season, "")``. Each row goes through
    ``normalize_stat_row``; a row it refuses is skipped and counted, so one
    bad line does not stop a season. ``season`` and ``date`` come from the
    row's nested game. A line whose game is not in ``games`` is dropped and
    counted, because its foreign key would fail the whole page; with every
    game type stored, any drop is unexpected. Players come from each kept
    row's nested ``player``. The page's games and teams must already be
    stored by ``write_games_page``.

    Raises:
        BackfillPageError: before any SQL, when a row's game belongs to
            another season.
        asyncpg.PostgresError: a value the database refuses, such as a team
            that is not stored. The page and its checkpoint roll back together.
    """
    lines: list[_StatLine] = []
    rejected = 0
    for row in rows:
        try:
            line = _parse_stat(league, row)
        except BdlStatRowError as exc:
            rejected += 1
            logger.warning("bdl_stat_row_rejected season=%s reason=%s", season, exc)
            continue
        if line.season != season:
            raise BackfillPageError(
                f"stats row {row['id']} is for a season {line.season} game, "
                f"but the page was requested for {season}"
            )
        lines.append(line)

    async with conn.transaction():
        requested = sorted({line.game_id for line in lines})
        stored = {record["bdl_game_id"] for record in await conn.fetch(_STORED_GAME_IDS, league, requested)}
        kept = [line for line in lines if line.game_id in stored]
        dropped = len(lines) - len(kept)
        if dropped:
            missing = sorted(set(requested) - stored)
            logger.warning(
                "bdl_stat_rows_dropped season=%s rows=%s missing_game_ids=%s", season, dropped, missing
            )
        if kept:
            players = {line.player_row[1]: line.player_row for line in kept}
            await conn.executemany(_UPSERT_PLAYER, list(players.values()))
            await conn.executemany(_UPSERT_STAT, [line.stat_row for line in kept])
        shard_rows = await conn.fetchval(_COUNT_SEASON_STATS, league, season)
        result = PageWrite(written=len(kept), shard_rows=shard_rows, dropped=dropped, rejected=rejected)
        await _move_checkpoint(conn, league, "stats", season, "", next_cursor, len(rows), result)
    return result
