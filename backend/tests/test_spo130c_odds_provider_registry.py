"""NBA odds registry is BALLDONTLIE. Snapshot keys include the provider name."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.bdl_odds_provider import BdlOddsProvider
from app.services.odds_gateway import OddsMarketGateway, PROVIDERS
from app.settings import settings


class _Cache:
    def __init__(self) -> None:
        self.values: dict = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value, ttl: int | None = None) -> None:
        self.values[key] = value


class _Named:
    name = "sample"


def test_registry_returns_balldontlie_for_nba():
    assert "nba_" + "odds_provider" not in settings.model_fields
    provider = PROVIDERS["nba"]
    assert isinstance(provider, BdlOddsProvider)
    assert provider.name == "balldontlie"
    with pytest.raises(ValueError, match="Unknown league"):
        PROVIDERS["wnba"]
    with pytest.raises(ValueError, match="Unknown league"):
        PROVIDERS["ncaa"]


@pytest.mark.asyncio
async def test_gateway_rejects_unknown_league_before_http():
    gateway = OddsMarketGateway(
        cache=_Cache(),
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        hot_keys_limit=10,
    )
    with pytest.raises(ValueError, match="Unknown league"):
        await gateway.get_market_snapshot(
            league="ncaa",
            event_id="21718080",
            regions="us",
            markets="player_points",
            odds_format="american",
        )


def test_cache_key_uses_the_provider_name_and_rejects_other_leagues():
    gateway = OddsMarketGateway(
        provider=_Named(),
        cache=_Cache(),
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        hot_keys_limit=10,
    )
    shared = dict(
        event_id="21718080",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )
    nba = gateway._build_snapshot_key(league="nba", **shared)
    other = gateway._build_snapshot_key(league="nba", provider_name="other", **shared)
    from_sport = gateway._build_snapshot_key(sport="basketball_nba", **shared)
    with pytest.raises(ValueError):
        gateway._build_snapshot_key(league="wnba", **shared)
    assert nba != other
    assert nba == from_sport
    assert nba.startswith("odds_snapshot:v2:sample:nba:")
    meta = gateway._build_snapshot_meta_key(league="nba", **shared)
    assert meta.startswith("odds_snapshot_meta:v2:sample:nba:")
