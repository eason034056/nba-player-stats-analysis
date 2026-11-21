"""
test_spo138i_qa_read_layer.py - QA probes for the SPO-138i read layer.

Behaviour checks against a real PostgreSQL, reusing the ``db`` fixture from
``test_migration_004_read_layer.py``. Skips when no server answers DATABASE_URL.
"""

from __future__ import annotations

import asyncpg
import pytest

from tests.test_migration_004_read_layer import (  # noqa: F401  (fixture import)
    FINAL_GAME,
    LEBRON,
    UPCOMING_GAME,
    db,
)


@pytest.mark.asyncio
async def test_an_insert_after_tip_off_is_refused_even_in_a_long_transaction(
    db: asyncpg.Connection,
) -> None:
    """A writer that opened its transaction before tip-off must not slip a row in after it."""
    await db.execute(
        "UPDATE games SET datetime_utc = clock_timestamp() + interval '1 second' "
        "WHERE league = 'nba' AND bdl_game_id = $1",
        UPCOMING_GAME,
    )
    with pytest.raises(asyncpg.CheckViolationError, match="tipped off"):
        async with db.transaction():
            await db.execute("SELECT 1")  # transaction starts before tip-off
            await db.execute("SELECT pg_sleep(1.5)")  # tip-off passes
            await db.execute(
                """
                INSERT INTO predictions
                    (league, bdl_game_id, bdl_player_id, market, model_version,
                     predicted_at, predicted_value)
                VALUES ('nba', $1, $2, 'player_points', 'v1', now(), 25)
                """,
                UPCOMING_GAME,
                LEBRON,
            )


@pytest.mark.asyncio
async def test_a_double_double_needs_two_of_the_five_categories(db: asyncpg.Connection) -> None:
    """10 pts + 10 stl is a double-double; 10 pts + 9 reb + 9 ast is not; 10/10/10 is a triple."""
    from tests.test_migration_004_read_layer import _actuals, _stat_line

    await _stat_line(db, FINAL_GAME, LEBRON, pts=10, reb=9, ast=9, stl=10, blk=0, fg3m=0)
    actuals = await _actuals(db, FINAL_GAME, LEBRON)
    assert actuals["player_double_double"] == 1
    assert actuals["player_triple_double"] == 0
    assert actuals["player_points_rebounds_assists"] == 28
