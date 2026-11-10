"""SPO-107: headline history matches production, playoffs stay out of it."""

from __future__ import annotations

from datetime import datetime, timedelta

from evaluation.paths import bootstrap
from evaluation.walk_forward import replay_league

bootstrap()

from app.services.csv_player_history import CSVPlayerHistoryService  # noqa: E402
from app.services.game_log_hygiene import (  # noqa: E402
    GAME_TYPE_NBA_CUP,
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_REGULAR,
)


class _Service:
    def __init__(self, cache: dict):
        self._cache = cache
        self.league = "nba"
        self._loaded = True


def _game(day: int, points: float, game_type: str) -> dict:
    return {
        "player_name": "Test Player",
        "game_date": datetime(2025, 11, 1) + timedelta(days=day),
        "minutes": 30.0,
        "points": points,
        "rebounds": 5.0,
        "assists": 4.0,
        "pra": points + 9.0,
        "team": "AAA",
        "season": "2025-2026",
        "game_type": game_type,
    }


def _replay(logs: list[dict]):
    return replay_league(
        _Service({"Test Player": logs}),
        "nba",
        ["L10"],
        eval_start=datetime(2025, 11, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
    )


def test_history_types_are_the_production_default():
    # One definition. The harness does not keep a second copy of the list.
    assert _history_is_production_default()


def _history_is_production_default() -> bool:
    from evaluation.walk_forward import _breakdown_types, _history_types

    assert _history_types() == CSVPlayerHistoryService._allowed_game_types()
    assert _history_types() == {GAME_TYPE_REGULAR}
    opted_in = CSVPlayerHistoryService._allowed_game_types(True, True)
    assert _breakdown_types() == opted_in - _history_types()
    assert _breakdown_types() == {GAME_TYPE_PLAYOFFS, GAME_TYPE_PLAY_IN}
    assert GAME_TYPE_NBA_CUP not in _history_types()
    assert GAME_TYPE_NBA_CUP not in _breakdown_types()
    return True


def test_playoffs_are_not_history_and_not_headline_targets():
    regular = [_game(offset, 10.0, GAME_TYPE_REGULAR) for offset in range(12)]
    cup = _game(20, 99.0, GAME_TYPE_NBA_CUP)
    play_in = _game(30, 40.0, GAME_TYPE_PLAY_IN)
    playoff = _game(40, 80.0, GAME_TYPE_PLAYOFFS)
    later = _game(50, 10.0, GAME_TYPE_REGULAR)
    replay = _replay([*regular, cup, play_in, playoff, later])

    headline_dates = {row.date for row in replay.daily}
    playoff_date = playoff["game_date"].strftime("%Y-%m-%d")
    play_in_date = play_in["game_date"].strftime("%Y-%m-%d")
    cup_date = cup["game_date"].strftime("%Y-%m-%d")
    later_date = later["game_date"].strftime("%Y-%m-%d")
    assert playoff_date not in headline_dates
    assert play_in_date not in headline_dates
    assert cup_date not in headline_dates
    assert later_date in headline_dates

    later_row = next(row for row in replay.daily if row.date == later_date)
    # 12 regular-season games. The Cup, the play-in, and the playoff stay out.
    assert later_row.n_games == 12
    assert later_row.p_over == 0.0
    assert later_row.line == 10.5
    assert later_row.game_type == GAME_TYPE_REGULAR

    post_dates = {row.date for row in replay.postseason_daily}
    assert post_dates == {play_in_date, playoff_date}
    playoff_row = next(row for row in replay.postseason_daily if row.date == playoff_date)
    play_in_row = next(row for row in replay.postseason_daily if row.date == play_in_date)
    assert playoff_row.game_type == GAME_TYPE_PLAYOFFS
    assert play_in_row.game_type == GAME_TYPE_PLAY_IN
    assert playoff_row.n_games == 12
    assert play_in_row.n_games == 12
    assert playoff_row.actual == 80.0
    assert replay.postseason_by_type[GAME_TYPE_PLAYOFFS]["targets"] == 1
    assert replay.postseason_by_type[GAME_TYPE_PLAY_IN]["targets"] == 1
    assert replay.targets == sum(1 for row in replay.daily)


def test_missing_game_type_counts_as_regular_season():
    logs = []
    for offset in range(12):
        game = _game(offset, 10.0, GAME_TYPE_REGULAR)
        del game["game_type"]
        logs.append(game)
    replay = _replay(logs)
    assert replay.daily
    assert all(row.game_type == GAME_TYPE_REGULAR for row in replay.daily)
    assert replay.postseason_daily == []


def test_real_playoff_game_is_a_breakdown_row():
    """A shipped playoff game is scored from regular-season history only."""
    from evaluation.walk_forward import load_historical

    historical = load_historical()
    service = historical._csv_for("nba")
    allowed = CSVPlayerHistoryService._allowed_game_types()
    player = None
    for name in sorted(service._cache):
        types = {CSVPlayerHistoryService._game_type_of(game) for game in service._cache[name]}
        if GAME_TYPE_PLAYOFFS in types and GAME_TYPE_REGULAR in types:
            player = name
            break
    assert player is not None
    replay = replay_league(
        service,
        "nba",
        ["L10"],
        players={player},
        markets=[("player_points", "points")],
        do_agent=False,
        validate=5,
        seed=7,
    )
    assert replay.validation["mismatches"] == 0
    assert replay.validation["checked"] > 0
    headline = {row.date for row in replay.daily}
    postseason = {row.date for row in replay.postseason_daily}
    assert headline.isdisjoint(postseason)
    assert postseason
    for row in replay.postseason_daily:
        assert row.game_type in {GAME_TYPE_PLAYOFFS, GAME_TYPE_PLAY_IN}
        target = datetime.strptime(row.date, "%Y-%m-%d")
        regular_before = [
            game
            for game in service._cache[player]
            if game.get("game_date")
            and game["game_date"] < target
            and (game.get("minutes") or 0) > 0
            and CSVPlayerHistoryService._game_type_of(game) in allowed
        ]
        assert row.n_games == len(regular_before)
