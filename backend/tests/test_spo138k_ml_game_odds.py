"""SPO-138k opening game odds, without a database.

The allow-list, the shared T, medians, and implied points. The scratch
database path is ``test_spo138k_ml_game_odds_db.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.ml.asof import prediction_instant
from app.ml.build_dataset import OUTPUT_COLUMNS, assemble_dataset
from app.ml.game_odds import (
    MEASUREMENT_SQL,
    MEASUREMENT_STATUS,
    ODDS_COLUMNS,
    OPENING_ODDS_LIMITATION,
    GameOddsError,
    implied_team_points,
    median_value,
    opening_odds_features,
)
from app.ml.labels import CATALOG_MARKETS
from app.ml.load import (
    GAME_ODDS_SQL,
    READ_QUERIES,
    ActualRecord,
    GameOddsRecord,
    GameRecord,
    StatRecord,
    load_opening_game_odds,
    load_span,
)
from app.ml.sources import (
    TIMESTAMP,
    SourceError,
    opening_game_odds_visible,
    require_feature_source,
    require_label_source,
)

PLAYER = 237
OTHER = 115
HOME = 14
AWAY = 10
REPO = Path(__file__).resolve().parents[2]
TIP = datetime(2015, 10, 28, 23, 0, tzinfo=UTC)
# hours_before_tip is 3, so T is 20:00 UTC on that tip.
T = datetime(2015, 10, 28, 20, 0, tzinfo=UTC)


def _game(
    game_id: int,
    on: date,
    season: int = 2015,
    *,
    tip: datetime | None = TIP,
    home: int | None = HOME,
) -> GameRecord:
    return GameRecord(
        league="nba",
        bdl_game_id=game_id,
        season=season,
        game_date=on,
        datetime_utc=tip,
        season_type="regular_season",
        home_team_id=home,
    )


def _stat(
    game_id: int,
    on: date,
    *,
    player: int = PLAYER,
    team: int = HOME,
    season: int = 2015,
    pts: int | None = 10,
) -> StatRecord:
    return StatRecord(
        league="nba",
        bdl_game_id=game_id,
        bdl_player_id=player,
        bdl_team_id=team,
        season=season,
        game_date=on,
        dnp=False,
        seconds_played=1800,
        pts=pts,
        reb=4,
        ast=5,
        fg3m=2,
        stl=1,
        blk=1,
    )


def _kept(game_id: int, player: int = PLAYER) -> list[ActualRecord]:
    values = {market: 0 for market in CATALOG_MARKETS}
    values["player_points"] = 10
    return [
        ActualRecord("nba", game_id, player, market, values[market]) for market in CATALOG_MARKETS
    ]


def _odds(
    game_id: int,
    book: str,
    snapshot_at: datetime | None,
    spread: float | None,
    total: float | None,
    *,
    kind: str = "opening",
    league: str = "nba",
) -> GameOddsRecord:
    return GameOddsRecord(
        league=league,
        bdl_game_id=game_id,
        book_key=book,
        snapshot_kind=kind,
        snapshot_at=snapshot_at,
        spread_home_value=spread,
        total_value=total,
    )


def _rows(
    games: list[GameRecord],
    stats: list[StatRecord],
    odds: list[GameOddsRecord],
    *,
    hours: float = 3,
    actuals: list[ActualRecord] | None = None,
) -> list[dict[str, object]]:
    dataset = assemble_dataset(
        games,
        stats,
        actuals if actuals is not None else _kept(stats[-1].bdl_game_id, stats[-1].bdl_player_id),
        season_start=2015,
        season_end=2015,
        hours_before_tip=hours,
        git_head="test-sha",
        odds=odds,
    )
    return dataset.rows


def test_allow_list_rejects_non_opening_after_t_and_null_snapshot_at() -> None:
    spec = require_feature_source("game_odds_snapshots")
    assert spec.role == "feature"
    assert spec.visibility == TIMESTAMP
    with pytest.raises(SourceError, match="player_prop_snapshots"):
        require_feature_source("player_prop_snapshots")
    with pytest.raises(SourceError, match="not a label"):
        require_label_source("game_odds_snapshots")

    assert not opening_game_odds_visible(snapshot_kind="closing", snapshot_at=T, as_of=T)
    assert not opening_game_odds_visible(
        snapshot_kind="live", snapshot_at=T - timedelta(hours=5), as_of=T
    )
    assert not opening_game_odds_visible(snapshot_kind="opening", snapshot_at=None, as_of=T)
    assert not opening_game_odds_visible(
        snapshot_kind="opening", snapshot_at=T + timedelta(seconds=1), as_of=T
    )
    with pytest.raises(SourceError, match="timezone-aware"):
        opening_game_odds_visible(
            snapshot_kind="opening",
            snapshot_at=datetime(2015, 10, 28, 20, 0),
            as_of=T,
        )


def test_boundary_includes_t_and_an_after_t_book_does_not_move_the_median() -> None:
    """One second before T and exactly T count. One second after T does not.

    The after-T book is -100. If it were included, the spread median of
    three numbers would be -6 and the book count would be 3.
    """
    on = date(2015, 10, 28)
    before = _odds(1, "draftkings", T - timedelta(seconds=1), -6, 200)
    exact = _odds(1, "fanduel", T, -4, 240)
    after = _odds(1, "betmgm", T + timedelta(seconds=1), -100, 900)
    closing = _odds(1, "caesars", T - timedelta(hours=1), 50, 400, kind="closing")
    live = _odds(1, "betway", T - timedelta(hours=1), 80, 500, kind="live")
    missing_time = _odds(1, "betrivers", None, -2, 210)
    rows = _rows(
        [_game(1, on)],
        [_stat(1, on)],
        [before, exact, after, closing, live, missing_time],
    )
    assert len(rows) == 1
    assert rows[0]["as_of"] == T
    assert rows[0]["opening_books"] == 2
    assert rows[0]["opening_spread_books"] == 2
    assert rows[0]["opening_total_books"] == 2
    assert rows[0]["opening_spread_home"] == -5
    assert rows[0]["opening_total"] == 220
    assert rows[0]["team_implied_points"] == 112.5
    assert rows[0]["opp_implied_points"] == 107.5
    assert opening_game_odds_visible(
        snapshot_kind="opening", snapshot_at=T - timedelta(seconds=1), as_of=T
    )
    assert opening_game_odds_visible(snapshot_kind="opening", snapshot_at=T, as_of=T)
    assert not opening_game_odds_visible(
        snapshot_kind="opening", snapshot_at=T + timedelta(seconds=1), as_of=T
    )


def test_null_tip_uses_the_same_midnight_t_and_does_not_subtract_again() -> None:
    """00:00 America/New_York is T. A line one hour earlier stays visible.

    Winter midnight is 05:00 UTC. Subtracting three hours from that midnight
    would hide a 04:00 UTC line. This test keeps that line.
    """
    on = date(2026, 1, 15)
    as_of = prediction_instant(on, None).as_of
    assert as_of == datetime(2026, 1, 15, 5, 0, tzinfo=UTC)
    kept = _odds(1, "draftkings", datetime(2026, 1, 15, 4, 0, tzinfo=UTC), -4, 220)
    exact = _odds(1, "fanduel", as_of, -4, 220)
    late = _odds(1, "betmgm", as_of + timedelta(seconds=1), -100, 900)
    rows = _rows(
        [_game(1, on, tip=None)],
        [_stat(1, on)],
        [kept, exact, late],
    )
    assert rows[0]["tip_fallback"] is True
    assert rows[0]["as_of"] == as_of
    assert rows[0]["opening_books"] == 2
    assert rows[0]["opening_spread_home"] == -4
    assert rows[0]["team_implied_points"] == 112
    assert rows[0]["opp_implied_points"] == 108


def test_median_odd_even_nulls_empty_and_zero_spread() -> None:
    assert median_value([]) is None
    assert median_value([-7, -4, -3]) == -4
    assert median_value([-7, -3]) == -5
    assert median_value([-6.5, -4, -3.5, -3]) == -3.75
    assert implied_team_points(220, -4) == 112
    assert implied_team_points(220, 4) == 108

    on = date(2015, 10, 28)
    odd = [
        _odds(1, "draftkings", T, -7, 210),
        _odds(1, "fanduel", T, None, 220),
        _odds(1, "betmgm", T, -3, None),
        _odds(1, "caesars", T, -4, 230),
    ]
    odd_rows = _rows([_game(1, on)], [_stat(1, on)], odd)
    assert odd_rows[0]["opening_books"] == 4
    assert odd_rows[0]["opening_spread_books"] == 3
    assert odd_rows[0]["opening_total_books"] == 3
    assert odd_rows[0]["opening_spread_home"] == -4
    assert odd_rows[0]["opening_total"] == 220
    assert odd_rows[0]["team_implied_points"] == 112
    assert odd_rows[0]["opp_implied_points"] == 108

    empty = _rows([_game(1, on)], [_stat(1, on)], [])
    assert empty[0]["opening_spread_home"] is None
    assert empty[0]["opening_total"] is None
    assert empty[0]["team_implied_points"] is None
    assert empty[0]["opp_implied_points"] is None
    assert empty[0]["opening_books"] == 0
    assert empty[0]["opening_spread_books"] == 0
    assert empty[0]["opening_total_books"] == 0

    zero = _rows([_game(1, on)], [_stat(1, on)], [_odds(1, "draftkings", T, 0, 220)])
    assert zero[0]["opening_spread_home"] == 0
    assert zero[0]["team_implied_points"] == 110
    assert zero[0]["opp_implied_points"] == 110

    spread_only = _rows(
        [_game(1, on)], [_stat(1, on)], [_odds(1, "draftkings", T, -4, None)]
    )
    assert spread_only[0]["opening_spread_home"] == -4
    assert spread_only[0]["opening_total"] is None
    assert spread_only[0]["team_implied_points"] is None
    assert spread_only[0]["opening_total_books"] == 0


def test_home_and_away_implied_points_stay_one_row_per_player() -> None:
    on = date(2015, 10, 28)
    later = date(2015, 10, 29)
    books = [
        _odds(1, "draftkings", T, -3, 220),
        _odds(1, "fanduel", T, -5, 220),
        _odds(1, "betmgm", T, -4, 220),
        _odds(2, "draftkings", datetime(2015, 10, 29, 20, 0, tzinfo=UTC), -4, 220),
        _odds(9, "draftkings", T, -20, 180, league="other"),
    ]
    games = [
        _game(1, on),
        _game(2, later, home=AWAY, tip=datetime(2015, 10, 29, 23, 0, tzinfo=UTC)),
    ]
    stats = [
        _stat(1, on, player=PLAYER, team=HOME, pts=10),
        _stat(1, on, player=OTHER, team=HOME, pts=12),
        _stat(2, later, player=PLAYER, team=HOME, pts=14),
    ]
    actuals = _kept(1, PLAYER) + _kept(1, OTHER) + _kept(2, PLAYER)
    rows = _rows(games, stats, books, actuals=actuals)
    assert len(rows) == 3
    assert [row["bdl_player_id"] for row in rows if row["bdl_game_id"] == 1] == [OTHER, PLAYER]
    for row in rows:
        if row["bdl_game_id"] != 1:
            continue
        assert row["is_home"] is True
        assert row["opening_books"] == 3
        assert row["opening_spread_home"] == -4
        assert row["opening_total"] == 220
        assert row["team_implied_points"] == 112
        assert row["opp_implied_points"] == 108
    away = next(row for row in rows if row["bdl_game_id"] == 2)
    assert away["is_home"] is False
    assert away["opening_books"] == 1
    assert away["team_implied_points"] == 108
    assert away["opp_implied_points"] == 112
    assert away["pts_last_5"] is None


def test_unknown_home_team_leaves_implied_points_null() -> None:
    on = date(2015, 10, 28)
    rows = _rows(
        [_game(1, on, home=None)],
        [_stat(1, on)],
        [_odds(1, "draftkings", T, -4, 220)],
    )
    assert rows[0]["is_home"] is None
    assert rows[0]["opening_spread_home"] == -4
    assert rows[0]["opening_total"] == 220
    assert rows[0]["team_implied_points"] is None
    assert rows[0]["opp_implied_points"] is None


def test_a_non_default_offset_moves_the_same_t_and_not_a_second_cutoff() -> None:
    on = date(2015, 10, 28)
    line = _odds(1, "draftkings", datetime(2015, 10, 28, 21, 0, tzinfo=UTC), -4, 220)
    hidden = _rows([_game(1, on)], [_stat(1, on)], [line], hours=3)
    visible = _rows([_game(1, on)], [_stat(1, on)], [line], hours=1)
    assert hidden[0]["as_of"] == T
    assert hidden[0]["opening_books"] == 0
    assert hidden[0]["team_implied_points"] is None
    assert visible[0]["as_of"] == datetime(2015, 10, 28, 22, 0, tzinfo=UTC)
    assert visible[0]["opening_books"] == 1
    assert visible[0]["team_implied_points"] == 112


def test_duplicate_visible_book_is_rejected_and_labels_do_not_add_rows() -> None:
    on = date(2015, 10, 28)
    duplicate = [
        _odds(1, "draftkings", T, -4, 220),
        _odds(1, "draftkings", T - timedelta(minutes=1), -6, 210),
    ]
    with pytest.raises(GameOddsError, match="duplicate opening book draftkings"):
        _rows([_game(1, on)], [_stat(1, on)], duplicate)

    closing_same_book = [
        _odds(1, "draftkings", T, -4, 220),
        _odds(1, "draftkings", T, -6, 210, kind="closing"),
    ]
    kept = _rows([_game(1, on)], [_stat(1, on)], closing_same_book)
    assert kept[0]["opening_books"] == 1
    assert kept[0]["opening_spread_home"] == -4

    dnp_actuals = [ActualRecord("nba", 1, PLAYER, market, None) for market in CATALOG_MARKETS]
    dataset = assemble_dataset(
        [_game(1, on)],
        [_stat(1, on)],
        dnp_actuals,
        season_start=2015,
        season_end=2015,
        git_head="test-sha",
        odds=[_odds(1, "draftkings", T, -4, 220), _odds(1, "fanduel", T, -6, 230)],
    )
    assert dataset.rows == []
    assert dataset.metadata["game_odds_coverage"] == {
        "kept_rows": 0,
        "rows_with_spread_median": 0,
        "rows_with_total_median": 0,
        "rows_with_implied_points": 0,
        "rows_with_no_eligible_book": 0,
        "games_with_eligible_book": 0,
    }


def test_metadata_records_features_coverage_and_the_pending_measurement() -> None:
    on = date(2015, 10, 28)
    dataset = assemble_dataset(
        [_game(1, on), _game(2, on)],
        [_stat(1, on, player=PLAYER), _stat(2, on, player=OTHER)],
        _kept(1, PLAYER) + _kept(2, OTHER),
        season_start=2015,
        season_end=2015,
        git_head="test-sha",
        odds=[_odds(1, "draftkings", T, -4, 220)],
    )
    assert dataset.metadata["feature_sources"] == [
        "games",
        "player_game_stats",
        "game_odds_snapshots",
    ]
    assert dataset.metadata["game_odds_features"] == list(ODDS_COLUMNS)
    assert all(name in OUTPUT_COLUMNS for name in ODDS_COLUMNS)
    assert dataset.metadata["game_odds_measurement"] == "PENDING"
    assert dataset.metadata["game_odds_measurement"] == MEASUREMENT_STATUS
    assert dataset.metadata["game_odds_measurement_sql"] == MEASUREMENT_SQL
    assert "://" not in str(dataset.metadata["game_odds_measurement_sql"])
    limitation = str(dataset.metadata["game_odds_limitation"])
    assert limitation == OPENING_ODDS_LIMITATION
    assert "not an immutable" in limitation
    assert "does not show that this application polled" in limitation
    assert "PENDING" in limitation
    coverage = dataset.metadata["game_odds_coverage"]
    assert coverage == {
        "kept_rows": 2,
        "rows_with_spread_median": 1,
        "rows_with_total_median": 1,
        "rows_with_implied_points": 1,
        "rows_with_no_eligible_book": 1,
        "games_with_eligible_book": 1,
    }
    direct = opening_odds_features(
        [_odds(1, "draftkings", T, -4, 220)],
        league="nba",
        bdl_game_id=1,
        is_home=True,
        as_of=T,
    )
    assert direct["team_implied_points"] == 112
    assert direct["opp_implied_points"] == 108


def test_opening_odds_sql_is_a_select_and_does_not_encode_t() -> None:
    folded = " ".join(GAME_ODDS_SQL.lower().split())
    assert folded.startswith("select")
    assert "from game_odds_snapshots" in folded
    assert "join games" in folded
    assert "snapshot_kind = 'opening'" in folded
    assert "snapshot_at is not null" in folded
    assert "interval" not in folded
    assert "hours" not in folded
    for forbidden in (
        "insert",
        "update",
        "delete",
        "predictions",
        "player_prop_snapshots",
        "home_score",
        "closing",
        "live",
    ):
        assert forbidden not in folded
    assert GAME_ODDS_SQL in READ_QUERIES
    assert "prop_actuals" in READ_QUERIES[2].lower()


def test_opening_odds_load_is_one_query_per_season() -> None:
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
    rows = asyncio.run(
        load_opening_game_odds(conn, league="nba", seasons=load_span(2015, 2016))
    )
    assert rows == []
    assert [call[1] for call in conn.calls] == [("nba", 2014), ("nba", 2015), ("nba", 2016)]
    assert conn.calls[0][0] == GAME_ODDS_SQL


def test_measurement_sql_is_pending_and_has_no_credential() -> None:
    sql_path = REPO / MEASUREMENT_SQL
    note_path = REPO / "docs/decisions/SPO-138/game-odds-opener-timing.md"
    sql = sql_path.read_text(encoding="utf-8")
    note = note_path.read_text(encoding="utf-8")
    for text in (sql, note):
        assert "PENDING" in text
        lowered = text.lower()
        assert "postgresql://" not in lowered
        assert "balldontlie_api_key" not in lowered
        assert "odds_" + "api_key" not in lowered
        assert "password" not in lowered
    folded = " ".join(sql.lower().split())
    assert "snapshot_kind = 'opening'" in folded
    assert "snapshot_at is null" in folded
    assert "datetime_utc is null" in folded
    assert "interval '3 hours'" in folded
    assert "snapshot_at <= t_tip_minus_3h" in folded
    assert "snapshot_at > t_tip_minus_3h" in folded
    assert "snapshot_at = t_tip_minus_3h" in folded
    assert "group by season" in folded
    assert "books_at_or_before_t" in folded
    assert "snapshot_minus_tip_hours" in folded
    for forbidden in ("insert ", "update ", "delete ", "player_prop_snapshots"):
        assert forbidden not in folded
    assert "00:00 America/New_York" in note or "00:00 America/New_York" in sql
    assert "not an immutable" in note or "not an immutable" in OPENING_ODDS_LIMITATION
