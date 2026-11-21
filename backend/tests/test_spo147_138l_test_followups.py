"""SPO-147 locks two SPO-138l gaps the earlier tests left open.

``assemble_dataset(league="wnba")`` stays ``pregame``, leaves the new
absence columns NULL, and does not call ``team_absences``. A listed status
word that is not one of the five injury-status constants, after whitespace
is stripped, gets no ``p_out`` and increments ``unknown_status_count``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.ml.absence import (
    ABSENCE_FEATURE_COLUMNS,
    SOURCE_ACTUAL,
    SOURCE_REPORTED,
    p_out_for_status,
    team_absences,
)
from app.ml.asof import prediction_instant
from app.ml.build_dataset import OUTPUT_COLUMNS, assemble_dataset, build_parser
from app.ml.labels import CATALOG_MARKETS
from app.ml.load import ActualRecord, GameRecord, InjuryRecord, LineupRecord, StatRecord
from app.services.injury_status import OUT

HOME = 14
AWAY = 10
PLAYER = 3
SUBJECT = 1
ON = date(2026, 1, 15)
TIP = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)


def _actuals(game_id: int, player: int, league: str) -> list[ActualRecord]:
    return [
        ActualRecord(league, game_id, player, market, 1 if market == "player_points" else 0)
        for market in CATALOG_MARKETS
    ]


def _stat(league: str, game_id: int, on: date, player: int, team: int, *, seconds: int = 900) -> StatRecord:
    return StatRecord(
        league=league,
        bdl_game_id=game_id,
        bdl_player_id=player,
        bdl_team_id=team,
        season=2025,
        game_date=on,
        dnp=False,
        seconds_played=seconds,
        pts=10,
        reb=1,
        ast=1,
        fg3m=1,
        stl=1,
        blk=1,
    )


def test_wnba_export_keeps_new_columns_null_and_skips_nba_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("team_absences must not run for a WNBA export")

    monkeypatch.setattr("app.ml.build_dataset.team_absences", _forbidden)
    games = [
        GameRecord("wnba", 1, 2025, date(2026, 1, 1), TIP, "regular_season", HOME, AWAY),
        GameRecord("wnba", 2, 2025, ON, None, "regular_season", HOME, AWAY),
    ]
    stats = [
        _stat("wnba", 1, date(2026, 1, 1), PLAYER, HOME),
        _stat("wnba", 2, ON, PLAYER, HOME, seconds=1800),
    ]
    injuries = [InjuryRecord("wnba", prediction_instant(ON, None).as_of, PLAYER, True, OUT)]
    lineups = [LineupRecord("wnba", 2, PLAYER, HOME, True)]
    dataset = assemble_dataset(
        games,
        stats,
        _actuals(2, PLAYER, "wnba"),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        league="wnba",
        injuries=injuries,
        lineups=lineups,
        absence_source=SOURCE_ACTUAL,
        hours_before_tip=9,
    )
    assert len(dataset.rows) == 1
    row = dataset.rows[0]
    assert row["info_source"] == "pregame"
    assert row["is_starter"] is None
    assert row["player_injury_status"] is None
    assert all(row[name] is None for name in ABSENCE_FEATURE_COLUMNS)
    assert set(ABSENCE_FEATURE_COLUMNS).issubset(OUTPUT_COLUMNS)
    assert dataset.metadata["info_source"] == "pregame"
    assert dataset.metadata["standin_row_count"] == 0
    assert dataset.metadata["feature_sources"] == [
        "games",
        "player_game_stats",
        "game_odds_snapshots",
    ]


def test_noncanonical_status_words_are_counted_and_not_given_p_out() -> None:
    words = ("out", "OUT", "Day To Day", "Out For Season", "doubtful", "gtd")
    for word in words:
        assert p_out_for_status(word) is None
    stats = [_stat("nba", gid, date(2026, 1, gid), SUBJECT, HOME) for gid in (1, 2, 3)]
    stats.append(_stat("nba", 8, ON, SUBJECT, HOME, seconds=1800))
    for word in words:
        result = team_absences(
            "nba",
            HOME,
            8,
            prediction_instant(ON, TIP, 3).as_of,
            SOURCE_REPORTED,
            target_date=ON,
            stats=stats,
            injuries=[InjuryRecord("nba", prediction_instant(ON, TIP, 3).as_of, SUBJECT, True, word)],
        )
        assert result.pairs == ()
        assert result.unknown_status_count == 1


def test_cli_rejects_league_wnba() -> None:
    """``--league wnba`` is not a CLI choice. The exporter stays NBA only."""
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(
            [
                "--dsn-env",
                "ML_DATABASE_URL",
                "--seasons",
                "2025:2025",
                "--out",
                "out.parquet",
                "--league",
                "wnba",
            ]
        )
    assert raised.value.code == 2
