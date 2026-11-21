"""SPO-138l absence, starter stand-in, and info_source. No database.

NBA only. The scratch-database path is ``test_spo138l_ml_absence_db.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.ml.absence import (
    COVERAGE_COVERED,
    COVERAGE_NOTE_UNKNOWN,
    COVERAGE_UNKNOWN,
    INFO_PREGAME,
    INFO_STANDIN,
    MARKET_COMPONENTS,
    P_OUT_BY_STATUS,
    SHARE_COLUMNS,
    SOURCE_ACTUAL,
    SOURCE_REPORTED,
    AbsenceIndex,
    TeamAbsences,
    absence_feature_values,
    known_at,
    latest_listed_injury,
    opponent_team,
    p_out_for_status,
    rows_for_final_scores,
    starter_for_player,
    team_absences,
)
from app.ml.asof import prediction_instant
from app.ml.build_dataset import OUTPUT_COLUMNS, assemble_dataset
from app.ml.labels import CATALOG_MARKETS
from app.ml.load import (
    ABSENCE_QUERIES,
    PLAYER_INJURIES_SQL,
    ActualRecord,
    GameRecord,
    InjuryRecord,
    LineupRecord,
    ProjectedStarterRow,
    StatRecord,
)
from app.ml.sources import SourceError, feature_source_names, require_absence_source, require_feature_source
from app.services.injury_status import (
    DAY_TO_DAY,
    DOUBTFUL,
    OUT,
    PROBABLE,
    QUESTIONABLE,
)

HOME = 14
AWAY = 10
OTHER = 20
FILLER = 70
SUBJECT = 1
DNP_PLAYER = 2
PLAYED = 3
TARGET = date(2025, 1, 20)
TARGET_GAME = 100
TIP = datetime(2025, 1, 20, 23, 0, tzinfo=UTC)
T = prediction_instant(TARGET, TIP, 3).as_of
EXACT_15_MIN = 15 * 60
FOURTEEN_59 = 14 * 60 + 59


def _day(day: int) -> date:
    return date(2025, 1, day)


def _game(
    game_id: int,
    on: date,
    *,
    home: int = HOME,
    visitor: int | None = AWAY,
    tip: datetime | None | object = TIP,
    season: int = 2025,
) -> GameRecord:
    return GameRecord(
        league="nba",
        bdl_game_id=game_id,
        season=season,
        game_date=on,
        datetime_utc=None if tip is None else tip,  # type: ignore[arg-type]
        season_type="regular_season",
        home_team_id=home,
        visitor_team_id=visitor,
    )


def _stat(
    game_id: int,
    on: date,
    player: int,
    team: int = HOME,
    *,
    dnp: bool = False,
    seconds: int | None = EXACT_15_MIN,
    pts: int | None = 10,
    reb: int | None = 1,
    ast: int | None = 1,
    fg3m: int | None = 1,
    stl: int | None = 1,
    blk: int | None = 1,
    season: int = 2025,
) -> StatRecord:
    if dnp:
        seconds = pts = reb = ast = fg3m = stl = blk = None
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


def _injury(
    player: int,
    at: datetime,
    status: str | None,
    *,
    listed: bool = True,
) -> InjuryRecord:
    return InjuryRecord(
        league="nba",
        snapshot_at=at,
        bdl_player_id=player,
        listed=listed,
        status=status if listed else None,
    )


def _kept(game_id: int, player: int, **overrides: int | None) -> list[ActualRecord]:
    values = {market: 0 for market in CATALOG_MARKETS}
    values["player_points"] = 10
    values.update(overrides)
    return [
        ActualRecord("nba", game_id, player, market, values[market]) for market in CATALOG_MARKETS
    ]


def _window(*extra: StatRecord) -> list[StatRecord]:
    """Ten team games. The filler played every one at exactly 15 minutes."""
    rows = [_stat(gid, _day(gid), FILLER, seconds=EXACT_15_MIN, pts=4) for gid in range(1, 11)]
    rows.extend(extra)
    return rows


def _target(*rows: StatRecord) -> list[StatRecord]:
    return [*rows, _stat(TARGET_GAME, TARGET, FILLER, seconds=1800, pts=8)]


def _absences(
    stats: list[StatRecord],
    source: str,
    injuries: list[InjuryRecord] | None = None,
    *,
    team: int = HOME,
    game: int = TARGET_GAME,
    on: date = TARGET,
    as_of: datetime = T,
) -> TeamAbsences:
    return team_absences(
        "nba",
        team,
        game,
        as_of,
        source,
        target_date=on,
        stats=stats,
        injuries=injuries or (),
    )


def test_status_scale_uses_the_shared_words_and_does_not_guess() -> None:
    assert set(P_OUT_BY_STATUS) == {OUT, DOUBTFUL, QUESTIONABLE, DAY_TO_DAY, PROBABLE}
    assert P_OUT_BY_STATUS[OUT] == 1
    assert P_OUT_BY_STATUS[DOUBTFUL] == 0.75
    assert P_OUT_BY_STATUS[QUESTIONABLE] == 0.5
    assert P_OUT_BY_STATUS[DAY_TO_DAY] == 0.25
    assert P_OUT_BY_STATUS[PROBABLE] == 0.1
    assert P_OUT_BY_STATUS[DOUBTFUL] != P_OUT_BY_STATUS[QUESTIONABLE]
    assert p_out_for_status(DOUBTFUL) == 0.75
    assert p_out_for_status(f"  {DOUBTFUL}  ") == 0.75
    assert p_out_for_status("GTD") is None
    assert p_out_for_status(None) is None
    assert p_out_for_status("  ") is None
    assert set(MARKET_COMPONENTS) == set(CATALOG_MARKETS)


def test_three_of_ten_at_exactly_fifteen_minutes_is_in() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    stats = _window(*played) + _target()
    result = _absences(stats, SOURCE_ACTUAL)
    assert result.pairs == ((SUBJECT, 1.0),)
    assert result.unknown_status_count == 0


def test_two_of_ten_is_out() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=1800) for gid in (1, 2)]
    stats = _window(*played) + _target()
    assert _absences(stats, SOURCE_ACTUAL).pairs == ()


def test_fourteen_minutes_fifty_nine_seconds_is_out() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=FOURTEEN_59) for gid in (1, 2, 3)]
    stats = _window(*played) + _target()
    assert FOURTEEN_59 == 899
    assert _absences(stats, SOURCE_ACTUAL).pairs == ()


def test_games_older_than_the_teams_last_ten_do_not_count() -> None:
    older = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    recent = [_stat(gid, _day(gid), FILLER, seconds=EXACT_15_MIN) for gid in range(4, 14)]
    stats = older + recent + [_stat(TARGET_GAME, TARGET, FILLER, seconds=1800)]
    assert _absences(stats, SOURCE_ACTUAL).pairs == ()


def test_a_player_traded_away_is_not_this_teams_rotation_player() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    traded = _stat(50, date(2025, 1, 15), SUBJECT, team=OTHER, seconds=1800)
    stats = _window(*played, traded) + _target()
    full = _absences(stats, SOURCE_ACTUAL)
    bundle = AbsenceIndex(stats).bundle("nba", HOME, TARGET, TARGET_GAME)
    narrow = _absences(list(bundle), SOURCE_ACTUAL)
    assert full.pairs == narrow.pairs == ()
    assert any(row.bdl_team_id == OTHER for row in bundle)


def test_a_same_day_game_does_not_count_as_earlier() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2)]
    same_day = _stat(90, TARGET, SUBJECT, seconds=EXACT_15_MIN)
    stats = _window(*played, same_day) + _target()
    assert _absences(stats, SOURCE_ACTUAL).pairs == ()

    three = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    other_same_day = _stat(91, TARGET, SUBJECT, team=OTHER, seconds=1800)
    stayed = _window(*three, other_same_day) + _target()
    assert _absences(stayed, SOURCE_ACTUAL).pairs == ((SUBJECT, 1.0),)


def test_actual_marks_a_missing_row_and_a_dnp_and_not_a_player_who_played() -> None:
    def prior(player: int, games: tuple[int, ...]) -> list[StatRecord]:
        return [_stat(gid, _day(gid), player, seconds=EXACT_15_MIN) for gid in games]

    stats = _window(
        *prior(SUBJECT, (1, 2, 3)),
        *prior(DNP_PLAYER, (1, 2, 4)),
        *prior(PLAYED, (1, 5, 6)),
    )
    stats.extend(
        [
            _stat(TARGET_GAME, TARGET, DNP_PLAYER, dnp=True),
            _stat(TARGET_GAME, TARGET, PLAYED, seconds=1800, pts=12),
            _stat(TARGET_GAME, TARGET, FILLER, seconds=1800, pts=8),
        ]
    )
    full = _absences(stats, SOURCE_ACTUAL)
    bundle = AbsenceIndex(stats).bundle("nba", HOME, TARGET, TARGET_GAME)
    narrow = _absences(list(bundle), SOURCE_ACTUAL)
    assert full.pairs == narrow.pairs == ((SUBJECT, 1.0), (DNP_PLAYER, 1.0))
    assert PLAYED not in {player for player, _ in full.pairs}


def test_reported_keeps_the_row_at_t_and_ignores_one_second_later() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    stats = _window(*played) + _target(_stat(TARGET_GAME, TARGET, SUBJECT, seconds=1800))
    injuries = [
        _injury(SUBJECT, T - timedelta(seconds=1), QUESTIONABLE),
        _injury(SUBJECT, T, QUESTIONABLE),
        _injury(SUBJECT, T + timedelta(seconds=1), OUT),
    ]
    result = _absences(stats, SOURCE_REPORTED, injuries)
    assert result.pairs == ((SUBJECT, P_OUT_BY_STATUS[QUESTIONABLE]),)
    assert known_at(T, T)
    assert not known_at(T + timedelta(seconds=1), T)


def test_a_removal_one_second_after_t_does_not_hide_the_out() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    stats = _window(*played) + _target()
    injuries = [
        _injury(SUBJECT, T, OUT),
        _injury(SUBJECT, T + timedelta(seconds=1), None, listed=False),
    ]
    assert _absences(stats, SOURCE_REPORTED, injuries).pairs == ((SUBJECT, 1.0),)


def test_listed_false_at_or_before_t_removes_the_older_out() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    stats = _window(*played) + _target()
    injuries = [
        _injury(SUBJECT, T - timedelta(days=1), OUT),
        _injury(SUBJECT, T, None, listed=False),
    ]
    result = _absences(stats, SOURCE_REPORTED, injuries)
    assert result.pairs == ()
    assert latest_listed_injury(injuries, "nba", SUBJECT, T) is None
    # Newest first, then listed. The older Out is still in the input.
    assert injuries[0].status == OUT


def test_each_listed_status_maps_and_an_unknown_word_is_counted() -> None:
    played = [_stat(gid, _day(gid), SUBJECT, seconds=EXACT_15_MIN) for gid in (1, 2, 3)]
    stats = _window(*played) + _target()
    for word, expected in P_OUT_BY_STATUS.items():
        result = _absences(stats, SOURCE_REPORTED, [_injury(SUBJECT, T, word)])
        assert result.pairs == ((SUBJECT, expected),)
        assert result.unknown_status_count == 0
    unknown = _absences(stats, SOURCE_REPORTED, [_injury(SUBJECT, T, "GTD")])
    blank = _absences(stats, SOURCE_REPORTED, [_injury(SUBJECT, T, None)])
    assert unknown.pairs == blank.pairs == ()
    assert unknown.unknown_status_count == 1
    assert blank.unknown_status_count == 1


def test_weighted_minutes_and_share_use_earlier_games_only() -> None:
    on = date(2025, 2, 1)
    stats = [
        _stat(1, date(2025, 1, 1), 1, seconds=900, pts=10),
        _stat(1, date(2025, 1, 1), 2, seconds=1200, pts=30),
        _stat(2, date(2025, 1, 2), 1, seconds=900, pts=10),
        _stat(2, date(2025, 1, 2), 2, seconds=1200, pts=30),
        _stat(3, date(2025, 1, 3), 1, seconds=900, pts=10),
        _stat(3, date(2025, 1, 3), 2, seconds=1200, pts=30),
        _stat(1, date(2025, 1, 1), 9, team=AWAY, seconds=1800, pts=5),
        _stat(2, date(2025, 1, 2), 9, team=AWAY, seconds=1800, pts=5),
        _stat(3, date(2025, 1, 3), 9, team=AWAY, seconds=1800, pts=5),
        # Target-game points must not enter the share.
        _stat(8, on, 1, seconds=2000, pts=100),
        _stat(8, on, 2, seconds=2000, pts=100),
    ]
    team = TeamAbsences(pairs=((2, 0.5), (1, 1.0)), unknown_status_count=0)
    opp = TeamAbsences(pairs=((9, 1.0),), unknown_status_count=0)
    values = absence_feature_values(
        team_result=team,
        opponent_result=opp,
        stats=stats,
        league="nba",
        team=HOME,
        opponent=AWAY,
        target_date=on,
        player_id=1,
        known=True,
    )
    # Player 2 averages 20 minutes. p_out 0.5 contributes 10. Player 1 is excluded.
    assert values["team_missing_minutes"] == 10
    # Points: player 2 produced 90 of the team's 120. 0.5 * 90 / 120 = 0.375.
    assert values["team_missing_share_player_points"] == 0.375
    assert values["opp_missing_minutes"] == 30
    assert values["team_missing_share_player_points"] != values["team_missing_share_player_rebounds"]


def test_a_null_component_does_not_become_zero_in_the_share() -> None:
    stats = [
        _stat(1, date(2025, 1, 1), 2, seconds=1200, pts=None),
        _stat(1, date(2025, 1, 1), 1, seconds=900, pts=10),
    ]
    values = absence_feature_values(
        team_result=TeamAbsences(pairs=((2, 1.0),), unknown_status_count=0),
        opponent_result=None,
        stats=stats,
        league="nba",
        team=HOME,
        opponent=None,
        target_date=TARGET,
        player_id=1,
        known=True,
    )
    assert values["team_missing_minutes"] == 20
    assert values["team_missing_share_player_points"] is None
    assert values["opp_missing_minutes"] is None


def test_unknown_coverage_does_not_write_a_pregame_zero_or_a_partial_total() -> None:
    history = [_stat(gid, _day(gid), PLAYED, seconds=EXACT_15_MIN, pts=10) for gid in (1, 2, 3)]
    history += [_stat(gid, _day(gid), SUBJECT, seconds=1200, pts=30) for gid in (1, 2, 3)]
    target_rows = [
        _stat(TARGET_GAME, TARGET, PLAYED, seconds=1800, pts=11),
        _stat(TARGET_GAME, TARGET, SUBJECT, seconds=1800, pts=12),
    ]
    games = [_game(gid, _day(gid)) for gid in (1, 2, 3)] + [_game(TARGET_GAME, TARGET)]
    stats = history + target_rows
    injuries = [_injury(SUBJECT, T, OUT), _injury(PLAYED, T, "GTD")]
    direct = _absences(stats, SOURCE_REPORTED, injuries)
    assert direct.pairs == ((SUBJECT, 1.0),)
    assert direct.unknown_status_count == 1

    blocked = assemble_dataset(
        games,
        stats,
        _kept(TARGET_GAME, PLAYED) + _kept(TARGET_GAME, SUBJECT),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        injuries=injuries,
        injury_coverage=COVERAGE_UNKNOWN,
    )
    by_player = {row["bdl_player_id"]: row for row in blocked.rows}
    assert by_player[PLAYED]["team_missing_minutes"] is None
    assert by_player[PLAYED]["team_missing_share_player_points"] is None
    assert by_player[PLAYED]["info_source"] == INFO_PREGAME
    assert by_player[PLAYED]["player_injury_status"] == "GTD"
    assert by_player[SUBJECT]["player_injury_status"] == OUT
    assert blocked.metadata["absence_coverage"] == COVERAGE_UNKNOWN
    assert blocked.metadata["absence_coverage_note"] == COVERAGE_NOTE_UNKNOWN
    assert blocked.metadata["unknown_injury_status_count"] == 1
    assert blocked.metadata["pregame_row_count"] == len(rows_for_final_scores(blocked.rows))
    assert "team_missing_minutes" in blocked.metadata["absence_features"]
    assert "team_missing_share_player_points" in blocked.metadata["absence_features"]
    assert "opp_missing_minutes" in blocked.metadata["absence_features"]

    covered = assemble_dataset(
        games,
        stats,
        _kept(TARGET_GAME, PLAYED) + _kept(TARGET_GAME, SUBJECT),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        injuries=injuries,
        injury_coverage=COVERAGE_COVERED,
    )
    covered_row = next(row for row in covered.rows if row["bdl_player_id"] == PLAYED)
    assert covered_row["team_missing_minutes"] == 20
    assert covered_row["team_missing_share_player_points"] == 0.75
    assert covered_row["info_source"] == INFO_PREGAME
    subject = next(row for row in covered.rows if row["bdl_player_id"] == SUBJECT)
    assert subject["team_missing_minutes"] == 0
    assert subject["player_injury_status"] == OUT


def test_actual_standin_matches_team_absences_and_nulls_own_status() -> None:
    stats = [
        _stat(1, _day(1), PLAYED, seconds=900, pts=10),
        _stat(1, _day(1), SUBJECT, seconds=1200, pts=30),
        _stat(1, _day(1), 9, team=AWAY, seconds=1800, pts=4),
        _stat(2, _day(2), PLAYED, seconds=900, pts=10),
        _stat(2, _day(2), SUBJECT, seconds=1200, pts=30),
        _stat(2, _day(2), 9, team=AWAY, seconds=1800, pts=4),
        _stat(3, _day(3), PLAYED, seconds=900, pts=10),
        _stat(3, _day(3), SUBJECT, seconds=1200, pts=30),
        _stat(3, _day(3), 9, team=AWAY, seconds=1800, pts=4),
        _stat(TARGET_GAME, TARGET, PLAYED, seconds=1800, pts=15),
    ]
    games = [_game(gid, _day(gid)) for gid in (1, 2, 3)] + [_game(TARGET_GAME, TARGET)]
    dataset = assemble_dataset(
        games,
        stats,
        _kept(TARGET_GAME, PLAYED),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        injuries=[_injury(PLAYED, T, OUT)],
        absence_source=SOURCE_ACTUAL,
    )
    assert len(dataset.rows) == 1
    row = dataset.rows[0]
    direct_team = team_absences(
        "nba", HOME, TARGET_GAME, row["as_of"], SOURCE_ACTUAL,
        target_date=TARGET, stats=stats,
    )
    direct_opp = team_absences(
        "nba", AWAY, TARGET_GAME, row["as_of"], SOURCE_ACTUAL,
        target_date=TARGET, stats=stats,
    )
    expected = absence_feature_values(
        team_result=direct_team,
        opponent_result=direct_opp,
        stats=stats,
        league="nba",
        team=HOME,
        opponent=AWAY,
        target_date=TARGET,
        player_id=PLAYED,
        known=True,
    )
    assert direct_team.pairs == ((SUBJECT, 1.0),)
    assert row["info_source"] == INFO_STANDIN
    assert row["player_injury_status"] is None
    assert row["team_missing_minutes"] == expected["team_missing_minutes"] == 20
    assert row["opp_missing_minutes"] == expected["opp_missing_minutes"] == 30
    assert row["team_missing_share_player_points"] == 0.75
    assert dataset.metadata["info_source"] == INFO_STANDIN
    assert dataset.metadata["standin_row_count"] == 1
    assert dataset.metadata["standin_actual_row_count"] == 1
    assert dataset.metadata["pregame_row_count"] == 0
    assert rows_for_final_scores(dataset.rows) == []
    assert dataset.metadata["feature_sources"] == list(feature_source_names())


def test_missing_visitor_leaves_opponent_minutes_null() -> None:
    stats = [_stat(gid, _day(gid), SUBJECT, seconds=1200, pts=20) for gid in (1, 2, 3)]
    stats.append(_stat(TARGET_GAME, TARGET, PLAYED, seconds=1800, pts=10))
    games = [_game(gid, _day(gid), visitor=None) for gid in (1, 2, 3)]
    games.append(_game(TARGET_GAME, TARGET, visitor=None))
    dataset = assemble_dataset(
        games,
        stats,
        _kept(TARGET_GAME, PLAYED),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        absence_source=SOURCE_ACTUAL,
    )
    row = dataset.rows[0]
    assert row["team_missing_minutes"] == 20
    assert row["opp_missing_minutes"] is None
    assert opponent_team(HOME, None, HOME) is None


def test_game_lineups_starter_marks_standin_and_clears_own_status() -> None:
    stats = [_stat(gid, _day(gid), PLAYED) for gid in (1, 2, 3)]
    stats.append(_stat(TARGET_GAME, TARGET, PLAYED, seconds=1800))
    games = [_game(gid, _day(gid), season=2025) for gid in (1, 2, 3)]
    games.append(_game(TARGET_GAME, TARGET, season=2025))
    lineup = [
        LineupRecord("nba", TARGET_GAME, PLAYED, HOME, True),
    ]
    injuries = [_injury(PLAYED, T, OUT)]
    dataset = assemble_dataset(
        games,
        stats,
        _kept(TARGET_GAME, PLAYED),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        injuries=injuries,
        lineups=lineup,
    )
    row = dataset.rows[0]
    assert row["is_starter"] is True
    assert row["info_source"] == INFO_STANDIN
    assert row["player_injury_status"] is None
    assert row["team_missing_minutes"] is None
    assert dataset.metadata["standin_lineup_row_count"] == 1
    assert dataset.metadata["standin_actual_row_count"] == 0
    assert rows_for_final_scores(dataset.rows) == []

    early = assemble_dataset(
        [_game(TARGET_GAME, TARGET, season=2024)],
        [_stat(TARGET_GAME, TARGET, PLAYED, season=2024)],
        _kept(TARGET_GAME, PLAYED),
        season_start=2024,
        season_end=2024,
        git_head="sha",
        injuries=injuries,
        lineups=lineup,
    )
    assert early.rows[0]["is_starter"] is None
    assert early.rows[0]["info_source"] == INFO_PREGAME
    assert early.rows[0]["player_injury_status"] == OUT


def test_projected_starters_follow_first_seen_at_and_stay_pregame() -> None:
    stats = [_stat(TARGET_GAME, TARGET, PLAYED, seconds=1800)]
    games = [_game(TARGET_GAME, TARGET)]
    visible = ProjectedStarterRow("nba", TARGET_GAME, HOME, T - timedelta(days=1), T, PLAYED)
    hidden = ProjectedStarterRow(
        "nba", TARGET_GAME, HOME, T, T + timedelta(seconds=1), DNP_PLAYER
    )
    decision = starter_for_player(
        league="nba",
        game=TARGET_GAME,
        team=HOME,
        player_id=PLAYED,
        season=2025,
        as_of=T,
        lineups=(),
        projected=(visible, hidden),
    )
    assert decision.is_starter is True
    assert decision.source == "projected"
    dataset = assemble_dataset(
        games,
        stats,
        _kept(TARGET_GAME, PLAYED),
        season_start=2025,
        season_end=2025,
        git_head="sha",
        projected=(visible, hidden),
        injuries=[_injury(PLAYED, T, QUESTIONABLE)],
        lineups=(LineupRecord("nba", TARGET_GAME, PLAYED, HOME, False),),
    )
    row = dataset.rows[0]
    assert row["is_starter"] is True
    assert row["info_source"] == INFO_PREGAME
    assert row["player_injury_status"] == QUESTIONABLE
    assert dataset.metadata["pregame_row_count"] == 1

    backfill = ProjectedStarterRow(
        "nba",
        TARGET_GAME,
        HOME,
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 18, tzinfo=UTC),
        PLAYED,
    )
    only_backfill = starter_for_player(
        league="nba",
        game=TARGET_GAME,
        team=HOME,
        player_id=PLAYED,
        season=2025,
        as_of=T,
        lineups=(),
        projected=(backfill,),
    )
    assert only_backfill.is_starter is None
    assert only_backfill.source is None


def test_null_tip_t_is_the_midnight_used_for_the_injury_read() -> None:
    on = date(2026, 1, 15)
    as_of = prediction_instant(on, None, 3).as_of
    assert as_of == datetime(2026, 1, 15, 5, 0, tzinfo=UTC)
    games = [_game(1, on, tip=None, season=2026)]
    stats = [_stat(1, on, PLAYED, seconds=1800, season=2026)]
    injuries = [
        _injury(PLAYED, datetime(2026, 1, 15, 4, 0, tzinfo=UTC), OUT),
        _injury(PLAYED, as_of + timedelta(seconds=1), QUESTIONABLE),
    ]
    dataset = assemble_dataset(
        games,
        stats,
        _kept(1, PLAYED),
        season_start=2026,
        season_end=2026,
        git_head="sha",
        injuries=injuries,
    )
    row = dataset.rows[0]
    assert row["as_of"] == as_of
    assert row["tip_fallback"] is True
    assert row["player_injury_status"] == OUT
    assert row["info_source"] == INFO_PREGAME
    assert row["team_missing_minutes"] is None

    exact = assemble_dataset(
        games,
        stats,
        _kept(1, PLAYED),
        season_start=2026,
        season_end=2026,
        git_head="sha",
        injuries=[_injury(PLAYED, as_of, QUESTIONABLE)],
    )
    assert exact.rows[0]["player_injury_status"] == QUESTIONABLE


def test_default_rows_stay_pregame_and_absence_features_are_null() -> None:
    on = date(2015, 10, 28)
    games = [_game(1, date(2015, 10, 1), season=2015), _game(2, on, season=2015, tip=None)]
    stats = [
        _stat(1, date(2015, 10, 1), PLAYED, season=2015, pts=14),
        _stat(2, on, PLAYED, season=2015, pts=21),
    ]
    dataset = assemble_dataset(
        games,
        stats,
        _kept(2, PLAYED, player_points=21),
        season_start=2015,
        season_end=2015,
        git_head="sha",
    )
    row = dataset.rows[0]
    assert row["info_source"] == INFO_PREGAME
    assert row["team_missing_minutes"] is None
    assert row["opp_missing_minutes"] is None
    assert row["is_starter"] is None
    assert row["player_injury_status"] is None
    assert all(row[name] is None for name in SHARE_COLUMNS)
    assert dataset.metadata["info_source"] == INFO_PREGAME
    assert dataset.metadata["feature_sources"] == ["games", "player_game_stats", "game_odds_snapshots"]
    assert "player_prop_snapshots" not in dataset.metadata["absence_sources"]
    assert dataset.metadata["standin_row_count"] == 0
    assert dataset.metadata["pregame_row_count"] == 1
    assert set(OUTPUT_COLUMNS).issuperset(SHARE_COLUMNS)


def test_absence_queries_are_selects_and_do_not_encode_t() -> None:
    for sql in ABSENCE_QUERIES:
        folded = " ".join(sql.lower().split())
        assert folded.startswith("select")
        for forbidden in ("player_prop_snapshots", "predictions", "home_score", "insert ", "delete "):
            assert forbidden not in folded
    injuries = " ".join(PLAYER_INJURIES_SQL.lower().split())
    assert "<=" not in injuries
    assert "snapshot_at <" not in injuries
    with pytest.raises(SourceError):
        require_absence_source("player_prop_snapshots")
    with pytest.raises(SourceError):
        require_feature_source("injury_snapshots")
