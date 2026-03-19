import asyncio
import os
import sys
from unittest.mock import AsyncMock


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import DAILY_PICKS_CACHE_TTL, DailyAnalysisService


def test_daily_picks_cache_ttl_matches_fifteen_minutes():
    assert DAILY_PICKS_CACHE_TTL == 15 * 60


def test_single_event_analysis_returns_player_team_code():
    service = DailyAnalysisService()
    service._get_props_for_market = AsyncMock(
        return_value=[
            {
                "key": "draftkings",
                "markets": [
                    {
                        "outcomes": [
                            {"description": "Stephen Curry", "point": 28.5},
                            {"description": "Stephen Curry", "point": 28.5},
                        ]
                    }
                ],
            }
        ]
    )
    service.csv_service.get_player_stats = lambda **_kwargs: {
        "p_over": 0.72,
        "p_under": 0.21,
        "n_games": 20,
        "game_logs": [{"team": "Warriors"}],
    }

    picks, players_count, props_count = asyncio.run(
        service._analyze_single_event(
            event_id="evt-1",
            home_team="Los Angeles Lakers",
            away_team="Golden State Warriors",
            commence_time="2026-03-13T02:00:00Z",
            projections={
                "Stephen Curry": {
                    "team": "GSW",
                    "points": 30.1,
                    "minutes": 35.0,
                }
            },
        )
    )

    assert players_count == 1
    assert props_count == 4
    assert len(picks) == 4
    assert all(pick.player_team == "GSW" for pick in picks)
    assert all(pick.player_team_code == "GSW" for pick in picks)
