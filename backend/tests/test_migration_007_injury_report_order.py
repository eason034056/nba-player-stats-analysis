"""Migration 007: stable injury-report order and a league-first index."""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio

from app.migrations.runner import upgrade

UTC = timezone.utc


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
    assert applied == ["001", "002", "003", "004", "005", "006", "007"]
    await scratch_conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label)
        VALUES ('nba', 2023, '2023-24');
        INSERT INTO teams (league, bdl_team_id, abbreviation, full_name) VALUES
            ('nba', 2, 'BOS', 'Boston Celtics'),
            ('nba', 20, 'NYK', 'New York Knicks');
        INSERT INTO games (
            league, bdl_game_id, season, date, datetime_utc, status_state,
            season_type, home_team_id, visitor_team_id
        ) VALUES (
            'nba', 701, 2023, '2024-01-15', '2024-01-16 02:00:00+00',
            'scheduled', 'regular_season', 20, 2
        );
        """
    )
    return scratch_conn


@pytest.mark.asyncio
async def test_007_second_pass_is_a_no_op_and_the_index_leads_with_league(
    db: asyncpg.Connection,
) -> None:
    assert await upgrade(db) == []
    indexdef = await db.fetchval(
        """
        SELECT indexdef FROM pg_indexes
        WHERE indexname = 'nba_injury_report_rows_game_report_idx'
        """
    )
    assert "(league, bdl_game_id, report_at)" in indexdef
    body = await db.fetchval(
        """
        SELECT pg_get_functiondef('injury_report_rows_asof(league_code, bigint, timestamptz)'::regprocedure)
        """
    )
    assert "ORDER BY r.team_name, r.player_raw, r.not_yet_submitted, r.matchup, r.id" in body


@pytest.mark.asyncio
async def test_rows_come_back_in_team_then_player_order(db: asyncpg.Connection) -> None:
    """Inserted last-to-first. The read order is team name, then player name."""
    report_at = datetime(2024, 1, 15, 22, 30, tzinfo=UTC)
    await db.executemany(
        """
        INSERT INTO nba_injury_report_rows (
            league, report_at, game_date, matchup, team_name,
            bdl_game_id, bdl_team_id, player_raw, status,
            not_yet_submitted, all_players_available
        ) VALUES (
            'nba', $1, '2024-01-15', 'BOS@NYK', $2, 701, $3, $4, 'Out', false, false
        )
        """,
        [
            (report_at, "New York Knicks", 20, "Aaa, Ann"),
            (report_at, "Boston Celtics", 2, "Zed, Zoe"),
            (report_at, "Boston Celtics", 2, "Doe, Alex"),
        ],
    )
    rows = await db.fetch(
        "SELECT team_name, player_raw FROM injury_report_rows_asof('nba', 701, $1)",
        report_at,
    )
    assert [(row["team_name"], row["player_raw"]) for row in rows] == [
        ("Boston Celtics", "Doe, Alex"),
        ("Boston Celtics", "Zed, Zoe"),
        ("New York Knicks", "Aaa, Ann"),
    ]
