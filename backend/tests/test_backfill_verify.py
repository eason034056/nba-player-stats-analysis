"""
test_backfill_verify.py - checking a walked season before its shards are marked done.

The season is stored with the real writer from the recorded 2025-26 pages:
the four games pages and the first stats page, each written as the last page
of its shard. The upstream-gap tests store single games captured by game id
(``explore_bdl_backfill.py --game-id``). The database tests apply the
shipped migrations to a scratch database (``conftest.py``).
"""

from __future__ import annotations

import collections
import copy
import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.backfill.verify import Problem, finish_season, verify_season
from app.backfill.walker import Shard
from app.backfill.writer import write_games_page, write_stats_page
from app.migrations.runner import upgrade
from app.services.bdl_stats import normalize_stat_row, parse_minutes

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
SEASON_TYPES = ("regular", "playoffs", "playin", "ist")


def _data(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURE_DIR / name).read_text())["response"]["data"]


def _games(season_type: str) -> list[dict[str, Any]]:
    return copy.deepcopy(_data(f"games__season2025_{season_type}_page1.json"))


def _stat_rows() -> list[dict[str, Any]]:
    return copy.deepcopy(_data("stats__season2025_page1.json"))


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    await upgrade(scratch_conn)
    return scratch_conn


async def _store_games(
    conn: asyncpg.Connection, season_type: str, games: list[dict[str, Any]] | None = None
) -> None:
    await write_games_page(
        conn, league="nba", season=2025, season_type=season_type,
        games=_games(season_type) if games is None else games, next_cursor=None,
    )


async def _store_stats(conn: asyncpg.Connection, rows: list[dict[str, Any]] | None = None) -> None:
    await write_stats_page(
        conn, league="nba", season=2025, rows=_stat_rows() if rows is None else rows, next_cursor=None
    )


async def _store_season(conn: asyncpg.Connection) -> None:
    for season_type in SEASON_TYPES:
        await _store_games(conn, season_type)
    await _store_stats(conn)


async def _statuses(conn: asyncpg.Connection) -> dict[tuple[str, str], tuple[str, str | None]]:
    rows = await conn.fetch(
        "SELECT data_type, shard_key, status, last_error FROM bdl_backfill_checkpoints WHERE season = 2025"
    )
    return {(row["data_type"], row["shard_key"]): (row["status"], row["last_error"]) for row in rows}


async def _finish(conn: asyncpg.Connection):
    return await finish_season(conn, league="nba", season=2025)


@pytest.mark.asyncio
async def test_a_fully_walked_season_passes_and_every_shard_is_done(db: asyncpg.Connection) -> None:
    await _store_season(db)

    report = await _finish(db)

    assert report.passed
    assert report.problems == ()
    assert set((await _statuses(db)).values()) == {("done", None)}
    assert len(await _statuses(db)) == 5
    assert report.games_by_type == {
        "regular_season": 100, "playoffs": 85, "play_in": 6, "cup_championship": 1,
    }
    assert report.stat_rows == 100
    assert report.dnp_rows == sum(normalize_stat_row(row).dnp for row in _stat_rows())
    assert report.rejected_rows == 0
    assert report.final_games_points_off_score == ()
    assert report.final_games_under_230_minutes == ()


@pytest.mark.asyncio
async def test_final_games_without_stats_are_listed_and_do_not_block(db: asyncpg.Connection) -> None:
    """Only the first stats page is stored, so most final games have no lines yet."""
    await _store_season(db)

    report = await _finish(db)

    per_game = collections.Counter(row["game"]["id"] for row in _stat_rows())
    final = {game["id"] for season_type in SEASON_TYPES for game in _games(season_type)
             if game["status_state"] == "final"}
    assert report.passed
    assert report.final_games_without_stats == tuple(sorted(final - set(per_game)))
    assert report.stat_rows_per_final_game == (min(per_game.values()), max(per_game.values()))


