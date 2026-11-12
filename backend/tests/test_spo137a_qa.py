"""SPO-137a QA: cache flush scopes, DELETE keys, and event-reads v1 miss.

daily_picks:nba:* matches the v2 key and the previous unversioned NBA
key, and it does not match WNBA or the pre-league keys. The date-scoped
NBA DELETE route removes v2 plus the three legacy keys, and leaves
WNBA. get_event_reads only reads the v2 key, so a v1 body is not
served.
"""

from __future__ import annotations

import asyncio
import fnmatch

import pytest

from app.services.cache import CacheService
from app.services.event_reads import (
    EVENT_READS_CACHE_TTL_SECONDS,
    event_reads_cache_key,
    get_event_reads,
)


def test_nba_glob_matches_v2_and_the_legacy_league_key_only() -> None:
    """The unversioned daily_picks:nba:{date}:tz{offset} key is in the NBA sweep.

    Pre-league keys (daily_picks:{date}:tz{offset} and daily_picks:{date})
    and WNBA keys are not.
    """
    keys = [
        "daily_picks:nba:v2:2026-11-10:tz480",
        "daily_picks:nba:2026-11-10:tz480",
        "daily_picks:wnba:2026-11-10:tz480",
        "daily_picks:2026-11-10:tz480",
        "daily_picks:2026-11-10",
    ]
    nba = [key for key in keys if fnmatch.fnmatch(key, "daily_picks:nba:*")]
    assert nba == [
        "daily_picks:nba:v2:2026-11-10:tz480",
        "daily_picks:nba:2026-11-10:tz480",
    ]
    wnba = [key for key in keys if fnmatch.fnmatch(key, "daily_picks:wnba:*")]
    assert wnba == ["daily_picks:wnba:2026-11-10:tz480"]


def test_nba_flush_drops_pre_league_keys_and_leaves_wnba() -> None:
    """clear_daily_picks_cache('nba') drops pre-league date keys and leaves WNBA."""
    from app.services.cache import CacheService

    class _Fake:
        def __init__(self) -> None:
            self.store = {
                "daily_picks:nba:v2:2026-11-10:tz480": "v2",
                "daily_picks:nba:2026-11-10:tz480": "legacy-nba",
                "daily_picks:wnba:2026-11-10:tz480": "wnba",
                "daily_picks:2026-11-10:tz480": "pre-league-tz",
                "daily_picks:2026-11-10": "pre-league",
            }

        async def scan_iter(self, match=None, count=100):
            for key in list(self.store):
                if match is None or fnmatch.fnmatch(key, match):
                    yield key

        async def delete(self, key):
            self.store.pop(key, None)

    service = CacheService()
    fake = _Fake()
    service._client = fake
    deleted = asyncio.run(service.clear_daily_picks_cache(league="nba"))
    assert deleted == 4
    assert fake.store == {
        "daily_picks:wnba:2026-11-10:tz480": "wnba",
    }


def test_nba_cache_route_deletes_v2_and_three_legacy_keys(
    monkeypatch,
) -> None:
    """DELETE /api/nba/daily-picks/cache drops exactly the four NBA keys."""
    from app.main import app
    from app.middleware.rate_limit import limiter
    import httpx

    deleted: list[str] = []

    async def fake_delete(key):
        deleted.append(key)
        return True

    monkeypatch.setattr("app.api.daily_picks.cache_service.delete", fake_delete)
    previous = limiter.enabled
    limiter.enabled = False
    try:
        transport = httpx.ASGITransport(app=app)

        async def _call():
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as http:
                return await http.request(
                    "DELETE",
                    "/api/nba/daily-picks/cache",
                    params={"date": "2026-11-10", "tz_offset": 480},
                )

        result = asyncio.run(_call())
    finally:
        limiter.enabled = previous

    assert result.status_code == 200
    assert deleted == [
        "daily_picks:nba:v2:2026-11-10:tz480",
        "daily_picks:nba:2026-11-10:tz480",
        "daily_picks:2026-11-10:tz480",
        "daily_picks:2026-11-10",
    ]


def test_event_reads_does_not_read_a_v1_body(monkeypatch) -> None:
    """A payload under nba:event-reads:v1 is not served."""
    from app.services.event_reads import BulkPropsStoreUnavailable
    import app.services.event_reads as event_reads

    seen: list[str] = []
    v1_key = "nba:event-reads:v1:evt-1:m=player_points"
    v1_body = {
        "event_id": "evt-1",
        "market": "player_points",
        "source": "snapshot",
        "reads": [],
    }

    class _Cache:
        async def get(self, key):
            seen.append(key)
            if key == v1_key:
                return v1_body
            return None

        async def set(self, key, value, ttl):
            raise AssertionError(f"unexpected set of {key}")

    class _Db:
        is_connected = False

    monkeypatch.setattr(event_reads, "cache_service", _Cache())
    monkeypatch.setattr(event_reads, "db_service", _Db())

    with pytest.raises(BulkPropsStoreUnavailable):
        asyncio.run(get_event_reads("evt-1", market="player_points"))

    assert seen == [event_reads_cache_key("evt-1", "player_points")]
    assert seen == ["nba:event-reads:v2:evt-1:m=player_points"]
    assert v1_key not in seen
    assert EVENT_READS_CACHE_TTL_SECONDS == 60
