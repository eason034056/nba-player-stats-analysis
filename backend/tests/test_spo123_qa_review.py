"""SPO-123 QA: edge cases for GET /api/nba/events/{event_id}.

Odds API bodies come from ``odds_api_events__basketball_nba.json``
through ``load_odds_fixture``. The daily-picks and lineup payloads are
this app's own Redis shapes, not an external API.
"""

from __future__ import annotations

import copy
from datetime import datetime as real_datetime, timezone

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.middleware.rate_limit import limiter
from app.services.bulk_props import event_id_is_well_formed
from app.services.cache import CacheService
from app.services.daily_analysis import daily_picks_cache_key
from app.services.odds_provider import OddsAPIError
from tests.fixtures.odds_api import load_odds_fixture

_RECORDED = load_odds_fixture("odds_api_events__basketball_nba.json")
_BY_TEAMS = {(e["away_team"], e["home_team"]): e for e in _RECORDED}
# 2026-11-11T01:10:00Z: 20:10 ET / 19:10 CT on 2026-11-10.
_BOS_PHI = _BY_TEAMS[("Boston Celtics", "Philadelphia 76ers")]
# 2026-11-10T00:10:00Z: 19:10 ET on 2026-11-09.
_LAL_ATL = _BY_TEAMS[("Los Angeles Lakers", "Atlanta Hawks")]


class _Calls:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.gateway = 0
        self.event_odds = 0
        self.cache_gets: list[str] = []


def _install(monkeypatch, calls: _Calls, cache: dict, *, events_exc=None, slate=None):
    async def fake_events(**kwargs):
        calls.events.append(kwargs)
        if events_exc is not None:
            raise events_exc
        return copy.deepcopy(_RECORDED)

    async def fake_gateway(*args, **kwargs):
        calls.gateway += 1
        return {"bookmakers": []}

    async def fake_event_odds(*args, **kwargs):
        calls.event_odds += 1
        return {}

    async def fake_get(key):
        calls.cache_gets.append(key)
        return copy.deepcopy(cache.get(key))

    async def fake_set(key, value, ttl):
        cache[key] = value
        return True

    async def fake_peek(date):
        return copy.deepcopy(slate or {})

    monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
    monkeypatch.setattr("app.api.nba.odds_provider.get_event_odds", fake_event_odds)
    monkeypatch.setattr("app.api.nba.odds_provider.get_event_odds_with_usage", fake_event_odds)
    monkeypatch.setattr("app.api.nba.odds_gateway.get_market_snapshot", fake_gateway)
    monkeypatch.setattr("app.api.nba.cache_service.get", fake_get)
    monkeypatch.setattr("app.api.nba.cache_service.set", fake_set)
    monkeypatch.setattr("app.api.nba.lineup_service.peek_lineups", fake_peek)


