"""
cache.py - Redis Cache Service

Encapsulates Redis operations and provides caching capabilities.
Caching reduces the number of external Odds API calls, lowering costs and improving response speed.
"""

import json
import logging
import redis.asyncio as redis
from typing import Optional, Any
from app.settings import settings

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        *,
        socket_timeout: Optional[float] = None,
        socket_connect_timeout: Optional[float] = None,
    ):
        """
        Initialize the cache service.

        Note: The actual Redis connection is established lazily
        and will only be set on the first usage.

        Args:
            socket_timeout: Seconds a Redis command may block. None
                leaves the client default. The injury reader sets this.
            socket_connect_timeout: Seconds the TCP connect may block.
        """
        self._client: Optional[redis.Redis] = None
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout

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
            kwargs: dict[str, Any] = {"decode_responses": True}
            if self._socket_timeout is not None:
                kwargs["socket_timeout"] = self._socket_timeout
            if self._socket_connect_timeout is not None:
                kwargs["socket_connect_timeout"] = self._socket_connect_timeout
            self._client = redis.from_url(settings.redis_url, **kwargs)
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

    async def clear_daily_picks_cache(self, league: str | None = None) -> int:
        """
        Clear daily picks cache, optionally scoped to a single league.

        When the CSV data is updated, or a lineup refresh lands, clear
        the picks cache so the next request parses the latest inputs.

        SPO-35 added league scoping. WNBA keys stay
        ``daily_picks:wnba:{date}:tz{offset}``. NBA keys are
        ``daily_picks:nba:v2:{date}:tz{offset}``. The NBA sweep is
        ``daily_picks:nba:*``, so v2 and the previous unversioned NBA
        keys both match, and WNBA keys do not.

        Before SPO-35, NBA daily picks lived under
        ``daily_picks:{date}:tz{offset}`` and ``daily_picks:{date}``
        (no league segment). The date-scoped NBA delete route already
        removes those keys for one date. Callers of this method did
        not. An NBA clear therefore also scans ``daily_picks:[0-9]*``.
        The segment after ``daily_picks:`` must start with a digit, so
        ``daily_picks:nba:*`` and ``daily_picks:wnba:*`` do not match
        that second pattern. ``delete_pattern`` forwards the pattern
        as Redis ``SCAN MATCH``. The test fake matches it with
        ``fnmatch``, which honors ``[0-9]``.

        A WNBA clear stays ``daily_picks:wnba:*`` only. ``league=None``
        stays ``daily_picks:*``, which still deletes every league and
        every pre-league key.

        Args:
            league: If provided (``"nba"`` / ``"wnba"``), restrict the
                    sweep to that league. ``"nba"`` also drops the
                    pre-league date keys. If ``None``, clear every
                    ``daily_picks:*`` key.

        Returns:
            int: number of keys deleted
        """
        if league is None:
            return await self.delete_pattern("daily_picks:*")
        normalized = league.lower()
        deleted = await self.delete_pattern(f"daily_picks:{normalized}:*")
        if normalized == "nba":
            # Digit after the prefix is a date, not a league name.
            deleted += await self.delete_pattern("daily_picks:[0-9]*")
        return deleted

    async def close(self):
        """
        Close the Redis connection.

        Call this to free resources when the application ends. TestClient
        can close the event loop before this runs, after a scheduler job
        has already opened Redis. The socket is gone in that case.
        """
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            await client.close()
        except RuntimeError as exc:
            if "Event loop is closed" not in str(exc):
                raise
            logger.warning("Redis close skipped; the event loop is already closed")

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
    def build_events_key(date: str, regions: str, league: str = "nba") -> str:
        """
        Construct the cache key for the event list.

        Format: events:{league}:{date}:{regions}

        The league segment isolates Redis namespaces between NBA / WNBA / future
        leagues so the same date+region request for two leagues doesn't collide.
        Default ``league="nba"`` preserves the historical NBA-only key shape —
        every existing NBA caller continues to produce ``events:nba:...`` keys
        with no source-code change.

        Args:
            date: date string (YYYY-MM-DD)
            regions: region code (e.g., "us")
            league: league segment, default "nba". Pass "wnba" for WNBA.

        Returns:
            cache key

        Example:
            >>> CacheService.build_events_key("2026-01-14", "us")
            "events:nba:2026-01-14:us"
            >>> CacheService.build_events_key("2026-05-13", "us", league="wnba")
            "events:wnba:2026-05-13:us"
        """
        return f"events:{league}:{date}:{regions}"

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
