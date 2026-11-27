"""Empty official-injury table versus a database that has no such table.

``export_dataset`` runs against Postgres. The fetch is not mocked.

An existing empty ``nba_injury_report_rows`` stays on the official path:
every row has ``injury_report_missing`` 1 and missing minutes NULL.
A database without that relation returns None from the loader and the
export uses the snapshot path, so ``injury_report_missing`` stays NULL.
Filling missing-report minutes with 0.0 fails the empty-table test.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import asyncpg
import pandas as pd
import pytest

from app.ml.build_dataset import export_dataset
from app.ml.load import load_official_injury_inputs

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
CORE = (
    "002_bdl_core.sql",
    "003_bdl_game_gaps.sql",
    "004_read_layer.sql",
    "005_bdl_pit.sql",
)
WITH_OFFICIAL_TABLE = CORE + (
    "006_injury_report_rows.sql",
    "007_injury_report_rows_order.sql",
)
GAME = 501
PLAYER = 10
HOME = 1
AWAY = 2
ON = date(2024, 11, 1)
TIP = datetime(2024, 11, 1, 23, 0, tzinfo=UTC)


async def _apply(dsn: str, names: tuple[str, ...]) -> None:
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        async with conn.transaction():
            for name in names:
                await conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
    finally:
        await conn.close()


async def _seed(dsn: str) -> None:
    """One final 2024-25 game and one played line. No injury rows."""
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        await conn.execute(
            """
            INSERT INTO seasons (league, season_start_year, label)
            VALUES ('nba', 2024, '2024-25')
            """
        )
        await conn.execute(
            """
            INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES
                ('nba', $1, 'HOM'), ('nba', $2, 'AWY')
            """,
            HOME,
            AWAY,
        )
        await conn.execute(
            """
            INSERT INTO players (league, bdl_player_id, display_name)
            VALUES ('nba', $1, 'QA Player')
            """,
            PLAYER,
        )
        await conn.execute(
            """
            INSERT INTO games
                (league, bdl_game_id, season, date, datetime_utc, status_state,
                 season_type, home_team_id, visitor_team_id)
            VALUES ('nba', $1, 2024, $2, $3, 'final', 'regular_season', $4, $5)
            """,
            GAME,
            ON,
            TIP,
            HOME,
            AWAY,
        )
        await conn.execute(
            """
            INSERT INTO player_game_stats
                (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id,
                 season, date, dnp, seconds_played, pts, reb, ast, fg3m, stl, blk)
            VALUES
                ('nba', $1, $2, $3, $4, 2024, $5, FALSE, 1800, 10, 2, 2, 1, 1, 0)
            """,
            GAME * 1000 + PLAYER,
            GAME,
            PLAYER,
            HOME,
            ON,
        )
    finally:
        await conn.close()


def _export(dsn: str, out: Path) -> pd.DataFrame:
    import os

    os.environ["SPO154_QA_DSN"] = dsn
    try:
        def _run() -> None:
            asyncio.run(
                export_dataset(
                    dsn_env="SPO154_QA_DSN",
                    season_start=2024,
                    season_end=2024,
                    hours_before_tip=3,
                    out=out,
                    league="nba",
                    git_head="spo154",
                )
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_run).result()
    finally:
        os.environ.pop("SPO154_QA_DSN", None)
    frame = pd.read_parquet(out)
    assert len(frame) == 1
    return frame


def _minutes_are_null(frame: pd.DataFrame) -> None:
    minutes = frame.iloc[0]["team_missing_minutes"]
    assert bool(pd.isna(minutes))
    assert bool(pd.isna(frame.iloc[0]["opp_missing_minutes"]))


@pytest.mark.asyncio
async def test_empty_official_table_marks_every_row_missing(
    scratch_dsn: str, tmp_path: Path
) -> None:
    await _apply(scratch_dsn, WITH_OFFICIAL_TABLE)
    await _seed(scratch_dsn)
    conn = await asyncpg.connect(scratch_dsn, timeout=10)
    try:
        assert await conn.fetchval("SELECT count(*) FROM nba_injury_report_rows") == 0
        assert await conn.fetchval("SELECT count(*) FROM source_refreshes") == 0
        loaded = await load_official_injury_inputs(conn, league="nba")
    finally:
        await conn.close()
    assert loaded is not None
    assert loaded[0] == []
    assert loaded[1] == []
    frame = _export(scratch_dsn, tmp_path / "empty.parquet")
    assert int(frame.iloc[0]["injury_report_missing"]) == 1
    _minutes_are_null(frame)
    assert bool(pd.isna(frame.iloc[0]["player_injury_status"]))
    assert frame.iloc[0]["info_source"] == "pregame"


@pytest.mark.asyncio
async def test_missing_official_table_uses_the_snapshot_path(
    scratch_dsn: str, tmp_path: Path
) -> None:
    await _apply(scratch_dsn, CORE)
    await _seed(scratch_dsn)
    conn = await asyncpg.connect(scratch_dsn, timeout=10)
    try:
        assert await conn.fetchval("SELECT to_regclass('public.nba_injury_report_rows')") is None
        loaded = await load_official_injury_inputs(conn, league="nba")
    finally:
        await conn.close()
    assert loaded is None
    frame = _export(scratch_dsn, tmp_path / "missing.parquet")
    assert bool(pd.isna(frame.iloc[0]["injury_report_missing"]))
    _minutes_are_null(frame)
    assert frame.iloc[0]["info_source"] == "pregame"
