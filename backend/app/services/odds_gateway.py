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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from app.services.cache import cache_service
from app.services.odds_provider import OddsAPIError, ProviderEvent, QuotaUsage
from app.services.odds_theoddsapi import (
    league_for_sport_key,
    normalize_league,
    odds_provider,
    sport_key_for_league,
)
from app.settings import settings

logger = logging.getLogger(__name__)

CacheState = Literal["fresh", "stale", "refreshed"]
SnapshotSource = Literal["snapshot_cache", "upstream"]
RequestPriority = Literal["interactive", "background"]

QUOTA_USAGE_KEY = "odds:quota_usage:v1"
HOT_KEYS_ZSET_KEY = "odds:hot_keys:v1"
HOT_KEY_LAST_SEEN_PREFIX = "odds:hot_seen:v1:"


class _LeagueProviders(Mapping[str, Any]):
    """League → provider. The NBA entry reads ``settings.nba_odds_provider``.

    Lookup is live, so a test can change the setting without rebuilding
    the table. The only accepted NBA value in this change is
    ``theoddsapi``. WNBA always uses that same client. Any other league
    raises ``ValueError``.
    """

    def __getitem__(self, league: str) -> Any:
        key = normalize_league(league)
        if key == "nba":
            selected = (settings.nba_odds_provider or "theoddsapi").strip().lower()
            if selected != "theoddsapi":
                raise ValueError(
                    f"Unsupported nba_odds_provider: {settings.nba_odds_provider!r}. "
                    "Allowed: 'theoddsapi'"
                )
        return odds_provider

    def __iter__(self):
        yield "nba"
        yield "wnba"

    def __len__(self) -> int:
        return 2


