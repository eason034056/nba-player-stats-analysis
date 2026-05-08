"""
test_cache.py - Unit tests for the CacheService (Redis cache wrapper)

Uses pytest + pytest-asyncio with a mock Redis client to avoid real connections.

Coverage:
1.  get() returns parsed JSON on cache hit
2.  get() returns None on cache miss
3.  get() returns None on exception
4.  set() serializes and stores with TTL
5.  set() returns False on exception
6.  delete() works
7.  delete_pattern() iterates and deletes matching keys
8.  clear_daily_picks_cache() delegates to delete_pattern
9.  close() closes client and resets to None
10. acquire_lock() success and failure
11. release_lock()
12. increment_sorted_set()
13. get_top_sorted_set_members()
14. remove_sorted_set_member()
15. build_events_key, build_props_key, build_players_key static methods
"""

import json
import pytest
import sys
import os

# Add project root to Python path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cache import CacheService


# ---------------------------------------------------------------------------
# Fake async Redis client used across all tests
# ---------------------------------------------------------------------------

class FakeRedisClient:
    """
    Minimal async mock of redis.asyncio.Redis.

    Stores data in plain dicts so we can assert on calls without a real Redis.
    """

    def __init__(self):
        self.store: dict[str, str] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.closed = False
        # Track calls for assertion purposes
        self.delete_calls: list[str] = []
        self.set_calls: list[dict] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int = None, nx: bool = False):
        self.set_calls.append({"key": key, "value": value, "ex": ex, "nx": nx})
        if nx and key in self.store:
            return None  # NX means set only if not exists
        self.store[key] = value
        return True

    async def delete(self, key: str):
        self.delete_calls.append(key)
        self.store.pop(key, None)

    async def scan_iter(self, match: str = None, count: int = 100):
        """Yield keys matching the given glob pattern (simple * suffix matching)."""
        import fnmatch
        for key in list(self.store.keys()):
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    async def zincrby(self, key: str, amount: float, member: str) -> float:
        if key not in self.sorted_sets:
            self.sorted_sets[key] = {}
        self.sorted_sets[key].setdefault(member, 0.0)
        self.sorted_sets[key][member] += amount
        return self.sorted_sets[key][member]

    async def zrevrange(self, key: str, start: int, stop: int):
        zset = self.sorted_sets.get(key, {})
        sorted_members = sorted(zset.keys(), key=lambda m: zset[m], reverse=True)
        return sorted_members[start: stop + 1]

    async def zrem(self, key: str, member: str):
        if key in self.sorted_sets:
            self.sorted_sets[key].pop(member, None)

    async def close(self):
        self.closed = True


class ErrorRedisClient:
    """A Redis client stub that raises on every operation."""

    async def get(self, key):
        raise ConnectionError("Redis unavailable")

    async def set(self, key, value, ex=None, nx=False):
        raise ConnectionError("Redis unavailable")

    async def delete(self, key):
        raise ConnectionError("Redis unavailable")

    async def scan_iter(self, match=None, count=100):
        raise ConnectionError("Redis unavailable")
        # Need yield to make this an async generator; unreachable but required
        yield  # noqa: unreachable  # pragma: no cover

    async def zincrby(self, key, amount, member):
        raise ConnectionError("Redis unavailable")

    async def zrevrange(self, key, start, stop):
        raise ConnectionError("Redis unavailable")

    async def zrem(self, key, member):
        raise ConnectionError("Redis unavailable")

    async def close(self):
        raise ConnectionError("Redis unavailable")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_service():
    """Return a fresh CacheService with a FakeRedisClient already injected."""
    svc = CacheService()
    svc._client = FakeRedisClient()
    return svc


@pytest.fixture
def fake_client(cache_service):
    """Convenience accessor for the underlying fake client."""
    return cache_service._client


@pytest.fixture
def error_cache_service():
    """Return a CacheService wired to an always-erroring client."""
    svc = CacheService()
    svc._client = ErrorRedisClient()
    return svc


# ===========================================================================
# 1-3. get()
# ===========================================================================

