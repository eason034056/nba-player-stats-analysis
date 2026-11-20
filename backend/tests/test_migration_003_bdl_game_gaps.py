"""
test_migration_003_bdl_game_gaps.py - BALLDONTLIE's broken games are listed and left out of player_game_log.

Games are stored with the real writer from recorded captures: game 18446820
from the 2025-26 pages, whose lines add up, and single games fetched by id
whose BALLDONTLIE data does not (``explore_bdl_backfill.py --game-id``).
The database tests apply the shipped migrations to a scratch database
(``conftest.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.backfill.writer import write_games_page, write_stats_page
from app.migrations.runner import upgrade

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
GOOD_GAME = 18446820  # final, 2025-26: both teams' lines add to the score and to 240 minutes
MINUTES_WRONG = 19052  # 2006-07: points match, Denver's minutes add to 54.8
FOUR_OVERTIMES = 48851  # the score stops after the third overtime
LINE_LEFT_OUT = 434  # 2018-19: Atlanta 4 points short


def _response_data(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text())["response"]["data"]


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    await upgrade(scratch_conn)
    return scratch_conn


async def _store(
    conn: asyncpg.Connection, season: int, game: dict[str, Any], rows: list[dict[str, Any]]
) -> None:
    await write_games_page(conn, league="nba", season=season, season_type="regular", games=[game], next_cursor=None)
    await write_stats_page(conn, league="nba", season=season, rows=rows, next_cursor=None)


async def _store_good_game(conn: asyncpg.Connection) -> None:
    game = next(g for g in _response_data("games__season2025_regular_page1.json") if g["id"] == GOOD_GAME)
    rows = [row for row in _response_data("stats__season2025_page1.json") if row["game"]["id"] == GOOD_GAME]
    await _store(conn, 2025, game, rows)


def _captured_rows(game_id: int) -> list[dict[str, Any]]:
    return _response_data(f"stats__game{game_id}_page1.json")


async def _store_captured(conn: asyncpg.Connection, game_id: int, rows: list[dict[str, Any]] | None = None) -> None:
    game = _response_data(f"games__game{game_id}_record.json")
    await _store(conn, game["season"], game, _captured_rows(game_id) if rows is None else rows)


async def _games_in_log(conn: asyncpg.Connection) -> set[int]:
    return {row["bdl_game_id"] for row in await conn.fetch("SELECT DISTINCT bdl_game_id FROM player_game_log")}


@pytest.mark.asyncio
async def test_games_whose_lines_do_not_add_up_are_listed(db: asyncpg.Connection) -> None:
    await _store_good_game(db)
    for game_id in (MINUTES_WRONG, FOUR_OVERTIMES, LINE_LEFT_OUT):
        await _store_captured(db, game_id)

    listed = await db.fetch(
        "SELECT bdl_game_id, season, points_off, minutes_short FROM bdl_games_with_gaps ORDER BY bdl_game_id"
    )

    assert [tuple(row) for row in listed] == [
        (LINE_LEFT_OUT, 2018, True, False),
        (MINUTES_WRONG, 2006, False, True),
        (FOUR_OVERTIMES, 2018, True, False),
    ]


@pytest.mark.asyncio
async def test_player_game_log_leaves_out_every_line_of_a_listed_game(db: asyncpg.Connection) -> None:
    """The lines stay in player_game_stats as sent; only the reader view leaves the game out."""
    await _store_good_game(db)
    await _store_captured(db, FOUR_OVERTIMES)

    stored = await db.fetchval("SELECT count(*) FROM player_game_stats WHERE bdl_game_id = $1", FOUR_OVERTIMES)
    good_lines = await db.fetchval("SELECT count(*) FROM player_game_log WHERE bdl_game_id = $1", GOOD_GAME)

    assert await _games_in_log(db) == {GOOD_GAME}
    assert stored == len(_captured_rows(FOUR_OVERTIMES))
    assert good_lines == await db.fetchval(
        "SELECT count(*) FROM player_game_stats WHERE bdl_game_id = $1", GOOD_GAME
    )


@pytest.mark.asyncio
async def test_a_game_balldontlie_corrects_comes_back_after_a_re_walk(db: asyncpg.Connection) -> None:
    """Nothing is kept on the side: the list is computed from the stored lines."""
    await _store_captured(db, MINUTES_WRONG)
    corrected = _captured_rows(MINUTES_WRONG)
    for row in corrected:
        row["min"] = "20"  # 12 lines a team, 240 minutes each

    await _store_captured(db, MINUTES_WRONG, corrected)

    assert await db.fetchval("SELECT count(*) FROM bdl_games_with_gaps") == 0
    assert await _games_in_log(db) == {MINUTES_WRONG}
