"""One-time Redis flush after NBA odds moved to BALLDONTLIE.

The first process to start after deploy deletes the old event lists,
daily picks, and snapshot bodies. A marker key set with SET NX makes a
restart and a second replica leave those keys alone. A Redis error is
logged and does not leave this function.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# SET NX target. A later start sees this key and does not scan again.
SPO130I_FLUSH_MARKER = "migrations:spo130i:odds_flush_done"

# SCAN patterns. Never KEYS. The marker itself matches none of these.
SPO130I_FLUSH_PATTERNS: tuple[str, ...] = (
    "daily_picks:nba*",
    "odds_snapshot:*",
    "events:nba:*",
    "*:wnba:*",
)

# Leftover monthly-quota object. Nothing writes it after this cut.
# Leaving it would make a background refresh think the budget is gone.
SPO130I_FLUSH_EXACT_KEYS: tuple[str, ...] = (
    "odds:quota_usage:v1",
)


async def flush_retired_odds_cache(cache: Any | None = None) -> int:
    """Delete retired odds keys once. Return how many keys were deleted.

    ``cache`` is the process cache when omitted. The first caller that
    wins SET NX scans and deletes. A caller that loses the race returns
    0 and deletes nothing. An error is logged and returns 0. This never
    raises.

    Args:
        cache: Object with ``get_client()``. None uses the process cache.

    Returns:
        Count of keys deleted, or 0 when the marker was already set or
        the scan failed.
    """
    if cache is None:
        from app.services.cache import cache_service

        cache = cache_service
    try:
        client = await cache.get_client()
        won = await client.set(SPO130I_FLUSH_MARKER, "1", nx=True)
        if not won:
            logger.info("spo130i odds cache flush already done")
            return 0
        deleted = 0
        for pattern in SPO130I_FLUSH_PATTERNS:
            async for key in client.scan_iter(match=pattern, count=100):
                if key == SPO130I_FLUSH_MARKER:
                    continue
                await client.delete(key)
                deleted += 1
        for key in SPO130I_FLUSH_EXACT_KEYS:
            if await client.delete(key):
                deleted += 1
        logger.info("spo130i odds cache flush deleted %s keys", deleted)
        return deleted
    except Exception as exc:
        # Warning, not error: a flush miss must not look like startup failed.
        logger.warning(
            "spo130i odds cache flush failed (%s)",
            type(exc).__name__,
        )
        return 0