PROVIDERS: Mapping[str, Any] = _LeagueProviders()


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
        provider=None,
        cache=cache_service,
        fresh_ttl_seconds: Optional[int] = None,
        stale_ttl_seconds: Optional[int] = None,
        lock_ttl_seconds: Optional[int] = None,
        wait_for_refresh_ms: Optional[int] = None,
        quota_protect_percent: Optional[int] = None,
        hot_keys_limit: Optional[int] = None,
    ):
        # None: pick the provider from PROVIDERS on each call.
        # A passed object is used for every league (gateway unit tests).
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
        sport: Optional[str] = None,
        event_id: str = "",
        regions: str = "us",
        markets: str = "",
        odds_format: str = "american",
        bookmakers: Optional[list[str]] = None,
        priority: RequestPriority = "interactive",
        record_hot_key: bool = True,
        *,
        league: Optional[str] = None,
    ) -> MarketSnapshotResult:
        """Shared snapshot for one event.

        Pass ``league`` (``nba`` or ``wnba``). ``sport`` is only for a
        hot-key member or test that still has an Odds API sport key.
        When both are set, ``league`` is the one that is used.
        """
        resolved_league = self._resolve_league(league, sport)
        normalized_markets = self._normalize_csv(markets)
        normalized_books = self._normalize_bookmakers(bookmakers)

        snapshot_key = self._build_snapshot_key(
            league=resolved_league,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        meta_key = self._build_snapshot_meta_key(
            league=resolved_league,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        lock_key = self._build_lock_key(snapshot_key)

        if priority == "interactive" and record_hot_key:
            await self._record_hot_key(
                league=resolved_league,
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
                        league=resolved_league,
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
                league=resolved_league,
                event_id=event_id,
                regions=regions,
                markets=normalized_markets,
                odds_format=odds_format,
                bookmakers=normalized_books,
            )
        finally:
            await self.cache.release_lock(lock_key)

    async def list_events(
        self,
        *,
        league: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[ProviderEvent]:
        """Events for ``league`` in the UTC window, from that league's provider."""
        provider = self._provider_for(league)
        return await provider.list_events(league, start_utc, end_utc)

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
            member_league = self._league_from_hot_key(context)
            if member_league is None:
                await self.cache.remove_sorted_set_member(HOT_KEYS_ZSET_KEY, member)
                continue
            normalized_markets = self._normalize_csv(context["markets"])
            normalized_books = self._normalize_bookmakers(context["bookmakers"])
            stored_provider = context.get("provider")
            provider_name = stored_provider if isinstance(stored_provider, str) and stored_provider else None
            snapshot_key = self._build_snapshot_key(
                league=member_league,
                event_id=context["event_id"],
                regions=context["regions"],
                markets=normalized_markets,
                odds_format=context["odds_format"],
                bookmakers=normalized_books,
                provider_name=provider_name,
            )
            meta_key = self._build_snapshot_meta_key(
                league=member_league,
                event_id=context["event_id"],
                regions=context["regions"],
                markets=normalized_markets,
                odds_format=context["odds_format"],
                bookmakers=normalized_books,
                provider_name=provider_name,
            )
            cached_result = await self._read_cached_snapshot(snapshot_key, meta_key)
            if cached_result and cached_result.data_age_seconds <= self.fresh_ttl_seconds:
                continue

            try:
                await self.refresh_market_snapshot(
                    league=member_league,
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
        sport: Optional[str] = None,
        event_id: str = "",
        regions: str = "us",
        markets: str = "",
        odds_format: str = "american",
        bookmakers: Optional[list[str]] = None,
        priority: RequestPriority = "background",
        *,
        league: Optional[str] = None,
    ) -> MarketSnapshotResult:
        resolved_league = self._resolve_league(league, sport)
        normalized_markets = self._normalize_csv(markets)
        normalized_books = self._normalize_bookmakers(bookmakers)
        snapshot_key = self._build_snapshot_key(
            league=resolved_league,
            event_id=event_id,
            regions=regions,
            markets=normalized_markets,
            odds_format=odds_format,
            bookmakers=normalized_books,
        )
        meta_key = self._build_snapshot_meta_key(
            league=resolved_league,
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
                league=resolved_league,
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
        league: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> MarketSnapshotResult:
        provider = self._provider_for(league)
        # Sport key is chosen here, inside the Odds API map, so the
        # request path is /v4/sports/{sport_key}/events/{id}/odds with
        # the same query the gateway sent before league= existed.
        data, usage = await provider.get_event_odds_with_usage(
            sport=sport_key_for_league(league),
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
        league: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> None:
        refresh_key = self._build_snapshot_key(
            league=league,
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
                    league=league,
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
        league: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str,
        bookmakers: Optional[list[str]],
    ) -> None:
        member = json.dumps(
            {
                "league": league,
                "provider": self._provider_name(league),
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
        sport: Optional[str] = None,
        event_id: str = "",
        regions: str = "",
        markets: str = "",
        odds_format: str = "",
        bookmakers: Optional[list[str]] = None,
        *,
        league: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> str:
        resolved = self._resolve_league(league, sport)
        name = provider_name or self._provider_name(resolved)
        return (
            "odds_snapshot:v2:"
            f"{name}:{resolved}:{event_id}:{regions}:{markets}:"
            f"{self._serialize_bookmakers(bookmakers)}:{odds_format}"
        )

    def _build_snapshot_meta_key(
        self,
        sport: Optional[str] = None,
        event_id: str = "",
        regions: str = "",
        markets: str = "",
        odds_format: str = "",
        bookmakers: Optional[list[str]] = None,
        *,
        league: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> str:
        resolved = self._resolve_league(league, sport)
        name = provider_name or self._provider_name(resolved)
        return (
            "odds_snapshot_meta:v2:"
            f"{name}:{resolved}:{event_id}:{regions}:{markets}:"
            f"{self._serialize_bookmakers(bookmakers)}:{odds_format}"
        )

    def _provider_for(self, league: str) -> Any:
        """Provider for ``league``. An injected provider wins over the table."""
        key = normalize_league(league)
        if self.provider is not None:
            return self.provider
        return PROVIDERS[key]

    def _provider_name(self, league: str) -> str:
        provider = self._provider_for(league)
        name = getattr(provider, "name", None)
        if isinstance(name, str) and name:
            return name
        return "theoddsapi"

    @staticmethod
    def _resolve_league(league: Optional[str], sport: Optional[str]) -> str:
        """League from ``league``, or from a legacy Odds API sport key."""
        if league is not None and str(league).strip() != "":
            return normalize_league(str(league))
        if sport:
            return league_for_sport_key(sport)
        raise ValueError("league is required")

    @staticmethod
    def _league_from_hot_key(context: dict) -> Optional[str]:
        """League stored on a hot-key member, including members written earlier.

        Members from before this change have ``sport`` and no ``league``.
        Their last-seen TTL is 5 minutes, so the old shape disappears on
        its own. An unknown sport is dropped.
        """
        raw_league = context.get("league")
        if isinstance(raw_league, str) and raw_league.strip():
            try:
                return normalize_league(raw_league)
            except ValueError:
                return None
        sport = context.get("sport")
        if not isinstance(sport, str) or not sport:
            return None
        try:
            return league_for_sport_key(sport)
        except ValueError:
            return None

    @staticmethod
    def _build_lock_key(snapshot_key: str) -> str:
        return f"odds_lock:{snapshot_key}"


odds_gateway = OddsMarketGateway()
