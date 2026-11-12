"""SPO-111: NBA top_read, read tiers, both-side rates, and the Lean floor.

Default NBA storage still keeps a historical side at or above 0.56 and
samples down to 5 games. The published board is now combined_probability
>= 0.65 and n_games >= 10 (SPO-121). WNBA storage stays on the old floors.
"""

import asyncio
import copy
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fixtures.odds_api import load_odds_fixture

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
    board_score,
    daily_picks_cache_key,
    market_key_for_metric,
    present_daily_picks,
    read_tier,
    select_daily_picks,
)


_RECORDED_ODDS = load_odds_fixture("odds_api_event_odds__player_points.json")
_RECORDED_EVENTS = load_odds_fixture("odds_api_events__basketball_nba.json")
_EVENT_ID = _RECORDED_ODDS["id"]


def _player_names(event: dict) -> list[str]:
    """First-seen player names in a recorded odds payload."""
    seen: list[str] = []
    for book in event["bookmakers"]:
        for market in book.get("markets", []):
            for outcome in market.get("outcomes", []):
                name = outcome.get("description")
                if isinstance(name, str) and name not in seen:
                    seen.append(name)
    return seen


_FIXTURE_PLAYERS = _player_names(_RECORDED_ODDS)
(
    _BOARD_OVER,
    _BOARD_UNDER,
    _LEAN_ONLY,
    _SHORT_SAMPLE,
    _BELOW_FLOOR,
    _TOO_FEW,
) = _FIXTURE_PLAYERS[:6]
_ROLE_NAMES = {
    _BOARD_OVER,
    _BOARD_UNDER,
    _LEAN_ONLY,
    _SHORT_SAMPLE,
    _BELOW_FLOOR,
    _TOO_FEW,
}
_EMPTY_EVENT_ID = next(
    event["id"]
    for event in _RECORDED_EVENTS
    if str(event.get("commence_time", "")).startswith("2026-11-10")
    and event["id"] != _EVENT_ID
)


def _books_for_roles() -> list[dict]:
    """Deep copy of the recorded bookmakers, limited to the six role players."""
    books = copy.deepcopy(_RECORDED_ODDS["bookmakers"])
    kept = []
    for book in books:
        markets = []
        for market in book.get("markets", []):
            market["outcomes"] = [
                outcome
                for outcome in market.get("outcomes", [])
                if outcome.get("description") in _ROLE_NAMES
            ]
            if market["outcomes"]:
                markets.append(market)
        if markets:
            book["markets"] = markets
            kept.append(book)
    return kept


def _recorded_event() -> dict:
    """Deep copy of the recorded event that owns the player-points snapshot."""
    return copy.deepcopy(
        next(event for event in _RECORDED_EVENTS if event["id"] == _EVENT_ID)
    )


def _same_local_date_events() -> list[dict]:
    """Deep copies of recorded events whose UTC commence date is 2026-11-10."""
    return [
        copy.deepcopy(event)
        for event in _RECORDED_EVENTS
        if str(event.get("commence_time", "")).startswith("2026-11-10")
    ]


def _stats(p_over: float, p_under: float, n_games: int) -> dict:
    return {
        "p_over": p_over,
        "p_under": p_under,
        "n_games": n_games,
        "game_logs": [{"team": "Lakers"}],
    }


