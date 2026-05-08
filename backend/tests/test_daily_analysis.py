import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import (
    DAILY_PICKS_CACHE_TTL,
    DailyAnalysisService,
    canonical_team_code,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeSnapshotResult:
    """Mimics MarketSnapshotResult returned by odds_gateway.get_market_snapshot."""
    data: Dict[str, Any]
    fetched_at: datetime = datetime(2026, 3, 30, tzinfo=timezone.utc)
    data_age_seconds: int = 0
    cache_state: str = "fresh"
    source: str = "api"
    usage: Optional[Any] = None


def _make_bookmakers_data(player_lines: Dict[str, list[float]]):
    """Build bookmakers list from {player_name: [line, ...]} for convenience."""
    outcomes = []
    for name, lines in player_lines.items():
        for line in lines:
            outcomes.append({"description": name, "point": line})
    return [{"key": "testbook", "markets": [{"outcomes": outcomes}]}]


def _make_service(**kwargs) -> DailyAnalysisService:
    """Create a DailyAnalysisService with sensible defaults."""
    svc = DailyAnalysisService(**kwargs)
    return svc


def _default_csv_stats(
    p_over=0.72,
    p_under=0.21,
    n_games=20,
    team="Warriors",
):
    return {
        "p_over": p_over,
        "p_under": p_under,
        "n_games": n_games,
        "game_logs": [{"team": team}],
    }


# ===========================================================================
# 1. Cache TTL constant
# ===========================================================================

def test_daily_picks_cache_ttl_matches_fifteen_minutes():
    assert DAILY_PICKS_CACHE_TTL == 15 * 60
    assert DAILY_PICKS_CACHE_TTL == 900


# ===========================================================================
# 2-6. canonical_team_code
# ===========================================================================

class TestCanonicalTeamCode:
    def test_full_name_golden_state_warriors(self):
        assert canonical_team_code("Golden State Warriors") == "GSW"

    def test_already_canonical_gsw(self):
        assert canonical_team_code("GSW") == "GSW"

    def test_nickname_lakers(self):
        assert canonical_team_code("Lakers") == "LAL"

    def test_empty_string_returns_empty(self):
        assert canonical_team_code("") == ""

    def test_alias_bkn(self):
        assert canonical_team_code("BKN") == "BKN"

    def test_alias_brooklyn_nets(self):
        assert canonical_team_code("Brooklyn Nets") == "BKN"

    def test_alias_nets(self):
        assert canonical_team_code("Nets") == "BKN"

    def test_alias_phx(self):
        assert canonical_team_code("PHX") == "PHX"

    def test_alias_pho(self):
        assert canonical_team_code("PHO") == "PHX"

    def test_alias_phoenix_suns(self):
        assert canonical_team_code("Phoenix Suns") == "PHX"

    def test_alias_suns(self):
        assert canonical_team_code("Suns") == "PHX"

    def test_alias_celtics(self):
        assert canonical_team_code("Celtics") == "BOS"

    def test_alias_boston_celtics(self):
        assert canonical_team_code("Boston Celtics") == "BOS"

    def test_alias_gs(self):
        assert canonical_team_code("GS") == "GSW"

    def test_alias_san_antonio_spurs(self):
        assert canonical_team_code("San Antonio Spurs") == "SAS"

    def test_alias_sa(self):
        assert canonical_team_code("SA") == "SAS"

    def test_alias_new_orleans_pelicans(self):
        assert canonical_team_code("New Orleans Pelicans") == "NOP"

    def test_alias_knicks(self):
        assert canonical_team_code("Knicks") == "NYK"

    def test_alias_ny(self):
        assert canonical_team_code("NY") == "NYK"

    def test_alias_washington_wizards(self):
        assert canonical_team_code("Washington Wizards") == "WAS"

    def test_alias_wsh(self):
        assert canonical_team_code("WSH") == "WAS"

    def test_alias_utah_jazz(self):
        assert canonical_team_code("Utah Jazz") == "UTA"

    def test_case_insensitive(self):
        assert canonical_team_code("lakers") == "LAL"
        assert canonical_team_code("LAKERS") == "LAL"
        assert canonical_team_code("LaKeRs") == "LAL"

    def test_strips_non_alphanumeric(self):
        # Non-alphanumeric chars (spaces, dots, hyphens) are stripped before lookup.
        # Full names with spaces resolve correctly:
        assert canonical_team_code("Los Angeles Lakers") == "LAL"
        assert canonical_team_code("Los Angeles Clippers") == "LAC"
        # Whitespace-only padding is stripped:
        assert canonical_team_code("  Warriors  ") == "GSW"
        assert canonical_team_code("  GSW  ") == "GSW"

    def test_unknown_team_returns_normalized(self):
        # Not in aliases dict -> returns the normalized (uppercased, stripped) string
        result = canonical_team_code("Unknown Team XYZ")
        assert result == "UNKNOWNTEAMXYZ"


# ===========================================================================
# 7-8. _group_props_by_player
# ===========================================================================

class TestGroupPropsByPlayer:
    def setup_method(self):
        self.service = _make_service()

    def test_groups_correctly(self):
        bookmakers_data = [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "outcomes": [
                            {"description": "Stephen Curry", "point": 24.5},
                            {"description": "LeBron James", "point": 27.5},
                        ]
                    }
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {
                        "outcomes": [
                            {"description": "Stephen Curry", "point": 25.5},
                            {"description": "LeBron James", "point": 27.5},
                        ]
                    }
                ],
            },
        ]
        result = self.service._group_props_by_player(bookmakers_data)
        assert set(result.keys()) == {"Stephen Curry", "LeBron James"}
        assert result["Stephen Curry"] == [24.5, 25.5]
        assert result["LeBron James"] == [27.5, 27.5]

    def test_ignores_entries_with_no_point(self):
        bookmakers_data = [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "outcomes": [
                            {"description": "Player A", "point": 10.5},
                            {"description": "Player B"},  # no point
                            {"description": "Player C", "point": None},  # explicit None
                        ]
                    }
                ],
            }
        ]
        result = self.service._group_props_by_player(bookmakers_data)
        assert "Player A" in result
        assert result["Player A"] == [10.5]
        assert "Player B" not in result
        assert "Player C" not in result

    def test_ignores_entries_with_no_description(self):
        bookmakers_data = [
            {
                "key": "book1",
                "markets": [
                    {
                        "outcomes": [
                            {"description": "", "point": 10.5},
                            {"point": 12.5},  # no description key
                        ]
                    }
                ],
            }
        ]
        result = self.service._group_props_by_player(bookmakers_data)
        # Empty description is falsy, skipped
        assert len(result) == 0

    def test_empty_bookmakers_data(self):
        result = self.service._group_props_by_player([])
        assert result == {}

    def test_multiple_markets_per_bookmaker(self):
        bookmakers_data = [
            {
                "key": "book1",
                "markets": [
                    {"outcomes": [{"description": "Player A", "point": 5.5}]},
                    {"outcomes": [{"description": "Player A", "point": 6.5}]},
                ],
            }
        ]
        result = self.service._group_props_by_player(bookmakers_data)
        assert result["Player A"] == [5.5, 6.5]

    def test_line_values_stored_as_floats(self):
        bookmakers_data = [
            {
                "key": "book1",
                "markets": [
                    {
                        "outcomes": [
                            {"description": "Player A", "point": 10},  # int
                        ]
                    }
                ],
            }
        ]
        result = self.service._group_props_by_player(bookmakers_data)
        assert result["Player A"] == [10.0]
        assert isinstance(result["Player A"][0], float)


