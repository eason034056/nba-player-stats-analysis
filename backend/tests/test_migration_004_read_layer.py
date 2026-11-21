"""
test_migration_004_read_layer.py - the SPO-138i read layer in a real PostgreSQL.

Each test creates a scratch database, applies 002 and 004 inside one
transaction, and drops the database afterwards. The tests skip when no server
answers ``DATABASE_URL``, like ``test_migration_002_bdl_core.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
FILES = ("002_bdl_core.sql", "004_read_layer.sql")

FINAL_GAME = 123
UPCOMING_GAME = 124
NO_TIP_TIME_GAME = 125
LIVE_GAME = 126

LEBRON, CURRY, DAVIS, GREEN, REAVES = 237, 115, 140, 185, 666


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    """Scratch database with 002 and 004 applied and four games to hang rows on."""
    async with scratch_conn.transaction():
        for name in FILES:
            await scratch_conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
    await scratch_conn.execute(
        f"""
        INSERT INTO seasons (league, season_start_year, label) VALUES ('nba', 2025, '2025-26');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES ('nba', 14, 'LAL'), ('nba', 10, 'GSW');
        INSERT INTO players (league, bdl_player_id, display_name) VALUES
            ('nba', {LEBRON}, 'LeBron James'), ('nba', {CURRY}, 'Stephen Curry'),
            ('nba', {DAVIS}, 'Anthony Davis'), ('nba', {GREEN}, 'Draymond Green'),
            ('nba', {REAVES}, 'Austin Reaves');
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, status_state, season_type,
             home_team_id, visitor_team_id)
        VALUES
            ('nba', {FINAL_GAME}, 2025, '2026-01-15', '2026-01-16 03:30Z', 'final',
             'regular_season', 14, 10),
            ('nba', {UPCOMING_GAME}, 2025, '2026-01-17', now() + interval '1 day', 'scheduled',
             'regular_season', 10, 14),
            ('nba', {NO_TIP_TIME_GAME}, 2025, '2026-01-19', NULL, 'scheduled',
             'regular_season', 14, 10),
            ('nba', {LIVE_GAME}, 2025, '2026-01-20', '2026-01-21 03:00Z', 'in_progress',
             'regular_season', 10, 14);
        """
    )
    return scratch_conn


async def _stat_line(
    conn: asyncpg.Connection, game: int, player: int, *, dnp: bool = False, **stats: int | None
) -> None:
    game_row = await conn.fetchrow(
        "SELECT season, date FROM games WHERE league = 'nba' AND bdl_game_id = $1", game
    )
    values: dict[str, int | None] = {} if dnp else {"seconds_played": 1800, **stats}
    columns = "".join(f", {name}" for name in values)
    placeholders = "".join(f", ${index}" for index in range(8, 8 + len(values)))
    await conn.execute(
        f"""
        INSERT INTO player_game_stats
            (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date, dnp{columns})
        VALUES ('nba', $1, $2, $3, $4, $5, $6, $7{placeholders})
        """,
        game * 1000 + player, game, player, 14, game_row["season"], game_row["date"], dnp,
        *values.values(),
    )


async def _actuals(conn: asyncpg.Connection, game: int, player: int) -> dict[str, int | None]:
    rows = await conn.fetch(
        "SELECT market, actual_value FROM prop_actuals WHERE bdl_game_id = $1 AND bdl_player_id = $2",
        game, player,
    )
    return {row["market"]: row["actual_value"] for row in rows}


async def _predict(
    conn: asyncpg.Connection,
    *,
    game: int = UPCOMING_GAME,
    market: str = "player_points",
    model: str = "v1",
    value: float = 24.5,
    distribution: str | None = None,
    predicted_at: datetime | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO predictions
            (league, bdl_game_id, bdl_player_id, market, model_version,
             predicted_at, predicted_value, distribution)
        VALUES ('nba', $1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT DO NOTHING
        """,
        game, LEBRON, market, model, predicted_at or datetime(2000, 1, 1, tzinfo=UTC), value,
        distribution,
    )


