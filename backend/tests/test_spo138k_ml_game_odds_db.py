"""SPO-138k opening odds through the loader and the CLI.

Applies 002 and 004 only. The opener-timing queries are executed here only
to prove they parse. The scratch rows are not the real measurement, which
stays PENDING.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from app.ml.asof import prediction_instant
from app.ml.build_dataset import main, metadata_path
from app.ml.game_odds import MEASUREMENT_SQL

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
REPO = Path(__file__).resolve().parents[2]
FILES = ("002_bdl_core.sql", "004_read_layer.sql")
PLAYER = 237
OTHER = 115
HOME = 14
AWAY = 10


def _statements(text: str) -> list[str]:
    """Split the timing script into statements, dropping full-line comments."""
    statements: list[str] = []
    for chunk in text.split(";"):
        lines = [
            line
            for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if lines:
            statements.append("\n".join(lines))
    return statements


@pytest_asyncio.fixture
async def seeded(scratch_dsn: str) -> str:
    """Scratch database with 002, 004, three games, and mixed odds rows."""
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        async with conn.transaction():
            for name in FILES:
                await conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
        await _seed(conn)
    finally:
        await conn.close()
    return scratch_dsn


async def _seed(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES
            ('nba', 2015, '2015-16');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES
            ('nba', 14, 'LAL'), ('nba', 10, 'GSW');
        INSERT INTO players (league, bdl_player_id, display_name) VALUES
            ('nba', 237, 'LeBron James'), ('nba', 115, 'Stephen Curry');
        """
    )
    tip = datetime(2015, 10, 28, 23, 0, tzinfo=UTC)
    boundary = tip - timedelta(hours=3)
    await _game(conn, 301, date(2015, 10, 28), HOME, tip)
    await _game(conn, 302, date(2015, 11, 1), AWAY, datetime(2015, 11, 1, 23, 0, tzinfo=UTC))
    await _game(conn, 303, date(2015, 10, 30), HOME, None)
    await _stat(conn, 301, PLAYER, HOME, 20)
    await _stat(conn, 301, OTHER, HOME, 18)
    await _stat(conn, 302, PLAYER, HOME, 16)
    await _stat(conn, 303, PLAYER, HOME, 14)

    await _line(conn, 301, "draftkings", "opening", boundary - timedelta(seconds=1), -6, 200)
    await _line(conn, 301, "fanduel", "opening", boundary, -4, 240)
    await _line(conn, 301, "betmgm", "opening", boundary + timedelta(seconds=1), -100, 900)
    await _line(conn, 301, "caesars", "closing", boundary - timedelta(hours=1), 50, 400)
    await _line(conn, 301, "betrivers", "opening", None, -2, 210)
    await _line(conn, 301, "fanatics", "opening", boundary - timedelta(hours=1), None, None)
    await _line(conn, 301, "betway", "live", boundary - timedelta(hours=1), 80, 500)

    await _line(
        conn, 302, "draftkings", "opening",
        datetime(2015, 11, 1, 20, 0, tzinfo=UTC), -4.5, 220.5,
    )
    null_tip_t = prediction_instant(date(2015, 10, 30), None).as_of
    await _line(conn, 303, "draftkings", "opening", null_tip_t - timedelta(hours=1), -4, 220)
    await _line(conn, 303, "fanduel", "opening", null_tip_t + timedelta(seconds=1), -100, 900)


async def _game(
    conn: asyncpg.Connection,
    game_id: int,
    on: date,
    home: int,
    tip: datetime | None,
) -> None:
    visitor = AWAY if home == HOME else HOME
    await conn.execute(
        """
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, status_state, season_type,
             home_team_id, visitor_team_id)
        VALUES ('nba', $1, 2015, $2, $3, 'final', 'regular_season', $4, $5)
        """,
        game_id, on, tip, home, visitor,
    )


async def _stat(conn: asyncpg.Connection, game_id: int, player: int, team: int, pts: int) -> None:
    await conn.execute(
        """
        INSERT INTO player_game_stats
            (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
             dnp, seconds_played, pts, reb, ast, fg3m, stl, blk)
        SELECT 'nba', $1, $2, $3, $4, g.season, g.date, FALSE, 1800, $5, 4, 5, 1, 1, 1
        FROM games g
        WHERE g.league = 'nba' AND g.bdl_game_id = $2
        """,
        game_id * 1000 + player, game_id, player, team, pts,
    )


