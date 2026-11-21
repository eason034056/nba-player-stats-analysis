"""SPO-138l live team_absences against a scratch database.

The live loader reads one team and one game. The training call passes the
season stats already loaded for the export. Both call ``team_absences``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from app.ml.absence import SOURCE_ACTUAL, SOURCE_REPORTED, team_absences
from app.ml.asof import prediction_instant
from app.ml.build_dataset import assemble_dataset
from app.ml.labels import CATALOG_MARKETS
from app.ml.load import (
    ActualRecord,
    injury_coverage_status,
    load_feature_rows,
    load_injuries,
    load_lineups,
    load_team_absence_inputs,
)
from app.services.injury_status import OUT, PROBABLE, QUESTIONABLE

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
FILES = ("002_bdl_core.sql", "004_read_layer.sql")
HOME = 14
AWAY = 10
OTHER = 20
DECOY_TEAM = 30
ROT = 1
DNP_PLAYER = 2
PLAYED = 3
SHORT = 4
LOW = 5
TRADED = 6
FILLER = 7
ROW = 8
DECOY = 99
TARGET = date(2025, 1, 20)
TARGET_GAME = 100
TIP = datetime(2025, 1, 20, 23, 0, tzinfo=UTC)
T = prediction_instant(TARGET, TIP, 3).as_of
EXACT = 15 * 60


@pytest_asyncio.fixture
async def seeded(scratch_dsn: str) -> str:
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        async with conn.transaction():
            for name in FILES:
                await conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
        await _seed(conn)
    finally:
        await conn.close()
    return scratch_dsn


async def _game(
    conn: asyncpg.Connection,
    game_id: int,
    on: date,
    home: int,
    visitor: int,
    *,
    season: int = 2025,
    tip: datetime | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, season_type,
             home_team_id, visitor_team_id)
        VALUES ('nba', $1, $2, $3, $4, 'regular_season', $5, $6)
        """,
        game_id,
        season,
        on,
        tip,
        home,
        visitor,
    )


async def _played(
    conn: asyncpg.Connection,
    game_id: int,
    player: int,
    team: int,
    *,
    seconds: int = EXACT,
    pts: int = 10,
    dnp: bool = False,
) -> None:
    await conn.execute(
        """
        INSERT INTO player_game_stats
            (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
             dnp, seconds_played, pts, reb, ast, fg3m, stl, blk)
        SELECT 'nba', $1, $2, $3, $4, g.season, g.date, $5, $6, $7, $8, $8, $8, $8, $8
        FROM games g
        WHERE g.league = 'nba' AND g.bdl_game_id = $2
        """,
        game_id * 1000 + player,
        game_id,
        player,
        team,
        dnp,
        None if dnp else seconds,
        None if dnp else pts,
        None if dnp else 1,
    )


async def _injury(
    conn: asyncpg.Connection,
    player: int,
    at: datetime,
    *,
    listed: bool,
    status: str | None,
    team: int | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO injury_snapshots
            (league, snapshot_at, bdl_player_id, listed, bdl_team_id, status)
        VALUES ('nba', $1, $2, $3, $4, $5)
        """,
        at,
        player,
        listed,
        team,
        status,
    )


async def _seed(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES
            ('nba', 2020, '2020-21'), ('nba', 2025, '2025-26');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES
            ('nba', 14, 'LAL'), ('nba', 10, 'GSW'), ('nba', 20, 'BOS'), ('nba', 30, 'NYK');
        INSERT INTO players (league, bdl_player_id, display_name) VALUES
            ('nba', 1, 'Rot'), ('nba', 2, 'Dnp'), ('nba', 3, 'Played'),
            ('nba', 4, 'Short'), ('nba', 5, 'Low'), ('nba', 6, 'Traded'),
            ('nba', 7, 'Filler'), ('nba', 8, 'Row'), ('nba', 99, 'Decoy');
        """
    )
    for gid in range(1, 11):
        await _game(conn, gid, date(2025, 1, gid), HOME, AWAY)
        await _played(conn, gid, FILLER, HOME)
    for gid in (1, 2, 3):
        await _played(conn, gid, ROT, HOME)
        await _played(conn, gid, TRADED, HOME)
    for gid in (1, 2, 4):
        await _played(conn, gid, DNP_PLAYER, HOME)
    for gid in (1, 5, 6):
        await _played(conn, gid, PLAYED, HOME)
    for gid in (1, 2):
        await _played(conn, gid, SHORT, HOME)
    for gid in (7, 8, 9):
        await _played(conn, gid, LOW, HOME, seconds=14 * 60 + 59)
    for gid in (8, 9, 10):
        await _played(conn, gid, ROW, HOME)
    await _game(conn, 50, date(2025, 1, 15), OTHER, AWAY)
    await _played(conn, 50, TRADED, OTHER, seconds=1800)
    await _game(conn, TARGET_GAME, TARGET, HOME, AWAY, tip=TIP)
    await _played(conn, TARGET_GAME, DNP_PLAYER, HOME, dnp=True)
    await _played(conn, TARGET_GAME, PLAYED, HOME, seconds=1800, pts=12)
    await _played(conn, TARGET_GAME, FILLER, HOME, seconds=1800, pts=8)
    await _played(conn, TARGET_GAME, ROW, HOME, seconds=1800, pts=9)
    await _game(conn, 900, date(2020, 1, 1), DECOY_TEAM, AWAY, season=2020)
    await _played(conn, 900, DECOY, DECOY_TEAM, seconds=1800)

    await _injury(conn, ROT, T, listed=True, status=OUT, team=HOME)
    await _injury(conn, ROT, T + timedelta(seconds=1), listed=True, status=PROBABLE, team=HOME)
    await _injury(conn, DNP_PLAYER, T, listed=True, status=QUESTIONABLE, team=HOME)
    await _injury(conn, PLAYED, T - timedelta(days=1), listed=True, status=OUT, team=HOME)
    await _injury(conn, PLAYED, T, listed=False, status=None, team=None)
    await _injury(conn, FILLER, T, listed=True, status="GTD", team=HOME)
    await _injury(conn, ROW, T, listed=True, status=OUT, team=HOME)
    await _injury(conn, DECOY, T, listed=True, status=OUT, team=DECOY_TEAM)
    await conn.execute(
        """
        INSERT INTO game_lineups
            (league, bdl_game_id, bdl_player_id, bdl_team_id, starter)
        VALUES ('nba', $1, $2, $3, true)
        """,
        TARGET_GAME,
        ROW,
        HOME,
    )


