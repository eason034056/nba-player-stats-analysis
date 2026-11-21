"""
test_backfill_writer.py - one BALLDONTLIE games or stats page into the SPO-138 tables.

Pages are the recorded captures in ``fixtures/bdl``. The database tests apply
the shipped migrations to a scratch database (``conftest.py``) and skip when
no Postgres answers.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.backfill.writer import (
    GAME_TYPE_BY_SEASON_TYPE,
    BackfillPageError,
    PageWrite,
    write_games_page,
    write_stats_page,
)
from app.migrations.runner import upgrade
from app.services.bdl_client import SEASON_TYPES
from app.services.bdl_stats import BOX_STATS, SHOOTING_PCTS, normalize_stat_row, parse_minutes
from app.services.game_log_hygiene import CANONICAL_GAME_TYPES

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
GAMES_2000 = "games__season2000_page1.json"
GAMES_2025 = "games__season2025_regular_page1.json"
STATS_2000 = "stats__season2000_page1.json"
STATS_2025 = "stats__season2025_page1.json"
SCORE_LINE = tuple(
    f"{side}_{part}"
    for side in ("home", "visitor")
    for part in ("q1", "q2", "q3", "q4", "ot1", "ot2", "ot3")
)


def _page(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text())["response"]


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    await upgrade(scratch_conn)
    return scratch_conn


async def _write(
    conn: asyncpg.Connection,
    name: str,
    season: int,
    season_type: str,
    games: list[dict[str, Any]] | None = None,
) -> PageWrite:
    page = _page(name)
    return await write_games_page(
        conn,
        league="nba",
        season=season,
        season_type=season_type,
        games=page["data"] if games is None else games,
        next_cursor=page["meta"].get("next_cursor"),
    )


async def _count(conn: asyncpg.Connection, table: str) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {table}")


async def _counters(conn: asyncpg.Connection, data_type: str) -> tuple[int, int, int]:
    """``rows_fetched``, ``rows_dropped``, ``rows_rejected`` of the one checkpoint for ``data_type``."""
    row = await conn.fetchrow(
        "SELECT rows_fetched, rows_dropped, rows_rejected FROM bdl_backfill_checkpoints WHERE data_type = $1",
        data_type,
    )
    return tuple(row)


def test_every_requested_type_translates_to_one_product_type() -> None:
    """The client's season types, the writer's translation, and the games CHECK name the same four types."""
    assert set(GAME_TYPE_BY_SEASON_TYPE) == set(SEASON_TYPES)
    assert sorted(GAME_TYPE_BY_SEASON_TYPE.values()) == sorted(CANONICAL_GAME_TYPES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("season_type", "game_type"),
    [
        ("regular", "regular_season"),
        ("playoffs", "playoffs"),
        ("playin", "play_in"),
        ("ist", "cup_championship"),
    ],
)
async def test_games_are_stored_under_the_product_type(
    db: asyncpg.Connection, season_type: str, game_type: str
) -> None:
    name = f"games__season2025_{season_type}_page1.json"
    result = await _write(db, name, 2025, season_type)

    rows = await db.fetch("SELECT bdl_game_id, season_type FROM games")
    assert {row["bdl_game_id"] for row in rows} == {game["id"] for game in _page(name)["data"]}
    assert {row["season_type"] for row in rows} == {game_type}
    assert result == PageWrite(written=len(rows), shard_rows=len(rows))


@pytest.mark.asyncio
async def test_a_game_keeps_the_recorded_values(db: asyncpg.Connection) -> None:
    """The first 2025-26 game went to double overtime. Every stored column comes from the capture."""
    game = _page("games__season2025_regular_page1.json")["data"][0]
    await _write(db, "games__season2025_regular_page1.json", 2025, "regular")

    row = await db.fetchrow("SELECT * FROM games WHERE bdl_game_id = $1", game["id"])
    assert (row["league"], row["season"]) == ("nba", 2025)
    assert row["date"] == date.fromisoformat(game["date"])
    assert row["datetime_utc"] == datetime.fromisoformat(game["datetime"])
    assert (row["home_team_id"], row["visitor_team_id"]) == (game["home_team"]["id"], game["visitor_team"]["id"])
    assert (row["home_score"], row["visitor_score"]) == (game["home_team_score"], game["visitor_team_score"])
    copied = ("status", "status_state", "postponed", "period", "ist_stage", *SCORE_LINE)
    assert {name: row[name] for name in copied} == {name: game[name] for name in copied}
    assert row["home_ot2"] is not None


@pytest.mark.asyncio
async def test_teams_and_the_season_come_from_the_page(db: asyncpg.Connection) -> None:
    """Teams are the nested home and visitor objects. 100 games name each team many times."""
    games = _page("games__season2000_page1.json")["data"]
    await _write(db, "games__season2000_page1.json", 2000, "regular")

    nested = {team["id"]: team for game in games for team in (game["home_team"], game["visitor_team"])}
    fields = ("abbreviation", "name", "full_name", "city", "conference", "division")
    stored = {
        row["bdl_team_id"]: {field: row[field] for field in fields}
        for row in await db.fetch("SELECT * FROM teams WHERE league = 'nba'")
    }
    assert stored == {team_id: {field: team[field] for field in fields} for team_id, team in nested.items()}
    assert await db.fetchval(
        "SELECT label FROM seasons WHERE league = 'nba' AND season_start_year = 2000"
    ) == "2000-01"


@pytest.mark.asyncio
async def test_the_checkpoint_points_past_the_page(db: asyncpg.Connection) -> None:
    """The cursor is BALLDONTLIE's, so the shard is named by the season_type the page was requested with."""
    page = _page("games__season2025_regular_page1.json")
    await _write(db, "games__season2025_regular_page1.json", 2025, "regular")

    checkpoint = await db.fetchrow("SELECT * FROM bdl_backfill_checkpoints")
    assert (checkpoint["league"], checkpoint["data_type"], checkpoint["season"], checkpoint["shard_key"]) == (
        "nba", "games", 2025, "regular",
    )
    assert checkpoint["cursor"] == str(page["meta"]["next_cursor"])
    assert (checkpoint["status"], checkpoint["rows_written"], checkpoint["pages_fetched"]) == ("in_progress", 100, 1)
    assert await _counters(db, "games") == (100, 0, 0)