# ===========================================================================
# 9-13. _analyze_single_event
# ===========================================================================

class TestAnalyzeSingleEvent:
    """Tests for _analyze_single_event with various stat/projection scenarios."""

    def _build_service(self, csv_stats, props_return=None, projections=None):
        """Build a service with mocked dependencies."""
        service = _make_service()

        if props_return is None:
            props_return = _make_bookmakers_data({"Stephen Curry": [28.5, 28.5]})

        service._get_props_for_market = AsyncMock(return_value=props_return)
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(return_value=csv_stats)

        return service

    def test_returns_player_team_and_edge_with_projections(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.72, p_under=0.21, n_games=20, team="Warriors"),
        )
        projections = {
            "Stephen Curry": {
                "team": "GSW",
                "points": 30.1,
                "rebounds": 6.0,
                "assists": 7.0,
                "pra": 43.1,
                "minutes": 35.0,
            }
        }

        picks, player_count, prop_count = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Los Angeles Lakers",
                away_team="Golden State Warriors",
                commence_time="2026-03-30T02:00:00Z",
                projections=projections,
            )
        )

        assert player_count == 1
        # 11 supported markets after SPO-16 Phase 1 expansion (4 baseline +
        # 7 new continuous: 3PM, STL, FTM, FGM, R+A, P+R, P+A). DD is binary
        # and lives in BINARY_MARKETS, not SUPPORTED_MARKETS, so it is NOT
        # counted here. The mock _get_props_for_market returns the same
        # bookmaker payload for every metric, so each market produces a pick.
        from app.services.daily_analysis import SUPPORTED_MARKETS
        assert prop_count == len(SUPPORTED_MARKETS) == 11
        assert len(picks) == 11
        assert all(p.player_team == "GSW" for p in picks)
        assert all(p.player_team_code == "GSW" for p in picks)
        # edge should still be projected_value - mode_threshold (28.5 mode)
        # for the 4 baseline metrics — the contract for those is unchanged.
        points_pick = [p for p in picks if p.metric == "points"][0]
        assert points_pick.has_projection is True
        assert points_pick.projected_value == 30.1
        assert points_pick.edge == round(30.1 - 28.5, 2)

    def test_filters_out_players_with_fewer_than_10_games(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.80, n_games=5),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) == 0

    def test_picks_over_when_p_over_above_threshold(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.72, p_under=0.21, n_games=20),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) > 0
        assert all(p.direction == "over" for p in picks)
        assert all(p.probability == 0.72 for p in picks)

    def test_picks_under_when_p_under_above_threshold(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.30, p_under=0.70, n_games=25),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) > 0
        assert all(p.direction == "under" for p in picks)
        assert all(p.probability == 0.70 for p in picks)

    def test_skips_when_both_probabilities_below_threshold(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.50, p_under=0.50, n_games=30),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) == 0

    def test_over_preferred_when_both_above_threshold(self):
        """When both p_over and p_under >= threshold, over is checked first."""
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.70, p_under=0.70, n_games=30),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        # The code checks p_over first with if/elif, so over wins
        assert all(p.direction == "over" for p in picks)

    def test_falls_back_to_csv_team_when_no_projection(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.72, n_games=20, team="Warriors"),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) > 0
        assert all(p.player_team == "Warriors" for p in picks)
        assert all(p.player_team_code == "GSW" for p in picks)

    def test_no_edge_when_no_projection(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.72, n_games=20),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) > 0
        assert all(p.edge is None for p in picks)
        assert all(p.has_projection is False for p in picks)

    def test_edge_negative_when_projection_below_line(self):
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.72, n_games=20),
        )
        projections = {
            "Stephen Curry": {
                "team": "GSW",
                "points": 25.0,
                "rebounds": 4.0,
                "assists": 5.0,
                "pra": 34.0,
                "minutes": 32.0,
            }
        }

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections=projections,
            )
        )

        points_pick = [p for p in picks if p.metric == "points"][0]
        # 25.0 - 28.5 = -3.5
        assert points_pick.edge == -3.5

    def test_empty_props_data_returns_no_picks(self):
        service = _make_service()
        service._get_props_for_market = AsyncMock(return_value=[])
        service.csv_service = MagicMock()

        picks, player_count, prop_count = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert picks == []
        assert player_count == 0
        assert prop_count == 0

    def test_projection_extras_passed_through(self):
        """opponent_rank, opponent_position_rank, injury_status, lineup_confirmed
        are set on the pick when present in projections."""
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.72, n_games=20),
        )
        projections = {
            "Stephen Curry": {
                "team": "GSW",
                "points": 30.0,
                "rebounds": 6.0,
                "assists": 7.0,
                "pra": 43.0,
                "minutes": 35.0,
                "opponent_rank": 5,
                "opponent_position_rank": 3,
                "injury_status": "Probable",
                "lineup_confirmed": True,
            }
        }

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections=projections,
            )
        )

        assert len(picks) > 0
        pick = picks[0]
        assert pick.opponent_rank == 5
        assert pick.opponent_position_rank == 3
        assert pick.injury_status == "Probable"
        assert pick.lineup_confirmed is True

    def test_threshold_boundary_exactly_065(self):
        """Probability exactly at 0.65 should be included."""
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.65, p_under=0.30, n_games=15),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) > 0
        assert all(p.direction == "over" for p in picks)

    def test_threshold_boundary_just_below_065(self):
        """Probability at 0.6499 should NOT be included."""
        service = self._build_service(
            csv_stats=_default_csv_stats(p_over=0.6499, p_under=0.3001, n_games=15),
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        assert len(picks) == 0


# ===========================================================================
# 14-17. run_daily_analysis
# ===========================================================================

class TestRunDailyAnalysis:
    """Tests for the top-level run_daily_analysis pipeline."""

    def test_returns_cached_result_when_available(self, monkeypatch):
        service = _make_service()

        cached_payload = {
            "date": "2026-03-30",
            "analyzed_at": "2026-03-30T10:00:00+00:00",
            "total_picks": 2,
            "picks": [],
            "stats": None,
            "message": None,
        }

        mock_cache_get = AsyncMock(return_value=cached_payload)
        mock_cache_set = AsyncMock()
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get", mock_cache_get
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", mock_cache_set
        )

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=True)
        )

        assert result.date == "2026-03-30"
        assert result.total_picks == 2
        mock_cache_get.assert_awaited_once()
        # Should NOT have called cache set since we returned from cache
        mock_cache_set.assert_not_awaited()

    def test_returns_error_response_when_events_fetch_fails(self, monkeypatch):
        service = _make_service()

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set",
            AsyncMock(),
        )

        # Make _get_events_for_date raise an exception
        service._get_events_for_date = AsyncMock(
            side_effect=Exception("Network error")
        )

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=True)
        )

        assert result.total_picks == 0
        assert result.picks == []
        assert result.message is not None
        assert "Failed to fetch events" in result.message
        assert "Network error" in result.message

    def test_returns_message_when_no_events(self, monkeypatch):
        service = _make_service()

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set",
            AsyncMock(),
        )

        # Return empty events list
        service._get_events_for_date = AsyncMock(return_value=[])

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=True)
        )

        assert result.total_picks == 0
        assert result.picks == []
        assert result.message == "No events today"
        assert result.stats is None

    def test_full_flow_with_mocked_events_and_analysis(self, monkeypatch):
        service = _make_service()

        # Mock cache: miss on get
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        mock_cache_set = AsyncMock()
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set",
            mock_cache_set,
        )

        # Mock projection service
        monkeypatch.setattr(
            "app.services.daily_analysis.projection_service.get_projections",
            AsyncMock(return_value={
                "Stephen Curry": {
                    "team": "GSW",
                    "points": 30.1,
                    "rebounds": 6.0,
                    "assists": 7.0,
                    "pra": 43.1,
                    "minutes": 35.0,
                }
            }),
        )

        # Mock _get_events_for_date to return one event
        events = [
            {
                "id": "evt-100",
                "home_team": "Los Angeles Lakers",
                "away_team": "Golden State Warriors",
                "commence_time": "2026-03-30T03:00:00Z",
            }
        ]
        service._get_events_for_date = AsyncMock(return_value=events)

        # Mock _get_props_for_market
        service._get_props_for_market = AsyncMock(
            return_value=_make_bookmakers_data({"Stephen Curry": [28.5, 28.5]})
        )

        # Mock csv stats -> high p_over
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value=_default_csv_stats(p_over=0.75, p_under=0.20, n_games=30)
        )

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=True)
        )

        assert result.date == "2026-03-30"
        assert result.total_picks > 0
        assert result.message is None
        assert result.stats is not None
        assert result.stats.total_events == 1
        assert result.stats.high_prob_count == result.total_picks

        # Picks should be sorted by probability descending
        probs = [p.probability for p in result.picks]
        assert probs == sorted(probs, reverse=True)

        # Cache should have been set
        mock_cache_set.assert_awaited_once()
        call_args = mock_cache_set.call_args
        assert call_args[1].get("ttl", call_args[0][2] if len(call_args[0]) > 2 else None) == DAILY_PICKS_CACHE_TTL

    def test_skips_cache_when_use_cache_false(self, monkeypatch):
        service = _make_service()

        mock_cache_get = AsyncMock(return_value=None)
        mock_cache_set = AsyncMock()
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get", mock_cache_get
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", mock_cache_set
        )

        monkeypatch.setattr(
            "app.services.daily_analysis.projection_service.get_projections",
            AsyncMock(return_value={}),
        )

        service._get_events_for_date = AsyncMock(return_value=[])

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=False)
        )

        # cache.get should NOT have been called when use_cache=False
        mock_cache_get.assert_not_awaited()
        # The response for no events should still come back
        assert result.message == "No events today"

    def test_projection_failure_does_not_break_analysis(self, monkeypatch):
        """If projection_service.get_projections raises, analysis still proceeds."""
        service = _make_service()

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
            AsyncMock(side_effect=Exception("Projection API down")),
        )

        events = [
            {
                "id": "evt-200",
                "home_team": "Team A",
                "away_team": "Team B",
                "commence_time": "2026-03-30T03:00:00Z",
            }
        ]
        service._get_events_for_date = AsyncMock(return_value=events)
        service._get_props_for_market = AsyncMock(
            return_value=_make_bookmakers_data({"Player X": [20.5, 20.5]})
        )
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value=_default_csv_stats(p_over=0.80, n_games=25)
        )

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=True)
        )

        # Should still succeed -- projections are optional
        assert result.total_picks > 0
        assert result.message is None

    def test_individual_event_failure_continues_to_next(self, monkeypatch):
        """If one event's analysis raises, others still get processed."""
        service = _make_service()

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

        events = [
            {
                "id": "evt-bad",
                "home_team": "Team A",
                "away_team": "Team B",
                "commence_time": "2026-03-30T01:00:00Z",
            },
            {
                "id": "evt-good",
                "home_team": "Team C",
                "away_team": "Team D",
                "commence_time": "2026-03-30T03:00:00Z",
            },
        ]
        service._get_events_for_date = AsyncMock(return_value=events)

        call_count = 0

        async def mock_analyze(event_id, home_team, away_team, commence_time, projections):
            nonlocal call_count
            call_count += 1
            if event_id == "evt-bad":
                raise Exception("boom")
            from app.models.schemas import DailyPick
            pick = DailyPick(
                player_name="Good Player",
                event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                commence_time=commence_time,
                metric="points",
                threshold=25.5,
                direction="over",
                probability=0.75,
                n_games=20,
                bookmakers_count=3,
            )
            return [pick], 1, 1

        service._analyze_single_event = mock_analyze

        result = asyncio.run(
            service.run_daily_analysis(date="2026-03-30", use_cache=True)
        )

        # Both events attempted
        assert call_count == 2
        # Only the good event's picks survive
        assert result.total_picks == 1
        assert result.stats.total_events == 2