async def _line(
    conn: asyncpg.Connection,
    game_id: int,
    book: str,
    kind: str,
    snapshot_at: datetime | None,
    spread: float | None,
    total: float | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO game_odds_snapshots
            (league, snapshot_kind, bdl_game_id, book_key, snapshot_at,
             spread_home_value, total_value)
        VALUES ('nba', $1, $2, $3, $4, $5, $6)
        """,
        kind, game_id, book, snapshot_at, spread, total,
    )


def _cell(value: object) -> object:
    import pandas as pd

    if value is None or bool(pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


@pytest.mark.asyncio
async def test_cli_exports_opening_medians_without_writing_predictions(
    seeded: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pandas as pd

    monkeypatch.setenv("ML_DATABASE_URL", seeded)
    out = tmp_path / "player_games.parquet"
    with ThreadPoolExecutor(max_workers=1) as pool:
        code = pool.submit(
            main,
            ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2015", "--out", str(out)],
        ).result()
    captured = capsys.readouterr()
    assert code == 0, captured.err
    blob = captured.out + captured.err
    assert "postgresql://" not in blob
    assert seeded not in blob

    frame = pd.read_parquet(out)
    meta = json.loads(metadata_path(out).read_text(encoding="utf-8"))
    assert len(frame) == 4
    assert meta["game_odds_measurement"] == "PENDING"
    assert meta["game_odds_measurement_sql"] == MEASUREMENT_SQL
    assert "not an immutable" in meta["game_odds_limitation"]
    assert meta["game_odds_coverage"]["kept_rows"] == 4
    assert meta["game_odds_coverage"]["games_with_eligible_book"] == 3
    assert meta["game_odds_coverage"]["rows_with_implied_points"] == 4
    assert "://" not in metadata_path(out).read_text(encoding="utf-8")

    home_rows = frame.loc[frame["bdl_game_id"] == 301]
    assert len(home_rows) == 2
    assert set(home_rows["bdl_player_id"].astype(int)) == {PLAYER, OTHER}
    for _, row in home_rows.iterrows():
        assert _cell(row["opening_books"]) == 3
        assert _cell(row["opening_spread_books"]) == 2
        assert _cell(row["opening_total_books"]) == 2
        assert _cell(row["opening_spread_home"]) == -5
        assert _cell(row["opening_total"]) == 220
        assert _cell(row["is_home"]) is True
        assert _cell(row["team_implied_points"]) == 112.5
        assert _cell(row["opp_implied_points"]) == 107.5

    away = frame.loc[frame["bdl_game_id"] == 302].iloc[0]
    assert _cell(away["is_home"]) is False
    assert _cell(away["opening_books"]) == 1
    assert _cell(away["opening_spread_home"]) == -4.5
    assert _cell(away["opening_total"]) == 220.5
    assert _cell(away["team_implied_points"]) == 108
    assert _cell(away["opp_implied_points"]) == 112.5

    fallback = frame.loc[frame["bdl_game_id"] == 303].iloc[0]
    assert _cell(fallback["tip_fallback"]) is True
    assert fallback["as_of"].to_pydatetime() == prediction_instant(date(2015, 10, 30), None).as_of
    assert _cell(fallback["opening_books"]) == 1
    assert _cell(fallback["team_implied_points"]) == 112
    assert _cell(fallback["opp_implied_points"]) == 108

    conn = await asyncpg.connect(seeded, timeout=5)
    try:
        assert await conn.fetchval("SELECT count(*) FROM predictions") == 0
        assert await conn.fetchval("SELECT count(*) FROM player_prop_snapshots") == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_opener_timing_sql_parses_and_is_not_the_measurement(seeded: str) -> None:
    """The script runs on Postgres 16. Scratch totals are not the finding."""
    statements = _statements((REPO / MEASUREMENT_SQL).read_text(encoding="utf-8"))
    assert len(statements) == 4
    conn = await asyncpg.connect(seeded, timeout=5)
    try:
        season_rows = await conn.fetch(statements[0])
        per_game = await conn.fetch(statements[1])
        rollup = await conn.fetch(statements[2])
        coverage = await conn.fetch(statements[3])
    finally:
        await conn.close()
    assert [row["season"] for row in season_rows] == [2015]
    assert season_rows[0]["null_snapshot_at"] == 1
    assert season_rows[0]["null_tip"] == 2
    assert "books_at_or_before_t" in per_game[0].keys()
    assert "median_books_at_or_before_t" in rollup[0].keys()
    assert coverage[0]["games"] == 3
    assert coverage[0]["games_with_any_opening_row"] == 3