@pytest.mark.asyncio
async def test_the_table_and_the_four_views_exist(db: asyncpg.Connection) -> None:
    kinds = dict(
        await db.fetch(
            """
            SELECT table_name, table_type FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ANY($1::text[])
            """,
            ["predictions", "prop_actuals", "current_predictions", "current_injuries",
             "current_projected_lineups"],
        )
    )
    assert kinds == {
        "predictions": "BASE TABLE",
        "prop_actuals": "VIEW",
        "current_predictions": "VIEW",
        "current_injuries": "VIEW",
        "current_projected_lineups": "VIEW",
    }


@pytest.mark.asyncio
async def test_every_stat_column_name_is_an_integer_column(db: asyncpg.Connection) -> None:
    """prop_actuals reads columns by name, so a typo would turn a market into NULLs."""
    unknown = await db.fetch(
        """
        SELECT m.market, c.name
        FROM prop_markets m, unnest(m.stat_columns) AS c(name)
        WHERE NOT EXISTS (
            SELECT 1 FROM information_schema.columns col
            WHERE col.table_schema = 'public' AND col.table_name = 'player_game_stats'
              AND col.column_name = c.name AND col.data_type = 'integer'
        )
        """
    )
    assert [tuple(row) for row in unknown] == []


@pytest.mark.asyncio
async def test_prop_actuals_settles_all_twelve_markets(db: asyncpg.Connection) -> None:
    await _stat_line(db, FINAL_GAME, LEBRON, pts=25, reb=11, ast=9, fg3m=3, stl=2, blk=1)
    await _stat_line(db, FINAL_GAME, DAVIS, pts=20, reb=10, ast=10, fg3m=0, stl=1, blk=4)

    assert await _actuals(db, FINAL_GAME, LEBRON) == {
        "player_points": 25,
        "player_rebounds": 11,
        "player_assists": 9,
        "player_threes": 3,
        "player_steals": 2,
        "player_blocks": 1,
        "player_points_rebounds": 36,
        "player_points_assists": 34,
        "player_rebounds_assists": 20,
        "player_points_rebounds_assists": 45,
        "player_double_double": 1,
        "player_triple_double": 0,
    }
    davis = await _actuals(db, FINAL_GAME, DAVIS)
    assert davis["player_triple_double"] == 1
    assert davis["player_double_double"] == 1


@pytest.mark.asyncio
async def test_a_dnp_line_is_void_in_every_market(db: asyncpg.Connection) -> None:
    await _stat_line(db, FINAL_GAME, CURRY, dnp=True)

    actuals = await _actuals(db, FINAL_GAME, CURRY)
    assert len(actuals) == 12
    assert set(actuals.values()) == {None}


@pytest.mark.asyncio
async def test_a_missing_stat_makes_only_its_markets_unknown(db: asyncpg.Connection) -> None:
    await _stat_line(db, FINAL_GAME, GREEN, pts=8, reb=12, ast=11, fg3m=1, stl=None, blk=1)

    actuals = await _actuals(db, FINAL_GAME, GREEN)
    assert actuals["player_steals"] is None
    assert actuals["player_double_double"] is None
    assert actuals["player_points"] == 8
    assert actuals["player_rebounds_assists"] == 23


@pytest.mark.asyncio
async def test_prop_actuals_waits_for_a_final_game(db: asyncpg.Connection) -> None:
    await _stat_line(db, LIVE_GAME, LEBRON, pts=12, reb=4, ast=3, fg3m=1, stl=0, blk=0)

    assert await _actuals(db, LIVE_GAME, LEBRON) == {}


@pytest.mark.asyncio
async def test_predicted_at_is_the_insert_time_not_the_writers_value(db: asyncpg.Connection) -> None:
    async with db.transaction():
        await _predict(db, predicted_at=datetime(2000, 1, 1, tzinfo=UTC))
        insert_time = await db.fetchval("SELECT now()")

    assert await db.fetchval("SELECT predicted_at FROM predictions") == insert_time


@pytest.mark.asyncio
async def test_a_prediction_after_tip_off_is_refused(db: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="tipped off"):
        await _predict(db, game=FINAL_GAME)


@pytest.mark.asyncio
async def test_a_game_without_a_tip_time_takes_no_prediction(db: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="no datetime_utc"):
        await _predict(db, game=NO_TIP_TIME_GAME)


@pytest.mark.asyncio
async def test_double_digit_markets_store_a_probability(db: asyncpg.Connection) -> None:
    await _predict(db, market="player_double_double", value=0.42)

    with pytest.raises(asyncpg.CheckViolationError, match="probability"):
        await _predict(db, market="player_triple_double", value=1.5)