@pytest.mark.asyncio
async def test_a_second_page_moves_the_cursor_and_counts_the_whole_shard(db: asyncpg.Connection) -> None:
    """The recorded page is split in two, so the shard has two pages and the second one is the last."""
    page = _page("games__season2025_regular_page1.json")
    first, second = page["data"][:40], page["data"][40:]
    for games, next_cursor in ((first, page["meta"]["next_cursor"]), (second, None)):
        result = await write_games_page(
            db, league="nba", season=2025, season_type="regular", games=games, next_cursor=next_cursor
        )

    assert result == PageWrite(written=60, shard_rows=100)
    checkpoint = await db.fetchrow("SELECT cursor, rows_written, pages_fetched FROM bdl_backfill_checkpoints")
    assert tuple(checkpoint) == (None, 100, 2)
    assert await _counters(db, "games") == (100, 0, 0)


@pytest.mark.asyncio
async def test_the_last_page_leaves_no_cursor(db: asyncpg.Connection) -> None:
    """The 2025-26 play-in fits on one page. ``done`` is the walker's call, after the season is verified."""
    await _write(db, "games__season2025_playin_page1.json", 2025, "playin")

    checkpoint = await db.fetchrow("SELECT cursor, status FROM bdl_backfill_checkpoints")
    assert (checkpoint["cursor"], checkpoint["status"]) == (None, "in_progress")


@pytest.mark.asyncio
async def test_an_empty_page_records_the_shard_and_nothing_else(db: asyncpg.Connection) -> None:
    """A season with no games of a type still gets a checkpoint, so a resumed walk does not ask again."""
    result = await _write(db, "games__season1900_empty.json", 1900, "regular")

    assert result == PageWrite(written=0, shard_rows=0)
    for table in ("seasons", "teams", "games"):
        assert await _count(db, table) == 0
    checkpoint = await db.fetchrow("SELECT cursor, rows_written, pages_fetched FROM bdl_backfill_checkpoints")
    assert tuple(checkpoint) == (None, 0, 1)
    assert await _counters(db, "games") == (0, 0, 0)


