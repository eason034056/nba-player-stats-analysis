"""Official injury-report features for the reported absence path.

The Harden numbers come from backend/tests/fixtures/spo153/harden_cle_bkn_20260301.json.
That file is parsed rows and made-up box-score seconds. It is not a PDF.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.ml.absence import (
    AVAILABLE,
    COVERAGE_COVERED,
    INFO_PREGAME,
    INFO_STANDIN,
    OFFICIAL_COUNT_COLUMNS,
    OFFICIAL_P_OUT_SCALE,
    P_OUT_BY_STATUS,
    SOURCE_ACTUAL,
    features_when_official_report_missing,
    official_columns_for_player,
    official_p_out,
    official_player_status,
    official_source_covered,
    p_out_for_status,
    read_official_team,
    select_official_report,
)
from app.ml.build_dataset import OUTPUT_COLUMNS, assemble_dataset
from app.ml.features import COUNT_COLUMNS, form_column_names
from app.ml.game_odds import ODDS_COLUMNS
from app.ml.labels import CATALOG_MARKETS
from app.ml.load import (
    OFFICIAL_REFRESH_SQL,
    OFFICIAL_ROWS_SQL,
    OFFICIAL_TABLE_SQL,
    ActualRecord,
    GameRecord,
    InjuryRecord,
    OfficialRefresh,
    OfficialReportRow,
    StatRecord,
    load_official_injury_inputs,
)
from app.ml.sources import feature_source_names
from app.services.injury_status import DAY_TO_DAY, DOUBTFUL, OUT, PROBABLE, QUESTIONABLE

UTC = timezone.utc
FIXTURE = Path(__file__).parent / "fixtures" / "spo153" / "harden_cle_bkn_20260301.json"
HARDEN = 192
CLE = 5
BKN = 2
GAME = 18447687
TIP = datetime(2026, 3, 1, 20, 30, tzinfo=UTC)
T = datetime(2026, 3, 1, 17, 30, tzinfo=UTC)


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _avg_minutes(seconds: list[int]) -> float:
    return (sum(seconds) / len(seconds)) / 60.0


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _stat(
    game_id: int,
    on: date,
    player: int,
    team: int,
    seconds: int,
    pts: int,
    *,
    season: int = 2025,
) -> StatRecord:
    return StatRecord(
        league="nba",
        bdl_game_id=game_id,
        bdl_player_id=player,
        bdl_team_id=team,
        season=season,
        game_date=on,
        dnp=False,
        seconds_played=seconds,
        pts=pts,
        reb=1,
        ast=1,
        fg3m=1,
        stl=1,
        blk=1,
    )


def _game(
    game_id: int,
    on: date,
    tip: datetime | None,
    *,
    home: int = BKN,
    visitor: int = CLE,
    season: int = 2025,
) -> GameRecord:
    return GameRecord(
        league="nba",
        bdl_game_id=game_id,
        season=season,
        game_date=on,
        datetime_utc=tip,
        season_type="regular_season",
        home_team_id=home,
        visitor_team_id=visitor,
    )


def _kept(game_id: int, player: int) -> list[ActualRecord]:
    values = {market: 0 for market in CATALOG_MARKETS}
    values["player_points"] = 10
    return [
        ActualRecord("nba", game_id, player, market, values[market]) for market in CATALOG_MARKETS
    ]


def _report_row(
    at: datetime,
    team: int | None,
    name: str,
    player: int | None,
    status: str | None,
    *,
    game_id: int = GAME,
    reason: str | None = None,
    category: str | None = None,
    not_yet: bool = False,
    all_available: bool = False,
) -> OfficialReportRow:
    return OfficialReportRow(
        league="nba",
        report_at=at,
        bdl_game_id=game_id,
        bdl_team_id=team,
        player_raw=name,
        bdl_player_id=player,
        status=status,
        reason=reason,
        category=category,
        not_yet_submitted=not_yet,
        all_players_available=all_available,
    )


def _refresh(at: datetime, *, complete: bool = True) -> OfficialRefresh:
    return OfficialRefresh(league="nba", refreshed_at=at, complete=complete)


def _rows_from(spec: dict, block: dict) -> list[OfficialReportRow]:
    game_id = spec["game"]["bdl_game_id"]
    at = _dt(block["report_at"])
    rows: list[OfficialReportRow] = []
    for item in block["rows"]:
        rows.append(
            _report_row(
                at,
                item["team_id"],
                item["player_raw"],
                item["bdl_player_id"],
                item["status"],
                game_id=item.get("bdl_game_id", game_id),
                reason=item["reason"],
                category=item["category"],
            )
        )
    return rows


def harden_inputs() -> tuple[
    list[GameRecord],
    list[StatRecord],
    list[OfficialReportRow],
    list[OfficialRefresh],
    list[ActualRecord],
]:
    """Build the CLE at BKN example from the fixture file.

    Prior seconds are the fixture's ``seconds_by_game``. The target game
    also has a played row for every one of those players, so a box-score
    absence would see them as present.
    """
    spec = _load()
    game = spec["game"]
    target_on = _day(game["date"])
    games = [
        _game(item["bdl_game_id"], _day(item["date"]), _dt(item["date"] + "T17:00:00+00:00"))
        for item in spec["prior_games"]
    ]
    games.append(_game(game["bdl_game_id"], target_on, _dt(game["datetime_utc"])))
    stats: list[StatRecord] = []
    for player in spec["minutes"]:
        for item, seconds, pts in zip(
            spec["prior_games"], player["seconds_by_game"], player["pts_by_game"], strict=True
        ):
            stats.append(
                _stat(
                    item["bdl_game_id"],
                    _day(item["date"]),
                    player["bdl_player_id"],
                    player["team_id"],
                    seconds,
                    pts,
                )
            )
        stats.append(
            _stat(
                game["bdl_game_id"],
                target_on,
                player["bdl_player_id"],
                player["team_id"],
                player["seconds_by_game"][-1],
                player["pts_by_game"][-1],
            )
        )
    rows = _rows_from(spec, spec["t_report"]) + _rows_from(spec, spec["tip_report"])
    refreshes = [_refresh(_dt(spec["refresh"]["refreshed_at"]))]
    return games, stats, rows, refreshes, _kept(GAME, HARDEN)


def _assemble(games, stats, rows, refreshes, actuals, **kwargs):
    return assemble_dataset(
        games,
        stats,
        actuals,
        season_start=2025,
        season_end=2025,
        git_head="spo153",
        official_rows=rows,
        official_refreshes=refreshes,
        **kwargs,
    )


def _one(dataset) -> dict:
    assert len(dataset.rows) == 1
    return dataset.rows[0]


def test_fixture_minutes_are_the_published_feature_values() -> None:
    """31.00 + 20.83 + 0.5 * 21.68 = 62.67. Dropping Ellis leaves 51.83."""
    spec = _load()
    by_id = {item["bdl_player_id"]: item for item in spec["minutes"]}
    mitchell = _avg_minutes(by_id[322]["seconds_by_game"])
    wade = _avg_minutes(by_id[666940]["seconds_by_game"])
    ellis = _avg_minutes(by_id[38017714]["seconds_by_game"])
    claxton = _avg_minutes(by_id[666508]["seconds_by_game"])
    demin = _avg_minutes(by_id[1057266813]["seconds_by_game"])
    powell = _avg_minutes(by_id[1057279425]["seconds_by_game"])
    assert mitchell == 31.0
    assert wade == 20.83
    assert ellis == 21.68
    assert mitchell + wade + 0.5 * ellis == 62.67
    assert mitchell + wade == 51.83
    assert claxton + demin + powell == 75.0


def test_harden_team_missing_minutes_uses_the_1215_report_not_the_tip_report() -> None:
    games, stats, rows, refreshes, actuals = harden_inputs()
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["as_of"] == T
    assert row["team_missing_minutes"] == 62.67
    assert row["opp_missing_minutes"] == 75.0
    assert row["rot_out_n"] == 2
    assert row["rot_q_n"] == 1
    assert row["unmatched_listed_n"] == 0
    assert row["injury_report_missing"] == 0
    assert row["player_injury_status"] == QUESTIONABLE
    assert row["info_source"] == INFO_PREGAME
    assert row["team_missing_share_player_points"] == 85 / 140


def test_a_report_after_t_does_not_change_the_harden_row() -> None:
    """Both reports are in the input. T still sees 62.67, not the tip's 51.83."""
    games, stats, rows, refreshes, actuals = harden_inputs()
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["team_missing_minutes"] == 62.67
    # Asking at the tip needs a refresh inside the 90 minutes before 20:30.
    # The 12:15 PM refresh is too old for that later instant, so it cannot
    # leak on its own. A 3:15 PM refresh makes the tip report eligible, and
    # that report is the 51.83 number.
    tip_refresh = _refresh(datetime(2026, 3, 1, 20, 15, 5, tzinfo=UTC))
    direct = _columns_at(stats, rows, [*refreshes, tip_refresh], TIP)
    assert direct["team_missing_minutes"] == 51.83
    assert direct["player_injury_status"] == AVAILABLE
    assert direct["rot_q_n"] == 0
    assert official_player_status(rows, "nba", GAME, CLE, HARDEN, T) == QUESTIONABLE


