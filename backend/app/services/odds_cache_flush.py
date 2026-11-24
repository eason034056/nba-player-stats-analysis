"""One-time Redis flush after NBA odds moved to BALLDONTLIE.

The first process to finish the scan deletes the old event lists, daily
picks, and snapshot bodies. A short lock stops a second replica from
running the same scan. The permanent marker is written only after every
delete succeeds, so a failed scan is retried on the next start. A Redis
error is logged and does not leave this function.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Written only after every delete succeeds. A later start sees this and
# does not scan again. It has no TTL.
SPO130I_FLUSH_MARKER = "migrations:spo130i:odds_flush_done"

# Held while a scan is in progress. SET NX EX so a crashed holder expires
# and the next start can retry. Two replicas do not scan together.
SPO130I_FLUSH_LOCK = "migrations:spo130i:odds_flush_lock"
SPO130I_FLUSH_LOCK_SECONDS = 60

# SCAN patterns. Never KEYS. The marker and the lock match none of these.
# ``*:wnba:*`` also matches leftover ``lineups:wnba:*`` and
# ``daily_picks:wnba:*``.
SPO130I_FLUSH_PATTERNS: tuple[str, ...] = (
    "daily_picks:nba*",
    "odds_snapshot:*",
    "odds_snapshot_meta:v2:*",
    "events:nba:*",
    "*:wnba:*",
)

# Leftover monthly-quota object. Nothing reads or writes it. The flush
# still deletes it so a stale copy does not sit in Redis.
SPO130I_FLUSH_EXACT_KEYS: tuple[str, ...] = (
    "odds:quota_usage:v1",
)


async def flush_retired_odds_cache(cache: Any | None = None) -> int:
    """Delete retired odds keys once. Return how many keys were deleted.

    ``cache`` is the process cache when omitted. A caller that finds the
    done marker, or that loses the in-progress lock, returns 0 and
    deletes nothing. The done marker is set only after every delete
    succeeds. An error releases the lock, leaves the marker unset, and
    returns 0. This never raises.

    Args:
        cache: Object with ``get_client()``. None uses the process cache.

    Returns:
        Count of keys deleted, or 0 when the flush was already done,
        another replica holds the lock, or the scan failed.
    """
    if cache is None:
        from app.services.cache import cache_service

        cache = cache_service
    client: Any = None
    holding_lock = False
    try:
        client = await cache.get_client()
        if await client.get(SPO130I_FLUSH_MARKER):
            logger.info("spo130i odds cache flush already done")
            return 0
        won = await client.set(
            SPO130I_FLUSH_LOCK,
            "1",
            nx=True,
            ex=SPO130I_FLUSH_LOCK_SECONDS,
        )
        if not won:
            logger.info("spo130i odds cache flush already running")
            return 0
        holding_lock = True
        if await client.get(SPO130I_FLUSH_MARKER):
            return 0
        deleted = 0
        for pattern in SPO130I_FLUSH_PATTERNS:
            async for key in client.scan_iter(match=pattern, count=100):
                if key in {SPO130I_FLUSH_MARKER, SPO130I_FLUSH_LOCK}:
                    continue
                await client.delete(key)
                deleted += 1
        for key in SPO130I_FLUSH_EXACT_KEYS:
            if await client.delete(key):
                deleted += 1
        await client.set(SPO130I_FLUSH_MARKER, "1")
        logger.info("spo130i odds cache flush deleted %s keys", deleted)
        return deleted
    except Exception as exc:
        # Warning, not error: a flush miss must not look like startup failed.
        logger.warning(
            "spo130i odds cache flush failed (%s)",
            type(exc).__name__,
        )
        return 0
    finally:
        if holding_lock and client is not None:
            try:
                await client.delete(SPO130I_FLUSH_LOCK)
            except Exception as exc:
                logger.warning(
                    "spo130i odds cache flush lock release failed (%s)",
                    type(exc).__name__,
                )
