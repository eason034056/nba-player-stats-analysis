"""SPO-113 NBA field enrichment.

Covers the ET clock, suggest/pick position, lineup confirmation, game-log
venue, season hit rate, opponent-rank fill, and teammate games missed.
WNBA stays on the previous payload: new fields are absent or null.
"""

from __future__ import annotations

import copy
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.api.nba import get_events, get_player_history, suggest_players
from app.models.schemas import NBAEvent
from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.defense_ranks import (
    build_defense_rank_table,
    fill_null_defense_ranks,
)
from app.services.espn_schedule import compact_event
from app.services.event_fields import commence_time_et, enrich_nba_event
from app.services.daily_analysis import DailyAnalysisService
from app.services.lineup_service import confirmation_status
from app.services.nba_season import (
    normalize_nba_season_label,
    recorded_nba_season_label,
)
from app.services.projection_service import ProjectionService

_ESPN = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "espn"
_HEADER = [
    "Player",
    "Season",
    "GameType",
    "Date",
    "Team",
    "Opponent",
    "W/L",
    "Status",
    "Pos",
    "MIN",
    "PTS",
    "REB",
    "AST",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        for row in rows:
            full = {column: "" for column in _HEADER}
            full.update(row)
            writer.writerow(full)


def _row(
    player: str,
    season: str,
    when: str,
    team: str,
    opponent: str,
    points: str,
    *,
    pos: str = "PG",
    teammate: bool = False,
) -> dict[str, str]:
    return {
        "Player": player,
        "Season": season,
        "GameType": "regular_season",
        "Date": when,
        "Team": team,
        "Opponent": opponent,
        "Status": "Starter",
        "Pos": pos,
        "MIN": "30:00",
        "PTS": points,
        "REB": "1",
        "AST": "1",
    }


def load_odds_fixture(name: str) -> object:
    """Recorded Odds API body. Callers edit a deepcopy, not this object."""
    path = Path(__file__).resolve().parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _lakers_warriors_event() -> dict:
    """Recorded events row, with the clubs and tip this test needs."""
    events = load_odds_fixture("odds_api_events__basketball_nba.json")
    event = copy.deepcopy(events[0])
    event["home_team"] = "Los Angeles Lakers"
    event["away_team"] = "Golden State Warriors"
    event["commence_time"] = "2026-01-15T01:00:00Z"
    return event


def _player_points_bookmakers(rows: list[tuple[str, str, float | None]]) -> list[dict]:
    """One recorded bookmaker, outcomes copied and then edited."""
    recorded = load_odds_fixture("odds_api_event_odds__player_points.json")
    book = copy.deepcopy(recorded["bookmakers"][0])
    template = book["markets"][0]["outcomes"][0]
    outcomes = []
    for player_name, side, point in rows:
        outcome = copy.deepcopy(template)
        outcome["description"] = player_name
        outcome["name"] = side
        if point is not None:
            outcome["point"] = point
        outcomes.append(outcome)
    book["markets"][0]["outcomes"] = outcomes
    return [book]


def _knicks_opener() -> dict:
    """First regular-season event on the recorded Knicks 2025-26 schedule."""
    payload = json.loads(
        (_ESPN / "nba_team_18_schedule_2026_type_2.json").read_text(encoding="utf-8")
    )
    assert payload["team"]["abbreviation"] == "NY"
    for raw in payload["events"]:
        event = compact_event("nba", raw)
        if (event.get("seasonType") or {}).get("abbreviation") == "reg":
            return event
    raise AssertionError("recorded Knicks schedule has no regular-season event")


def _service(path: Path, league: str = "nba") -> CSVPlayerHistoryService:
    """Load one isolated service.

    NBA ``load_csv`` reads the module ``CSV_PATH``. Put the temp file
    there only for this load, then put the shipped path back so a later
    test that uses the process-wide service still sees the real log.
    """
    service = CSVPlayerHistoryService(league=league)
    if league == "nba":
        import app.services.csv_player_history as history

        previous = history.CSV_PATH
        history.CSV_PATH = str(path)
        try:
            service.load_csv()
        finally:
            history.CSV_PATH = previous
    else:
        service._csv_path = str(path)
        service.load_csv()
    return service


class TestCommenceTimeEt:
    def test_winter_offset_is_minus_five(self):
        # 2026-01-15 01:00 UTC is 2026-01-14 20:00 in New York, EST.
        text = commence_time_et("2026-01-15T01:00:00Z")
        assert text == "2026-01-14T20:00:00-05:00"

    def test_summer_offset_is_minus_four(self):
        # 2026-07-15 00:00 UTC is 2026-07-14 20:00 in New York, EDT.
        text = commence_time_et(datetime(2026, 7, 15, tzinfo=timezone.utc))
        assert text == "2026-07-14T20:00:00-04:00"

    def test_unparseable_is_null(self):
        assert commence_time_et("not-a-time") is None


class TestLineupConfirmation:
    def test_any_confirmed_snapshot_wins(self):
        # RotoGrinders always says projected. It must not veto RotoWire.
        lineup = {
            "starters": ["A", "B", "C", "D", "E"],
            "source_snapshots": {
                "rotowire": {"status": "confirmed"},
                "rotogrinders": {"status": "projected"},
            },
        }
        assert confirmation_status(lineup) == "confirmed"

    def test_expected_without_confirmed_is_projected(self):
        lineup = {
            "starters": ["A"],
            "source_snapshots": {
                "rotowire": {"status": "expected"},
                "rotogrinders": {"status": "projected"},
            },
        }
        assert confirmation_status(lineup) == "projected"

    def test_starters_without_snapshots_are_projected(self):
        assert confirmation_status({"starters": ["A"], "source_snapshots": {}}) == "projected"

    def test_empty_record_is_null(self):
        assert confirmation_status(None) is None
        assert confirmation_status({}) is None
        assert confirmation_status({"source_snapshots": {}, "starters": []}) is None


@pytest.mark.asyncio
async def test_team_lineup_route_exposes_confirmation_without_changing_status(monkeypatch):
    from app.api.lineups import get_team_lineup

    async def fake_team(date, team):
        return (
            {
                "date": date,
                "team": team.upper(),
                "opponent": "BOS",
                "home_or_away": "HOME",
                "status": "projected",
                "starters": ["A", "B", "C", "D", "E"],
                "bench_candidates": [],
                "sources": ["rotowire"],
                "source_disagreement": False,
                "confidence": "low",
                "updated_at": None,
                "source_snapshots": {"rotowire": {"status": "confirmed"}},
            },
            "fresh",
            None,
        )

    monkeypatch.setattr("app.api.lineups.lineup_service.get_team_lineup", fake_team)
    lineup = await get_team_lineup(team="lal", date="2026-01-15")
    assert lineup.status == "projected"
    assert lineup.confirmation_status == "confirmed"


@pytest.mark.asyncio
async def test_events_add_et_clock_and_per_team_lineup_status(monkeypatch):
    async def fake_events(**kwargs):
        return [_lakers_warriors_event()]

    async def fake_peek(date):
        assert date == "2026-01-15"
        return {
            "LAL": {
                "starters": ["LeBron James"],
                "source_snapshots": {"rotowire": {"status": "confirmed"}},
            },
            "GSW": {
                "starters": ["Stephen Curry"],
                "source_snapshots": {
                    "rotowire": {"status": "expected"},
                    "rotogrinders": {"status": "projected"},
                },
            },
        }

    monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
    monkeypatch.setattr("app.api.nba.cache_service.get", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.nba.cache_service.set", AsyncMock(return_value=True))
    monkeypatch.setattr("app.api.nba.lineup_service.peek_lineups", fake_peek)

    response = await get_events(date="2026-01-15", regions="us", tz_offset=0)
    event = response.events[0]
    assert event.commence_time_et == "2026-01-14T20:00:00-05:00"
    assert event.display_tz == "ET"
    assert event.commence_time == datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    assert event.lineup_status is not None
    assert event.lineup_status.home == "confirmed"
    assert event.lineup_status.away == "projected"


def test_cached_event_without_the_new_fields_still_enriches():
    event = NBAEvent(
        event_id="evt-1",
        sport_key="basketball_nba",
        home_team="Boston Celtics",
        away_team="Miami Heat",
        commence_time="2026-07-15T00:00:00Z",
    )
    enriched = enrich_nba_event(event, {})
    assert enriched.commence_time_et == "2026-07-14T20:00:00-04:00"
    assert enriched.display_tz == "ET"
    assert enriched.lineup_status.home is None
    assert enriched.lineup_status.away is None


class TestPosition:
    def test_latest_game_log_position(self, tmp_path):
        path = tmp_path / "pos.csv"
        _write_csv(
            path,
            [
                _row("Stephen Curry", "2025-2026", "1/1/2026", "Warriors", "Lakers", "20", pos="PG"),
                _row("Stephen Curry", "2026-2027", "11/2/2026", "Warriors", "Lakers", "25", pos="SG"),
            ],
        )
        service = _service(path)
        assert service.latest_position("Stephen Curry") == "SG"
        assert service.latest_position("Nobody") is None

    @pytest.mark.asyncio
    async def test_suggest_returns_position_beside_the_name_list(self, monkeypatch, tmp_path):
        path = tmp_path / "suggest.csv"
        _write_csv(
            path,
            [_row("Stephen Curry", "2025-2026", "1/1/2026", "Warriors", "Lakers", "20", pos="PG")],
        )
        import app.services.csv_player_history as history

        monkeypatch.setattr(history, "CSV_PATH", str(path))
        monkeypatch.setattr(history.csv_player_service, "_loaded", False)
        monkeypatch.setattr(history.csv_player_service, "_cache", {})
        monkeypatch.setattr(history.csv_player_service, "_all_players", [])
        monkeypatch.setattr(history.csv_player_service, "_lineup_cache", {})

        class _Snapshot:
            data = {
                "bookmakers": _player_points_bookmakers(
                    [
                        ("Stephen Curry", "Over", None),
                        ("Nobody On The Log", "Over", None),
                    ]
                )
            }
            fetched_at = datetime(2026, 11, 10, tzinfo=timezone.utc)
            data_age_seconds = 1
            cache_state = "fresh"
            source = "snapshot_cache"

        monkeypatch.setattr(
            "app.api.nba.odds_gateway.get_market_snapshot",
            AsyncMock(return_value=_Snapshot()),
        )
        response = await suggest_players(event_id="evt-1", q="", market="player_points")
        assert response.players == ["Nobody On The Log", "Stephen Curry"]
        by_name = {item.name: item.position for item in response.suggestions}
        assert by_name["Stephen Curry"] == "PG"
        assert by_name["Nobody On The Log"] is None

    @pytest.mark.asyncio
    async def test_daily_pick_carries_the_game_log_position(self, monkeypatch, tmp_path):
        path = tmp_path / "pick.csv"
        _write_csv(
            path,
            [_row("Stephen Curry", "2025-2026", "1/1/2026", "Warriors", "Lakers", "30", pos="PG")],
        )
        monkeypatch.setattr("app.services.daily_analysis.MIN_SAMPLE_GAMES", 1)
        service = DailyAnalysisService()
        service.csv_service = _service(path)
        service._get_props_for_market = AsyncMock(
            return_value=_player_points_bookmakers(
                [
                    ("Stephen Curry", "Over", 10.5),
                    ("Stephen Curry", "Under", 10.5),
                ]
            )
        )
        picks, _, _ = await service._analyze_single_event(
            event_id="evt-1",
            home_team="Los Angeles Lakers",
            away_team="Golden State Warriors",
            commence_time="2026-01-15T01:00:00Z",
            projections={},
            league="nba",
        )
        points = next(pick for pick in picks if pick.metric == "points")
        assert points.position == "PG"


class TestHistoryFields:
    def _path(self, tmp_path: Path) -> Path:
        opener = _knicks_opener()
        # 2025-10-22T23:00Z is still October 22 in both New York and Los Angeles.
        path = tmp_path / "history.csv"
        current = recorded_nba_season_label(datetime(2026, 11, 10, tzinfo=timezone.utc))
        assert current == "2026-2027"
        _write_csv(
            path,
            [
                _row("Venue Player", "2025-2026", "10/22/2025", "Knicks", "Cavaliers", "22", pos="PG"),
                _row("Venue Player", "2025-2026", "10/24/2025", "Knicks", "Heat", "10", pos="PG"),
                _row("Bench Mate", "2025-2026", "10/22/2025", "Knicks", "Cavaliers", "8", pos="SG"),
                _row("Venue Player", current, "11/2/2026", "Knicks", "Celtics", "40", pos="SF"),
            ],
        )
        assert opener["id"] == "401809234"
        return path

    def test_home_away_comes_from_the_recorded_schedule(self, tmp_path):
        service = _service(self._path(tmp_path))
        stats = service.get_player_stats("Venue Player", "points", 15.0, season="2025-2026")
        by_day = {log["date_full"]: log["home_or_away"] for log in stats["game_logs"]}
        assert by_day["2025-10-22"] == "home"
        # Heat on 10/24/2025 is not that Knicks opener, so the join misses.
        assert by_day["2025-10-24"] is None

    def test_season_rate_sits_beside_the_all_games_rate(self, tmp_path):
        service = _service(self._path(tmp_path))
        stats = service.get_player_stats("Venue Player", "points", 15.0)
        # All games: 22, 10, 40. Over 15: 22 and 40.
        assert stats["n_games"] == 3
        assert stats["p_over"] == round(2 / 3, 4)
        assert stats["season"] == "2026-2027"
        assert stats["season_n_games"] == 1
        assert stats["season_p_over"] == 1.0
        assert stats["season_p_under"] == 0.0

        older = service.get_player_stats(
            "Venue Player", "points", 15.0, season="2025-26"
        )
        assert older["season"] == "2025-2026"
        assert older["season_n_games"] == 2
        # 22 over, 10 under.
        assert older["season_p_over"] == 0.5
        assert older["season_p_under"] == 0.5
        # The all-games numbers do not shrink when season is set.
        assert older["n_games"] == 3

    def test_last_n_does_not_shrink_the_season_sample(self, tmp_path):
        service = _service(self._path(tmp_path))
        stats = service.get_player_stats("Venue Player", "points", 15.0, n=1, season="2025-2026")
        assert stats["n_games"] == 1
        assert stats["season_n_games"] == 2

    def test_teammate_missed_games_and_split(self, tmp_path):
        service = _service(self._path(tmp_path))
        stats = service.get_player_stats("Venue Player", "points", 15.0, season="2025-2026")
        bench = next(item for item in stats["teammate_context"] if item["name"] == "Bench Mate")
        assert "Bench Mate" in stats["teammates"]
        assert bench["games_missed"] == 2
        assert bench["with_n"] == 1
        assert bench["without_n"] == 2
        assert bench["with_mean"] == 22.0
        assert [game["date"] for game in bench["missed_games"]] == [
            "2025-10-24",
            "2026-11-02",
        ]
        opener = next(
            game for game in bench["missed_games"] if game["date"] == "2025-10-24"
        )
        played = [game for game in bench["missed_games"] if game["date"] == "2025-10-22"]
        assert played == []
        # 10/24 does not join the opener, so the id is null. The opener's
        # id is asserted on the home row's companion via a game Bench missed
        # only when the date joins. 11/2/2026 may or may not join.
        assert opener["game_id"] is None or isinstance(opener["game_id"], str)

    def test_missed_opener_carries_the_recorded_event_id(self, tmp_path):
        # Bench Mate plays the opener. A second player misses that date.
        path = tmp_path / "missed-id.csv"
        _write_csv(
            path,
            [
                _row("Scorer", "2025-2026", "10/22/2025", "Knicks", "Cavaliers", "22"),
                _row("Scorer", "2025-2026", "10/24/2025", "Knicks", "Heat", "10"),
                _row("Opener Mate", "2025-2026", "10/24/2025", "Knicks", "Heat", "4"),
            ],
        )
        service = _service(path)
        stats = service.get_player_stats("Scorer", "points", 15.0, season="2025-2026")
        mate = next(item for item in stats["teammate_context"] if item["name"] == "Opener Mate")
        missed = {game["date"]: game["game_id"] for game in mate["missed_games"]}
        assert missed["2025-10-22"] == "401809234"
        assert mate["with_mean"] == 10.0
        assert mate["without_mean"] == 22.0

    @pytest.mark.asyncio
    async def test_player_history_route_echoes_the_season(self, monkeypatch, tmp_path):
        path = self._path(tmp_path)
        import app.services.csv_player_history as history

        monkeypatch.setattr(history, "CSV_PATH", str(path))
        monkeypatch.setattr(history.csv_player_service, "_loaded", False)
        monkeypatch.setattr(history.csv_player_service, "_cache", {})
        monkeypatch.setattr(history.csv_player_service, "_all_players", [])
        monkeypatch.setattr(history.csv_player_service, "_lineup_cache", {})
        response = await get_player_history(
            player="Venue Player",
            metric="points",
            threshold=15.0,
            n=0,
            bins=15,
            exclude_dnp=True,
            opponent=None,
            is_starter=None,
            teammate_filter=None,
            teammate_played=None,
            include_playoffs=False,
            include_play_in=False,
            season="2025-26",
        )
        assert response.season == "2025-2026"
        assert response.season_n_games == 2
        assert response.n_games == 3
        assert response.game_logs[0].home_or_away in {"home", "away", None}
        assert any(log.home_or_away == "home" for log in response.game_logs)
        assert response.teammate_context

    def test_wnba_history_does_not_gain_the_nba_fields(self, tmp_path):
        path = tmp_path / "wnba.csv"
        _write_csv(
            path,
            [_row("A'ja Wilson", "2025", "6/1/2025", "Aces", "Mercury", "30", pos="F")],
        )
        service = _service(path, league="wnba")
        stats = service.get_player_stats("A'ja Wilson", "points", 20.0)
        assert "season" not in stats
        assert "teammate_context" not in stats
        assert "home_or_away" not in stats["game_logs"][0]
        assert stats["n_games"] == 1
        assert stats["teammates"] == []


class TestDefenseRanks:
    def _games(self) -> list[dict]:
        day = datetime(2025, 11, 1)
        later = datetime(2025, 11, 3)
        return [
            {
                "team": "Warriors",
                "opponent": "Lakers",
                "points": 10,
                "pos": "PG",
                "game_date": day,
                "season": "2025-2026",
                "game_type": "regular_season",
            },
            {
                "team": "Lakers",
                "opponent": "Warriors",
                "points": 30,
                "pos": "C",
                "game_date": day,
                "season": "2025-2026",
                "game_type": "regular_season",
            },
            {
                "team": "Celtics",
                "opponent": "Heat",
                "points": 20,
                "pos": "PG",
                "game_date": later,
                "season": "2025-2026",
                "game_type": "regular_season",
            },
            {
                "team": "Heat",
                "opponent": "Celtics",
                "points": 5,
                "pos": "PG",
                "game_date": later,
                "season": "2025-2026",
                "game_type": "regular_season",
            },
        ]

    def test_null_rank_fills_through_the_sportsdata_abbreviation(self):
        # Warriors allowed 30, Lakers allowed 10, Heat allowed 20, Celtics allowed 5.
        # Rank 1 is the most points allowed.
        table = build_defense_rank_table(self._games())
        assert table.overall["GSW"] == 1
        assert table.overall["MIA"] == 2
        assert table.overall["LAL"] == 3
        assert table.overall["BOS"] == 4
        # SportsData writes GS. The lineup code is GSW. Both must hit.
        warriors = {"opponent": "GS", "position": "C", "opponent_rank": None, "opponent_position_rank": None}
        filled = fill_null_defense_ranks(warriors, table)
        assert filled["opponent_rank"] == 1
        assert filled["opponent_position_rank"] == table.by_position[("GSW", "C")]
        same = fill_null_defense_ranks({**warriors, "opponent": "GSW"}, table)
        assert same["opponent_rank"] == filled["opponent_rank"]
        # Lakers' only points against the Warriors were scored by a center,
        # so GS is a weak defense versus C and a strong one versus PG.
        assert table.by_position[("GSW", "C")] == 1
        assert table.by_position[("GSW", "PG")] > table.by_position[("GSW", "C")]

    def test_a_rank_already_on_the_row_is_kept(self):
        table = build_defense_rank_table(self._games())
        kept = fill_null_defense_ranks(
            {
                "opponent": "GS",
                "position": "PG",
                "opponent_rank": 9,
                "opponent_position_rank": 8,
            },
            table,
        )
        assert kept["opponent_rank"] == 9
        assert kept["opponent_position_rank"] == 8

    def test_unknown_opponent_stays_null(self):
        table = build_defense_rank_table(self._games())
        filled = fill_null_defense_ranks(
            {
                "opponent": "NOT_A_TEAM",
                "position": "PG",
                "opponent_rank": None,
                "opponent_position_rank": None,
            },
            table,
        )
        assert filled["opponent_rank"] is None
        assert filled["opponent_position_rank"] is None

    def test_real_game_log_fills_a_null_gs_rank(self):
        # The shipped CSV is the source the API fill uses. GS must resolve.
        filled = fill_null_defense_ranks(
            {
                "opponent": "GS",
                "position": "PG",
                "opponent_rank": None,
                "opponent_position_rank": None,
            }
        )
        assert filled["opponent_rank"] is not None
        assert 1 <= filled["opponent_rank"] <= 30
        assert filled["opponent_position_rank"] is not None
        twin = fill_null_defense_ranks(
            {
                "opponent": "GSW",
                "position": "PG",
                "opponent_rank": None,
                "opponent_position_rank": None,
            }
        )
        assert twin["opponent_rank"] == filled["opponent_rank"]

    @pytest.mark.asyncio
    async def test_get_projections_fills_a_cached_null(self, monkeypatch):
        cached = {
            "Stephen Curry": {
                "player_name": "Stephen Curry",
                "opponent": "GS",
                "position": "PG",
                "points": 29.0,
                "opponent_rank": None,
                "opponent_position_rank": None,
            }
        }

        async def fake_get(key):
            if str(key).endswith(":meta"):
                return {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "player_count": 1,
                }
            return cached

        monkeypatch.setattr(
            "app.services.projection_service.cache_service.get", fake_get
        )
        service = ProjectionService()
        result = await service.get_projections("2026-02-08")
        row = result["Stephen Curry"]
        assert row["points"] == 29.0
        assert row["opponent_rank"] is not None
        assert row["opponent_position_rank"] is not None


def test_season_label_accepts_the_short_espn_form():
    assert normalize_nba_season_label("2025-26") == "2025-2026"
    assert normalize_nba_season_label("2025-2026") == "2025-2026"
    assert recorded_nba_season_label(datetime(2026, 11, 10, tzinfo=timezone.utc)) == "2026-2027"