@pytest.mark.asyncio
async def test_replaying_a_page_adds_no_rows(db: asyncpg.Connection) -> None:
    """``rows_written`` is set from a count, so a replay cannot double it.

    ``rows_fetched`` counts every fetch, so it does double. A walk never fetches a
    stored page again, and a restart resets the row before it replays one.
    """
    for _ in range(2):
        result = await _write(db, "games__season2025_regular_page1.json", 2025, "regular")

    assert await _count(db, "games") == 100
    assert result.shard_rows == 100
    checkpoint = await db.fetchrow("SELECT rows_written, pages_fetched FROM bdl_backfill_checkpoints")
    assert tuple(checkpoint) == (100, 2)
    assert await _counters(db, "games") == (200, 0, 0)


@pytest.mark.asyncio
async def test_a_page_that_fails_part_way_leaves_nothing(db: asyncpg.Connection) -> None:
    """The bad value reaches the database after the season and teams are written. They roll back with it."""
    games = copy.deepcopy(_page("games__season2025_regular_page1.json")["data"])
    games[-1]["home_q1"] = "not a number"

    with pytest.raises(asyncpg.DataError):
        await _write(db, "games__season2025_regular_page1.json", 2025, "regular", games)
    for table in ("seasons", "teams", "games", "bdl_backfill_checkpoints"):
        assert await _count(db, table) == 0


@pytest.mark.asyncio
async def test_a_game_from_another_season_refuses_the_page(db: asyncpg.Connection) -> None:
    """A game outside the requested season means the filter did not apply. Nothing is written."""
    games = copy.deepcopy(_page("games__season2025_regular_page1.json")["data"])
    games[5]["season"] = 2024

    with pytest.raises(BackfillPageError, match="2024"):
        await _write(db, "games__season2025_regular_page1.json", 2025, "regular", games)
    for table in ("games", "bdl_backfill_checkpoints"):
        assert await _count(db, table) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("season_type", ["preseason", "regular_season"])
async def test_a_type_the_client_does_not_request_refuses_the_page(
    db: asyncpg.Connection, season_type: str
) -> None:
    """``regular_season`` is the product name. The walker passes BALLDONTLIE's name, the one it requested."""
    with pytest.raises(BackfillPageError):
        await _write(db, "games__season2025_regular_page1.json", 2025, season_type)
    assert await _count(db, "bdl_backfill_checkpoints") == 0


# ---------------------------------------------------------------------------
# Stats pages
# ---------------------------------------------------------------------------


async def _write_stats(
    conn: asyncpg.Connection, name: str, season: int, rows: list[dict[str, Any]] | None = None
) -> PageWrite:
    page = _page(name)
    return await write_stats_page(
        conn,
        league="nba",
        season=season,
        rows=page["data"] if rows is None else rows,
        next_cursor=page["meta"].get("next_cursor"),
    )


def _key(row: dict[str, Any]) -> tuple[int, int]:
    return row["game"]["id"], row["player"]["id"]


@pytest_asyncio.fixture
async def games_2025(db: asyncpg.Connection) -> asyncpg.Connection:
    """Every game the recorded 2025-26 stats page names is on the recorded games page."""
    await _write(db, GAMES_2025, 2025, "regular")
    return db


@pytest_asyncio.fixture
async def games_2000(db: asyncpg.Connection) -> asyncpg.Connection:
    await _write(db, GAMES_2000, 2000, "regular")
    return db


async def _stored_stats(conn: asyncpg.Connection) -> dict[tuple[int, int], asyncpg.Record]:
    rows = await conn.fetch("SELECT * FROM player_game_stats")
    return {(row["bdl_game_id"], row["bdl_player_id"]): row for row in rows}


@pytest.mark.asyncio
async def test_each_line_is_stored_with_its_game(games_2025: asyncpg.Connection) -> None:
    rows = _page(STATS_2025)["data"]
    result = await _write_stats(games_2025, STATS_2025, 2025)

    stored = await _stored_stats(games_2025)
    assert set(stored) == {_key(row) for row in rows}
    assert {
        _key(row): (stored[_key(row)]["bdl_stat_id"], stored[_key(row)]["season"], stored[_key(row)]["date"])
        for row in rows
    } == {_key(row): (row["id"], row["game"]["season"], date.fromisoformat(row["game"]["date"])) for row in rows}
    assert result == PageWrite(written=100, shard_rows=100)


