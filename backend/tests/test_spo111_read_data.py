"""SPO-111: NBA top_read, read tiers, both-side rates, and the Lean floor.

The published board stays probability >= 0.65 and n_games >= 10.
Default NBA storage also keeps Lean rows and samples down to 5 games.
WNBA storage stays on the old floors.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.schemas import AnalysisStats, DailyPick, DailyPicksResponse, NBAEvent
from app.services.cache import cache_service
from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    LEAN_PROBABILITY_FLOOR,
    MIN_SAMPLE_GAMES,
    READ_TIER_CUTOFFS,
    STORED_MIN_SAMPLE_GAMES,
    DailyAnalysisService,
    attach_top_reads,
    best_top_reads,
    market_key_for_metric,
    present_daily_picks,
    read_tier,
    select_daily_picks,
)


def _book(players: dict[str, list[float]]) -> list[dict]:
    outcomes = []
    for name, lines in players.items():
        for line in lines:
            outcomes.append({"description": name, "point": line})
    return [{"key": "testbook", "markets": [{"outcomes": outcomes}]}]


def _stats(p_over: float, p_under: float, n_games: int) -> dict:
    return {
        "p_over": p_over,
        "p_under": p_under,
        "n_games": n_games,
        "game_logs": [{"team": "Lakers"}],
    }


# Rows the default NBA service sees for one event, points market only.
_PLAYERS = {
    "Board Over": _stats(0.72, 0.21, 20),
    "Board Under": _stats(0.57, 0.90, 22),
    "Lean Only": _stats(0.60, 0.30, 18),
    "Short Sample": _stats(0.80, 0.10, 6),
    "Below Floor": _stats(0.50, 0.40, 30),
    "Too Few Games": _stats(0.95, 0.02, 4),
}


def _identity(pick: DailyPick) -> tuple:
    return (
        pick.player_name,
        pick.metric,
        pick.direction,
        pick.probability,
        pick.n_games,
        pick.threshold,
    )


def _analyze(league: str = "nba", explicit_threshold: float | None = None):
    if explicit_threshold is None:
        service = DailyAnalysisService()
    else:
        service = DailyAnalysisService(probability_threshold=explicit_threshold)

    async def props(event_id, market_key, league="nba"):
        if market_key != "player_points":
            return []
        return _book({name: [20.5, 20.5] for name in _PLAYERS})

    service._get_props_for_market = props
    service.csv_service = MagicMock()
    service.csv_service.get_player_stats = MagicMock(
        side_effect=lambda player_name, metric, threshold, n=0, exclude_dnp=True: _PLAYERS[player_name]
    )
    return asyncio.run(
        service._analyze_single_event(
            event_id="evt-1",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            commence_time="2026-03-30T03:00:00Z",
            projections={},
            league=league,
        )
    )


class TestReadTier:
    def test_cutoffs_are_the_single_table(self):
        assert READ_TIER_CUTOFFS == (
            ("Strong play", 0.70),
            ("Playable", 0.65),
            ("Lean", 0.56),
        )
        assert LEAN_PROBABILITY_FLOOR == 0.56
        assert HIGH_PROBABILITY_THRESHOLD == 0.65
        assert MIN_SAMPLE_GAMES == 10
        assert STORED_MIN_SAMPLE_GAMES == 5

    @pytest.mark.parametrize(
        ("probability", "tier"),
        [
            (None, None),
            (0.5599, None),
            (0.56, "Lean"),
            (0.6499, "Lean"),
            (0.65, "Playable"),
            (0.6999, "Playable"),
            (0.70, "Strong play"),
            (0.91, "Strong play"),
        ],
    )
    def test_boundaries(self, probability, tier):
        assert read_tier(probability) == tier


class TestStoredCandidates:
    def test_default_board_matches_the_old_rows(self):
        """A 0.57 over must not steal a 0.90 under off the default board."""
        picks, _, _ = _analyze()
        by_name = {pick.player_name: pick for pick in picks}

        assert set(by_name) == {"Board Over", "Board Under", "Lean Only", "Short Sample"}
        assert "Below Floor" not in by_name
        assert "Too Few Games" not in by_name

        under = by_name["Board Under"]
        assert under.direction == "under"
        assert under.probability == pytest.approx(0.90)
        assert under.p_over == pytest.approx(0.57)
        assert under.p_under == pytest.approx(0.90)
        assert under.tier == "Strong play"

        lean = by_name["Lean Only"]
        assert lean.direction == "over"
        assert lean.tier == "Lean"
        assert lean.p_over == pytest.approx(0.60)
        assert lean.p_under == pytest.approx(0.30)

        short = by_name["Short Sample"]
        assert short.n_games == 6
        assert short.tier == "Strong play"
        assert short.p_over == pytest.approx(0.80)
        assert short.p_under == pytest.approx(0.10)

        default_rows = [_identity(pick) for pick in select_daily_picks(picks)]
        # _analyze_single_event keeps insertion order. run_daily_analysis sorts.
        assert default_rows == [
            _identity(by_name["Board Over"]),
            _identity(under),
        ]
        assert all(row[3] >= 0.65 and row[4] >= 10 for row in default_rows)

        lean_rows = [
            pick.player_name
            for pick in select_daily_picks(picks, min_probability=0.56, min_games=10)
        ]
        assert lean_rows == ["Board Over", "Board Under", "Lean Only"]

        with_short = [
            pick.player_name
            for pick in select_daily_picks(picks, min_probability=0.56, min_games=5)
        ]
        assert with_short == ["Board Over", "Board Under", "Lean Only", "Short Sample"]

    def test_explicit_threshold_keeps_the_old_storage_floors(self):
        picks, _, _ = _analyze(explicit_threshold=0.65)
        names = {pick.player_name for pick in picks}
        assert names == {"Board Over", "Board Under"}

    def test_wnba_storage_does_not_keep_lean_or_short_samples(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.daily_analysis.wnba_csv_player_service.get_player_stats",
            MagicMock(
                side_effect=lambda player_name, metric, threshold, n=0, exclude_dnp=True: _PLAYERS[player_name]
            ),
        )
        picks, _, _ = _analyze(league="wnba")
        assert {pick.player_name for pick in picks} == {"Board Over", "Board Under"}
        assert all(pick.p_over is not None and pick.p_under is not None for pick in picks)

    def test_published_count_stays_the_board_while_storage_is_wider(self, monkeypatch):
        service = DailyAnalysisService()
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.projection_service.get_projections",
            AsyncMock(return_value={}),
        )
        service._get_events_for_date = AsyncMock(
            return_value=[
                {
                    "id": "evt-1",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Boston Celtics",
                    "commence_time": "2026-03-30T03:00:00Z",
                }
            ]
        )

        async def props(event_id, market_key, league="nba"):
            if market_key != "player_points":
                return []
            return _book({name: [20.5, 20.5] for name in _PLAYERS})

        service._get_props_for_market = props
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            side_effect=lambda player_name, metric, threshold, n=0, exclude_dnp=True: _PLAYERS[player_name]
        )

        result = asyncio.run(service.run_daily_analysis(date="2026-03-30", use_cache=False))
        assert result.total_picks == 4
        assert result.stats is not None
        assert result.stats.high_prob_count == 2
        presented = present_daily_picks(result)
        assert presented.total_picks == 2
        assert [pick.player_name for pick in presented.picks] == ["Board Under", "Board Over"]
        assert presented.stats.high_prob_count == 2


class TestDailyPicksRoute:
    def _stored(self) -> DailyPicksResponse:
        picks, _, _ = _analyze()
        return DailyPicksResponse(
            date="2026-03-30",
            analyzed_at="2026-03-30T12:00:00+00:00",
            total_picks=len(picks),
            picks=picks,
            stats=AnalysisStats(
                total_events=1,
                total_players=6,
                total_props=4,
                high_prob_count=2,
                analysis_duration_seconds=0.1,
            ),
        )

    def test_query_defaults_are_the_published_board(self):
        from app.api.daily_picks import get_daily_picks

        params = get_daily_picks.__signature__ if hasattr(get_daily_picks, "__signature__") else None
        import inspect

        signature = params or inspect.signature(get_daily_picks)
        assert signature.parameters["min_probability"].default.default == HIGH_PROBABILITY_THRESHOLD
        assert signature.parameters["min_games"].default.default == MIN_SAMPLE_GAMES

    def test_default_get_and_trigger_match_the_old_board(self, monkeypatch):
        import inspect

        from app.api.daily_picks import get_daily_picks, trigger_daily_analysis

        stored = self._stored()
        monkeypatch.setattr(
            "app.api.daily_picks.daily_analysis_service.run_daily_analysis",
            AsyncMock(return_value=stored),
        )
        signature = inspect.signature(get_daily_picks)
        default_probability = signature.parameters["min_probability"].default.default
        default_games = signature.parameters["min_games"].default.default

        default = asyncio.run(
            get_daily_picks(
                date="2026-03-30",
                tz_offset=480,
                refresh=False,
                min_probability=default_probability,
                min_games=default_games,
            )
        )
        lean = asyncio.run(
            get_daily_picks(
                date="2026-03-30",
                tz_offset=480,
                refresh=False,
                min_probability=0.56,
                min_games=default_games,
            )
        )
        with_short = asyncio.run(
            get_daily_picks(
                date="2026-03-30",
                tz_offset=480,
                refresh=False,
                min_probability=0.56,
                min_games=5,
            )
        )
        trigger = asyncio.run(
            trigger_daily_analysis(date="2026-03-30", tz_offset=480)
        )

        assert [pick.player_name for pick in default.picks] == ["Board Over", "Board Under"]
        assert default.total_picks == 2
        assert default.stats is not None
        assert default.stats.high_prob_count == 2
        under = next(pick for pick in default.picks if pick.player_name == "Board Under")
        assert under.direction == "under"
        assert under.tier == "Strong play"
        assert under.p_over == pytest.approx(0.57)
        assert under.p_under == pytest.approx(0.90)
        assert "Lean Only" not in {pick.player_name for pick in default.picks}

        assert [pick.player_name for pick in lean.picks] == [
            "Board Over",
            "Board Under",
            "Lean Only",
        ]
        lean_row = lean.picks[-1]
        assert lean_row.tier == "Lean"
        assert lean_row.probability == pytest.approx(0.60)

        assert [pick.player_name for pick in with_short.picks] == [
            "Board Over",
            "Board Under",
            "Lean Only",
            "Short Sample",
        ]
        assert [pick.player_name for pick in trigger.picks] == [
            "Board Over",
            "Board Under",
        ]


class TestTopRead:
    def test_market_key_matches_the_odds_api_key(self):
        assert market_key_for_metric("points") == "player_points"
        assert market_key_for_metric("pra") == "player_points_rebounds_assists"
        assert market_key_for_metric("threes_made") == "player_threes"

    def test_best_pick_wins_and_a_tie_keeps_the_earlier_row(self):
        reads = best_top_reads(
            {
                "picks": [
                    {
                        "event_id": "evt-tie",
                        "player_name": "First",
                        "metric": "points",
                        "direction": "over",
                        "threshold": 10.5,
                        "probability": 0.80,
                    },
                    {
                        "event_id": "evt-tie",
                        "player_name": "Second",
                        "metric": "rebounds",
                        "direction": "under",
                        "threshold": 8.5,
                        "probability": 0.80,
                    },
                    {
                        "event_id": "evt-best",
                        "player_name": "Weaker",
                        "metric": "assists",
                        "direction": "over",
                        "threshold": 6.5,
                        "probability": 0.66,
                    },
                    {
                        "event_id": "evt-best",
                        "player_name": "Stronger",
                        "metric": "points",
                        "direction": "under",
                        "threshold": 24.5,
                        "probability": 0.91,
                    },
                ]
            }
        )
        assert reads["evt-tie"].player == "First"
        assert reads["evt-tie"].market == "player_points"
        assert reads["evt-tie"].side == "over"
        assert reads["evt-best"].player == "Stronger"
        assert reads["evt-best"].side == "under"
        assert reads["evt-best"].line == 24.5
        assert reads["evt-best"].market == "player_points"
        assert reads["evt-best"].probability == pytest.approx(0.91)

    def test_missing_cache_and_bad_rows_are_empty(self):
        assert best_top_reads(None) == {}
        assert best_top_reads({"picks": [{"event_id": "x", "direction": "over"}]}) == {}

    def test_events_route_joins_stored_picks_without_a_props_call(self, monkeypatch):
        from app.api.nba import get_events

        odds_calls = {"events": 0, "props": 0}

        async def fake_events(**kwargs):
            odds_calls["events"] += 1
            return [
                {
                    "id": "evt-best",
                    "sport_key": "basketball_nba",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Boston Celtics",
                    "commence_time": "2026-03-30T03:00:00Z",
                },
                {
                    "id": "evt-empty",
                    "sport_key": "basketball_nba",
                    "home_team": "Miami Heat",
                    "away_team": "New York Knicks",
                    "commence_time": "2026-03-30T04:00:00Z",
                },
            ]

        async def fake_props(*args, **kwargs):
            odds_calls["props"] += 1
            raise AssertionError("top_read must not request props")

        store: dict = {
            "daily_picks:nba:2026-03-30:tz480": {
                "picks": [
                    {
                        "event_id": "evt-best",
                        "player_name": "Weaker",
                        "metric": "assists",
                        "direction": "over",
                        "threshold": 6.5,
                        "probability": 0.66,
                    },
                    {
                        "event_id": "evt-best",
                        "player_name": "Stronger",
                        "metric": "points",
                        "direction": "under",
                        "threshold": 24.5,
                        "probability": 0.91,
                    },
                ]
            }
        }

        async def fake_get(key):
            return store.get(key)

        async def fake_set(key, value, ttl):
            store[key] = value
            return True

        monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
        monkeypatch.setattr("app.api.nba.odds_gateway.get_market_snapshot", fake_props)
        monkeypatch.setattr(cache_service, "get", fake_get)
        monkeypatch.setattr(cache_service, "set", fake_set)

        response = asyncio.run(
            get_events(date="2026-03-30", regions="us", tz_offset=480)
        )

        assert odds_calls == {"events": 1, "props": 0}
        by_id = {event.event_id: event for event in response.events}
        assert by_id["evt-best"].top_read is not None
        assert by_id["evt-best"].top_read.player == "Stronger"
        assert by_id["evt-best"].top_read.market == "player_points"
        assert by_id["evt-best"].top_read.side == "under"
        assert by_id["evt-best"].top_read.line == 24.5
        assert by_id["evt-best"].top_read.probability == pytest.approx(0.91)
        assert by_id["evt-empty"].top_read is None

        # A later read uses the events cache and still joins picks.
        # No second events call.
        again = asyncio.run(
            get_events(date="2026-03-30", regions="us", tz_offset=480)
        )
        assert odds_calls["events"] == 1
        assert odds_calls["props"] == 0
        again_best = {event.event_id: event for event in again.events}["evt-best"]
        assert again_best.top_read is not None
        assert again_best.top_read.player == "Stronger"

    def test_cache_miss_on_picks_leaves_top_read_null(self, monkeypatch):
        from app.api.nba import get_events

        async def fake_events(**kwargs):
            return [
                {
                    "id": "evt-1",
                    "sport_key": "basketball_nba",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Boston Celtics",
                    "commence_time": "2026-03-30T03:00:00Z",
                }
            ]

        monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
        monkeypatch.setattr(cache_service, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(cache_service, "set", AsyncMock(return_value=True))

        response = asyncio.run(
            get_events(date="2026-03-30", regions="us", tz_offset=480)
        )
        assert response.events[0].top_read is None

    def test_attach_sets_null_when_the_event_has_no_pick(self):
        from app.models.schemas import EventsResponse

        response = EventsResponse(
            date="2026-03-30",
            events=[
                NBAEvent(
                    event_id="evt-1",
                    sport_key="basketball_nba",
                    home_team="Los Angeles Lakers",
                    away_team="Boston Celtics",
                    commence_time=datetime(2026, 3, 30, 3, 0, tzinfo=timezone.utc),
                )
            ],
        )
        attached = attach_top_reads(response, {})
        assert attached.events[0].top_read is None
        assert response.events[0].top_read is None


class TestBotPickKeepsBothRates:
    def test_default_bot_response_skips_lean_and_short_samples(self, monkeypatch):
        import inspect

        from app.api.picks import get_picks_today

        picks, _, _ = _analyze()
        stored = DailyPicksResponse(
            date="2026-03-30",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_picks=len(picks),
            picks=picks,
            stats=None,
        )
        monkeypatch.setattr(
            "app.api.picks.daily_analysis_service.run_daily_analysis",
            AsyncMock(return_value=stored),
        )
        monkeypatch.setattr("app.api.picks.settings.bot_api_keys_premium", "prem-key")

        endpoint = get_picks_today
        while hasattr(endpoint, "__wrapped__"):
            endpoint = endpoint.__wrapped__
        signature = inspect.signature(endpoint)
        response = asyncio.run(
            endpoint(
                request=MagicMock(),
                api_key="prem-key",
                tz_offset=480,
                min_confidence=signature.parameters["min_confidence"].default.default,
            )
        )

        names = [row.player for row in response.picks]
        assert names == ["Board Over", "Board Under"]
        under = next(row for row in response.picks if row.player == "Board Under")
        assert under.p_over == pytest.approx(0.57)
        assert under.p_under == pytest.approx(0.90)
        assert under.direction == "under"