@pytest.mark.asyncio
async def test_rejected_lines_block_done(db: asyncpg.Connection) -> None:
    """A refused line is a spelling the normalizer cannot read yet: fixed in code, then re-walked.

    The 2019-20 to 2021-22 play-in lines were refused and their seasons still
    marked done, with 3 to 7 lines stored for 13 games.
    """
    for season_type in SEASON_TYPES:
        await _store_games(db, season_type)
    rows = _stat_rows()
    rows[3]["min"] = "3 minutes"
    await _store_stats(db, rows)

    report = await _finish(db)

    assert report.rejected_rows == 1
    assert report.problems == (Problem(Shard("stats", 2025, ""), "1 lines refused by normalize_stat_row"),)
    assert (await _statuses(db))[("stats", "")] == ("error", "verification: 1 lines refused by normalize_stat_row")


async def _store_season_with(conn: asyncpg.Connection, rows: list[dict[str, Any]]) -> None:
    for season_type in SEASON_TYPES:
        await _store_games(conn, season_type)
    await _store_stats(conn, rows)


GAME = 18446820  # final, both teams complete on the first stats page: 119 and 109 points, 241 and 240 minutes


@pytest.mark.asyncio
async def test_a_team_whose_points_differ_from_its_score_is_listed_and_does_not_block(
    db: asyncpg.Connection,
) -> None:
    """Player points that miss the score: a line left out, or a score that stops after the third overtime.

    A re-walk returns the same data, so neither can block.
    """
    rows = _stat_rows()
    next(row for row in rows if row["game"]["id"] == GAME and row["pts"])["pts"] += 2
    await _store_season_with(db, rows)

    report = await _finish(db)

    assert report.passed
    assert report.final_games_points_off_score == (GAME,)
    assert report.final_games_under_230_minutes == ()


@pytest.mark.asyncio
async def test_a_team_under_230_minutes_is_listed_and_does_not_block(db: asyncpg.Connection) -> None:
    """2005-06 and 2006-07 have 53 such team-games: points match the score, the minutes field is wrong."""
    rows = _stat_rows()
    starter = next(row for row in rows if row["game"]["id"] == GAME and (parse_minutes(row["min"]) or 0) >= 20 * 60)
    starter["min"] = "1"
    await _store_season_with(db, rows)

    report = await _finish(db)

    assert report.passed
    assert report.final_games_under_230_minutes == (GAME,)
    assert report.final_games_points_off_score == ()


@pytest.mark.asyncio
async def test_a_final_game_with_one_team_missing_is_listed(db: asyncpg.Connection) -> None:
    """No lines for one side reads as 0 points and 0 minutes for it, not as nothing to compare."""
    rows = _stat_rows()
    away = next(row["team"]["id"] for row in rows if row["game"]["id"] == GAME)
    await _store_season_with(db, [row for row in rows if (row["game"]["id"], row["team"]["id"]) != (GAME, away)])

    report = await _finish(db)

    assert report.final_games_points_off_score == (GAME,)
    assert report.final_games_under_230_minutes == (GAME,)