@pytest.mark.asyncio
async def test_a_negative_value_is_refused(db: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await _predict(db, value=-1)


@pytest.mark.asyncio
async def test_distribution_must_be_a_json_object(db: asyncpg.Connection) -> None:
    await _predict(db, model="v1", distribution='{"mean": 24.5, "sd": 6.1}')

    with pytest.raises(asyncpg.CheckViolationError):
        await _predict(db, model="v2", distribution="[24.5, 6.1]")


@pytest.mark.asyncio
async def test_predictions_cannot_be_updated_or_deleted(db: asyncpg.Connection) -> None:
    await _predict(db)

    with pytest.raises(asyncpg.RestrictViolationError, match="UPDATE"):
        await db.execute("UPDATE predictions SET predicted_value = 30")
    with pytest.raises(asyncpg.RestrictViolationError, match="DELETE"):
        await db.execute("DELETE FROM predictions")


@pytest.mark.asyncio
async def test_a_replay_inside_one_transaction_keeps_one_row(db: asyncpg.Connection) -> None:
    async with db.transaction():
        await _predict(db, value=24.5)
        await _predict(db, value=24.5)

    assert await db.fetchval("SELECT count(*) FROM predictions") == 1


@pytest.mark.asyncio
async def test_current_predictions_keeps_the_latest_run_per_model(db: asyncpg.Connection) -> None:
    await _predict(db, model="v1", value=20)
    await _predict(db, model="v1", value=22)
    await _predict(db, model="v2", value=18)

    rows = await db.fetch(
        "SELECT model_version, predicted_value FROM current_predictions ORDER BY model_version"
    )
    assert [(row["model_version"], float(row["predicted_value"])) for row in rows] == [
        ("v1", 22.0), ("v2", 18.0),
    ]
    assert await db.fetchval("SELECT count(*) FROM predictions") == 3


@pytest.mark.asyncio
async def test_current_injuries_shows_the_newest_word_and_drops_removals(
    db: asyncpg.Connection,
) -> None:
    await db.execute(
        f"""
        INSERT INTO injury_snapshots (league, snapshot_at, bdl_player_id, listed, bdl_team_id, status)
        VALUES
            ('nba', '2026-01-15 17:07Z', {DAVIS}, true, 14, 'Out'),
            ('nba', '2026-01-15 17:37Z', {DAVIS}, false, NULL, NULL),
            ('nba', '2026-01-15 17:07Z', {REAVES}, true, 14, 'Questionable'),
            ('nba', '2026-01-15 17:37Z', {REAVES}, true, 14, 'Doubtful');
        """
    )

    rows = await db.fetch("SELECT bdl_player_id, status FROM current_injuries")
    assert [tuple(row) for row in rows] == [(REAVES, "Doubtful")]


@pytest.mark.asyncio
async def test_current_projected_lineups_shows_only_the_newest_version(
    db: asyncpg.Connection,
) -> None:
    await db.execute(
        f"""
        INSERT INTO projected_lineups
            (league, bdl_game_id, bdl_team_id, updated_at, first_seen_at, status)
        VALUES
            ('nba', {UPCOMING_GAME}, 14, '2026-01-17 17:00Z', '2026-01-17 17:02Z', 'expected'),
            ('nba', {UPCOMING_GAME}, 14, '2026-01-17 23:45Z', '2026-01-17 23:46Z', 'confirmed');
        INSERT INTO projected_lineup_players
            (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id, position)
        VALUES
            ('nba', {UPCOMING_GAME}, 14, '2026-01-17 17:00Z', {LEBRON}, 'F'),
            ('nba', {UPCOMING_GAME}, 14, '2026-01-17 17:00Z', {DAVIS}, 'C'),
            ('nba', {UPCOMING_GAME}, 14, '2026-01-17 23:45Z', {LEBRON}, 'F'),
            ('nba', {UPCOMING_GAME}, 14, '2026-01-17 23:45Z', {REAVES}, 'G');
        """
    )

    rows = await db.fetch(
        "SELECT bdl_player_id, status FROM current_projected_lineups ORDER BY bdl_player_id"
    )
    assert [tuple(row) for row in rows] == [(LEBRON, "confirmed"), (REAVES, "confirmed")]
