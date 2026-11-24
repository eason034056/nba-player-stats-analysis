"""Migration 006: official injury-report rows and the new source value."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from app.migrations.runner import discover, upgrade

UTC = timezone.utc
SQL = Path(__file__).resolve().parents[1] / "app" / "migrations" / "006_injury_report_rows.sql"
OLD_SOURCES = (
    "injuries",
    "projected_lineups",
    "game_odds_live",
    "game_odds_closing",
    "props_live",
    "props_closing",
)


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    applied = await upgrade(scratch_conn)
    assert applied == ["001", "002", "003", "004", "005", "006", "007"]
    return scratch_conn


def test_006_keeps_every_previous_source_and_adds_the_official_one() -> None:
    text = SQL.read_text(encoding="utf-8")
    for source in (*OLD_SOURCES, "injuries_nba_official"):
        assert f"'{source}'" in text
    assert "report_at <=" in text
    assert "nba_injury_report_rows_game_report_idx" in text


@pytest.mark.asyncio
async def test_006_applies_on_001_through_005_and_a_second_pass_is_a_no_op(
    db: asyncpg.Connection,
) -> None:
    assert await upgrade(db) == []
    versions = await db.fetch("SELECT version FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in versions] == ["001", "002", "003", "004", "005", "006", "007"]
    assert await db.fetchval("SELECT to_regclass('public.nba_injury_report_rows') IS NOT NULL")
    indexdef = await db.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'nba_injury_report_rows_game_report_idx'"
    )
    assert "bdl_game_id" in indexdef
    assert "report_at" in indexdef


@pytest.mark.asyncio
async def test_official_source_inserts_and_old_sources_still_insert(
    db: asyncpg.Connection,
) -> None:
    moment = datetime(2026, 1, 15, 22, 30, tzinfo=UTC)
    await db.execute(
        """
        INSERT INTO source_refreshes (league, source, refreshed_at, complete, rows_seen)
        VALUES ('nba', 'injuries_nba_official', $1, true, 3)
        """,
        moment,
    )
    for offset, source in enumerate(OLD_SOURCES, start=1):
        await db.execute(
            """
            INSERT INTO source_refreshes (league, source, refreshed_at, complete)
            VALUES ('nba', $1, $2, true)
            """,
            source,
            moment + timedelta(minutes=offset),
        )
    count = await db.fetchval("SELECT count(*) FROM source_refreshes")
    assert count == 1 + len(OLD_SOURCES)
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            """
            INSERT INTO source_refreshes (league, source, refreshed_at, complete)
            VALUES ('nba', 'not_a_source', now(), true)
            """
        )


@pytest.mark.asyncio
async def test_shipped_versions_include_006() -> None:
    versions = [migration.version for migration in discover()]
    assert "006" in versions
    assert versions[-1] == "007"