def _labels(game_id: int, player: int) -> list[ActualRecord]:
    return [
        ActualRecord(
            "nba",
            game_id,
            player,
            market,
            10 if market == "player_points" else 0,
        )
        for market in CATALOG_MARKETS
    ]


@pytest.mark.asyncio
async def test_live_loader_and_training_history_call_team_absences(seeded: str) -> None:
    conn = await asyncpg.connect(seeded, timeout=5)
    try:
        live = await load_team_absence_inputs(conn, league="nba", team=HOME, game=TARGET_GAME)
        _games, stats = await load_feature_rows(conn, league="nba", seasons=range(2025, 2026))
        injuries = await load_injuries(conn, league="nba")
        coverage, note = await injury_coverage_status(conn)
    finally:
        await conn.close()

    assert live.target_date == TARGET
    assert 900 not in {row.bdl_game_id for row in live.stats}
    assert DECOY not in {row.bdl_player_id for row in live.injuries}
    assert coverage == "unknown"
    assert "schema" in note
    assert "://" not in note

    for source in (SOURCE_ACTUAL, SOURCE_REPORTED):
        from_live = team_absences(
            "nba",
            HOME,
            TARGET_GAME,
            T,
            source,
            target_date=live.target_date,
            stats=live.stats,
            injuries=live.injuries,
        )
        from_training = team_absences(
            "nba",
            HOME,
            TARGET_GAME,
            T,
            source,
            target_date=TARGET,
            stats=stats,
            injuries=injuries,
        )
        assert from_live.pairs == from_training.pairs
        assert from_live.unknown_status_count == from_training.unknown_status_count

    actual = team_absences(
        "nba", HOME, TARGET_GAME, T, SOURCE_ACTUAL,
        target_date=TARGET, stats=stats, injuries=injuries,
    )
    reported = team_absences(
        "nba", HOME, TARGET_GAME, T, SOURCE_REPORTED,
        target_date=TARGET, stats=stats, injuries=injuries,
    )
    assert actual.pairs == ((ROT, 1.0), (DNP_PLAYER, 1.0))
    assert reported.pairs == ((ROT, 1.0), (DNP_PLAYER, 0.5), (ROW, 1.0))
    assert reported.unknown_status_count == 1
    assert PLAYED not in {player for player, _ in reported.pairs}
    assert TRADED not in {player for player, _ in actual.pairs}
    assert LOW not in {player for player, _ in actual.pairs}
    assert SHORT not in {player for player, _ in actual.pairs}


@pytest.mark.asyncio
async def test_export_inputs_keep_pregame_features_null_until_coverage_exists(seeded: str) -> None:
    conn = await asyncpg.connect(seeded, timeout=5)
    try:
        games, stats = await load_feature_rows(conn, league="nba", seasons=range(2025, 2026))
        injuries = await load_injuries(conn, league="nba")
        coverage, note = await injury_coverage_status(conn)
    finally:
        await conn.close()
    dataset = assemble_dataset(
        games,
        stats,
        _labels(TARGET_GAME, PLAYED) + _labels(TARGET_GAME, FILLER) + _labels(TARGET_GAME, ROW),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        injuries=injuries,
        injury_coverage=coverage,
        coverage_relation_note=note,
    )
    by_player = {row["bdl_player_id"]: row for row in dataset.rows if row["bdl_game_id"] == TARGET_GAME}
    assert by_player[ROW]["info_source"] == "pregame"
    assert by_player[ROW]["player_injury_status"] == OUT
    assert by_player[ROW]["team_missing_minutes"] is None
    assert by_player[PLAYED]["player_injury_status"] is None
    assert dataset.metadata["absence_coverage"] == "unknown"
    assert dataset.metadata["standin_row_count"] == 0
    assert dataset.metadata["pregame_row_count"] == dataset.metadata["row_count"]
    assert "not healthy" in str(dataset.metadata["absence_coverage_note"])


@pytest.mark.asyncio
async def test_loaded_game_lineups_starter_marks_the_row_standin(seeded: str) -> None:
    conn = await asyncpg.connect(seeded, timeout=5)
    try:
        games, stats = await load_feature_rows(conn, league="nba", seasons=range(2025, 2026))
        injuries = await load_injuries(conn, league="nba")
        lineups = await load_lineups(conn, league="nba", seasons=range(2025, 2026))
    finally:
        await conn.close()
    dataset = assemble_dataset(
        games,
        stats,
        _labels(TARGET_GAME, ROW),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        injuries=injuries,
        lineups=lineups,
    )
    row = next(item for item in dataset.rows if item["bdl_player_id"] == ROW and item["bdl_game_id"] == TARGET_GAME)
    assert row["is_starter"] is True
    assert row["info_source"] == "standin"
    assert row["player_injury_status"] is None
    assert dataset.metadata["standin_lineup_row_count"] >= 1