UPSTREAM_GAPS = [
    pytest.param(19865, False, True, id="2005-06 points match, minutes add to 172 and 126"),
    pytest.param(19052, False, True, id="2006-07 37 points in '0' minutes"),
    pytest.param(48851, True, False, id="four overtimes, the score stops after the third"),
    pytest.param(434, True, False, id="2018-19 a 4-point line left out"),
    pytest.param(1038278, False, True, id="2023-24 points match, minutes add to 228"),
    pytest.param(1038319, True, False, id="2023-24 2 points short"),
    pytest.param(1038379, True, True, id="2023-24 points and minutes short"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("game_id", "points_off", "minutes_short"), UPSTREAM_GAPS)
async def test_recorded_upstream_gaps_are_listed(
    db: asyncpg.Connection, game_id: int, points_off: bool, minutes_short: bool
) -> None:
    """Games whose BALLDONTLIE data is wrong, fetched again by game id: every line is read, the game is listed."""
    game = json.loads((FIXTURE_DIR / f"games__game{game_id}_record.json").read_text())["response"]["data"]
    rows = _data(f"stats__game{game_id}_page1.json")
    season = game["season"]
    await write_games_page(db, league="nba", season=season, season_type="regular", games=[game], next_cursor=None)
    await write_stats_page(db, league="nba", season=season, rows=rows, next_cursor=None)

    report = await verify_season(db, league="nba", season=season)

    assert report.rejected_rows == 0
    assert report.stat_rows == len(rows)
    listed = (game_id in report.final_games_points_off_score, game_id in report.final_games_under_230_minutes)
    assert listed == (points_off, minutes_short)


@pytest.mark.asyncio
async def test_a_shard_not_walked_to_the_end_blocks_done(db: asyncpg.Connection) -> None:
    await write_games_page(
        db, league="nba", season=2025, season_type="regular", games=_games("regular"), next_cursor=18446918,
    )
    for season_type in ("playoffs", "playin", "ist"):
        await _store_games(db, season_type)
    await _store_stats(db)

    report = await _finish(db)

    regular = Shard("games", 2025, "regular")
    assert not report.passed
    assert [problem.shard for problem in report.problems] == [regular]
    assert "18446918" in report.problems[0].message
    statuses = await _statuses(db)
    assert statuses[("games", "regular")][0] == "error"
    assert "done" not in {status for status, _ in statuses.values()}


@pytest.mark.asyncio
async def test_a_game_fetched_under_two_types_blocks_done(db: asyncpg.Connection) -> None:
    """The regular game also on the ist page ends up stored once, under the type walked last."""
    regular = _games("regular")
    for season_type in ("regular", "playoffs", "playin"):
        await _store_games(db, season_type)
    await _store_games(db, "ist", _games("ist") + [regular[-1]])
    await _store_stats(db)

    report = await _finish(db)

    assert report.problems == (Problem(Shard("games", 2025, "regular"), "99 games stored, 100 fetched"),)
    statuses = await _statuses(db)
    assert statuses[("games", "regular")] == ("error", "verification: 99 games stored, 100 fetched")
    assert {key: status for key, (status, _) in statuses.items() if key != ("games", "regular")} == {
        ("games", "playoffs"): "in_progress",
        ("games", "playin"): "in_progress",
        ("games", "ist"): "in_progress",
        ("stats", ""): "in_progress",
    }


@pytest.mark.asyncio
async def test_dropped_lines_block_done(db: asyncpg.Connection) -> None:
    """Every game type is stored, so a line whose game is missing means a games page was lost."""
    rows = _stat_rows()
    missing = rows[0]["game"]["id"]
    await _store_games(db, "regular", [game for game in _games("regular") if game["id"] != missing])
    for season_type in ("playoffs", "playin", "ist"):
        await _store_games(db, season_type)
    await _store_stats(db, rows)

    report = await _finish(db)

    dropped = sum(1 for row in rows if row["game"]["id"] == missing)
    assert report.problems == (
        Problem(Shard("stats", 2025, ""), f"{dropped} lines dropped because their game is not stored"),
    )


@pytest.mark.asyncio
async def test_a_line_fetched_on_two_pages_blocks_done(db: asyncpg.Connection) -> None:
    """Ten lines come back on both pages. The upsert stores them once, so stored and fetched disagree."""
    for season_type in SEASON_TYPES:
        await _store_games(db, season_type)
    rows = _stat_rows()
    await write_stats_page(db, league="nba", season=2025, rows=rows[:60], next_cursor=20758310)
    await write_stats_page(db, league="nba", season=2025, rows=rows[50:], next_cursor=None)

    report = await _finish(db)

    assert report.problems == (
        Problem(Shard("stats", 2025, ""), "100 lines stored, 0 dropped, 0 rejected, 110 fetched"),
    )


@pytest.mark.asyncio
async def test_done_clears_an_earlier_verification_message(db: asyncpg.Connection) -> None:
    await _store_season(db)
    await db.execute(
        "UPDATE bdl_backfill_checkpoints SET status = 'error', last_error = 'verification: earlier'"
        " WHERE data_type = 'stats'"
    )

    await _finish(db)

    assert (await _statuses(db))[("stats", "")] == ("done", None)


@pytest.mark.asyncio
async def test_verify_season_only_reads(db: asyncpg.Connection) -> None:
    """The current season is reported without being marked done."""
    await _store_season(db)

    report = await verify_season(db, league="nba", season=2025)

    assert report.passed
    assert set((await _statuses(db)).values()) == {("in_progress", None)}
