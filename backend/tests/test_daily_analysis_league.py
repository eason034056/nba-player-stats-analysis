"""Tests for SPO-35 league-aware daily_analysis (NBA + WNBA).

Focus: prove that `run_daily_analysis(league="wnba")` …

  1. Validates the league up front (raises on unknown).
  2. Routes The Odds API sport_key to `basketball_wnba` (not `basketball_nba`).
  3. Uses `wnba_csv_player_service` for historical probability lookups.
  4. Namespaces the Redis cache key under `daily_picks:wnba:…`.
  5. Skips the projection prefetch entirely (graceful-degrade since the
     WNBA projection wrapper isn't wired yet).

These tests run with no external network (everything is mocked) and no
PostgreSQL (the cache service is mocked at the module reference).

CLAUDE.md § External API Wrappers requires a live integration test for
provider wrappers, not for downstream consumers like this one — the live
WNBA odds wrapper is exercised by `tests/test_wnba_odds_integration.py`
(SPO-33), which is gated behind `RUN_INTEGRATION=1`.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import (  # noqa: E402
    DailyAnalysisService,
    _resolve_csv_service,
    _resolve_sport_key,
)
from tests.fixtures.odds_api import (  # noqa: E402
    RECORDED_NBA_EVENTS,
    derive_line_board,
    load_odds_fixture,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bookmakers_for(player: str, lines: list[float]) -> list[dict[str, Any]]:
    """One recorded bookmaker, with this test's player and lines.

    ``derive_line_board`` copies FanDuel from the recorded ``player_points``
    event and the first outcome on that book (Dyson Daniels Over, price
    -113, point 10.5). ``description`` and ``point`` are replaced with
    ``player`` and ``lines``. The bookmaker key, market key, outcome
    name, and price stay the values that capture posted. Callers pass
    the player and the lines this case controls. They do not pass a price.
    """
    return derive_line_board([{player: lines}])


def _listed_event(
    event_id: str,
    home_team: str,
    away_team: str,
    commence_time: str,
    *,
    league: str = "nba",
) -> dict[str, Any]:
    """Copy the first recorded NBA event and override identity and tip time.

    Source: ``odds_api_events__basketball_nba.json[0]`` (Los Angeles
    Lakers at Atlanta Hawks, ``2026-11-10T00:10:00Z``). ``id``,
    ``home_team``, ``away_team``, and ``commence_time`` are this test's
    controls. Every other field stays on the recording.

    No WNBA events file is on disk. WNBA is paused, so this helper does
    not add a WNBA recording. A WNBA case is that same NBA object with
    only the league fields rewritten: ``sport_key`` from
    ``basketball_nba`` to ``basketball_wnba``, and ``sport_title`` from
    ``NBA`` to ``WNBA``.
    """
    recorded = load_odds_fixture(RECORDED_NBA_EVENTS)
    event = copy.deepcopy(recorded[0])
    event["id"] = event_id
    event["home_team"] = home_team
    event["away_team"] = away_team
    event["commence_time"] = commence_time
    if league == "wnba":
        # Derived from the NBA events capture. No WNBA recording exists.
        event["sport_key"] = "basketball_wnba"
        event["sport_title"] = "WNBA"
    return event


# ---------------------------------------------------------------------------
# 1. Resolver invariants
# ---------------------------------------------------------------------------

class TestResolveSportKey:
    """`_resolve_sport_key` is the single source of truth for league →
    The Odds API sport key. Breakage here corrupts every WNBA call."""

    def test_nba_maps_to_basketball_nba(self):
        assert _resolve_sport_key("nba") == "basketball_nba"

    def test_wnba_maps_to_basketball_wnba(self):
        assert _resolve_sport_key("wnba") == "basketball_wnba"

    def test_case_insensitive(self):
        assert _resolve_sport_key("WNBA") == "basketball_wnba"
        assert _resolve_sport_key("Nba") == "basketball_nba"

    def test_unknown_league_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported league"):
            _resolve_sport_key("ncaa")


class TestResolveCsvService:
    """`_resolve_csv_service` plumbs the per-league CSV service into the
    analyse loop. The two services point at *different CSV files* so a
    mis-route silently returns NBA history for a WNBA player or vice
    versa — silent badness."""

    def test_nba_returns_csv_player_service(self):
        from app.services.csv_player_history import csv_player_service

        assert _resolve_csv_service("nba") is csv_player_service

    def test_wnba_returns_wnba_csv_player_service(self):
        from app.services.csv_player_history import wnba_csv_player_service

        assert _resolve_csv_service("wnba") is wnba_csv_player_service

    def test_unknown_league_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported league"):
            _resolve_csv_service("ncaa")


# ---------------------------------------------------------------------------
# 2. run_daily_analysis(league="wnba") end-to-end (mocked)
# ---------------------------------------------------------------------------

class TestRunDailyAnalysisLeagueRouting:
    """Behavioural tests that prove the league plumbing is connected end
    to end. Each test mocks only the boundary it cares about asserting on,
    so a failure points at the *specific* breakage."""

    # ---- 2.1 Validation ---------------------------------------------------

    def test_unknown_league_raises_before_any_io(self, monkeypatch):
        """League validation MUST happen up front so a bad call doesn't
        even hit the cache or odds gateway."""
        service = DailyAnalysisService()

        # Both side-effects should NOT be reached.
        cache_get = AsyncMock()
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get", cache_get
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events",
            AsyncMock(),
        )

        with pytest.raises(ValueError, match="Unsupported league"):
            asyncio.run(service.run_daily_analysis(date="2026-05-14", league="ncaa"))

        cache_get.assert_not_awaited()

    # ---- 2.2 Sport key dispatch ------------------------------------------

    def test_wnba_passes_basketball_wnba_sport_key_to_odds_provider(
        self, monkeypatch
    ):
        """`run_daily_analysis(league="wnba")` MUST call odds_provider with
        ``league='wnba'``. The provider maps that to ``basketball_wnba``.
        If this regresses, we silently fetch NBA events under a WNBA cache key."""
        service = DailyAnalysisService()

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", AsyncMock()
        )

        get_events = AsyncMock(return_value=[])  # no events → short-circuit
        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events", get_events
        )

        asyncio.run(
            service.run_daily_analysis(
                date="2026-05-14",
                use_cache=True,
                league="wnba",
            )
        )

        get_events.assert_awaited_once()
        kwargs = get_events.await_args.kwargs
        assert kwargs["league"] == "wnba"
        assert _resolve_sport_key(kwargs["league"]) == "basketball_wnba"

    def test_nba_default_keeps_basketball_nba_sport_key(self, monkeypatch):
        """Regression guard — adding the `league` parameter must NOT
        change the NBA default behaviour. Existing NBA callers stay on
        ``basketball_nba``."""
        service = DailyAnalysisService()

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", AsyncMock()
        )

        get_events = AsyncMock(return_value=[])
        monkeypatch.setattr(
            "app.services.daily_analysis.odds_provider.get_events", get_events
        )

        asyncio.run(service.run_daily_analysis(date="2026-05-14"))

        get_events.assert_awaited_once()
        assert get_events.await_args.kwargs["league"] == "nba"
        assert _resolve_sport_key("nba") == "basketball_nba"

    # ---- 2.3 Cache key namespace ----------------------------------------

    def test_wnba_uses_league_namespaced_cache_key(self, monkeypatch):
        """Cache key must be ``daily_picks:wnba:{date}:tz{offset}`` —
        NBA and WNBA cannot share keys (different picks, different inputs,
        different TTL refresh cadence)."""
        service = DailyAnalysisService()

        captured_get_keys: list[str] = []
        captured_set_keys: list[str] = []

        async def fake_get(key: str):
            captured_get_keys.append(key)
            return None

        async def fake_set(key: str, *args, **kwargs):
            captured_set_keys.append(key)

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get", fake_get
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", fake_set
        )

        service._get_events_for_date = AsyncMock(return_value=[])

        asyncio.run(
            service.run_daily_analysis(
                date="2026-05-14",
                use_cache=True,
                tz_offset_minutes=480,
                league="wnba",
            )
        )

        assert captured_get_keys == ["daily_picks:wnba:2026-05-14:tz480"]
        # No events → no cache set (the early return path skips the
        # write). The intent is just to prove the GET key shape.

    def test_nba_keeps_legacy_cache_key_shape_with_league_segment(
        self, monkeypatch
    ):
        """SPO-35 added the league segment to NBA's key too — pre-SPO-35
        keys (without the segment) roll off via TTL within 15 min."""
        service = DailyAnalysisService()

        captured: list[str] = []

        async def fake_get(key: str):
            captured.append(key)
            return None

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get", fake_get
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", AsyncMock()
        )
        service._get_events_for_date = AsyncMock(return_value=[])

        asyncio.run(
            service.run_daily_analysis(
                date="2026-05-14",
                use_cache=True,
                tz_offset_minutes=480,
            )
        )

        assert captured == ["daily_picks:nba:v2:2026-05-14:tz480"]

    # ---- 2.4 No projection client for either league ----------------------

    def test_neither_league_imports_a_projection_service(self):
        """NBA and WNBA share one analysis tree and neither calls a projection client."""
        import app.services.daily_analysis as daily_analysis

        assert not hasattr(daily_analysis, "projection_service")

    def test_wnba_analysis_still_runs_without_a_projection_client(self, monkeypatch):
        """WNBA sources stay on the Odds API and the WNBA CSV."""
        service = DailyAnalysisService()

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", AsyncMock()
        )
        service._get_events_for_date = AsyncMock(
            return_value=[
                _listed_event(
                    "wnba-evt-1",
                    "Toronto Tempo",
                    "Seattle Storm",
                    "2026-05-14T23:00:00Z",
                    league="wnba",
                )
            ]
        )
        service._get_props_for_market = AsyncMock(return_value=[])

        result = asyncio.run(
            service.run_daily_analysis(date="2026-05-14", league="wnba")
        )
        assert result.picks == []
        assert result.stats is not None

    # ---- 2.5 CSV service routing inside _analyze_single_event ------------

    def test_wnba_uses_wnba_csv_service_for_history(self, monkeypatch):
        """When analysing a WNBA event with real props, the history
        lookup MUST hit `wnba_csv_player_service`, not the NBA CSV — a
        silent NBA fallback would return zero games for every WNBA
        player (or worse, NBA history for an NBA player who shares a name)."""
        service = DailyAnalysisService()

        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.set", AsyncMock()
        )

        service._get_events_for_date = AsyncMock(
            return_value=[
                _listed_event(
                    "wnba-evt-1",
                    "Toronto Tempo",
                    "Seattle Storm",
                    "2026-05-14T23:00:00Z",
                    league="wnba",
                )
            ]
        )

        # Provide ONE market's worth of props so the analyse loop reaches
        # the CSV-history step. Other markets return empty.
        async def fake_props(event_id, market, league="nba"):
            if market == "player_points":
                return _bookmakers_for("A'ja Wilson", [14.5, 14.5, 15.5])
            return []

        service._get_props_for_market = AsyncMock(side_effect=fake_props)

        # Patch the WNBA singleton's CSV lookup so we can observe it.
        wnba_stats = MagicMock(return_value={
            "p_over": 0.74,
            "p_under": 0.19,
            "n_games": 18,
            "game_logs": [{"team": "Aces"}],
        })
        monkeypatch.setattr(
            "app.services.daily_analysis.wnba_csv_player_service.get_player_stats",
            wnba_stats,
        )

        # Patch NBA's too — and assert it's NEVER called for a WNBA run.
        nba_stats = MagicMock(return_value={
            "p_over": 0.0,
            "p_under": 0.0,
            "n_games": 0,
            "game_logs": [],
        })
        monkeypatch.setattr(
            "app.services.daily_analysis.csv_player_service.get_player_stats",
            nba_stats,
        )

        result = asyncio.run(
            service.run_daily_analysis(date="2026-05-14", league="wnba")
        )

        wnba_stats.assert_called()
        nba_stats.assert_not_called()
        assert result.total_picks == 1
        # Pick was generated from WNBA history (74% > 65% threshold).
        assert result.picks[0].player_name == "A'ja Wilson"
        assert result.picks[0].probability == pytest.approx(0.74, abs=1e-6)
        assert result.picks[0].signals is None
        assert result.picks[0].combined_probability is None