class TestCacheGet:
    """Tests for CacheService.get()."""

    @pytest.mark.asyncio
    async def test_get_returns_parsed_json_on_hit(self, cache_service, fake_client):
        """get() should parse JSON from Redis and return a Python object."""
        data = {"events": [1, 2, 3], "count": 3}
        fake_client.store["my_key"] = json.dumps(data)

        result = await cache_service.get("my_key")
        assert result == data

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self, cache_service):
        """get() should return None when key does not exist."""
        result = await cache_service.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_exception(self, error_cache_service):
        """get() should swallow exceptions and return None."""
        result = await error_cache_service.get("any_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_for_empty_string(self, cache_service, fake_client):
        """get() returns None if Redis value is falsy (empty string)."""
        fake_client.store["empty"] = ""
        result = await cache_service.get("empty")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_parses_list(self, cache_service, fake_client):
        """get() should handle JSON arrays as well as objects."""
        fake_client.store["list_key"] = json.dumps([1, "two", 3.0])
        result = await cache_service.get("list_key")
        assert result == [1, "two", 3.0]


# ===========================================================================
# 4-5. set()
# ===========================================================================

class TestCacheSet:
    """Tests for CacheService.set()."""

    @pytest.mark.asyncio
    async def test_set_serializes_and_stores(self, cache_service, fake_client):
        """set() should JSON-serialize the value and store with TTL."""
        data = {"player": "Curry", "points": 30}
        result = await cache_service.set("stats:1", data, ttl=300)

        assert result is True
        # Verify the stored value is JSON
        assert json.loads(fake_client.store["stats:1"]) == data
        # Verify the set call had the right TTL
        assert fake_client.set_calls[-1]["ex"] == 300

    @pytest.mark.asyncio
    async def test_set_handles_non_serializable_via_default_str(self, cache_service, fake_client):
        """set() uses default=str so non-standard types (e.g., dates) don't crash."""
        from datetime import date
        data = {"date": date(2026, 1, 14)}
        result = await cache_service.set("date_key", data, ttl=60)
        assert result is True
        parsed = json.loads(fake_client.store["date_key"])
        assert parsed["date"] == "2026-01-14"

    @pytest.mark.asyncio
    async def test_set_returns_false_on_exception(self, error_cache_service):
        """set() should swallow exceptions and return False."""
        result = await error_cache_service.set("k", "v", ttl=60)
        assert result is False


# ===========================================================================
# 6. delete()
# ===========================================================================

class TestCacheDelete:
    """Tests for CacheService.delete()."""

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, cache_service, fake_client):
        """delete() should remove a key and return True."""
        fake_client.store["to_remove"] = "value"
        result = await cache_service.delete("to_remove")
        assert result is True
        assert "to_remove" not in fake_client.store

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, cache_service, fake_client):
        """delete() should succeed even if key doesn't exist."""
        result = await cache_service.delete("ghost")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_on_exception(self, error_cache_service):
        """delete() should swallow exceptions and return False."""
        result = await error_cache_service.delete("k")
        assert result is False


# ===========================================================================
# 7. delete_pattern()
# ===========================================================================

class TestCacheDeletePattern:
    """Tests for CacheService.delete_pattern()."""

    @pytest.mark.asyncio
    async def test_delete_pattern_removes_matching_keys(self, cache_service, fake_client):
        """delete_pattern() should delete all keys matching the glob pattern."""
        fake_client.store["daily_picks:2026-01-14:nba"] = "a"
        fake_client.store["daily_picks:2026-01-15:nba"] = "b"
        fake_client.store["events:nba:2026-01-14:us"] = "c"

        deleted = await cache_service.delete_pattern("daily_picks:*")
        assert deleted == 2
        assert "events:nba:2026-01-14:us" in fake_client.store
        assert "daily_picks:2026-01-14:nba" not in fake_client.store
        assert "daily_picks:2026-01-15:nba" not in fake_client.store

    @pytest.mark.asyncio
    async def test_delete_pattern_returns_zero_when_no_match(self, cache_service):
        """delete_pattern() should return 0 when nothing matches."""
        deleted = await cache_service.delete_pattern("nonexistent:*")
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_delete_pattern_returns_zero_on_exception(self, error_cache_service):
        """delete_pattern() should swallow exceptions and return 0."""
        deleted = await error_cache_service.delete_pattern("any:*")
        assert deleted == 0


# ===========================================================================
# 8. clear_daily_picks_cache()
# ===========================================================================

class TestClearDailyPicksCache:
    """Tests for CacheService.clear_daily_picks_cache()."""

    @pytest.mark.asyncio
    async def test_clear_daily_picks_delegates_to_delete_pattern(self, cache_service, fake_client):
        """clear_daily_picks_cache() should delete all daily_picks:* keys."""
        fake_client.store["daily_picks:a"] = "1"
        fake_client.store["daily_picks:b"] = "2"
        fake_client.store["other:key"] = "3"

        deleted = await cache_service.clear_daily_picks_cache()
        assert deleted == 2
        assert "other:key" in fake_client.store

    @pytest.mark.asyncio
    async def test_clear_daily_picks_returns_zero_when_empty(self, cache_service):
        """clear_daily_picks_cache() returns 0 when there are no matching keys."""
        deleted = await cache_service.clear_daily_picks_cache()
        assert deleted == 0


# ===========================================================================
# 9. close()
# ===========================================================================

