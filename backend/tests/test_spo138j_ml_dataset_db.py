"""SPO-138j loader → labels → Parquet on a scratch database.

Applies 002 and 004 only. 003 is not on this branch and is not required.
The test skips when ``DATABASE_URL`` has no local Postgres; that skip is
this module, not the session.
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
from app.ml.build_dataset import main, metadata_path, read_git_head
from app.ml.labels import CATALOG_MARKETS
from app.ml.load import connect_readonly

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
FILES = ("002_bdl_core.sql", "004_read_layer.sql")
PLAYER = 237
HOME = 14
AWAY = 10


@pytest_asyncio.fixture
async def seeded(scratch_dsn: str) -> str:
    """Scratch database with 002, 004, and a two-season player."""
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
    season: int,
    on: date,
    *,
    home: int,
    status: str,
    tip: datetime | None,
    season_type: str = "regular_season",
) -> None:
    await conn.execute(
        """
        INSERT INTO games
            (league, bdl_game_id, season, date, datetime_utc, status_state, season_type,
             home_team_id, visitor_team_id)
        VALUES ('nba', $1, $2, $3, $4, $5, $6, $7, $8)
        """,
        game_id, season, on, tip, status, season_type, home, AWAY if home == HOME else HOME,
    )


async def _stat(
    conn: asyncpg.Connection,
    game_id: int,
    *,
    team: int,
    dnp: bool = False,
    pts: int | None = None,
    reb: int | None = None,
    ast: int | None = None,
    fg3m: int | None = None,
    stl: int | None = None,
    blk: int | None = None,
    seconds: int | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO player_game_stats
            (league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
             dnp, seconds_played, pts, reb, ast, fg3m, stl, blk)
        SELECT 'nba', $1, $2, $3, $4, g.season, g.date, $5, $6, $7, $8, $9, $10, $11, $12
        FROM games g
        WHERE g.league = 'nba' AND g.bdl_game_id = $2
        """,
        game_id * 1000 + PLAYER,
        game_id,
        PLAYER,
        team,
        dnp,
        seconds,
        pts,
        reb,
        ast,
        fg3m,
        stl,
        blk,
    )


