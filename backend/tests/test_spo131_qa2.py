"""SPO-131 QA round 2 — page cap and cache TTL on the recorded fixtures.

BDL bodies are the recorded page or a copy of it.
"""

from __future__ import annotations

import asyncio
import copy

from tests import test_spo131_bdl_injuries as base
from tests.test_spo131_bdl_injuries import (
    INJURY_PAGE,
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    STANDINGS,
    nba_injuries,
    refresh_nba_injuries,
    team_id_to_code_from_standings,
)

_MAPPING = team_id_to_code_from_standings(STANDINGS)


# ---------------------------------------------------------------------------
# Page cap
# ---------------------------------------------------------------------------


class _EndlessRecordedPages:
    """Every call returns the recorded page with a fresh next_cursor."""

    def __init__(self) -> None:
        self.calls = 0

    async def list_player_injuries(self, *, cursor=None, per_page=100) -> dict:
        self.calls += 1
        page = copy.deepcopy(INJURY_PAGE)
        page["meta"]["next_cursor"] = INJURY_PAGE["meta"]["next_cursor"] + self.calls
        return page


def test_page_cap_does_not_replace_the_previous_snapshot():
    service, _fake = base._cache()
    previous = base._old_snapshot()
    asyncio.run(service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS))
    client = _EndlessRecordedPages()

    result = asyncio.run(refresh_nba_injuries(client, service, _MAPPING))

    assert client.calls == nba_injuries.NBA_INJURIES_MAX_PAGES
    assert result is None
    assert asyncio.run(service.get(NBA_INJURIES_CACHE_KEY)) == previous


# ---------------------------------------------------------------------------
# TTL 24h / stale 6h
# ---------------------------------------------------------------------------


def test_redis_ttl_is_a_day_and_staleness_is_six_hours():
    assert nba_injuries.NBA_INJURIES_CACHE_TTL_SECONDS == 24 * 60 * 60
    assert nba_injuries.NBA_INJURIES_STALE_AFTER_SECONDS == 6 * 60 * 60


def test_refresh_writes_with_the_24h_ttl():
    service, fake = base._cache()
    page = copy.deepcopy(INJURY_PAGE)
    page["meta"]["next_cursor"] = None
    asyncio.run(refresh_nba_injuries(base.PageClient([page]), service, _MAPPING))
    writes = [c for c in fake.set_calls if c["key"] == NBA_INJURIES_CACHE_KEY]
    assert writes[-1]["ex"] == 24 * 60 * 60


