"""SPO-138j dataset core, without a database.

Source boundaries, form features, labels, and the Parquet round trip. The
scratch-database path is ``test_spo138j_ml_dataset_db.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.ml.asof import DEFAULT_HOURS_BEFORE_TIP, prediction_instant
from app.ml.build_dataset import (
    OUTPUT_COLUMNS,
    assemble_dataset,
    build_parser,
    metadata_path,
    parse_seasons,
    write_outputs,
)
from app.ml.features import DNP_ROW_WINDOW, features_for_target
from app.ml.labels import CATALOG_MARKETS, pivot_labels
from app.ml.load import (
    READ_QUERIES,
    ActualRecord,
    GameRecord,
    LoadError,
    StatRecord,
    connect_readonly,
    dsn_from_env,
    load_feature_rows,
    load_labels,
    load_span,
    output_span,
    sanitize_error,
)
from app.ml.sources import (
    PRIOR_DATE,
    TIMESTAMP,
    SourceError,
    require_feature_source,
    require_label_source,
    row_is_visible,
)

PLAYER = 237
OTHER = 115
HOME = 14
AWAY = 10
SECRET_DSN = "postgresql://ml_user:super-secret-password@db.internal:5432/nba"


def _game(
    game_id: int,
    on: date,
    season: int,
    *,
    tip: datetime | None | object = "set",
    home: int | None = HOME,
    season_type: str = "regular_season",
) -> GameRecord:
    if tip == "set":
        tip_at: datetime | None = datetime(on.year, on.month, on.day, 23, 0, tzinfo=UTC)
    else:
        tip_at = tip  # type: ignore[assignment]
    return GameRecord(
        league="nba",
        bdl_game_id=game_id,
        season=season,
        game_date=on,
        datetime_utc=tip_at,
        season_type=season_type,
        home_team_id=home,
    )


def _stat(
    game_id: int,
    on: date,
    season: int,
    *,
    player: int = PLAYER,
    team: int = HOME,
    dnp: bool = False,
    pts: int | None = 10,
    reb: int | None = 4,
    ast: int | None = 5,
    fg3m: int | None = 2,
    stl: int | None = 1,
    blk: int | None = 1,
    seconds: int | None = 1800,
) -> StatRecord:
    if dnp:
        pts = reb = ast = fg3m = stl = blk = seconds = None
    return StatRecord(
        league="nba",
        bdl_game_id=game_id,
        bdl_player_id=player,
        bdl_team_id=team,
        season=season,
        game_date=on,
        dnp=dnp,
        seconds_played=seconds,
        pts=pts,
        reb=reb,
        ast=ast,
        fg3m=fg3m,
        stl=stl,
        blk=blk,
    )


def _actuals(game_id: int, player: int = PLAYER, **markets: int | None) -> list[ActualRecord]:
    return [
        ActualRecord("nba", game_id, player, market, markets.get(market))
        for market in CATALOG_MARKETS
    ]


def _kept(game_id: int, player: int = PLAYER, **overrides: int | None) -> list[ActualRecord]:
    values: dict[str, int | None] = {market: 0 for market in CATALOG_MARKETS}
    values["player_points"] = 10
    values.update(overrides)
    return _actuals(game_id, player, **values)


def _build(
    games: list[GameRecord],
    stats: list[StatRecord],
    actuals: list[ActualRecord],
    *,
    start: int = 2015,
    end: int = 2015,
    hours: float = DEFAULT_HOURS_BEFORE_TIP,
) -> list[dict[str, object]]:
    dataset = assemble_dataset(
        games,
        stats,
        actuals,
        season_start=start,
        season_end=end,
        hours_before_tip=hours,
        git_head="test-sha",
    )
    return dataset.rows


def test_timestamp_boundary_includes_t_and_excludes_the_next_second() -> None:
    as_of = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
    kwargs = {"row_date": None, "target_date": None, "as_of": as_of}
    assert row_is_visible(TIMESTAMP, observed_at=as_of - timedelta(seconds=1), **kwargs)
    assert row_is_visible(TIMESTAMP, observed_at=as_of, **kwargs)
    assert not row_is_visible(TIMESTAMP, observed_at=as_of + timedelta(seconds=1), **kwargs)
    assert not row_is_visible(TIMESTAMP, observed_at=None, **kwargs)


def test_games_and_stats_use_the_prior_date_rule_including_same_day() -> None:
    target = date(2026, 1, 15)
    as_of = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
    for name in ("games", "player_game_stats"):
        spec = require_feature_source(name)
        assert spec.visibility == PRIOR_DATE
        assert spec.role == "feature"
        # A same-day game whose tip is already before T is still hidden.
        assert not row_is_visible(
            spec.visibility,
            observed_at=as_of - timedelta(seconds=1),
            row_date=target,
            target_date=target,
            as_of=as_of,
        )
        assert row_is_visible(
            spec.visibility,
            observed_at=None,
            row_date=target - timedelta(days=1),
            target_date=target,
            as_of=None,
        )
        assert not row_is_visible(
            spec.visibility,
            observed_at=None,
            row_date=target + timedelta(days=1),
            target_date=target,
            as_of=None,
        )


def test_allow_list_rejects_props_unknown_sources_and_label_routes() -> None:
    with pytest.raises(SourceError, match="player_prop_snapshots"):
        require_feature_source("player_prop_snapshots")
    with pytest.raises(SourceError, match="player_prop_snapshots"):
        require_label_source("player_prop_snapshots")
    with pytest.raises(SourceError, match="feature allow-list"):
        require_feature_source("injury_snapshots")
    with pytest.raises(SourceError, match="not a feature"):
        require_feature_source("prop_actuals")
    with pytest.raises(SourceError, match="not a label"):
        require_label_source("player_game_stats")
    assert require_label_source("prop_actuals").role == "label"
    with pytest.raises(SourceError, match="unknown visibility"):
        row_is_visible("whenever", observed_at=None, row_date=None, target_date=None, as_of=None)


def test_default_hours_before_tip_is_three_and_null_tip_uses_new_york_midnight() -> None:
    assert DEFAULT_HOURS_BEFORE_TIP == 3
    tip = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    known = prediction_instant(date(2026, 1, 15), tip)
    assert known.as_of == datetime(2026, 1, 15, 21, 30, tzinfo=UTC)
    assert known.tip_fallback is False
    assert known.hours_before_tip == 3

    winter = prediction_instant(date(2026, 1, 15), None)
    assert winter.tip_fallback is True
    assert winter.as_of == datetime(2026, 1, 15, 5, 0, tzinfo=UTC)
    assert prediction_instant(date(2026, 1, 15), None, hours_before_tip=9).as_of == winter.as_of

    summer = prediction_instant(date(2026, 7, 15), None, hours_before_tip=6)
    assert summer.tip_fallback is True
    assert summer.as_of == datetime(2026, 7, 15, 4, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="timezone-aware"):
        prediction_instant(date(2026, 1, 15), datetime(2026, 1, 15, 23, 0))
    with pytest.raises(ValueError, match=">= 0"):
        prediction_instant(date(2026, 1, 15), tip, hours_before_tip=-1)


def test_own_game_later_game_and_same_day_game_do_not_change_features() -> None:
    """Five prior games of 10 points. The target, a same-day 999, and a later 1000 stay out."""
    prior = []
    games = []
    for offset in range(5):
        on = date(2015, 10, 20 + offset)
        prior.append(_stat(offset + 1, on, 2015, pts=10))
        games.append(_game(offset + 1, on, 2015))
    target_day = date(2015, 10, 28)
    same_day = _stat(50, target_day, 2015, pts=999)
    target = _stat(51, target_day, 2015, pts=500)
    later = _stat(52, date(2015, 10, 29), 2015, pts=1000)
    games.extend(
        [
            _game(50, target_day, 2015),
            _game(51, target_day, 2015),
            _game(52, date(2015, 10, 29), 2015),
        ]
    )
    rows = _build(
        games,
        prior + [target, same_day, later],
        _kept(51, player_points=500) + _kept(50, player_points=999) + _kept(52, player_points=1000),
    )
    target_row = next(row for row in rows if row["bdl_game_id"] == 51)
    assert target_row["n_played_prev"] == 5
    assert target_row["n_prev_games"] == 5
    assert target_row["pts_last_5"] == 10
    assert target_row["pts_last_10"] is None
    assert target_row["seconds_played_last_5"] == 1800
    assert 999 not in (target_row["pts_last_5"], target_row["pts_last_10"])
    assert target_row["y_player_points"] == 500


def test_shuffled_input_and_season_boundaries_produce_the_same_rows() -> None:
    games: list[GameRecord] = []
    stats: list[StatRecord] = []
    for offset in range(10):
        on = date(2014, 12, 1) + timedelta(days=offset)
        games.append(_game(offset + 1, on, 2014))
        stats.append(_stat(offset + 1, on, 2014, pts=offset + 1, team=AWAY))
    games.append(_game(100, date(2015, 10, 28), 2015))
    stats.append(_stat(100, date(2015, 10, 28), 2015, pts=50, team=HOME))
    games.append(_game(200, date(2016, 1, 15), 2016, season_type="playoffs", home=AWAY))
    stats.append(_stat(200, date(2016, 1, 15), 2016, pts=999, team=HOME))
    actuals = _kept(100, player_points=50) + _kept(200, player_points=999)

    only = assemble_dataset(
        games, stats, actuals, season_start=2015, season_end=2015, git_head="test-sha"
    )
    both = assemble_dataset(
        list(reversed(games)),
        list(reversed(stats)),
        list(reversed(actuals)),
        season_start=2015,
        season_end=2016,
        git_head="test-sha",
    )
    assert [row["season"] for row in only.rows] == [2015]
    assert only.rows[0]["pts_last_10"] == sum(range(1, 11)) / 10
    assert only.rows[0]["pts_last_5"] == sum(range(6, 11)) / 5
    assert only.rows[0]["n_played_prev"] == 10
    assert only.rows[0]["is_home"] is True
    season_2015 = next(row for row in both.rows if row["bdl_game_id"] == 100)
    assert season_2015 == only.rows[0]
    later = next(row for row in both.rows if row["bdl_game_id"] == 200)
    assert later["season_type"] == "playoffs"
    assert later["is_home"] is False
    assert later["n_played_prev"] == 11
    assert later["pts_last_10"] == (sum(range(1, 11)) - 1 + 50) / 10
    assert later["y_player_points"] == 999


def test_dnp_is_not_a_played_game_and_not_a_zero() -> None:
    days = [date(2015, 11, 1) + timedelta(days=offset) for offset in range(5)]
    stats = [
        _stat(1, days[0], 2015, pts=10),
        _stat(2, days[1], 2015, dnp=True),
        _stat(3, days[2], 2015, pts=30),
        _stat(4, days[3], 2015, dnp=True),
        _stat(5, days[4], 2015, pts=12),
    ]
    games = [_game(row.bdl_game_id, row.game_date, 2015) for row in stats]
    # The DNP line's actuals are all NULL. It must not become a row of zeros.
    actuals = _kept(5, player_points=12) + _actuals(4) + _kept(1) + _kept(3)
    rows = _build(games, stats, actuals)
    assert [row["bdl_game_id"] for row in rows] == [1, 3, 5]
    target = rows[-1]
    assert target["n_prev_games"] == 4
    assert target["n_played_prev"] == 2
    assert target["pts_last_5"] is None
    assert target["pts_last_10"] is None
    assert target["dnp_last_10"] == 2
    assert target["dnp_last_10_window"] == 4
    assert target["days_rest"] == 1
    assert target["is_back_to_back"] is True
    assert target["y_player_points"] == 12


def test_dnp_last_10_counts_rows_not_the_played_window() -> None:
    """The oldest of 11 prior rows is a DNP and sits outside the last-10-row window."""
    assert DNP_ROW_WINDOW == 10
    stats = [_stat(1, date(2015, 10, 1), 2015, dnp=True)]
    for offset in range(10):
        stats.append(_stat(offset + 2, date(2015, 10, 2) + timedelta(days=offset), 2015, pts=10))
    target_day = date(2015, 10, 20)
    stats.append(_stat(20, target_day, 2015, pts=15))
    games = [_game(row.bdl_game_id, row.game_date, 2015) for row in stats]
    rows = _build(games, stats, _kept(20, player_points=15))
    target = rows[-1]
    assert target["n_prev_games"] == 11
    assert target["n_played_prev"] == 10
    assert target["dnp_last_10"] == 0
    assert target["dnp_last_10_window"] == 10
    assert target["pts_last_10"] == 10

    # A DNP inside the last 10 rows counts, and it is not inside the played mean.
    mixed = [_stat(offset + 1, date(2015, 1, 1) + timedelta(days=offset), 2015, pts=8) for offset in range(9)]
    mixed.append(_stat(30, date(2015, 1, 20), 2015, dnp=True))
    mixed.append(_stat(31, date(2015, 1, 21), 2015, pts=18))
    mixed_games = [_game(row.bdl_game_id, row.game_date, 2015) for row in mixed]
    mixed_rows = _build(mixed_games, mixed, _kept(31, player_points=18))
    latest = mixed_rows[-1]
    assert latest["dnp_last_10"] == 1
    assert latest["n_played_prev"] == 9
    assert latest["pts_last_10"] is None
    assert latest["pts_last_5"] == 8
    assert latest["days_rest"] == 1


def test_too_little_history_is_null_plus_the_count_and_a_null_stat_is_not_skipped() -> None:
    stats = [_stat(offset + 1, date(2015, 10, offset + 1), 2015, pts=10) for offset in range(3)]
    target = _stat(9, date(2015, 10, 20), 2015, pts=20)
    games = [_game(row.bdl_game_id, row.game_date, 2015) for row in stats + [target]]
    row = _build(games, stats + [target], _kept(9, player_points=20))[0]
    assert row["n_played_prev"] == 3
    assert row["n_prev_games"] == 3
    assert row["pts_last_5"] is None
    assert row["pts_last_10"] is None
    assert row["days_rest"] == 17
    assert row["is_back_to_back"] is False

    partial = [_stat(offset + 1, date(2015, 11, offset + 1), 2015, pts=10) for offset in range(4)]
    partial.append(_stat(8, date(2015, 11, 10), 2015, pts=None, reb=6))
    partial.append(_stat(9, date(2015, 11, 12), 2015, pts=20))
    partial_games = [_game(row.bdl_game_id, row.game_date, 2015) for row in partial]
    partial_row = _build(partial_games, partial, _kept(9))[0]
    assert partial_row["n_played_prev"] == 5
    assert partial_row["pts_last_5"] is None
    assert partial_row["reb_last_5"] == (4 * 4 + 6) / 5


def test_rest_home_and_a_trade_use_the_target_row() -> None:
    first = _stat(1, date(2015, 10, 1), 2015, team=AWAY, pts=12)
    target = _stat(2, date(2015, 10, 3), 2015, team=HOME, pts=22)
    games = [
        _game(1, date(2015, 10, 1), 2015, home=HOME),
        _game(2, date(2015, 10, 3), 2015, home=HOME, season_type="playoffs"),
    ]
    rows = _build(games, [first, target], _kept(1, player_points=12) + _kept(2, player_points=22))
    assert rows[0]["is_home"] is False
    assert rows[0]["season_type"] == "regular_season"
    assert rows[0]["days_rest"] is None
    assert rows[0]["is_back_to_back"] is None
    assert rows[1]["is_home"] is True
    assert rows[1]["bdl_team_id"] == HOME
    assert rows[1]["season_type"] == "playoffs"
    assert rows[1]["days_rest"] == 2
    assert rows[1]["is_back_to_back"] is False

    no_home = _game(2, date(2015, 10, 3), 2015, home=None)
    bare = features_for_target([first, target], target, no_home)
    assert bare["is_home"] is None


def test_labels_keep_per_market_nulls_drop_all_null_rows_and_pass_through_doubles() -> None:
    assert pivot_labels({}) is None
    assert pivot_labels({"player_points": None, "not_a_market": 9}) is None
    kept = pivot_labels(
        {
            "player_points": 20,
            "player_threes": None,
            "player_double_double": 1,
            "player_triple_double": 0,
        }
    )
    assert kept is not None
    assert kept["y_player_points"] == 20
    assert kept["y_player_threes"] is None
    assert kept["y_player_double_double"] == 1
    assert kept["y_player_triple_double"] == 0
    assert kept["y_player_rebounds"] is None

    on = date(2015, 12, 1)
    dnp_day = date(2015, 12, 2)
    games = [_game(1, on, 2015), _game(2, dnp_day, 2015)]
    stats = [_stat(1, on, 2015, pts=20), _stat(2, dnp_day, 2015, dnp=True)]
    actuals = _actuals(
        1,
        player_points=20,
        player_rebounds=10,
        player_assists=4,
        player_threes=None,
        player_steals=1,
        player_blocks=0,
        player_points_rebounds=30,
        player_points_assists=24,
        player_rebounds_assists=14,
        player_points_rebounds_assists=34,
        player_double_double=1,
        player_triple_double=0,
    ) + _actuals(2)
    dataset = assemble_dataset(
        games, stats, actuals, season_start=2015, season_end=2015, git_head="test-sha"
    )
    assert dataset.metadata["rows_before_label_filter"] == 2
    assert dataset.metadata["label_drop_count"] == 1
    assert dataset.metadata["row_count"] == 1
    assert dataset.metadata["label_null_counts"]["y_player_threes"] == 1
    assert dataset.metadata["label_null_counts"]["y_player_points"] == 0
    row = dataset.rows[0]
    assert row["y_player_double_double"] == 1
    assert row["y_player_triple_double"] == 0
    assert row["y_player_threes"] is None
    assert row["info_source"] == "pregame"
    assert row["pts_last_5"] is None


def test_labels_do_not_change_feature_values() -> None:
    on = date(2015, 10, 28)
    prior = date(2015, 10, 20)
    games = [_game(1, prior, 2015), _game(2, on, 2015, tip=None)]
    stats = [_stat(1, prior, 2015, pts=10), _stat(2, on, 2015, pts=40)]
    low = assemble_dataset(
        games, stats, _kept(2, player_points=1), season_start=2015, season_end=2015, git_head="sha"
    )
    high = assemble_dataset(
        games,
        stats,
        _kept(2, player_points=99, player_double_double=1),
        season_start=2015,
        season_end=2015,
        git_head="sha",
    )
    feature_names = [name for name in OUTPUT_COLUMNS if not name.startswith("y_")]
    assert {name: low.rows[0][name] for name in feature_names} == {
        name: high.rows[0][name] for name in feature_names
    }
    assert low.rows[0]["y_player_points"] == 1
    assert high.rows[0]["y_player_points"] == 99
    assert high.rows[0]["tip_fallback"] is True
    assert high.metadata["null_tip_fallback_count"] == 1
    assert high.rows[0]["as_of"] == prediction_instant(on, None).as_of
    assert high.metadata["info_source"] == "pregame"
    assert high.metadata["feature_sources"] == [
        "games",
        "player_game_stats",
        "game_odds_snapshots",
    ]
    assert high.metadata["label_source"] == "prop_actuals"
    assert "player_prop_snapshots" not in high.metadata["feature_sources"]


def test_another_players_games_are_not_this_players_form() -> None:
    on = date(2015, 10, 28)
    games = [_game(1, date(2015, 10, 1), 2015), _game(2, on, 2015)]
    stats = [
        _stat(1, date(2015, 10, 1), 2015, player=OTHER, pts=80),
        _stat(2, on, 2015, player=PLAYER, pts=11),
    ]
    rows = _build(games, stats, _kept(2, player_points=11))
    assert rows[0]["n_played_prev"] == 0
    assert rows[0]["pts_last_5"] is None


def test_season_window_is_inclusive_and_loads_the_prior_season() -> None:
    assert parse_seasons("2015:2025") == (2015, 2025)
    assert list(output_span(2015, 2025))[0] == 2015
    assert list(output_span(2015, 2025))[-1] == 2025
    assert list(load_span(2015, 2025))[0] == 2014
    assert list(load_span(2015, 2015)) == [2014, 2015]
    with pytest.raises(Exception):
        parse_seasons("2025:2015")
    with pytest.raises(Exception):
        parse_seasons("2015-2025")
    help_text = build_parser().format_help()
    assert "inclusive" in help_text
    args = build_parser().parse_args(
        ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2025", "--out", "x.parquet"]
    )
    assert args.hours_before_tip == 3
    assert args.seasons == (2015, 2025)
    assert metadata_path(Path("exports/player_games.parquet")) == Path("exports/player_games.meta.json")


def test_queries_are_selects_and_do_not_touch_props_scores_or_predictions() -> None:
    for sql in READ_QUERIES:
        folded = " ".join(sql.lower().split())
        assert folded.startswith("select")
        for forbidden in ("insert", "update", "delete", "predictions", "player_prop_snapshots", "home_score"):
            assert forbidden not in folded
    assert "prop_actuals" in READ_QUERIES[2].lower()


def test_feature_loads_are_one_query_per_season() -> None:
    class _Txn:
        async def __aenter__(self) -> "_Txn":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

    class _Conn:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def transaction(self, readonly: bool = False) -> _Txn:
            assert readonly is True
            return _Txn()

        async def fetch(self, sql: str, *args: object) -> list[object]:
            self.calls.append((sql, args))
            return []

    conn = _Conn()
    games, stats = asyncio.run(
        load_feature_rows(conn, league="nba", seasons=load_span(2015, 2016))
    )
    assert games == []
    assert stats == []
    assert [call[1] for call in conn.calls] == [
        ("nba", 2014),
        ("nba", 2014),
        ("nba", 2015),
        ("nba", 2015),
        ("nba", 2016),
        ("nba", 2016),
    ]
    assert conn.calls[0][0].lstrip().startswith("SELECT")
    label_conn = _Conn()
    asyncio.run(load_labels(label_conn, league="nba", seasons=output_span(2015, 2016)))
    assert [call[1] for call in label_conn.calls] == [("nba", 2015), ("nba", 2016)]
    assert "prop_actuals" in label_conn.calls[0][0]


def test_connection_errors_and_a_missing_env_var_hide_the_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = sanitize_error(OSError(f"failed {SECRET_DSN}"), SECRET_DSN)
    assert "super-secret-password" not in hidden
    assert SECRET_DSN not in hidden
    assert "postgresql://" not in hidden
    assert "db.internal" not in hidden

    async def _boom(*args: object, **kwargs: object) -> None:
        raise OSError(f"could not connect to {SECRET_DSN}")

    monkeypatch.setattr("app.ml.load.asyncpg.connect", _boom)
    with pytest.raises(LoadError) as caught:
        asyncio.run(connect_readonly(SECRET_DSN))
    assert "super-secret-password" not in str(caught.value)
    assert SECRET_DSN not in str(caught.value)

    monkeypatch.delenv("ML_DATABASE_URL", raising=False)
    with pytest.raises(LoadError, match="ML_DATABASE_URL") as missing:
        dsn_from_env("ML_DATABASE_URL")
    assert "postgresql://" not in str(missing.value)


def test_cli_connection_error_does_not_print_the_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from app.ml.build_dataset import main

    monkeypatch.setenv("ML_DATABASE_URL", SECRET_DSN.replace("db.internal:5432", "127.0.0.1:1"))
    code = main(
        [
            "--dsn-env",
            "ML_DATABASE_URL",
            "--seasons",
            "2015:2015",
            "--out",
            str(tmp_path / "x.parquet"),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert "super-secret-password" not in blob
    assert "postgresql://" not in blob
    assert "ml_user" not in blob


def test_parquet_and_metadata_round_trip(tmp_path: Path) -> None:
    import pandas as pd

    on = date(2015, 10, 28)
    games = [_game(1, date(2015, 10, 1), 2014), _game(2, on, 2015, tip=None)]
    stats = [
        _stat(1, date(2015, 10, 1), 2014, pts=14),
        _stat(2, on, 2015, pts=21),
    ]
    dataset = assemble_dataset(
        games,
        stats,
        _actuals(
            2,
            player_points=21,
            player_rebounds=4,
            player_assists=5,
            player_threes=None,
            player_double_double=0,
            player_triple_double=0,
        ),
        season_start=2015,
        season_end=2015,
        git_head="abc123",
    )
    out = tmp_path / "nested" / "player_games.parquet"
    meta_path = write_outputs(dataset, out)
    assert meta_path == tmp_path / "nested" / "player_games.meta.json"
    frame = pd.read_parquet(out)
    assert list(frame.columns) == list(OUTPUT_COLUMNS)
    assert len(frame) == 1
    assert int(frame.loc[0, "y_player_points"]) == 21
    assert pd.isna(frame.loc[0, "y_player_threes"])
    assert int(frame.loc[0, "y_player_double_double"]) == 0
    assert frame.loc[0, "info_source"] == "pregame"
    assert bool(frame.loc[0, "tip_fallback"]) is True
    assert int(frame.loc[0, "n_played_prev"]) == 1
    assert pd.isna(frame.loc[0, "pts_last_5"])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["seasons"] == {"start": 2015, "end": 2015, "inclusive": True}
    assert meta["hours_before_tip"] == 3
    assert meta["null_tip_fallback_count"] == 1
    assert meta["git_head"] == "abc123"
    assert meta["row_count"] == 1
    assert meta["label_drop_count"] == 0
    assert "datetime_utc" in meta["t_rule"]
    assert "America/New_York" in meta["t_rule"]

    empty = assemble_dataset([], [], [], season_start=2015, season_end=2015, git_head="abc123")
    empty_out = tmp_path / "empty.parquet"
    write_outputs(empty, empty_out)
    empty_frame = pd.read_parquet(empty_out)
    assert list(empty_frame.columns) == list(OUTPUT_COLUMNS)
    assert len(empty_frame) == 0
    assert json.loads(metadata_path(empty_out).read_text(encoding="utf-8"))["row_count"] == 0


def test_importing_the_api_does_not_import_the_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = ""
    env.pop("ML_DATABASE_URL", None)
    script = (
        "import app.main, sys; "
        "bad = [name for name in sys.modules if name == 'app.ml' or name.startswith('app.ml.')]; "
        "raise SystemExit(1 if bad else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