def _columns_at(stats, rows, refreshes, as_of: datetime) -> dict:
    target = date(2026, 3, 1)
    team = read_official_team(
        rows,
        refreshes,
        league="nba",
        team=CLE,
        game=GAME,
        as_of=as_of,
        target_date=target,
        stats=stats,
    )
    opponent = read_official_team(
        rows,
        refreshes,
        league="nba",
        team=BKN,
        game=GAME,
        as_of=as_of,
        target_date=target,
        stats=stats,
    )
    return official_columns_for_player(
        team,
        opponent,
        stats=stats,
        league="nba",
        team=CLE,
        opponent=BKN,
        target_date=target,
        player_id=HARDEN,
        own_status=official_player_status(rows, "nba", GAME, CLE, HARDEN, as_of),
    )


def test_no_report_before_t_is_null_and_does_not_use_a_snapshot() -> None:
    games, stats, _rows, refreshes, actuals = harden_inputs()
    snapshot = InjuryRecord(
        league="nba",
        snapshot_at=T - timedelta(hours=1),
        bdl_player_id=322,
        listed=True,
        status=OUT,
    )
    dataset = _assemble(
        games,
        stats,
        [],
        refreshes,
        actuals,
        injuries=[snapshot],
        injury_coverage=COVERAGE_COVERED,
    )
    row = _one(dataset)
    assert row["team_missing_minutes"] is None
    assert row["opp_missing_minutes"] is None
    assert row["team_missing_share_player_points"] is None
    assert row["rot_out_n"] is None
    assert row["rot_q_n"] is None
    assert row["unmatched_listed_n"] is None
    assert row["injury_report_missing"] == 1
    assert row["player_injury_status"] is None
    assert features_when_official_report_missing()["injury_report_missing"] == 1