# ===========================================================================
# 18. _get_events_for_date
# ===========================================================================

class TestGetEventsForDate:
    """Tests for timezone-aware event filtering."""

    def test_filters_by_local_date_with_positive_tz_offset(self, monkeypatch):
        """UTC+8 (tz_offset_minutes=480): 2026-03-30 local = 2026-03-29T16:00Z to 2026-03-30T15:59Z"""
        service = _make_service()

        # Event at 2026-03-30T02:00Z => local 2026-03-30T10:00 (UTC+8) -> matches
        # Event at 2026-03-30T17:00Z => local 2026-03-31T01:00 (UTC+8) -> does NOT match
        # Event at 2026-03-29T15:00Z => local 2026-03-29T23:00 (UTC+8) -> does NOT match
        # Event at 2026-03-29T16:30Z => local 2026-03-30T00:30 (UTC+8) -> matches
        raw_events = [
            {"id": "e1", "commence_time": "2026-03-30T02:00:00Z", "home_team": "A", "away_team": "B"},
            {"id": "e2", "commence_time": "2026-03-30T17:00:00Z", "home_team": "C", "away_team": "D"},
            {"id": "e3", "commence_time": "2026-03-29T15:00:00Z", "home_team": "E", "away_team": "F"},
            {"id": "e4", "commence_time": "2026-03-29T16:30:00Z", "home_team": "G", "away_team": "H"},
        ]

        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events",
            AsyncMock(return_value=raw_events),
        )

        result = asyncio.run(
            service._get_events_for_date("2026-03-30", tz_offset_minutes=480)
        )

        result_ids = [e["id"] for e in result]
        assert "e1" in result_ids
        assert "e4" in result_ids
        assert "e2" not in result_ids
        assert "e3" not in result_ids

    def test_filters_by_local_date_with_negative_tz_offset(self, monkeypatch):
        """UTC-5 (tz_offset_minutes=-300): 2026-03-30 local = 2026-03-30T05:00Z to 2026-03-31T04:59Z"""
        service = _make_service()

        # Event at 2026-03-30T06:00Z => local 2026-03-30T01:00 (UTC-5) -> matches
        # Event at 2026-03-31T04:30Z => local 2026-03-30T23:30 (UTC-5) -> matches
        # Event at 2026-03-30T04:00Z => local 2026-03-29T23:00 (UTC-5) -> does NOT match
        # Event at 2026-03-31T05:30Z => local 2026-03-31T00:30 (UTC-5) -> does NOT match
        raw_events = [
            {"id": "e1", "commence_time": "2026-03-30T06:00:00Z", "home_team": "A", "away_team": "B"},
            {"id": "e2", "commence_time": "2026-03-31T04:30:00Z", "home_team": "C", "away_team": "D"},
            {"id": "e3", "commence_time": "2026-03-30T04:00:00Z", "home_team": "E", "away_team": "F"},
            {"id": "e4", "commence_time": "2026-03-31T05:30:00Z", "home_team": "G", "away_team": "H"},
        ]

        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events",
            AsyncMock(return_value=raw_events),
        )

        result = asyncio.run(
            service._get_events_for_date("2026-03-30", tz_offset_minutes=-300)
        )

        result_ids = [e["id"] for e in result]
        assert "e1" in result_ids
        assert "e2" in result_ids
        assert "e3" not in result_ids
        assert "e4" not in result_ids

    def test_filters_by_local_date_utc_zero(self, monkeypatch):
        """UTC+0 (tz_offset_minutes=0): local date matches UTC date exactly."""
        service = _make_service()

        raw_events = [
            {"id": "e1", "commence_time": "2026-03-30T12:00:00Z", "home_team": "A", "away_team": "B"},
            {"id": "e2", "commence_time": "2026-03-31T00:30:00Z", "home_team": "C", "away_team": "D"},
        ]

        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events",
            AsyncMock(return_value=raw_events),
        )

        result = asyncio.run(
            service._get_events_for_date("2026-03-30", tz_offset_minutes=0)
        )

        result_ids = [e["id"] for e in result]
        assert "e1" in result_ids
        assert "e2" not in result_ids

    def test_no_events_returned_from_api(self, monkeypatch):
        service = _make_service()

        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events",
            AsyncMock(return_value=[]),
        )

        result = asyncio.run(
            service._get_events_for_date("2026-03-30", tz_offset_minutes=480)
        )

        assert result == []

    def test_events_with_bad_commence_time_skipped(self, monkeypatch):
        """Events with unparseable commence_time are silently dropped."""
        service = _make_service()

        raw_events = [
            {"id": "e1", "commence_time": "not-a-date", "home_team": "A", "away_team": "B"},
            {"id": "e2", "commence_time": "2026-03-30T10:00:00Z", "home_team": "C", "away_team": "D"},
        ]

        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events",
            AsyncMock(return_value=raw_events),
        )

        result = asyncio.run(
            service._get_events_for_date("2026-03-30", tz_offset_minutes=480)
        )

        # e1 skipped due to parse error, e2 needs to be checked
        # e2: 2026-03-30T10:00Z + 480min = 2026-03-30T18:00 local -> matches 2026-03-30
        result_ids = [e["id"] for e in result]
        assert "e1" not in result_ids
        assert "e2" in result_ids