# Rows the default NBA service sees for one recorded event, points market only.
# Names are the first six players in the recorded player-points snapshot.
_PLAYERS = {
    _BOARD_OVER: _stats(0.72, 0.21, 20),
    _BOARD_UNDER: _stats(0.57, 0.90, 22),
    _LEAN_ONLY: _stats(0.60, 0.30, 18),
    _SHORT_SAMPLE: _stats(0.80, 0.10, 6),
    _BELOW_FLOOR: _stats(0.50, 0.40, 30),
    _TOO_FEW: _stats(0.95, 0.02, 4),
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

    recorded = _recorded_event()

    async def props(event_id, market_key, league="nba"):
        if market_key != "player_points":
            return []
        return _books_for_roles()

    service._get_props_for_market = props
    service.csv_service = MagicMock()
    service.csv_service.get_player_stats = MagicMock(
        side_effect=lambda player_name, metric, threshold, n=0, exclude_dnp=True: _PLAYERS[player_name]
    )
    return asyncio.run(
        service._analyze_single_event(
            event_id=recorded["id"],
            home_team=recorded["home_team"],
            away_team=recorded["away_team"],
            commence_time=recorded["commence_time"],
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

    def test_non_finite_probability_is_not_a_tier(self):
        assert read_tier(float("inf")) is None
        assert read_tier(float("-inf")) is None
        assert read_tier(float("nan")) is None


class TestStoredCandidates:
    def test_default_board_matches_the_old_rows(self):
        """A 0.57 over must not steal a 0.90 under off the default board."""
        picks, _, _ = _analyze()
        by_name = {pick.player_name: pick for pick in picks}

        assert set(by_name) == {_BOARD_OVER, _BOARD_UNDER, _LEAN_ONLY, _SHORT_SAMPLE}
        assert _BELOW_FLOOR not in by_name
        assert _TOO_FEW not in by_name

        under = by_name[_BOARD_UNDER]
        assert under.direction == "under"
        assert under.probability == pytest.approx(0.90)
        assert under.p_over == pytest.approx(0.57)
        assert under.p_under == pytest.approx(0.90)
        assert under.tier == read_tier(under.combined_probability)

        lean = by_name[_LEAN_ONLY]
        assert lean.direction == "over"
        assert lean.probability == pytest.approx(0.60)
        assert lean.tier == read_tier(lean.combined_probability)
        assert lean.p_over == pytest.approx(0.60)
        assert lean.p_under == pytest.approx(0.30)

        short = by_name[_SHORT_SAMPLE]
        assert short.n_games == 6
        assert short.probability == pytest.approx(0.80)
        assert short.tier == read_tier(short.combined_probability)
        assert short.p_over == pytest.approx(0.80)
        assert short.p_under == pytest.approx(0.10)

        # _analyze_single_event keeps insertion order. The board is the
        # combined score, not the historical rate those names were given.
        default_picks = select_daily_picks(picks)
        assert [pick.player_name for pick in default_picks] == [
            pick.player_name
            for pick in picks
            if (score := board_score(pick)) is not None
            and score >= 0.65
            and pick.n_games >= 10
        ]
        assert all(
            pick.combined_probability is not None
            and pick.combined_probability >= 0.65
            and pick.n_games >= 10
            for pick in default_picks
        )

        lean_rows = [
            pick.player_name
            for pick in select_daily_picks(picks, min_probability=0.56, min_games=10)
        ]
        assert lean_rows == [
            pick.player_name
            for pick in picks
            if (score := board_score(pick)) is not None
            and score >= 0.56
            and pick.n_games >= 10
        ]

        with_short = [
            pick.player_name
            for pick in select_daily_picks(picks, min_probability=0.56, min_games=5)
        ]
        assert with_short == [
            pick.player_name
            for pick in picks
            if (score := board_score(pick)) is not None
            and score >= 0.56
            and pick.n_games >= 5
        ]

    def test_explicit_threshold_keeps_the_old_storage_floors(self):
        picks, _, _ = _analyze(explicit_threshold=0.65)
        names = {pick.player_name for pick in picks}
        assert names == {_BOARD_OVER, _BOARD_UNDER}

    def test_wnba_storage_does_not_keep_lean_or_short_samples(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.daily_analysis.wnba_csv_player_service.get_player_stats",
            MagicMock(
                side_effect=lambda player_name, metric, threshold, n=0, exclude_dnp=True: _PLAYERS[player_name]
            ),
        )
        picks, _, _ = _analyze(league="wnba")
        assert {pick.player_name for pick in picks} == {_BOARD_OVER, _BOARD_UNDER}
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
        service._get_events_for_date = AsyncMock(return_value=[_recorded_event()])

        async def props(event_id, market_key, league="nba"):
            if market_key != "player_points":
                return []
            return _books_for_roles()

        service._get_props_for_market = props
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            side_effect=lambda player_name, metric, threshold, n=0, exclude_dnp=True: _PLAYERS[player_name]
        )

        result = asyncio.run(service.run_daily_analysis(date="2026-03-30", use_cache=False))
        assert result.total_picks == 4
        assert result.stats is not None
        expected = select_daily_picks(result.picks)
        assert result.stats.high_prob_count == len(expected)
        presented = present_daily_picks(result)
        assert presented.total_picks == len(expected)
        assert [pick.player_name for pick in presented.picks] == [
            pick.player_name for pick in expected
        ]
        assert presented.stats.high_prob_count == len(expected)


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
                high_prob_count=len(select_daily_picks(picks)),
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

        expected_default = select_daily_picks(stored.picks)
        assert [pick.player_name for pick in default.picks] == [
            pick.player_name for pick in expected_default
        ]
        assert default.total_picks == len(expected_default)
        assert default.stats is not None
        assert default.stats.high_prob_count == len(expected_default)
        under = next(pick for pick in stored.picks if pick.player_name == _BOARD_UNDER)
        assert under.direction == "under"
        assert under.tier == read_tier(under.combined_probability)
        assert under.probability == pytest.approx(0.90)
        assert under.p_over == pytest.approx(0.57)
        assert under.p_under == pytest.approx(0.90)

        assert [pick.player_name for pick in lean.picks] == [
            pick.player_name
            for pick in select_daily_picks(stored.picks, min_probability=0.56, min_games=10)
        ]
        lean_row = next(pick for pick in stored.picks if pick.player_name == _LEAN_ONLY)
        assert lean_row.tier == read_tier(lean_row.combined_probability)
        assert lean_row.probability == pytest.approx(0.60)

        assert [pick.player_name for pick in with_short.picks] == [
            pick.player_name
            for pick in select_daily_picks(stored.picks, min_probability=0.56, min_games=5)
        ]
        assert [pick.player_name for pick in trigger.picks] == [
            pick.player_name for pick in expected_default
        ]


class TestTopRead:
    def test_market_key_matches_the_odds_api_key(self):
        assert market_key_for_metric("points") == "player_points"
        assert market_key_for_metric("pra") == "player_points_rebounds_assists"
        assert market_key_for_metric("threes_made") == "player_threes"
        assert market_key_for_metric("") is None
        assert market_key_for_metric(None) is None
        assert market_key_for_metric("not_a_market") is None

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

    def test_unmapped_metric_skips_the_pick(self):
        base = {
            "event_id": "evt",
            "player_name": "Nobody",
            "direction": "over",
            "threshold": 10.5,
            "probability": 0.91,
        }
        assert best_top_reads({"picks": [{**base, "metric": ""}]}) == {}
        assert best_top_reads({"picks": [base]}) == {}
        assert best_top_reads({"picks": [{**base, "metric": "not_a_market"}]}) == {}

    def test_top_read_rejects_non_finite_numbers(self):
        from pydantic import ValidationError

        from app.models.schemas import TopRead

        with pytest.raises(ValidationError):
            TopRead(
                player="A",
                market="player_points",
                side="over",
                line=1.5,
                probability=float("nan"),
            )
        with pytest.raises(ValidationError):
            TopRead(
                player="A",
                market="player_points",
                side="over",
                line=float("inf"),
                probability=0.8,
            )
        with pytest.raises(ValidationError):
            TopRead(
                player="A",
                market="",
                side="over",
                line=1.5,
                probability=0.8,
            )

    def test_events_route_joins_stored_picks_without_a_props_call(self, monkeypatch):
        from app.api.nba import get_events

        odds_calls = {"events": 0, "props": 0}

        async def fake_events(**kwargs):
            odds_calls["events"] += 1
            return _same_local_date_events()

        async def fake_props(*args, **kwargs):
            odds_calls["props"] += 1
            raise AssertionError("top_read must not request props")

        store: dict = {
            daily_picks_cache_key("nba", "2026-11-10", 480): {
                "picks": [
                    {
                        "event_id": _EVENT_ID,
                        "player_name": "Weaker",
                        "metric": "assists",
                        "direction": "over",
                        "threshold": 6.5,
                        "probability": 0.66,
                    },
                    {
                        "event_id": _EVENT_ID,
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
            get_events(date="2026-11-10", regions="us", tz_offset=480)
        )

        assert odds_calls == {"events": 1, "props": 0}
        by_id = {event.event_id: event for event in response.events}
        assert by_id[_EVENT_ID].top_read is not None
        assert by_id[_EVENT_ID].top_read.player == "Stronger"
        assert by_id[_EVENT_ID].top_read.market == "player_points"
        assert by_id[_EVENT_ID].top_read.side == "under"
        assert by_id[_EVENT_ID].top_read.line == 24.5
        assert by_id[_EVENT_ID].top_read.probability == pytest.approx(0.91)
        assert by_id[_EMPTY_EVENT_ID].top_read is None

        # A later read uses the events cache and still joins picks.
        # No second events call.
        again = asyncio.run(
            get_events(date="2026-11-10", regions="us", tz_offset=480)
        )
        assert odds_calls["events"] == 1
        assert odds_calls["props"] == 0
        again_best = {event.event_id: event for event in again.events}[_EVENT_ID]
        assert again_best.top_read is not None
        assert again_best.top_read.player == "Stronger"

    def test_cache_miss_on_picks_leaves_top_read_null(self, monkeypatch):
        from app.api.nba import get_events

        async def fake_events(**kwargs):
            return [_recorded_event()]

        monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
        monkeypatch.setattr(cache_service, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(cache_service, "set", AsyncMock(return_value=True))

        response = asyncio.run(
            get_events(date="2026-11-10", regions="us", tz_offset=480)
        )
        assert response.events[0].event_id == _EVENT_ID
        assert response.events[0].top_read is None

    def test_omitted_tz_offset_matches_daily_picks(self, monkeypatch):
        from app.api.nba import get_events
        from app.services.daily_analysis import daily_picks_cache_key

        seen: list[str] = []

        async def fake_get(key):
            seen.append(key)
            return None

        async def fake_events(**kwargs):
            return [_recorded_event()]

        monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
        monkeypatch.setattr(cache_service, "get", fake_get)
        monkeypatch.setattr(cache_service, "set", AsyncMock(return_value=True))

        asyncio.run(get_events(date="2026-11-10", regions="us", tz_offset=None))
        assert daily_picks_cache_key("nba", "2026-11-10", 480) in seen

    def test_attach_sets_null_when_the_event_has_no_pick(self):
        from app.models.schemas import EventsResponse

        raw = _recorded_event()
        response = EventsResponse(
            date="2026-11-10",
            events=[
                NBAEvent(
                    event_id=raw["id"],
                    sport_key=raw["sport_key"],
                    home_team=raw["home_team"],
                    away_team=raw["away_team"],
                    commence_time=raw["commence_time"],
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
        assert names == [_BOARD_OVER, _BOARD_UNDER]
        under = next(row for row in response.picks if row.player == _BOARD_UNDER)
        assert under.p_over == pytest.approx(0.57)
        assert under.p_under == pytest.approx(0.90)
        assert under.direction == "under"
