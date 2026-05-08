"""
odds_gateway.py - Shared odds market snapshot gateway

Centralized management for expensive event odds requests, providing:
- Shared snapshot cache
- Stale-while-revalidate
- Single-flight deduplication
- Quota protection
- Recording and prewarming hot keys
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from app.services.cache import cache_service
from app.services.odds_provider import OddsAPIError, QuotaUsage
from app.services.odds_theoddsapi import odds_provider
from app.settings import settings

logger = logging.getLogger(__name__)

CacheState = Literal["fresh", "stale", "refreshed"]
SnapshotSource = Literal["snapshot_cache", "upstream"]
RequestPriority = Literal["interactive", "background"]

QUOTA_USAGE_KEY = "odds:quota_usage:v1"
HOT_KEYS_ZSET_KEY = "odds:hot_keys:v1"
HOT_KEY_LAST_SEEN_PREFIX = "odds:hot_seen:v1:"


@dataclass(frozen=True)
class MarketSnapshotResult:
    data: Dict[str, Any]
    fetched_at: datetime
    data_age_seconds: int
    cache_state: CacheState
    source: SnapshotSource
    usage: Optional[QuotaUsage] = None


class OddsMarketGateway:
    """
    The only entrance for expensive odds requests.

    All event odds-related requests should be processed through this gateway
    before performing any calculations or derivations in upper layers.
    """

    def __init__(
        self,
        provider=odds_provider,
        cache=cache_service,
        fresh_ttl_seconds: Optional[int] = None,
        stale_ttl_seconds: Optional[int] = None,
        lock_ttl_seconds: Optional[int] = None,
        wait_for_refresh_ms: Optional[int] = None,
        quota_protect_percent: Optional[int] = None,
        hot_keys_limit: Optional[int] = None,
    ):
        self.provider = provider
        self.cache = cache
        self.fresh_ttl_seconds = fresh_ttl_seconds or settings.cache_ttl_market_fresh
        self.stale_ttl_seconds = stale_ttl_seconds or settings.cache_ttl_market_stale
        self.lock_ttl_seconds = lock_ttl_seconds or settings.odds_refresh_lock_ttl
        self.wait_for_refresh_ms = wait_for_refresh_ms or settings.odds_wait_for_refresh_ms
        self.quota_protect_percent = quota_protect_percent or settings.odds_quota_protect_percent
        self.hot_keys_limit = hot_keys_limit or settings.odds_hot_keys_limit
        self._background_refreshes: set[str] = set()

    async def get_market_snapshot(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str = "american",
        bookmakers: Optional[list[str]] = None,
        priority: RequestPriority = "interactive",
        record_hot_key: bool = True,
    ) -> MarketSnapshotResult:
        normalized_markets = self._normalize_csv(markets)
        normalized_books = self._normalize_bookmakers(bookmakers)

        snapshot_key = self._build_snapshot_key(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        meta_key = self._build_snapshot_meta_key(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        lock_key = self._build_lock_key(snapshot_key)

        if priority == "interactive" and record_hot_key:
            await self._record_hot_key(
                sport=sport,
                event_id=event_id,
                regions=regions,
                markets=normalized_markets,
                odds_format=odds_format,
                bookmakers=normalized_books,
            )

        cached_result = await self._read_cached_snapshot(snapshot_key, meta_key)
        if cached_result:
            if cached_result.data_age_seconds <= self.fresh_ttl_seconds:
                return cached_result

            if cached_result.data_age_seconds <= self.stale_ttl_seconds:
                if priority != "background" or not await self.is_quota_protected():
                    self._trigger_background_refresh(
                        sport=sport,
                        event_id=event_id,
                        regions=regions,
                        markets=normalized_markets,
                        odds_format=odds_format,
                        bookmakers=normalized_books,
                    )

                return MarketSnapshotResult(
                    data=cached_result.data,
                    fetched_at=cached_result.fetched_at,
                    data_age_seconds=cached_result.data_age_seconds,
                    cache_state="stale",
                    source="snapshot_cache",
                    usage=cached_result.usage,
                )

        if priority == "background" and await self.is_quota_protected():
            raise OddsAPIError("Quota protection active for background refresh", 503)

        lock_acquired = await self.cache.acquire_lock(lock_key, self.lock_ttl_seconds)
        if not lock_acquired:
            return await self._wait_for_inflight_snapshot(
                snapshot_key=snapshot_key,
                meta_key=meta_key,
            )

        try:
            refreshed_cache = await self._read_cached_snapshot(snapshot_key, meta_key)
            if refreshed_cache and refreshed_cache.data_age_seconds <= self.fresh_ttl_seconds:
                return refreshed_cache

            return await self._fetch_and_store(
                snapshot_key=snapshot_key,
                meta_key=meta_key,
                sport=sport,
                event_id=event_id,
                regions=regions,
                markets=normalized_markets,
                odds_format=odds_format,
                bookmakers=normalized_books,
            )
        finally:
            await self.cache.release_lock(lock_key)

    async def record_quota_usage(self, usage: QuotaUsage) -> None:
        await self.cache.set(
            QUOTA_USAGE_KEY,
            {
                "remaining": usage.remaining,
                "used": usage.used,
                "last": usage.last,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
            ttl=24 * 60 * 60,
        )
        self._check_quota_alerts(usage)

    async def get_quota_usage(self) -> Optional[QuotaUsage]:
        cached_usage = await self.cache.get(QUOTA_USAGE_KEY)
        if not cached_usage:
            return None
        return QuotaUsage(
            remaining=cached_usage.get("remaining"),
            used=cached_usage.get("used"),
            last=cached_usage.get("last"),
        )

    async def is_quota_protected(self) -> bool:
        usage = await self.get_quota_usage()
        if not usage:
            return False

        remaining_ratio = usage.remaining_ratio
        if remaining_ratio is None:
            return False

        return remaining_ratio < (self.quota_protect_percent / 100)

    @staticmethod
    def _check_quota_alerts(usage: QuotaUsage) -> None:
        ratio = usage.remaining_ratio
        if ratio is None:
            return
        pct = round(ratio * 100, 1)
        if pct <= settings.odds_quota_critical_percent:
            logger.critical(
                "odds_api_quota_critical remaining=%s%% used=%s remaining=%s",
                pct, usage.used, usage.remaining,
            )
        elif pct <= settings.odds_quota_warn_percent:
            logger.warning(
                "odds_api_quota_warning remaining=%s%% used=%s remaining=%s",
                pct, usage.used, usage.remaining,
            )

    async def prewarm_hot_keys(self) -> int:
        if await self.is_quota_protected():
            return 0

        members = await self.cache.get_top_sorted_set_members(HOT_KEYS_ZSET_KEY, self.hot_keys_limit * 3)
        now = datetime.now(timezone.utc)
        warmed = 0

        for member in members:
            if warmed >= self.hot_keys_limit:
                break

            last_seen = await self.cache.get(f"{HOT_KEY_LAST_SEEN_PREFIX}{member}")
            if not last_seen:
                await self.cache.remove_sorted_set_member(HOT_KEYS_ZSET_KEY, member)
                continue

            seen_at_raw = last_seen.get("seen_at")
            if not seen_at_raw:
                await self.cache.remove_sorted_set_member(HOT_KEYS_ZSET_KEY, member)
                continue

            seen_at = datetime.fromisoformat(seen_at_raw)
            if seen_at.tzinfo is None:
                seen_at = seen_at.replace(tzinfo=timezone.utc)

            if now - seen_at > timedelta(minutes=5):
                await self.cache.remove_sorted_set_member(HOT_KEYS_ZSET_KEY, member)
                continue

            context = json.loads(member)
            normalized_markets = self._normalize_csv(context["markets"])
            normalized_books = self._normalize_bookmakers(context["bookmakers"])
            snapshot_key = self._build_snapshot_key(
                sport=context["sport"],
                event_id=context["event_id"],
                regions=context["regions"],
                markets=normalized_markets,
                odds_format=context["odds_format"],
                bookmakers=normalized_books,
            )
            meta_key = self._build_snapshot_meta_key(
                sport=context["sport"],
                event_id=context["event_id"],
                regions=context["regions"],
                markets=normalized_markets,
                odds_format=context["odds_format"],
                bookmakers=normalized_books,
            )
            cached_result = await self._read_cached_snapshot(snapshot_key, meta_key)
            if cached_result and cached_result.data_age_seconds <= self.fresh_ttl_seconds:
                continue

            try:
                await self.refresh_market_snapshot(
                    sport=context["sport"],
                    event_id=context["event_id"],
                    regions=context["regions"],
                    markets=normalized_markets,
                    odds_format=context["odds_format"],
                    bookmakers=normalized_books,
                    priority="background",
                )
                warmed += 1
            except OddsAPIError:
                continue

        return warmed

    async def refresh_market_snapshot(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str = "american",
        bookmakers: Optional[list[str]] = None,
        priority: RequestPriority = "background",
    ) -> MarketSnapshotResult:
        normalized_markets = self._normalize_csv(markets)
        normalized_books = self._normalize_bookmakers(bookmakers)
        snapshot_key = self._build_snapshot_key(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        meta_key = self._build_snapshot_meta_key(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        lock_key = self._build_lock_key(snapshot_key)

        if priority == "background" and await self.is_quota_protected():
            stale_result = await self._read_cached_snapshot(snapshot_key, meta_key)
            if stale_result and stale_result.data_age_seconds <= self.stale_ttl_seconds:
                return MarketSnapshotResult(
                    data=stale_result.data,
                    fetched_at=stale_result.fetched_at,
                    data_age_seconds=stale_result.data_age_seconds,
                    cache_state="stale",
                    source="snapshot_cache",
                    usage=stale_result.usage,
                )
            raise OddsAPIError("Quota protection active for background refresh", 503)

        lock_acquired = await self.cache.acquire_lock(lock_key, self.lock_ttl_seconds)
        if not lock_acquired:
            return await self._wait_for_inflight_snapshot(snapshot_key, meta_key)

        try:
            return await self._fetch_and_store(
                snapshot_key=snapshot_key,
                meta_key=meta_key,
                sport=sport,
                event_id=event_id,
                regions=regions,
                markets=normalized_markets,
                odds_format=odds_format,
                bookmakers=normalized_books,
            )
        finally:
            await self.cache.release_lock(lock_key)

    async def _fetch_and_store(
        self,
        snapshot_key: str,
        meta_key: str,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> MarketSnapshotResult:
        data, usage = await self.provider.get_event_odds_with_usage(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers,
        )

        if usage:
            await self.record_quota_usage(usage)

        fetched_at = datetime.now(timezone.utc)
        meta = {
            "fetched_at": fetched_at.isoformat(),
            "usage": {
                "remaining": usage.remaining if usage else None,
                "used": usage.used if usage else None,
                "last": usage.last if usage else None,
            },
        }

        await self.cache.set(snapshot_key, data, ttl=self.stale_ttl_seconds)
        await self.cache.set(meta_key, meta, ttl=self.stale_ttl_seconds)

        return MarketSnapshotResult(
            data=data,
            fetched_at=fetched_at,
            data_age_seconds=0,
            cache_state="fresh",
            source="upstream",
            usage=usage,
        )

    async def _wait_for_inflight_snapshot(
        self,
        snapshot_key: str,
        meta_key: str,
    ) -> MarketSnapshotResult:
        await asyncio.sleep(self.wait_for_refresh_ms / 1000)
        cached_result = await self._read_cached_snapshot(snapshot_key, meta_key)
        if cached_result:
            cache_state: CacheState = "refreshed"
            if cached_result.data_age_seconds > self.fresh_ttl_seconds:
                cache_state = "stale"

            return MarketSnapshotResult(
                data=cached_result.data,
                fetched_at=cached_result.fetched_at,
                data_age_seconds=cached_result.data_age_seconds,
                cache_state=cache_state,
                source="snapshot_cache",
                usage=cached_result.usage,
            )

        raise OddsAPIError("Odds refresh in progress; snapshot unavailable", 503)

    async def _read_cached_snapshot(
        self,
        snapshot_key: str,
        meta_key: str,
    ) -> Optional[MarketSnapshotResult]:
        cached_data = await self.cache.get(snapshot_key)
        cached_meta = await self.cache.get(meta_key)
        if not cached_data or not cached_meta:
            return None

        fetched_at_raw = cached_meta.get("fetched_at")
        if not fetched_at_raw:
            return None

        fetched_at = datetime.fromisoformat(fetched_at_raw)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        usage_meta = cached_meta.get("usage", {})
        usage = QuotaUsage(
            remaining=usage_meta.get("remaining"),
            used=usage_meta.get("used"),
            last=usage_meta.get("last"),
        )
        age_seconds = max(
            int((datetime.now(timezone.utc) - fetched_at).total_seconds()),
            0,
        )

        return MarketSnapshotResult(
            data=cached_data,
            fetched_at=fetched_at,
            data_age_seconds=age_seconds,
            cache_state="fresh",
            source="snapshot_cache",
            usage=usage,
        )

    def _trigger_background_refresh(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> None:
        refresh_key = self._build_snapshot_key(
            sport=sport,
            event_id=event_id,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers,
        )
        if refresh_key in self._background_refreshes:
            return

        self._background_refreshes.add(refresh_key)

        async def _do_refresh() -> None:
            try:
                await self.refresh_market_snapshot(
                    sport=sport,
                    event_id=event_id,
                    regions=regions,
                    markets=markets,
                    odds_format=odds_format,
                    bookmakers=bookmakers,
                    priority="background",
                )
            except OddsAPIError:
                pass
            finally:
                self._background_refreshes.discard(refresh_key)

        asyncio.create_task(_do_refresh())

    async def _record_hot_key(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> None:
        member = json.dumps(
            {
                "sport": sport,
                "event_id": event_id,
                "regions": regions,
                "markets": markets,
                "odds_format": odds_format,
                "bookmakers": bookmakers,
            },
            sort_keys=True,
        )
        await self.cache.increment_sorted_set(HOT_KEYS_ZSET_KEY, member, 1.0)
        await self.cache.set(
            f"{HOT_KEY_LAST_SEEN_PREFIX}{member}",
            {"seen_at": datetime.now(timezone.utc).isoformat()},
            ttl=5 * 60,
        )

    @staticmethod
    def _normalize_csv(value: str) -> str:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        return ",".join(sorted(dict.fromkeys(parts)))

    @staticmethod
    def _normalize_bookmakers(bookmakers: Optional[list[str]]) -> Optional[list[str]]:
        if not bookmakers:
            return None
        return sorted(dict.fromkeys(bookmakers))

    @staticmethod
    def _serialize_bookmakers(bookmakers: Optional[list[str]]) -> str:
        if not bookmakers:
            return "all"
        return ",".join(bookmakers)

    def _build_snapshot_key(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> str:
        return (
            "odds_snapshot:"
            f"{sport}:{event_id}:{regions}:{markets}:"
            f"{self._serialize_bookmakers(bookmakers)}:{odds_format}"
        )

    def _build_snapshot_meta_key(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> str:
        return (
            "odds_snapshot_meta:"
            f"{sport}:{event_id}:{regions}:{markets}:"
            f"{self._serialize_bookmakers(bookmakers)}:{odds_format}"
        )

    @staticmethod
    def _build_lock_key(snapshot_key: str) -> str:
        return f"odds_lock:{snapshot_key}"


odds_gateway = OddsMarketGateway()