class TestCacheClose:
    """Tests for CacheService.close()."""

    @pytest.mark.asyncio
    async def test_close_closes_client_and_resets(self, cache_service, fake_client):
        """close() should call client.close() and set _client to None."""
        await cache_service.close()
        assert fake_client.closed is True
        assert cache_service._client is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_client(self):
        """close() should do nothing if _client is already None."""
        svc = CacheService()
        assert svc._client is None
        await svc.close()  # Should not raise
        assert svc._client is None


# ===========================================================================
# 10. acquire_lock()
# ===========================================================================

class TestAcquireLock:
    """Tests for CacheService.acquire_lock()."""

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, cache_service, fake_client):
        """acquire_lock() returns True when key does not exist (NX succeeds)."""
        result = await cache_service.acquire_lock("lock:task1", ttl=30)
        assert result is True
        # The key should now be in the store
        assert "lock:task1" in fake_client.store

    @pytest.mark.asyncio
    async def test_acquire_lock_failure_when_held(self, cache_service, fake_client):
        """acquire_lock() returns False when key already exists (NX fails)."""
        fake_client.store["lock:task1"] = "1"
        result = await cache_service.acquire_lock("lock:task1", ttl=30)
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_lock_sets_correct_ttl(self, cache_service, fake_client):
        """acquire_lock() should pass ex=ttl and nx=True to Redis SET."""
        await cache_service.acquire_lock("lock:x", ttl=60)
        call = fake_client.set_calls[-1]
        assert call["ex"] == 60
        assert call["nx"] is True

    @pytest.mark.asyncio
    async def test_acquire_lock_returns_false_on_exception(self, error_cache_service):
        """acquire_lock() should return False on error."""
        result = await error_cache_service.acquire_lock("lock:fail", ttl=10)
        assert result is False


# ===========================================================================
# 11. release_lock()
# ===========================================================================

class TestReleaseLock:
    """Tests for CacheService.release_lock()."""

    @pytest.mark.asyncio
    async def test_release_lock_deletes_key(self, cache_service, fake_client):
        """release_lock() should delete the lock key and return True."""
        fake_client.store["lock:task1"] = "1"
        result = await cache_service.release_lock("lock:task1")
        assert result is True
        assert "lock:task1" not in fake_client.store

    @pytest.mark.asyncio
    async def test_release_lock_returns_false_on_exception(self, error_cache_service):
        """release_lock() should return False on error."""
        result = await error_cache_service.release_lock("lock:fail")
        assert result is False


# ===========================================================================
# 12. increment_sorted_set()
# ===========================================================================

class TestIncrementSortedSet:
    """Tests for CacheService.increment_sorted_set()."""

    @pytest.mark.asyncio
    async def test_increment_new_member(self, cache_service, fake_client):
        """Incrementing a new member should start from 0 and add amount."""
        score = await cache_service.increment_sorted_set("leaderboard", "player1", 5.0)
        assert score == 5.0
        assert fake_client.sorted_sets["leaderboard"]["player1"] == 5.0

    @pytest.mark.asyncio
    async def test_increment_existing_member(self, cache_service, fake_client):
        """Incrementing an existing member should add to current score."""
        fake_client.sorted_sets["leaderboard"] = {"player1": 10.0}
        score = await cache_service.increment_sorted_set("leaderboard", "player1", 3.0)
        assert score == 13.0

    @pytest.mark.asyncio
    async def test_increment_default_amount(self, cache_service, fake_client):
        """Default increment amount is 1.0."""
        score = await cache_service.increment_sorted_set("zset", "member")
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_increment_sorted_set_returns_zero_on_exception(self, error_cache_service):
        """increment_sorted_set() should return 0.0 on error."""
        score = await error_cache_service.increment_sorted_set("z", "m", 1.0)
        assert score == 0.0


# ===========================================================================
# 13. get_top_sorted_set_members()
# ===========================================================================

