"""SPO-130c: league-keyed odds provider registry.

The Odds API request for a league must match the request dev sends when
the caller passes the sport key directly. No new response shape is
invented: event and odds bodies are the recorded ``odds_api_*`` files.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.odds_gateway import PROVIDERS, OddsMarketGateway
from app.services.odds_theoddsapi import TheOddsAPIProvider, odds_provider
from app.settings import settings
from tests.fixtures.odds_api import (
    RECORDED_NBA_EVENTS,
    RECORDED_PLAYER_POINTS,
    load_odds_fixture,
)


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.headers = {
            "x-requests-remaining": "10",
            "x-requests-used": "1",
            "x-requests-last": "1",
        }
        self.text = ""

    def json(self):
        return self._payload


def _install_capture(monkeypatch, module, payload):
    captured: list[tuple[str, dict]] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            captured.append((url, dict(params or {})))
            return _Response(payload)

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda timeout=30.0: _Client())
    return captured


def _provider() -> TheOddsAPIProvider:
    provider = TheOddsAPIProvider()
    provider.base_url = "https://api.the-odds-api.com"
    provider.api_key = "test-key"
    return provider


class _Cache:
    def __init__(self):
        self.values: dict = {}
        self.locks: set[str] = set()

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value, ttl: int):
        self.values[key] = value
        return True

    async def acquire_lock(self, key: str, ttl: int) -> bool:
        if key in self.locks:
            return False
        self.locks.add(key)
        return True

    async def release_lock(self, key: str) -> bool:
        self.locks.discard(key)
        return True


def _gateway(provider) -> OddsMarketGateway:
    return OddsMarketGateway(
        provider=provider,
        cache=_Cache(),
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )


def test_registry_returns_the_odds_api_for_both_leagues():
    assert settings.nba_odds_provider == "theoddsapi"
    assert isinstance(PROVIDERS["nba"], TheOddsAPIProvider)
    assert isinstance(PROVIDERS["wnba"], TheOddsAPIProvider)
    assert PROVIDERS["nba"] is odds_provider
    assert PROVIDERS["wnba"] is odds_provider
    assert PROVIDERS["nba"].name == "theoddsapi"
    assert PROVIDERS["wnba"].name == "theoddsapi"


def test_unknown_league_and_unknown_nba_provider_raise(monkeypatch):
    with pytest.raises(ValueError, match="Unknown league"):
        PROVIDERS["ncaa"]

    monkeypatch.setattr(settings, "nba_odds_provider", "other")
    with pytest.raises(ValueError, match="nba_odds_provider"):
        PROVIDERS["nba"]
    assert PROVIDERS["wnba"].name == "theoddsapi"


@pytest.mark.asyncio
async def test_gateway_rejects_unknown_league_before_http(monkeypatch):
    import app.services.odds_theoddsapi as odds_module

    captured = _install_capture(monkeypatch, odds_module, [])
    gateway = OddsMarketGateway(
        cache=_Cache(),
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )
    with pytest.raises(ValueError, match="Unknown league"):
        await gateway.get_market_snapshot(
            league="ncaa",
            event_id="evt",
            regions="us",
            markets="player_points",
        )
    assert captured == []
    monkeypatch.setattr(settings, "nba_odds_provider", "other")
    with pytest.raises(ValueError, match="nba_odds_provider"):
        await gateway.get_market_snapshot(
            league="nba",
            event_id="evt",
            regions="us",
            markets="player_points",
        )
    assert captured == []
    assert gateway._provider_for("wnba").name == "theoddsapi"


@pytest.mark.asyncio
async def test_league_events_request_matches_sport_key_request(monkeypatch):
    import app.services.odds_theoddsapi as odds_module

    recorded = load_odds_fixture(RECORDED_NBA_EVENTS)
    captured = _install_capture(monkeypatch, odds_module, recorded)
    provider = _provider()
    start = datetime(2026, 11, 9, 0, 0, 0)
    end = datetime(2026, 11, 11, 23, 59, 59)

    for league, sport in (("nba", "basketball_nba"), ("wnba", "basketball_wnba")):
        before = len(captured)
        await provider.get_events(
            sport=sport,
            regions="us",
            date_from=start,
            date_to=end,
        )
        await provider.get_events(
            league=league,
            regions="us",
            date_from=start,
            date_to=end,
        )
        await provider.list_events(league, start, end)
        sport_call, league_call, listed = captured[before : before + 3]
        assert sport_call == league_call == listed
        assert sport_call[0] == f"https://api.the-odds-api.com/v4/sports/{sport}/events"
        assert set(sport_call[1]) == {"apiKey", "commenceTimeFrom", "commenceTimeTo"}
        assert sport_call[1]["commenceTimeFrom"] == "2026-11-09T00:00:00Z"
        assert sport_call[1]["commenceTimeTo"] == "2026-11-11T23:59:59Z"

    events = await provider.list_events("nba", start, end)
    first = recorded[0]
    listed = events[0]
    assert listed.event_id == first["id"]
    assert listed.commence_time == first["commence_time"]
    assert listed.home_team == first["home_team"]
    assert listed.away_team == first["away_team"]
    assert listed.home_code == "ATL"
    assert listed.away_code == "LAL"
    assert listed.status == "scheduled"
    # 2026-11-10T00:10:00Z is still 2026-11-09 in America/New_York.
    assert listed.slate_date == "2026-11-09"


@pytest.mark.asyncio
async def test_league_props_request_matches_sport_key_request(monkeypatch):
    import app.services.odds_theoddsapi as odds_module

    recorded = load_odds_fixture(RECORDED_PLAYER_POINTS)
    captured = _install_capture(monkeypatch, odds_module, recorded)
    provider = _provider()
    event_id = recorded["id"]

    for league, sport in (("nba", "basketball_nba"), ("wnba", "basketball_wnba")):
        before = len(captured)
        await provider.get_event_odds_with_usage(
            sport=sport,
            event_id=event_id,
            regions="us",
            markets="player_points",
            odds_format="american",
        )
        board = await provider.get_event_props(league, event_id, ("player_points",))
        direct, via_league = captured[before : before + 2]
        assert direct == via_league
        assert direct[0] == (
            f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"
        )
        assert direct[1]["regions"] == "us"
        assert direct[1]["markets"] == "player_points"
        assert direct[1]["oddsFormat"] == "american"
        assert "bookmakers" not in direct[1]
        assert board.provider == "theoddsapi"
        assert board.player_ids == {}
        assert board.bookmakers == recorded["bookmakers"]
        assert board.fetched_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_gateway_league_request_matches_sport_request(monkeypatch):
    import app.services.odds_theoddsapi as odds_module

    recorded = load_odds_fixture(RECORDED_PLAYER_POINTS)
    captured = _install_capture(monkeypatch, odds_module, recorded)
    provider = _provider()
    event_id = recorded["id"]

    for league, sport in (("nba", "basketball_nba"), ("wnba", "basketball_wnba")):
        before = len(captured)
        await _gateway(provider).get_market_snapshot(
            sport=sport,
            event_id=event_id,
            regions="us",
            markets="player_rebounds,player_points",
            odds_format="american",
            bookmakers=["fanduel", "draftkings"],
            record_hot_key=False,
        )
        await _gateway(provider).get_market_snapshot(
            league=league,
            event_id=event_id,
            regions="us",
            markets="player_points,player_rebounds",
            odds_format="american",
            bookmakers=["draftkings", "fanduel"],
            record_hot_key=False,
        )
        by_sport, by_league = captured[before : before + 2]
        assert by_sport == by_league
        assert by_sport[0].endswith(f"/v4/sports/{sport}/events/{event_id}/odds")
        assert by_sport[1]["markets"] == "player_points,player_rebounds"
        assert by_sport[1]["bookmakers"] == "draftkings,fanduel"
        assert by_sport[1]["regions"] == "us"
        assert by_sport[1]["oddsFormat"] == "american"


def test_cache_key_differs_by_provider_and_by_league():
    gateway = _gateway(_provider())
    shared = dict(
        event_id="evt",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )
    nba = gateway._build_snapshot_key(league="nba", **shared)
    wnba = gateway._build_snapshot_key(league="wnba", **shared)
    other = gateway._build_snapshot_key(league="nba", provider_name="other", **shared)
    from_sport = gateway._build_snapshot_key(sport="basketball_nba", **shared)
    assert nba != wnba
    assert nba != other
    assert nba == from_sport
    assert nba.startswith("odds_snapshot:v2:theoddsapi:nba:")
    assert wnba.startswith("odds_snapshot:v2:theoddsapi:wnba:")
    assert other.startswith("odds_snapshot:v2:other:nba:")
    meta = gateway._build_snapshot_meta_key(league="nba", **shared)
    assert meta.startswith("odds_snapshot_meta:v2:theoddsapi:nba:")


@pytest.mark.asyncio
async def test_rate_status_reads_the_gateway_quota_key(monkeypatch):
    from app.services.cache import cache_service
    from app.services.odds_gateway import QUOTA_USAGE_KEY

    seen: list[str] = []

    async def _get(key: str):
        seen.append(key)
        return {"remaining": 4, "used": 1, "last": 1}

    monkeypatch.setattr(cache_service, "get", _get)
    status = await odds_provider.rate_status()
    assert seen == [QUOTA_USAGE_KEY]
    assert status.recorded is True
    assert status.provider == "theoddsapi"
    assert (status.remaining, status.used, status.last, status.total) == (4, 1, 1, 5)
    assert status.remaining_ratio == 0.8

    async def _missing(_key: str):
        return None

    monkeypatch.setattr(cache_service, "get", _missing)
    empty = await odds_provider.rate_status()
    assert empty.recorded is False
    assert empty.remaining is None