def _freeze_utc_now(monkeypatch, frozen: real_datetime) -> None:
    class _Frozen(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr("app.api.nba.datetime", _Frozen)


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def test_every_recorded_odds_api_id_is_well_formed():
    assert _RECORDED
    for event in _RECORDED:
        assert event_id_is_well_formed(event["id"]), event["id"]
    assert not event_id_is_well_formed("")
    assert not event_id_is_well_formed("-" + _BOS_PHI["id"])
    assert not event_id_is_well_formed("a" * 129)
    assert event_id_is_well_formed("a" * 128)


# --- Local date across UTC midnight -------------------------------------


@pytest.mark.asyncio
async def test_late_us_game_is_found_on_its_local_date(client, monkeypatch):
    """BOS@PHI tips 20:10 ET on 11-10, which is 11-11 in UTC."""
    calls = _Calls()
    _install(monkeypatch, calls, {})
    for tz in (-300, -360):
        response = await client.get(
            f"/api/nba/events/{_BOS_PHI['id']}",
            params={"date": "2026-11-10", "regions": "us", "tz_offset": tz},
        )
        assert response.status_code == 200, tz
        body = response.json()
        assert body["event_id"] == _BOS_PHI["id"]
        assert body["commence_time_et"] == "2026-11-10T20:10:00-05:00"


@pytest.mark.asyncio
async def test_late_us_game_is_404_on_the_utc_date_with_us_offset(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    response = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}",
        params={"date": "2026-11-11", "regions": "us", "tz_offset": -300},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Event not found"


@pytest.mark.asyncio
async def test_previous_local_evening_game_is_not_on_next_local_date(client, monkeypatch):
    """LAL@ATL is 19:10 ET on 11-09; with an ET offset it is not on 11-10."""
    calls = _Calls()
    _install(monkeypatch, calls, {})
    on_10 = await client.get(
        f"/api/nba/events/{_LAL_ATL['id']}",
        params={"date": "2026-11-10", "tz_offset": -300},
    )
    on_09 = await client.get(
        f"/api/nba/events/{_LAL_ATL['id']}",
        params={"date": "2026-11-09", "tz_offset": -300},
    )
    assert on_10.status_code == 404
    assert on_09.status_code == 200


@pytest.mark.asyncio
async def test_omitted_date_is_the_callers_local_day(client, monkeypatch):
    """7:30 PM CT on 11-10 is 01:30Z on 11-11.

    With date omitted and tz_offset=-360 the detail route searches the
    caller's local date, 2026-11-10, once. BOS@PHI tips that evening.
    It does not search 2026-11-11 and it does not call the provider again.
    """
    _freeze_utc_now(monkeypatch, real_datetime(2026, 11, 11, 1, 30, tzinfo=timezone.utc))
    calls = _Calls()
    cache: dict = {}
    _install(monkeypatch, calls, cache)

    response = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}", params={"tz_offset": -360}
    )

    local_key = f"{CacheService.build_events_key('2026-11-10', 'us')}:tz-360"
    utc_key = f"{CacheService.build_events_key('2026-11-11', 'us')}:tz-360"
    assert response.status_code == 200
    assert response.json()["event_id"] == _BOS_PHI["id"]
    assert local_key in cache
    assert utc_key not in cache
    assert len(calls.events) == 1
    assert calls.gateway == 0 and calls.event_odds == 0

    with_date = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}",
        params={"date": "2026-11-10", "tz_offset": -360},
    )
    assert with_date.status_code == 200
    assert len(calls.events) == 1


# --- Cache key parity with the list route --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params, key_suffix",
    [
        ({"date": "2026-11-10", "regions": "us", "tz_offset": -360}, "2026-11-10|us|-360"),
        ({"date": "2026-11-10", "tz_offset": 480}, "2026-11-10|us|480"),
        ({"date": "2026-11-10"}, "2026-11-10|us|480"),
        ({"date": "2026-11-10", "regions": "uk", "tz_offset": 0}, "2026-11-10|uk|0"),
    ],
)
async def test_list_then_detail_share_one_cache_key(client, monkeypatch, params, key_suffix):
    date, regions, tz = key_suffix.split("|")
    calls = _Calls()
    cache: dict = {}
    _install(monkeypatch, calls, cache)

    listing = await client.get("/api/nba/events", params=params)
    assert listing.status_code == 200
    assert listing.json()["events"]
    target = listing.json()["events"][0]

    detail = await client.get(f"/api/nba/events/{target['event_id']}", params=params)

    assert detail.status_code == 200
    assert len(calls.events) == 1
    expected_key = f"{CacheService.build_events_key(date, regions)}:tz{tz}"
    events_keys = [k for k in cache if k.startswith("events:")]
    assert events_keys == [expected_key]
    assert calls.event_odds == 0 and calls.gateway == 0