def test_a_report_one_second_after_t_is_not_used() -> None:
    built = _tiny(report_at=T + timedelta(seconds=1))
    row = _one(_assemble(*built))
    assert row["team_missing_minutes"] is None
    assert row["injury_report_missing"] == 1


def test_a_report_exactly_at_t_is_used() -> None:
    built = _tiny(report_at=T)
    row = _one(_assemble(*built))
    assert row["team_missing_minutes"] == 20.0
    assert row["injury_report_missing"] == 0


def test_a_stale_refresh_blocks_numbers_even_when_the_report_is_before_t() -> None:
    games, stats, rows, _refreshes, actuals = harden_inputs()
    stale = [_refresh(datetime(2026, 3, 1, 15, 59, 59, tzinfo=UTC))]
    row = _one(_assemble(games, stats, rows, stale, actuals))
    assert row["team_missing_minutes"] is None
    assert row["injury_report_missing"] == 1
    fresh = datetime(2026, 3, 1, 16, 0, tzinfo=UTC)
    assert official_source_covered([_refresh(fresh)], "nba", T) is True
    assert official_source_covered(stale, "nba", T) is False
    assert official_source_covered([_refresh(T, complete=False)], "nba", T) is False
    assert official_source_covered([_refresh(T + timedelta(seconds=1))], "nba", T) is False


def test_not_yet_submitted_nulls_that_team_and_still_reads_the_opponent() -> None:
    games, stats, rows, refreshes, _actuals = _tiny(report_at=T)
    rows.append(
        _report_row(T, CLE, "", None, None, not_yet=True, reason="NOT YET SUBMITTED")
    )
    dataset = _assemble(games, stats, rows, refreshes, _kept(GAME, 10))
    row = _one(dataset)
    assert row["team_missing_minutes"] is None
    assert row["rot_out_n"] is None
    assert row["player_injury_status"] is None
    assert row["opp_missing_minutes"] == 20.0
    assert row["injury_report_missing"] == 0


def test_doubtful_counts_as_a_rotation_out_at_the_old_weight() -> None:
    games, stats, _rows, refreshes, actuals = _tiny(report_at=T)
    rows = [
        _report_row(T, CLE, "Teammate, Doubtful", 14, DOUBTFUL),
        _report_row(T, BKN, "Opponent, Out", 11, OUT),
    ]
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["rot_out_n"] == 1
    assert row["rot_q_n"] == 0
    assert row["team_missing_minutes"] == 15.0


def test_opponent_not_yet_submitted_leaves_only_the_opponent_null() -> None:
    games, stats, rows, refreshes, actuals = _tiny(report_at=T)
    rows.append(_report_row(T, BKN, "", None, None, not_yet=True))
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["team_missing_minutes"] == 20.0
    assert row["opp_missing_minutes"] is None
    assert row["injury_report_missing"] == 0
    assert row["rot_out_n"] == 1