async def _seed(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label) VALUES
            ('nba', 2014, '2014-15'), ('nba', 2015, '2015-16');
        INSERT INTO teams (league, bdl_team_id, abbreviation) VALUES
            ('nba', 14, 'LAL'), ('nba', 10, 'GSW');
        INSERT INTO players (league, bdl_player_id, display_name)
        VALUES ('nba', 237, 'LeBron James');
        """
    )
    for offset in range(8):
        on = date(2014, 12, 1) + timedelta(days=offset)
        await _game(
            conn, offset + 1, 2014, on, home=HOME, status="final",
            tip=datetime(on.year, on.month, on.day, 23, 0, tzinfo=UTC),
        )
        await _stat(
            conn, offset + 1, team=AWAY, pts=10 + offset, reb=4, ast=5, fg3m=2,
            stl=1, blk=1, seconds=1800,
        )

    async def final(
        game_id: int,
        on: date,
        *,
        team: int,
        home: int,
        pts: int | None,
        tip: datetime | None,
        season_type: str = "regular_season",
        fg3m: int | None = 1,
        reb: int = 2,
        ast: int = 2,
        stl: int = 0,
        blk: int = 0,
        seconds: int = 1800,
        dnp: bool = False,
        status: str = "final",
    ) -> None:
        await _game(
            conn, game_id, 2015, on, home=home, status=status, tip=tip, season_type=season_type,
        )
        if dnp:
            await _stat(conn, game_id, team=team, dnp=True)
            return
        await _stat(
            conn, game_id, team=team, pts=pts, reb=reb, ast=ast, fg3m=fg3m,
            stl=stl, blk=blk, seconds=seconds,
        )

    await final(
        201, date(2015, 10, 28), team=HOME, home=HOME, pts=30, reb=10, ast=8, fg3m=3,
        stl=1, blk=1, seconds=2000,
        tip=datetime(2015, 10, 28, 23, 0, tzinfo=UTC),
    )
    await final(
        202, date(2015, 10, 29), team=HOME, home=HOME, pts=40,
        tip=datetime(2015, 10, 29, 23, 0, tzinfo=UTC),
    )
    await final(203, date(2015, 10, 30), team=HOME, home=HOME, pts=11, tip=None)
    await final(204, date(2015, 10, 31), team=HOME, home=HOME, pts=None, tip=datetime(2015, 10, 31, 23, 0, tzinfo=UTC), dnp=True)
    await final(
        205, date(2015, 11, 1), team=HOME, home=HOME, pts=20, reb=10, ast=5, fg3m=None,
        stl=0, blk=0,
        tip=datetime(2015, 11, 1, 23, 0, tzinfo=UTC),
    )
    await final(
        206, date(2015, 11, 2), team=HOME, home=HOME, pts=99,
        tip=datetime(2015, 11, 2, 17, 0, tzinfo=UTC),
    )
    await final(
        207, date(2015, 11, 2), team=HOME, home=HOME, pts=5,
        tip=datetime(2015, 11, 2, 23, 0, tzinfo=UTC),
    )
    await final(
        208, date(2015, 11, 3), team=HOME, home=HOME, pts=77, status="scheduled",
        tip=datetime(2015, 11, 3, 23, 0, tzinfo=UTC),
    )
    await final(
        210, date(2015, 12, 1), team=HOME, home=AWAY, pts=18, season_type="playoffs",
        tip=datetime(2015, 12, 1, 23, 0, tzinfo=UTC),
    )
    await final(
        211, date(2015, 12, 20), team=HOME, home=HOME, pts=1000,
        tip=datetime(2015, 12, 20, 23, 0, tzinfo=UTC),
    )


def _row(frame: object, game_id: int) -> object:
    import pandas as pd

    assert isinstance(frame, pd.DataFrame)
    matched = frame.loc[frame["bdl_game_id"] == game_id]
    assert len(matched) == 1
    return matched.iloc[0]


def _cell(value: object) -> object:
    import pandas as pd

    if value is None or bool(pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


@pytest.mark.asyncio
async def test_cli_exports_form_labels_and_parquet(
    seeded: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pandas as pd

    monkeypatch.setenv("ML_DATABASE_URL", seeded)
    out = tmp_path / "player_games.parquet"
    # main() calls asyncio.run, which cannot nest inside the test's loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        code = pool.submit(
            main,
            ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2015", "--out", str(out)],
        ).result()
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "postgresql://" not in captured.out + captured.err
    frame = pd.read_parquet(out)
    meta = json.loads(metadata_path(out).read_text(encoding="utf-8"))

    assert meta["seasons"] == {"start": 2015, "end": 2015, "inclusive": True}
    assert meta["history_season_start"] == 2014
    assert meta["hours_before_tip"] == 3
    assert meta["null_tip_fallback_count"] == 1
    assert meta["git_head"] == read_git_head()
    assert meta["row_count"] == 8
    assert meta["rows_before_label_filter"] == 10
    assert meta["label_drop_count"] == 2
    assert meta["info_source"] == "pregame"
    assert meta["feature_sources"] == ["games", "player_game_stats"]
    assert set(frame["season"].astype(int)) == {2015}
    assert set(frame["info_source"]) == {"pregame"}
    assert "home_score" not in frame.columns
    assert not any(str(column).startswith("y_") and "prop" in str(column) for column in frame.columns)

    db_markets = None
    conn = await asyncpg.connect(seeded, timeout=5)
    try:
        db_markets = {
            row["market"]
            for row in await conn.fetch("SELECT market FROM prop_markets WHERE league = 'nba'")
        }
        assert await conn.fetchval("SELECT count(*) FROM predictions") == 0
    finally:
        await conn.close()
    assert db_markets == set(CATALOG_MARKETS)

    first = _row(frame, 201)
    assert _cell(first["n_played_prev"]) == 8
    assert _cell(first["pts_last_5"]) == 15
    assert _cell(first["pts_last_10"]) is None
    assert _cell(first["is_home"]) is True
    assert first["season_type"] == "regular_season"
    assert _cell(first["y_player_points"]) == 30
    assert _cell(first["y_player_rebounds"]) == 10
    assert _cell(first["y_player_points_rebounds_assists"]) == 30 + 10 + 8
    assert _cell(first["y_player_double_double"]) == 1
    assert _cell(first["y_player_triple_double"]) == 0
    assert _cell(first["tip_fallback"]) is False

    nxt = _row(frame, 202)
    assert _cell(nxt["days_rest"]) == 1
    assert _cell(nxt["is_back_to_back"]) is True
    assert _cell(nxt["pts_last_5"]) == pytest.approx((14 + 15 + 16 + 17 + 30) / 5)
    assert _cell(nxt["y_player_double_double"]) == 0

    fallback = _row(frame, 203)
    assert _cell(fallback["tip_fallback"]) is True
    expected = prediction_instant(date(2015, 10, 30), None)
    assert fallback["as_of"].to_pydatetime() == expected.as_of

    assert 204 not in set(frame["bdl_game_id"].astype(int))
    assert 208 not in set(frame["bdl_game_id"].astype(int))

    threes = _row(frame, 205)
    assert _cell(threes["y_player_threes"]) is None
    assert _cell(threes["y_player_points"]) == 20
    assert _cell(threes["y_player_double_double"]) == 1
    assert _cell(threes["y_player_triple_double"]) == 0
    assert _cell(threes["dnp_last_10"]) == 1
    assert _cell(threes["days_rest"]) == 1
    assert _cell(threes["n_played_prev"]) == 11
    history_pts = list(range(10, 18)) + [30, 40, 11]
    assert _cell(threes["pts_last_10"]) == pytest.approx(sum(history_pts[-10:]) / 10)

    later_same_day = _row(frame, 207)
    assert _cell(later_same_day["n_played_prev"]) == 12
    played_before = history_pts + [20]
    assert _cell(later_same_day["pts_last_5"]) == pytest.approx(sum(played_before[-5:]) / 5)

    away = _row(frame, 210)
    assert _cell(away["is_home"]) is False
    assert away["season_type"] == "playoffs"
    assert _cell(away["n_played_prev"]) == 15


@pytest.mark.asyncio
async def test_readonly_connection_does_not_write(seeded: str) -> None:
    conn = await connect_readonly(seeded)
    try:
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute("INSERT INTO predictions (league) VALUES ('nba')")
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute("CREATE TABLE spo138j_should_not_exist (id integer)")
    finally:
        await conn.close()
    check = await asyncpg.connect(seeded, timeout=5)
    try:
        assert await check.fetchval("SELECT count(*) FROM predictions") == 0
        assert await check.fetchval("SELECT to_regclass('public.spo138j_should_not_exist')") is None
    finally:
        await check.close()