@pytest.mark.asyncio
async def test_a_played_line_keeps_the_recorded_values(games_2025: asyncpg.Connection) -> None:
    """The team is the one that played the game. ``player.team_id`` is the player's team today."""
    row = next(
        row for row in _page(STATS_2025)["data"]
        if row["team"]["id"] != row["player"]["team_id"] and not normalize_stat_row(row).dnp
    )
    await _write_stats(games_2025, STATS_2025, 2025)

    stored = (await _stored_stats(games_2025))[_key(row)]
    assert (stored["bdl_team_id"], stored["dnp"]) == (row["team"]["id"], False)
    assert (stored["min_raw"], stored["seconds_played"]) == (row["min"], parse_minutes(row["min"]))
    counted = (*BOX_STATS, "plus_minus")
    assert {name: stored[name] for name in counted} == {name: row[name] for name in counted}
    assert {
        name: None if stored[name] is None else float(stored[name]) for name in SHOOTING_PCTS
    } == {name: row[name] for name in SHOOTING_PCTS}


@pytest.mark.asyncio
async def test_did_not_play_lines_are_stored_without_a_line(games_2025: asyncpg.Connection) -> None:
    """2025-26 sends DNP as ``min: "00"`` with zeros. The row keeps the raw minutes and no stats."""
    rows = _page(STATS_2025)["data"]
    expected = {_key(row): row["min"] for row in rows if normalize_stat_row(row).dnp}
    await _write_stats(games_2025, STATS_2025, 2025)

    stored = await _stored_stats(games_2025)
    assert {key: row["min_raw"] for key, row in stored.items() if row["dnp"]} == expected
    assert all(
        stored[key][name] is None for key in expected for name in (*BOX_STATS, *SHOOTING_PCTS, "plus_minus")
    )


@pytest.mark.asyncio
async def test_players_come_from_the_lines(games_2000: asyncpg.Connection) -> None:
    """Some 2000-01 players appear twice on one page. Each is one players row."""
    rows = _page(STATS_2000)["data"]
    await _write_stats(games_2000, STATS_2000, 2000)

    nested = {row["player"]["id"]: row["player"] for row in rows}
    assert len(nested) < len(rows)
    stored = {
        row["bdl_player_id"]: tuple(row)[2:]
        for row in await games_2000.fetch(
            "SELECT league, bdl_player_id, first_name, last_name, display_name, position FROM players"
        )
    }
    assert stored == {
        player_id: (p["first_name"], p["last_name"], f"{p['first_name']} {p['last_name']}", p["position"])
        for player_id, p in nested.items()
    }


@pytest.mark.asyncio
async def test_a_line_whose_game_is_not_stored_is_dropped_and_counted(db: asyncpg.Connection) -> None:
    rows = _page(STATS_2025)["data"]
    missing = rows[0]["game"]["id"]
    await _write(db, GAMES_2025, 2025, "regular", [g for g in _page(GAMES_2025)["data"] if g["id"] != missing])

    result = await _write_stats(db, STATS_2025, 2025)

    kept = [row for row in rows if row["game"]["id"] != missing]
    assert result == PageWrite(written=len(kept), shard_rows=len(kept), dropped=len(rows) - len(kept))
    assert set(await _stored_stats(db)) == {_key(row) for row in kept}
    assert await db.fetchval("SELECT count(*) FROM players") == len({row["player"]["id"] for row in kept})
    assert await _counters(db, "stats") == (len(rows), len(rows) - len(kept), 0)


@pytest.mark.asyncio
async def test_a_row_the_normalizer_refuses_is_skipped_and_counted(games_2025: asyncpg.Connection) -> None:
    rows = copy.deepcopy(_page(STATS_2025)["data"])
    rows[3]["min"] = "3 minutes"

    result = await _write_stats(games_2025, STATS_2025, 2025, rows)

    assert result == PageWrite(written=99, shard_rows=99, rejected=1)
    assert await _counters(games_2025, "stats") == (100, 0, 1)
    assert _key(rows[3]) not in await _stored_stats(games_2025)