def test_a_null_team_id_is_not_counted_for_either_team() -> None:
    games, stats, rows, refreshes, actuals = _tiny(report_at=T)
    rows = [row for row in rows if row.bdl_team_id != CLE]
    rows.append(_report_row(T, None, "Teammate, Out", 14, OUT))
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["team_missing_minutes"] == 0.0
    assert row["opp_missing_minutes"] == 20.0


def test_a_team_left_off_a_covering_report_has_zero_missing_minutes() -> None:
    games, stats, _rows, refreshes, _actuals = _tiny(report_at=T)
    only_opponent = [
        _report_row(T, BKN, "Opponent, Out", 11, OUT),
    ]
    dataset = _assemble(games, stats, only_opponent, refreshes, _kept(GAME, 10))
    row = _one(dataset)
    assert row["team_missing_minutes"] == 0.0
    assert row["opp_missing_minutes"] == 20.0
    assert row["injury_report_missing"] == 0
    marker = [_report_row(T, CLE, "", None, None, all_available=True)]
    ready = _one(_assemble(games, stats, marker, refreshes, _kept(GAME, 10)))
    assert ready["team_missing_minutes"] == 0.0
    assert ready["opp_missing_minutes"] == 0.0


def test_available_is_zero_on_the_official_scale_only() -> None:
    assert official_p_out(AVAILABLE) == 0.0
    assert p_out_for_status(AVAILABLE) is None
    assert set(P_OUT_BY_STATUS) == {OUT, DOUBTFUL, QUESTIONABLE, DAY_TO_DAY, PROBABLE}
    assert OFFICIAL_P_OUT_SCALE[OUT] == 1
    assert OFFICIAL_P_OUT_SCALE[DOUBTFUL] == 0.75
    assert OFFICIAL_P_OUT_SCALE[QUESTIONABLE] == 0.5
    assert OFFICIAL_P_OUT_SCALE[DAY_TO_DAY] == 0.25
    assert OFFICIAL_P_OUT_SCALE[PROBABLE] == 0.1
    assert OFFICIAL_P_OUT_SCALE[AVAILABLE] == 0.0
    games, stats, rows, refreshes, actuals = _tiny(report_at=T)
    rows.append(_report_row(T, CLE, "Teammate, Available", 12, AVAILABLE))
    stats.extend(_played(12, CLE, 1800, 10))
    dataset = _assemble(games, stats, rows, refreshes, actuals)
    row = _one(dataset)
    assert row["team_missing_minutes"] == 20.0
    assert dataset.metadata["unknown_injury_status_count"] == 0


def test_box_score_standin_does_not_fill_official_count_columns() -> None:
    games, stats, rows, refreshes, actuals = harden_inputs()
    dataset = _assemble(games, stats, rows, refreshes, actuals, absence_source=SOURCE_ACTUAL)
    row = _one(dataset)
    assert row["info_source"] == INFO_STANDIN
    assert row["team_missing_minutes"] == 0.0
    assert row["rot_out_n"] is None
    assert row["rot_q_n"] is None
    assert row["unmatched_listed_n"] is None
    assert row["injury_report_missing"] is None


def test_unmatched_names_skip_g_league_lines() -> None:
    games, stats, rows, refreshes, actuals = _tiny(report_at=T)
    rows.append(_report_row(T, CLE, "Real, Player", None, OUT, category="Injury/Illness"))
    rows.append(
        _report_row(
            T,
            CLE,
            "Two, Way",
            None,
            OUT,
            reason="G League - Two-Way",
            category="G League",
        )
    )
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["unmatched_listed_n"] == 1
    assert row["team_missing_minutes"] == 20.0


def test_one_unknown_word_is_counted_once_for_the_team() -> None:
    games, stats, rows, refreshes, _actuals = _tiny(report_at=T)
    rows.append(_report_row(T, CLE, "Mystery, Word", 12, "Mystery"))
    stats.extend(_played(12, CLE, 1200, 4))
    stats.extend(_played(13, CLE, 1200, 4))
    actuals = _kept(GAME, 10) + _kept(GAME, 13)
    dataset = _assemble(games, stats, rows, refreshes, actuals)
    assert len(dataset.rows) == 2
    assert dataset.metadata["unknown_injury_status_count"] == 1


