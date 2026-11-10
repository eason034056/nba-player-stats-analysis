"""
test_odds_gateway.py - Odds market snapshot gateway 測試

驗證共享 snapshot、stale-while-revalidate、single-flight 與 quota 保護。
"""

import asyncio
import copy
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# 將專案根目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.odds_provider import OddsAPIError
from app.services.odds_gateway import HOT_KEYS_ZSET_KEY, OddsMarketGateway, QuotaUsage
from tests.fixtures.odds_api import RECORDED_PLAYER_POINTS, load_odds_fixture


class FakeCache:
    def __init__(self):
        self.values = {}
        self.locks = set()
        self.zsets = {}

    async def get(self, key: str):
        value = self.values.get(key)
        return copy.deepcopy(value)

    async def set(self, key: str, value, ttl: int):
        self.values[key] = copy.deepcopy(value)
        return True

    async def acquire_lock(self, key: str, ttl: int) -> bool:
        if key in self.locks:
            return False
        self.locks.add(key)
        return True

    async def release_lock(self, key: str) -> bool:
        self.locks.discard(key)
        return True

    async def increment_sorted_set(self, key: str, member: str, amount: float = 1.0) -> float:
        bucket = self.zsets.setdefault(key, {})
        bucket[member] = bucket.get(member, 0.0) + amount
        return bucket[member]

    async def get_top_sorted_set_members(self, key: str, limit: int):
        bucket = self.zsets.get(key, {})
        ordered = sorted(bucket.items(), key=lambda item: item[1], reverse=True)
        return [member for member, _ in ordered[:limit]]

    async def remove_sorted_set_member(self, key: str, member: str) -> bool:
        bucket = self.zsets.get(key, {})
        bucket.pop(member, None)
        return True


class FakeProvider:
    def __init__(self, responses, delay: float = 0.0):
        self.responses = list(responses)
        self.delay = delay
        self.calls = []

    async def get_event_odds_with_usage(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str = "american",
        bookmakers=None,
    ):
        self.calls.append({
            "sport": sport,
            "event_id": event_id,
            "regions": regions,
            "markets": markets,
            "odds_format": odds_format,
            "bookmakers": bookmakers,
        })
        if self.delay:
            await asyncio.sleep(self.delay)
        if not self.responses:
            raise OddsAPIError("no more fake responses", 500)
        payload = self.responses.pop(0)
        usage = QuotaUsage(remaining=900, used=100, last=1)
        return copy.deepcopy(payload), usage


def _recorded_gateway_payload() -> dict:
    """FanDuel's first Over/Under pair from the recorded player_points event.

    Starts at ``odds_api_event_odds__player_points.json``. Keeps the event
    shell and the first bookmaker (FanDuel). Keeps the first player's
    Over and Under (Dyson Daniels, 10.5, -113/-113 in that capture) and
    drops every other bookmaker and outcome. Prices, the market key, and
    the event id stay as recorded.
    """
    event = load_odds_fixture(RECORDED_PLAYER_POINTS)
    book = copy.deepcopy(event["bookmakers"][0])
    market = book["markets"][0]
    player_name = market["outcomes"][0]["description"]
    market["outcomes"] = [
        outcome
        for outcome in market["outcomes"]
        if outcome.get("description") == player_name
        and outcome.get("name") in ("Over", "Under")
    ]
    # One pair is enough for the gateway. Later alt-lines for the same
    # player, if a future capture adds them, are not part of this slice.
    pair: list[dict] = []
    seen: set[str] = set()
    for outcome in market["outcomes"]:
        side = outcome["name"]
        if side in seen:
            continue
        seen.add(side)
        pair.append(outcome)
    market["outcomes"] = pair
    book["markets"] = [market]
    event = copy.deepcopy(event)
    event["bookmakers"] = [book]
    return event


def _derive_gateway_payload(description: str, line: float) -> dict:
    """Relabel the recorded FanDuel pair.

    ``_recorded_gateway_payload`` is the start. ``description`` and
    ``point`` on both outcomes are then set to the values this test uses
    to tell a stale snapshot from the refresh. The event id, FanDuel
    key, market key, and prices stay recorded.
    """
    payload = _recorded_gateway_payload()
    for outcome in payload["bookmakers"][0]["markets"][0]["outcomes"]:
        outcome["description"] = description
        outcome["point"] = line
    return payload