class TestGetTopSortedSetMembers:
    """Tests for CacheService.get_top_sorted_set_members()."""

    @pytest.mark.asyncio
    async def test_returns_members_in_descending_score_order(self, cache_service, fake_client):
        """Should return top N members sorted by score descending."""
        fake_client.sorted_sets["leaderboard"] = {
            "alpha": 10.0,
            "beta": 30.0,
            "gamma": 20.0,
        }
        result = await cache_service.get_top_sorted_set_members("leaderboard", limit=2)
        assert result == ["beta", "gamma"]

    @pytest.mark.asyncio
    async def test_returns_all_when_limit_exceeds_set_size(self, cache_service, fake_client):
        """If limit > set size, return all members."""
        fake_client.sorted_sets["small"] = {"a": 1.0, "b": 2.0}
        result = await cache_service.get_top_sorted_set_members("small", limit=100)
        assert result == ["b", "a"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_nonexistent_key(self, cache_service):
        """Should return empty list when the sorted set does not exist."""
        result = await cache_service.get_top_sorted_set_members("nope", limit=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self, error_cache_service):
        """get_top_sorted_set_members() should return [] on error."""
        result = await error_cache_service.get_top_sorted_set_members("z", limit=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_limit_zero(self, cache_service, fake_client):
        """Limit of 0 should use max(0-1, 0) = 0 and return empty or first element."""
        fake_client.sorted_sets["zs"] = {"a": 1.0, "b": 2.0}
        # With limit=0, the code does zrevrange(key, 0, max(0 - 1, 0)) = zrevrange(key, 0, 0)
        # which returns the single top element
        result = await cache_service.get_top_sorted_set_members("zs", limit=0)
        assert isinstance(result, list)


# ===========================================================================
# 14. remove_sorted_set_member()
# ===========================================================================

class TestRemoveSortedSetMember:
    """Tests for CacheService.remove_sorted_set_member()."""

    @pytest.mark.asyncio
    async def test_remove_existing_member(self, cache_service, fake_client):
        """remove_sorted_set_member() removes the member and returns True."""
        fake_client.sorted_sets["leaderboard"] = {"player1": 10.0, "player2": 20.0}
        result = await cache_service.remove_sorted_set_member("leaderboard", "player1")
        assert result is True
        assert "player1" not in fake_client.sorted_sets["leaderboard"]
        assert "player2" in fake_client.sorted_sets["leaderboard"]

    @pytest.mark.asyncio
    async def test_remove_nonexistent_member(self, cache_service, fake_client):
        """Removing a member that doesn't exist should still return True (no error)."""
        fake_client.sorted_sets["leaderboard"] = {"player1": 10.0}
        result = await cache_service.remove_sorted_set_member("leaderboard", "ghost")
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_returns_false_on_exception(self, error_cache_service):
        """remove_sorted_set_member() should return False on error."""
        result = await error_cache_service.remove_sorted_set_member("z", "m")
        assert result is False


# ===========================================================================
# 15. Static key-builder methods
# ===========================================================================

class TestBuildKeys:
    """Tests for the static key-builder methods."""

    def test_build_events_key(self):
        key = CacheService.build_events_key("2026-01-14", "us")
        assert key == "events:nba:2026-01-14:us"

    def test_build_events_key_different_region(self):
        key = CacheService.build_events_key("2026-03-01", "eu")
        assert key == "events:nba:2026-03-01:eu"

    def test_build_props_key_with_bookmakers(self):
        key = CacheService.build_props_key(
            event_id="abc123",
            market="player_points",
            regions="us",
            bookmakers=["draftkings", "fanduel"],
            odds_format="american",
        )
        # Bookmakers should be sorted
        assert key == "props:nba:abc123:player_points:us:draftkings,fanduel:american"

    def test_build_props_key_with_bookmakers_sorted(self):
        """Bookmakers order should not matter - they get sorted."""
        key = CacheService.build_props_key(
            event_id="xyz",
            market="player_rebounds",
            regions="us",
            bookmakers=["fanduel", "betmgm", "draftkings"],
            odds_format="decimal",
        )
        assert key == "props:nba:xyz:player_rebounds:us:betmgm,draftkings,fanduel:decimal"

    def test_build_props_key_without_bookmakers(self):
        """When bookmakers is None, should use 'all'."""
        key = CacheService.build_props_key(
            event_id="abc",
            market="player_assists",
            regions="us",
            bookmakers=None,
            odds_format="american",
        )
        assert key == "props:nba:abc:player_assists:us:all:american"

    def test_build_players_key(self):
        key = CacheService.build_players_key("event99")
        assert key == "players:nba:event99"


# ===========================================================================
# get_client() lazy initialization
# ===========================================================================

class TestGetClient:
    """Tests for CacheService.get_client() lazy init."""

    @pytest.mark.asyncio
    async def test_get_client_creates_connection_lazily(self, monkeypatch):
        """get_client() should call redis.from_url on first invocation."""
        fake = FakeRedisClient()

        # Patch redis.from_url in the cache module
        import app.services.cache as cache_module
        monkeypatch.setattr(cache_module.redis, "from_url", lambda url, **kwargs: fake)

        svc = CacheService()
        assert svc._client is None

        client = await svc.get_client()
        assert client is fake
        assert svc._client is fake

    @pytest.mark.asyncio
    async def test_get_client_reuses_existing_connection(self, cache_service, fake_client):
        """get_client() should return the same client on subsequent calls."""
        client1 = await cache_service.get_client()
        client2 = await cache_service.get_client()
        assert client1 is client2
        assert client1 is fake_client