@pytest.mark.asyncio
async def test_the_stats_checkpoint_points_past_the_page(games_2025: asyncpg.Connection) -> None:
    """A stats walk is one shard per season."""
    page = _page(STATS_2025)
    await _write_stats(games_2025, STATS_2025, 2025)

    checkpoint = await games_2025.fetchrow("SELECT * FROM bdl_backfill_checkpoints WHERE data_type = 'stats'")
    assert (checkpoint["league"], checkpoint["season"], checkpoint["shard_key"]) == ("nba", 2025, "")
    assert checkpoint["cursor"] == str(page["meta"]["next_cursor"])
    assert (checkpoint["status"], checkpoint["rows_written"], checkpoint["pages_fetched"]) == ("in_progress", 100, 1)
    assert await _counters(games_2025, "stats") == (100, 0, 0)


@pytest.mark.asyncio
async def test_replaying_a_stats_page_adds_no_rows(games_2025: asyncpg.Connection) -> None:
    for _ in range(2):
        await _write_stats(games_2025, STATS_2025, 2025)

    assert await _count(games_2025, "player_game_stats") == 100
    checkpoint = await games_2025.fetchrow(
        "SELECT rows_written, pages_fetched FROM bdl_backfill_checkpoints WHERE data_type = 'stats'"
    )
    assert tuple(checkpoint) == (100, 2)
    assert await _counters(games_2025, "stats") == (200, 0, 0)


@pytest.mark.asyncio
async def test_a_second_stats_page_counts_the_whole_season(games_2025: asyncpg.Connection) -> None:
    page = _page(STATS_2025)
    first, second = page["data"][:30], page["data"][30:]
    for rows, next_cursor in ((first, page["meta"]["next_cursor"]), (second, None)):
        result = await write_stats_page(games_2025, league="nba", season=2025, rows=rows, next_cursor=next_cursor)

    assert result == PageWrite(written=70, shard_rows=100)
    checkpoint = await games_2025.fetchrow(
        "SELECT cursor, rows_written, pages_fetched FROM bdl_backfill_checkpoints WHERE data_type = 'stats'"
    )
    assert tuple(checkpoint) == (None, 100, 2)
    assert await _counters(games_2025, "stats") == (100, 0, 0)


@pytest.mark.asyncio
async def test_a_stats_row_from_another_season_refuses_the_page(games_2025: asyncpg.Connection) -> None:
    rows = copy.deepcopy(_page(STATS_2025)["data"])
    rows[7]["game"]["season"] = 2024

    with pytest.raises(BackfillPageError, match="2024"):
        await _write_stats(games_2025, STATS_2025, 2025, rows)
    assert await _count(games_2025, "player_game_stats") == 0


@pytest.mark.asyncio
async def test_a_stats_page_that_fails_part_way_leaves_nothing(games_2025: asyncpg.Connection) -> None:
    """A team that is not stored fails the stats insert after the players are written. They roll back with it."""
    rows = copy.deepcopy(_page(STATS_2025)["data"])
    rows[-1]["team"]["id"] = 99_999

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await _write_stats(games_2025, STATS_2025, 2025, rows)
    for table in ("players", "player_game_stats"):
        assert await _count(games_2025, table) == 0
    assert await games_2025.fetchval(
        "SELECT count(*) FROM bdl_backfill_checkpoints WHERE data_type = 'stats'"
    ) == 0


@pytest.mark.asyncio
async def test_the_counters_add_up_across_pages(db: asyncpg.Connection) -> None:
    """The middle row's game is not stored, and its lines fall on both halves. One line on each half is refused."""
    page = _page(STATS_2025)
    rows = copy.deepcopy(page["data"])
    missing = rows[50]["game"]["id"]
    await _write(db, GAMES_2025, 2025, "regular", [g for g in _page(GAMES_2025)["data"] if g["id"] != missing])
    first, second = rows[:50], rows[50:]
    for half in (first, second):
        assert {row["game"]["id"] == missing for row in half} == {True, False}
        next(row for row in half if row["game"]["id"] != missing)["min"] = "3 minutes"

    for half, next_cursor in ((first, page["meta"]["next_cursor"]), (second, None)):
        await write_stats_page(db, league="nba", season=2025, rows=half, next_cursor=next_cursor)

    dropped = sum(1 for row in rows if row["game"]["id"] == missing)
    assert await _counters(db, "stats") == (len(rows), dropped, 2)
    assert await _count(db, "player_game_stats") == len(rows) - dropped - 2