@pytest.mark.asyncio
async def test_same_semantic_key_hits_upstream_once():
    cache = FakeCache()
    provider = FakeProvider([_recorded_gateway_payload()])
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )

    first = await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_rebounds,player_points",
        odds_format="american",
        bookmakers=["fanduel", "draftkings"],
    )
    second = await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points,player_rebounds",
        odds_format="american",
        bookmakers=["draftkings", "fanduel"],
    )

    assert len(provider.calls) == 1
    assert first.source == "upstream"
    assert second.source == "snapshot_cache"
    assert second.cache_state == "fresh"


@pytest.mark.asyncio
async def test_stale_snapshot_returns_cached_value_and_refreshes_in_background():
    cache = FakeCache()
    provider = FakeProvider([
        _derive_gateway_payload("old value", 28.5),
        _derive_gateway_payload("fresh value", 29.5),
    ])
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )

    initial = await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )
    assert initial.data["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "old value"

    meta_key = gateway._build_snapshot_meta_key(  # noqa: SLF001
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )
    cache.values[meta_key]["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=50)
    ).isoformat()

    stale = await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )

    assert stale.cache_state == "stale"
    assert stale.source == "snapshot_cache"
    assert stale.data["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "old value"

    await asyncio.sleep(0.01)

    refreshed = await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )
    assert len(provider.calls) == 2
    assert refreshed.data["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "fresh value"


@pytest.mark.asyncio
async def test_concurrent_requests_share_single_upstream_fetch():
    cache = FakeCache()
    recorded = _recorded_gateway_payload()
    recorded_id = recorded["id"]
    provider = FakeProvider([recorded], delay=0.05)
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )

    async def _fetch():
        return await gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id="evt_123",
            regions="us",
            markets="player_points",
            odds_format="american",
            bookmakers=None,
        )

    results = await asyncio.gather(*[_fetch() for _ in range(20)])

    assert len(provider.calls) == 1
    assert all(result.data["id"] == recorded_id for result in results)


@pytest.mark.asyncio
async def test_background_priority_skips_upstream_when_quota_protected_and_stale_exists():
    cache = FakeCache()
    provider = FakeProvider([_recorded_gateway_payload()])
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )

    await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )

    meta_key = gateway._build_snapshot_meta_key(  # noqa: SLF001
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
    )
    cache.values[meta_key]["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=60)
    ).isoformat()

    await gateway.record_quota_usage(QuotaUsage(remaining=10, used=90, last=1))

    result = await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
        priority="background",
    )

    assert len(provider.calls) == 1
    assert result.cache_state == "stale"
    assert result.source == "snapshot_cache"


@pytest.mark.asyncio
async def test_prewarm_cleans_expired_hot_keys():
    cache = FakeCache()
    provider = FakeProvider([_recorded_gateway_payload()])
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=45,
        stale_ttl_seconds=120,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )

    expired_member = (
        '{"bookmakers": null, "event_id": "evt_old", "markets": "player_points", '
        '"odds_format": "american", "regions": "us", "sport": "basketball_nba"}'
    )
    fresh_member = (
        '{"bookmakers": null, "event_id": "evt_123", "markets": "player_points", '
        '"odds_format": "american", "regions": "us", "sport": "basketball_nba"}'
    )

    cache.zsets[HOT_KEYS_ZSET_KEY] = {
        expired_member: 5.0,
        fresh_member: 4.0,
    }
    cache.values[f"odds:hot_seen:v1:{expired_member}"] = {
        "seen_at": (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    }
    cache.values[f"odds:hot_seen:v1:{fresh_member}"] = {
        "seen_at": datetime.now(timezone.utc).isoformat()
    }

    warmed = await gateway.prewarm_hot_keys()

    assert warmed == 1
    assert expired_member not in cache.zsets[HOT_KEYS_ZSET_KEY]
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_prewarm_skips_hot_keys_that_are_still_fresh():
    cache = FakeCache()
    provider = FakeProvider([_recorded_gateway_payload()])
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=600,
        stale_ttl_seconds=900,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=300,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )

    await gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="evt_123",
        regions="us",
        markets="player_points",
        odds_format="american",
        bookmakers=None,
        priority="interactive",
    )

    warmed = await gateway.prewarm_hot_keys()

    assert warmed == 0
    assert len(provider.calls) == 1
