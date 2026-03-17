"""
cache.py - Redis Cache Service

Encapsulates Redis operations and provides caching capabilities.
Caching reduces the number of external Odds API calls, lowering costs and improving response speed.
"""

import json
import redis.asyncio as redis
from typing import Optional, Any
from app.settings import settings


class CacheService:
    """
    Redis Cache Service

    Uses singleton pattern (module-level instance) to ensure the entire application shares the same connection.

    Main features:
    - get: retrieve cached data
    - set: set cached data (with TTL)
    - delete: delete cached data
    - build_key: construct cache key
    """

    def __init__(self):
        """
        Initialize the cache service.

        Note: The actual Redis connection is established lazily
        and will only be set on the first usage.
        """
        self._client: Optional[redis.Redis] = None

    async def get_client(self) -> redis.Redis:
        """
        Get the Redis client connection.

        Uses lazy initialization:
        The connection is only established when first needed.

        redis.from_url: establishes a Redis connection from a URL string
        - decode_responses=True: automatically decode bytes to strings

        Returns:
            Redis client instance
        """
        if self._client is None:
            self._client = redis.from_url(
                settings.redis_url,
                decode_responses=True  # Auto-decode to string
            )
        return self._client

    async def get(self, key: str) -> Optional[Any]:
        """
        Retrieve data from cache.

        Procedure:
        1. Get the string from Redis
        2. If it exists, parse JSON to a Python object
        3. If not, return None

        Args:
            key: cache key

        Returns:
            Cached data (parsed to a Python object), or None

        Example:
            >>> data = await cache.get("events:nba:2026-01-14:us")
            >>> if data:
            ...     print(f"Cache hit: {len(data['events'])} events")
        """
        try:
            client = await self.get_client()
            value = await client.get(key)

            if value:
                return json.loads(value)
            return None

        except Exception as e:
            # Cache failure should not affect main functionality, log and return None
            print(f"Cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """
        Set cached data.

        Args:
            key: cache key
            value: data to cache (will be serialized as JSON)
            ttl: Time To Live (seconds)
                 After this time, Redis will automatically delete the key

        Returns:
            Success status

        Example:
            >>> await cache.set(
            ...     "events:nba:2026-01-14:us",
            ...     {"events": [...]},
            ...     ttl=300  # 5 minutes
            ... )
        """
        try:
            client = await self.get_client()
            # Serialize Python object as JSON string
            json_value = json.dumps(value, default=str)
            # ex=ttl: set expiry in seconds
            await client.set(key, json_value, ex=ttl)
            return True

        except Exception as e:
            print(f"Cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete cached data.

        Args:
            key: cache key

        Returns:
            Success status
        """
        try:
            client = await self.get_client()
            await client.delete(key)
            return True

        except Exception as e:
            print(f"Cache delete error: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all cache entries matching the pattern.

        Uses Redis SCAN + DELETE (safer than KEYS, will not block Redis).

        Args:
            pattern: pattern string (supports * wildcard)
                     For example: "daily_picks:*" will delete all keys starting with daily_picks:

        Returns:
            int: number of keys deleted

        Example:
            >>> await cache.delete_pattern("daily_picks:*")
            3  # deleted 3 keys
        """
        try:
            client = await self.get_client()
            deleted_count = 0

            # Use SCAN to find all keys matching the pattern
            # scan_iter: async iterator, yields batches of matching keys
            # match=pattern: matching pattern
            # count=100: number of records per scan (recommended value)
            async for key in client.scan_iter(match=pattern, count=100):
                await client.delete(key)
                deleted_count += 1

            if deleted_count > 0:
                print(f"🗑️ Deleted {deleted_count} cache entries (pattern: {pattern})")

            return deleted_count

        except Exception as e:
            print(f"Cache delete_pattern error: {e}")
            return 0

    async def clear_daily_picks_cache(self) -> int:
        """
        Clear all daily picks cache.

        When the CSV data is updated, clear all daily picks cache
        so the next request will parse and use the latest data.

        Returns:
            int: number of keys deleted
        """
        return await self.delete_pattern("daily_picks:*")

    async def close(self):
        """
        Close the Redis connection.

        Call this to free resources when the application ends.
        """
        if self._client:
            await self._client.close()
            self._client = None

    async def acquire_lock(self, key: str, ttl: int) -> bool:
        """
        Acquire a simple distributed lock.

        Uses SET key value NX EX ttl; return True on success.
        """
        try:
            client = await self.get_client()
            acquired = await client.set(key, "1", ex=ttl, nx=True)
            return bool(acquired)
        except Exception as e:
            print(f"Cache acquire_lock error: {e}")
            return False

    async def release_lock(self, key: str) -> bool:
        """
        Release the distributed lock.
        """
        try:
            client = await self.get_client()
            await client.delete(key)
            return True
        except Exception as e:
            print(f"Cache release_lock error: {e}")
            return False

    async def increment_sorted_set(self, key: str, member: str, amount: float = 1.0) -> float:
        """
        Increment the score of a sorted set member.
        """
        try:
            client = await self.get_client()
            return await client.zincrby(key, amount, member)
        except Exception as e:
            print(f"Cache increment_sorted_set error: {e}")
            return 0.0

    async def get_top_sorted_set_members(self, key: str, limit: int) -> list[str]:
        """
        Get the top N members from a sorted set by score.
        """
        try:
            client = await self.get_client()
            members = await client.zrevrange(key, 0, max(limit - 1, 0))
            return list(members)
        except Exception as e:
            print(f"Cache get_top_sorted_set_members error: {e}")
            return []

    async def remove_sorted_set_member(self, key: str, member: str) -> bool:
        """
        Remove a specified member from a sorted set.
        """
        try:
            client = await self.get_client()
            await client.zrem(key, member)
            return True
        except Exception as e:
            print(f"Cache remove_sorted_set_member error: {e}")
            return False

    @staticmethod
    def build_events_key(date: str, regions: str) -> str:
        """
        Construct the cache key for the event list.

        Format: events:nba:{date}:{regions}

        Args:
            date: date string (YYYY-MM-DD)
            regions: region code (e.g., "us")

        Returns:
            cache key

        Example:
            >>> CacheService.build_events_key("2026-01-14", "us")
            "events:nba:2026-01-14:us"
        """
        return f"events:nba:{date}:{regions}"

    @staticmethod
    def build_props_key(
        event_id: str,
        market: str,
        regions: str,
        bookmakers: Optional[list],
        odds_format: str
    ) -> str:
        """
        Construct the cache key for Props data.

        Format: props:nba:{event_id}:{market}:{regions}:{bookmakers}:{odds_format}

        Args:
            event_id: event ID
            market: market type (e.g., "player_points")
            regions: region code
            bookmakers: list of bookmakers (None for all)
            odds_format: odds format

        Returns:
            cache key
        """
        # Sort the bookmaker list and join as a string to ensure identical content yields the same key
        books_str = ",".join(sorted(bookmakers)) if bookmakers else "all"
        return f"props:nba:{event_id}:{market}:{regions}:{books_str}:{odds_format}"

    @staticmethod
    def build_players_key(event_id: str) -> str:
        """
        Construct the cache key for the player list.

        Format: players:nba:{event_id}

        Args:
            event_id: event ID

        Returns:
            cache key
        """
        return f"players:nba:{event_id}"


# Create a global cache service instance
cache_service = CacheService()
