"""Fit p_out from T-time official status and the box-score did-not-play label.

The hand table is 21 labeled players in one 2024-25 game. Counts:

- Out 4/4
- Doubtful 3/4
- Questionable 2/4
- Probable 1/5
- Available 0/4

An earlier report, a report one second after T, a player with no box row,
an unmatched name, and a player listed twice with two statuses are in the
input and are not in those counts. 2025-26 and 2026-27 games are added in
the leak test. Nothing here is a full-season 2024-25 measurement.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone

import pytest

from app.ml.absence import official_p_out
from app.ml.build_dataset import assemble_dataset
from app.ml.injury_weights import (
    DAY_TO_DAY_P_OUT,
    P_OUT_BY_OFFICIAL_STATUS,
    TRAINING_SEASON,
    WEIGHT_TABLE_SOURCE,
    FitObservation,
    WeightFitError,
    fit_official_status_weights,
    official_scale,
    rates_from_observations,
)
from app.ml.load import (
    ActualRecord,
    GameRecord,
    OfficialRefresh,
    OfficialReportRow,
    StatRecord,
)
from app.services.injury_status import DAY_TO_DAY, DOUBTFUL, OUT, PROBABLE, QUESTIONABLE

UTC = timezone.utc
GAME = 9001
TIP = datetime(2024, 12, 1, 23, 0, tzinfo=UTC)
T = TIP - timedelta(hours=3)
ON = date(2024, 12, 1)
HOME = 1
AWAY = 2

# player id, status at T, did-not-play. Checked by hand.
HAND = (
    (1, OUT, True),
    (2, OUT, True),
    (3, OUT, True),
    (4, OUT, True),
    (5, DOUBTFUL, True),
    (6, DOUBTFUL, True),
    (7, DOUBTFUL, True),
    (8, DOUBTFUL, False),
    (9, QUESTIONABLE, True),
    (10, QUESTIONABLE, True),
    (11, QUESTIONABLE, False),
    (12, QUESTIONABLE, False),
    (13, PROBABLE, True),
    (14, PROBABLE, False),
    (15, PROBABLE, False),
    (16, PROBABLE, False),
    (17, PROBABLE, False),
    (18, "Available", False),
    (19, "Available", False),
    (20, "Available", False),
    (21, "Available", False),
)
EXPECTED = {
    OUT: (4, 4),
    DOUBTFUL: (4, 3),
    QUESTIONABLE: (4, 2),
    PROBABLE: (5, 1),
    "Available": (4, 0),
}


def _game(game_id: int, season: int, on: date, tip: datetime) -> GameRecord:
    return GameRecord(
        league="nba",
        bdl_game_id=game_id,
        season=season,
        game_date=on,
        datetime_utc=tip,
        season_type="regular_season",
        home_team_id=HOME,
        visitor_team_id=AWAY,
    )


def _stat(game_id: int, season: int, on: date, player: int, dnp: bool) -> StatRecord:
    played = not dnp
    return StatRecord(
        league="nba",
        bdl_game_id=game_id,
        bdl_player_id=player,
        bdl_team_id=HOME,
        season=season,
        game_date=on,
        dnp=dnp,
        seconds_played=1200 if played else None,
        pts=10 if played else None,
        reb=2 if played else None,
        ast=2 if played else None,
        fg3m=1 if played else None,
        stl=1 if played else None,
        blk=0 if played else None,
    )


def _line(
    at: datetime,
    player: int | None,
    status: str | None,
    *,
    game_id: int = GAME,
    name: str | None = None,
) -> OfficialReportRow:
    return OfficialReportRow(
        league="nba",
        report_at=at,
        bdl_game_id=game_id,
        bdl_team_id=HOME,
        player_raw=name if name is not None else f"Player, {player}",
        bdl_player_id=player,
        status=status,
        reason=None,
        category=None,
        not_yet_submitted=False,
        all_players_available=False,
    )


def hand_world() -> tuple[list[GameRecord], list[OfficialReportRow], list[StatRecord]]:
    """One 2024-25 game. The report at T is the one that counts.

    An hour-earlier report calls player 18 Out. The T report calls him
    Available, and he played. A second T line gives player 40 both Out and
    Available. Player 30 is Questionable and has no box row. One line has
    no player id.
    """
    games = [_game(GAME, TRAINING_SEASON, ON, TIP)]
    rows = [_line(T - timedelta(hours=1), 18, OUT)]
    stats = []
    for player, status, dnp in HAND:
        rows.append(_line(T, player, status))
        stats.append(_stat(GAME, TRAINING_SEASON, ON, player, dnp))
    rows.append(_line(T, 30, QUESTIONABLE))
    rows.append(_line(T, None, QUESTIONABLE, name="No, Match"))
    rows.append(_line(T, 40, OUT))
    rows.append(_line(T, 40, "Available"))
    stats.append(_stat(GAME, TRAINING_SEASON, ON, 40, True))
    return games, rows, stats


def _expect(fit) -> None:
    assert fit.season == TRAINING_SEASON
    assert tuple(row.status for row in fit.weights) == (
        OUT,
        DOUBTFUL,
        QUESTIONABLE,
        PROBABLE,
        "Available",
    )
    for row in fit.weights:
        row_count, dnp_count = EXPECTED[row.status]
        assert row.row_count == row_count
        assert row.did_not_play_count == dnp_count
        assert row.p_out == dnp_count / row_count


def test_fixture_rates_match_the_hand_count() -> None:
    games, rows, stats = hand_world()
    fit = fit_official_status_weights(games, rows, stats)
    _expect(fit)
    assert fit.weight_for(OUT).p_out == 1.0
    assert fit.weight_for(DOUBTFUL).p_out == 3 / 4
    assert fit.weight_for(QUESTIONABLE).p_out == 2 / 4
    assert fit.weight_for(PROBABLE).p_out == 1 / 5
    assert fit.weight_for("Available").p_out == 0.0


def test_a_report_exactly_at_t_counts_and_one_second_later_does_not() -> None:
    games = [_game(GAME, TRAINING_SEASON, ON, TIP)]
    stats = [_stat(GAME, TRAINING_SEASON, ON, 1, True)]
    at_t = fit_official_status_weights(games, [_line(T, 1, OUT)], stats)
    assert at_t.weight_for(OUT).row_count == 1
    assert at_t.weight_for(OUT).did_not_play_count == 1
    late = fit_official_status_weights(
        games, [_line(T + timedelta(seconds=1), 1, OUT)], stats
    )
    assert late.weight_for(OUT).row_count == 0
    assert late.weight_for(OUT).p_out is None


def test_post_t_and_later_seasons_do_not_change_the_weights() -> None:
    games, rows, stats = hand_world()
    rows.append(_line(T + timedelta(seconds=1), 11, OUT))
    later_tip = datetime(2025, 12, 1, 23, 0, tzinfo=UTC)
    games.append(_game(9002, 2025, date(2025, 12, 1), later_tip))
    for player in range(101, 111):
        rows.append(
            _line(
                later_tip - timedelta(hours=3),
                player,
                QUESTIONABLE,
                game_id=9002,
            )
        )
        stats.append(_stat(9002, 2025, date(2025, 12, 1), player, True))
    future_tip = datetime(2026, 12, 1, 23, 0, tzinfo=UTC)
    games.append(_game(9003, 2026, date(2026, 12, 1), future_tip))
    for player in range(201, 205):
        rows.append(
            _line(
                future_tip - timedelta(hours=3),
                player,
                "Available",
                game_id=9003,
            )
        )
        stats.append(_stat(9003, 2026, date(2026, 12, 1), player, True))
    fit = fit_official_status_weights(games, rows, stats)
    _expect(fit)


def test_a_later_season_observation_is_refused() -> None:
    row = FitObservation(
        season=2025,
        bdl_game_id=1,
        bdl_player_id=1,
        status=OUT,
        report_at=T,
        as_of=T,
        did_not_play=True,
    )
    with pytest.raises(WeightFitError):
        rates_from_observations([row])


def test_a_post_t_observation_is_refused() -> None:
    row = FitObservation(
        season=TRAINING_SEASON,
        bdl_game_id=1,
        bdl_player_id=1,
        status=OUT,
        report_at=T + timedelta(seconds=1),
        as_of=T,
        did_not_play=True,
    )
    with pytest.raises(WeightFitError):
        rates_from_observations([row])


def test_the_fitter_refuses_to_target_another_season() -> None:
    games, rows, stats = hand_world()
    with pytest.raises(WeightFitError):
        fit_official_status_weights(games, rows, stats, season=2025)


def test_an_empty_fit_does_not_invent_a_zero_rate() -> None:
    fit = fit_official_status_weights([], [], [])
    assert len(fit.weights) == 5
    assert all(row.row_count == 0 and row.p_out is None for row in fit.weights)


def test_the_feature_table_is_still_the_prior_not_the_fixture() -> None:
    assert WEIGHT_TABLE_SOURCE == "prior"
    assert TRAINING_SEASON == 2024
    assert P_OUT_BY_OFFICIAL_STATUS == {
        OUT: 1.0,
        DOUBTFUL: 0.75,
        QUESTIONABLE: 0.5,
        PROBABLE: 0.1,
        "Available": 0.0,
    }
    fit = fit_official_status_weights(*hand_world())
    assert fit.weight_for(PROBABLE).p_out == 1 / 5
    assert P_OUT_BY_OFFICIAL_STATUS[PROBABLE] == 0.1
    assert "Day-To-Day" not in P_OUT_BY_OFFICIAL_STATUS


def test_feature_code_reads_the_weight_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(P_OUT_BY_OFFICIAL_STATUS, DOUBTFUL, 0.25)
    assert official_p_out(DOUBTFUL) == 0.25
    assert official_scale()[DOUBTFUL] == 0.25
    assert official_scale()[DAY_TO_DAY] == DAY_TO_DAY_P_OUT
    games = [
        _game(101, 2024, date(2024, 11, 1), datetime(2024, 11, 1, 23, tzinfo=UTC)),
        _game(102, 2024, date(2024, 11, 2), datetime(2024, 11, 2, 23, tzinfo=UTC)),
        _game(103, 2024, date(2024, 11, 3), datetime(2024, 11, 3, 23, tzinfo=UTC)),
        _game(GAME, 2024, ON, TIP),
    ]
    stats: list[StatRecord] = []
    for game_id, on in (
        (101, date(2024, 11, 1)),
        (102, date(2024, 11, 2)),
        (103, date(2024, 11, 3)),
        (GAME, ON),
    ):
        stats.append(_stat(game_id, 2024, on, 10, False))
        stats.append(_stat(game_id, 2024, on, 14, False))
    rows = [_line(T, 14, DOUBTFUL)]
    refreshes = [OfficialRefresh(league="nba", refreshed_at=T, complete=True)]
    actuals = [ActualRecord("nba", GAME, 10, "player_points", 10)]
    dataset = assemble_dataset(
        games,
        stats,
        actuals,
        season_start=2024,
        season_end=2024,
        git_head="spo154",
        official_rows=rows,
        official_refreshes=refreshes,
    )
    assert len(dataset.rows) == 1
    assert dataset.rows[0]["team_missing_minutes"] == 5.0


def test_absence_module_has_no_second_hardcoded_scale() -> None:
    import app.ml.absence as absence

    text = inspect.getsource(absence)
    for token in ("0.75", "0.5", "0.25", "0.10", "0.1"):
        assert token not in text