def test_another_games_row_at_the_same_time_does_not_change_harden() -> None:
    games, stats, rows, refreshes, actuals = harden_inputs()
    chosen = select_official_report(rows, "nba", GAME, T)
    assert chosen is not None
    assert all(row.bdl_game_id == GAME for row in chosen)
    assert chosen[0].report_at == datetime(2026, 3, 1, 17, 15, 5, tzinfo=UTC)
    row = _one(_assemble(games, stats, rows, refreshes, actuals))
    assert row["team_missing_minutes"] == 62.67


def test_official_counts_are_outside_the_baseline_feature_list() -> None:
    headline = ("is_home",) + COUNT_COLUMNS + form_column_names() + ODDS_COLUMNS
    for name in OFFICIAL_COUNT_COLUMNS:
        assert name not in headline
        assert name in OUTPUT_COLUMNS
    assert "team_missing_minutes" not in headline
    assert "nba_injury_report_rows" not in headline
    assert "injuries_nba_official" not in headline
    assert feature_source_names() == ("games", "player_game_stats", "game_odds_snapshots")


def test_official_sql_does_not_filter_time_or_write() -> None:
    for sql in (OFFICIAL_TABLE_SQL, OFFICIAL_ROWS_SQL, OFFICIAL_REFRESH_SQL):
        folded = " ".join(sql.lower().split())
        assert folded.startswith("select")
        assert "<=" not in folded
        assert "predictions" not in folded
        assert "insert" not in folded
    import app.ml.absence as absence
    import app.ml.build_dataset as build_dataset
    import app.ml.load as load

    text = inspect.getsource(absence) + inspect.getsource(load) + inspect.getsource(build_dataset)
    for name in ("injury_report_match", "injury_report_parser", "injury_report_fetcher"):
        assert name not in text


def test_importing_the_api_does_not_import_app_ml() -> None:
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


def test_loader_skips_a_missing_table_and_maps_a_present_one() -> None:
    import asyncio

    class _Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> bool:
            return False

    class _Conn:
        def __init__(self, answers: dict[str, list[dict]]):
            self.answers = answers

        def transaction(self, readonly: bool = True) -> _Tx:
            del readonly
            return _Tx()

        async def fetch(self, sql: str, *args: object) -> list[dict]:
            for key, rows in self.answers.items():
                if key in sql:
                    return rows
            raise AssertionError(sql)

    missing = asyncio.run(
        load_official_injury_inputs(_Conn({"to_regclass": [{"name": None}]}), league="nba")
    )
    assert missing is None
    at = T
    present = asyncio.run(
        load_official_injury_inputs(
            _Conn(
                {
                    "to_regclass": [{"name": "nba_injury_report_rows"}],
                    "FROM nba_injury_report_rows": [
                        {
                            "league": "nba",
                            "report_at": at,
                            "bdl_game_id": GAME,
                            "bdl_team_id": CLE,
                            "player_raw": "Harden, James",
                            "bdl_player_id": HARDEN,
                            "status": QUESTIONABLE,
                            "reason": None,
                            "category": None,
                            "not_yet_submitted": False,
                            "all_players_available": False,
                        }
                    ],
                    "FROM source_refreshes": [
                        {"league": "nba", "refreshed_at": at, "complete": True}
                    ],
                }
            ),
            league="nba",
        )
    )
    assert present is not None
    assert present[0][0].bdl_player_id == HARDEN
    assert present[1][0].complete is True


def _played(player: int, team: int, seconds: int, pts: int) -> list[StatRecord]:
    rows = []
    for offset, game_id in enumerate((101, 102, 103), start=1):
        rows.append(_stat(game_id, date(2026, 2, offset), player, team, seconds, pts))
    rows.append(_stat(GAME, date(2026, 3, 1), player, team, seconds, pts))
    return rows


def _tiny(report_at: datetime):
    """CLE subject, one CLE Out, and one BKN Out.

    Both listed players average 20 minutes. The subject is rotation and is
    not on the report, so his own team total is the teammate's 20 minutes.
    """
    games = [
        _game(101, date(2026, 2, 1), datetime(2026, 2, 1, 17, tzinfo=UTC)),
        _game(102, date(2026, 2, 2), datetime(2026, 2, 2, 17, tzinfo=UTC)),
        _game(103, date(2026, 2, 3), datetime(2026, 2, 3, 17, tzinfo=UTC)),
        _game(GAME, date(2026, 3, 1), TIP),
    ]
    stats = _played(10, CLE, 1200, 8) + _played(14, CLE, 1200, 6) + _played(11, BKN, 1200, 6)
    rows = [
        _report_row(report_at, CLE, "Teammate, Out", 14, OUT),
        _report_row(report_at, BKN, "Opponent, Out", 11, OUT),
    ]
    return games, stats, rows, [_refresh(T)], _kept(GAME, 10)