# ===========================================================================
# Additional edge-case tests
# ===========================================================================

class TestCustomProbabilityThreshold:
    """Verify the service respects a custom probability_threshold."""

    def test_custom_threshold_lower(self):
        service = DailyAnalysisService(probability_threshold=0.50)
        service._get_props_for_market = AsyncMock(
            return_value=_make_bookmakers_data({"Player A": [20.5, 20.5]})
        )
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value=_default_csv_stats(p_over=0.55, p_under=0.40, n_games=20)
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        # 0.55 >= 0.50 threshold -> should get picks
        assert len(picks) > 0

    def test_custom_threshold_higher(self):
        service = DailyAnalysisService(probability_threshold=0.80)
        service._get_props_for_market = AsyncMock(
            return_value=_make_bookmakers_data({"Player A": [20.5, 20.5]})
        )
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value=_default_csv_stats(p_over=0.75, p_under=0.20, n_games=20)
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={},
            )
        )

        # 0.75 < 0.80 threshold -> no picks
        assert len(picks) == 0


class TestPickFields:
    """Ensure pick objects carry all expected field values."""

    def test_pick_has_correct_fields(self):
        service = _make_service()
        service._get_props_for_market = AsyncMock(
            return_value=_make_bookmakers_data({"Player Z": [15.5, 16.5, 15.5]})
        )
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value=_default_csv_stats(p_over=0.80, p_under=0.15, n_games=40, team="Heat")
        )

        picks, _, _ = asyncio.run(
            service._analyze_single_event(
                event_id="evt-fields",
                home_team="Boston Celtics",
                away_team="Miami Heat",
                commence_time="2026-03-30T23:30:00Z",
                projections={},
            )
        )

        assert len(picks) > 0
        pick = picks[0]
        assert pick.player_name == "Player Z"
        assert pick.event_id == "evt-fields"
        assert pick.home_team == "Boston Celtics"
        assert pick.away_team == "Miami Heat"
        assert pick.commence_time == "2026-03-30T23:30:00Z"
        assert pick.direction == "over"
        assert pick.probability == 0.80
        assert pick.n_games == 40
        assert pick.bookmakers_count == 3
        assert pick.all_lines == sorted([15.5, 16.5, 15.5])
        assert pick.player_team == "Heat"
        assert pick.player_team_code == "MIA"