@pytest.mark.asyncio
async def test_unknown_id_on_cache_miss_calls_the_list_once_then_uses_cache(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    params = {"date": "2026-11-10", "tz_offset": -300}
    unknown = "0" * 32
    for _ in range(3):
        response = await client.get(f"/api/nba/events/{unknown}", params=params)
        assert response.status_code == 404
    assert len(calls.events) == 1


@pytest.mark.asyncio
async def test_empty_day_list_is_cached_and_404s(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    params = {"date": "2026-07-01", "tz_offset": -300}
    for _ in range(2):
        response = await client.get(f"/api/nba/events/{_BOS_PHI['id']}", params=params)
        assert response.status_code == 404
    assert len(calls.events) == 1


# --- Same body as the list item ------------------------------------------


@pytest.mark.asyncio
async def test_detail_body_equals_the_list_item_with_top_read_and_lineups(client, monkeypatch):
    date, tz = "2026-11-10", -300
    calls = _Calls()
    cache = {
        daily_picks_cache_key("nba", date, tz): {
            "picks": [
                {
                    "event_id": _BOS_PHI["id"],
                    "player_name": "Jayson Tatum",
                    "metric": "points",
                    "direction": "over",
                    "threshold": 26.5,
                    "probability": 0.71,
                }
            ]
        }
    }
    slate = {
        "BOS": {"starters": ["Jayson Tatum"], "source_snapshots": {"rotowire": {"status": "confirmed"}}},
        "PHI": {"starters": ["Tyrese Maxey"], "source_snapshots": {"rotogrinders": {"status": "projected"}}},
    }
    _install(monkeypatch, calls, cache, slate=slate)
    params = {"date": date, "tz_offset": tz}

    listing = await client.get("/api/nba/events", params=params)
    detail = await client.get(f"/api/nba/events/{_BOS_PHI['id']}", params=params)

    assert detail.status_code == 200
    item = next(e for e in listing.json()["events"] if e["event_id"] == _BOS_PHI["id"])
    assert detail.json() == item
    assert item["top_read"]["player"] == "Jayson Tatum"
    assert item["top_read"]["market"] == "player_points"
    assert item["lineup_status"] == {"home": "projected", "away": "confirmed"}


# --- Upstream failure is not a 404 ---------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 503])
async def test_odds_api_error_passes_through_not_404(client, monkeypatch, status):
    calls = _Calls()
    _install(monkeypatch, calls, {}, events_exc=OddsAPIError("upstream failed", status_code=status))
    response = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}",
        params={"date": "2026-11-10", "tz_offset": -300},
    )
    assert response.status_code == status
    assert response.json()["detail"] != "Event not found"


@pytest.mark.asyncio
async def test_unexpected_provider_error_is_500_and_nothing_is_cached(client, monkeypatch):
    calls = _Calls()
    cache: dict = {}
    _install(monkeypatch, calls, cache, events_exc=RuntimeError("socket closed"))
    response = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}",
        params={"date": "2026-11-10", "tz_offset": -300},
    )
    assert response.status_code == 500
    assert not [k for k in cache if k.startswith("events:")]


# --- Input validation -----------------------------------------------------


@pytest.mark.asyncio
async def test_impossible_calendar_date_is_422(client, monkeypatch):
    """2026-13-45 matches the digit pattern and is not a real day."""
    calls = _Calls()
    _install(monkeypatch, calls, {})
    response = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}", params={"date": "2026-13-45"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid date"
    assert calls.events == [] and calls.cache_gets == []

    listing = await client.get("/api/nba/events", params={"date": "2026-13-45"})
    assert listing.status_code == 422
    assert listing.json()["detail"] == "Invalid date"
    assert calls.events == [] and calls.cache_gets == []


@pytest.mark.asyncio
async def test_malformed_date_is_422_before_any_read(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    response = await client.get(
        f"/api/nba/events/{_BOS_PHI['id']}", params={"date": "11/10/2026"}
    )
    assert response.status_code == 422
    assert calls.events == [] and calls.cache_gets == []


@pytest.mark.asyncio
async def test_malformed_id_checked_before_date_cache_or_provider(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    response = await client.get("/api/nba/events/-leading-dash", params={"date": "2026-11-10"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Malformed event_id"
    assert calls.events == [] and calls.cache_gets == []


# --- Routing / league scope -------------------------------------------------


def test_new_route_is_nba_only_and_does_not_shadow_props():
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/api/nba/events/{event_id}" in paths
    assert "/api/wnba/events/{event_id}" not in paths
    assert "/api/nba/events/{event_id}/props" in paths


@pytest.mark.asyncio
async def test_wnba_events_list_still_served(client, monkeypatch):
    async def fake_events(**kwargs):
        return []

    async def fake_get(key):
        return None

    async def fake_set(key, value, ttl):
        return True

    monkeypatch.setattr("app.api.wnba.odds_provider.get_events", fake_events)
    monkeypatch.setattr("app.api.wnba.cache_service.get", fake_get)
    monkeypatch.setattr("app.api.wnba.cache_service.set", fake_set)
    response = await client.get("/api/wnba/events", params={"date": "2026-11-10", "tz_offset": -300})
    assert response.status_code == 200
    assert response.json()["events"] == []
