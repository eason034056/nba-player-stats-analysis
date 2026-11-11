"""SPO-123: one NBA event from the events list.

The recorded body is ``odds_api_events__basketball_nba.json``
(GET /v4/sports/basketball_nba/events). Tests copy that list. They do
not type an Odds API event by hand, and they do not call the live API.
"""

from __future__ import annotations

import copy
from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.middleware.rate_limit import limiter
from app.models.schemas import NBAEvent
from app.services.bulk_props import event_id_is_well_formed
from app.services.cache import CacheService
from app.settings import settings
from tests.fixtures.odds_api import load_odds_fixture

_DATE = "2026-11-10"
_REGIONS = "us"
_TZ = 0
_QUERY = {"date": _DATE, "regions": _REGIONS, "tz_offset": _TZ}

_RECORDED = load_odds_fixture("odds_api_events__basketball_nba.json")
_ON_DATE = [
    event
    for event in _RECORDED
    if str(event.get("commence_time", "")).startswith(_DATE)
]
_FOUND = _ON_DATE[0]
_FOUND_ID = _FOUND["id"]
# Recorded, but its tip is not on _DATE, so the list filter drops it.
_OTHER_DAY = next(
    event for event in _RECORDED if not str(event.get("commence_time", "")).startswith(_DATE)
)


def _events_cache_key() -> str:
    return f"{CacheService.build_events_key(_DATE, _REGIONS)}:tz{_TZ}"


def _cached_list() -> dict:
    """The JSON ``get_events`` stores: list fields, values from the recording."""
    return {
        "date": _DATE,
        "events": [
            {
                "event_id": event["id"],
                "sport_key": event["sport_key"],
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "commence_time": event["commence_time"],
            }
            for event in _ON_DATE
        ],
    }


class _Calls:
    def __init__(self) -> None:
        self.events = 0
        self.gateway = 0
        self.event_odds = 0


def _install(monkeypatch, calls: _Calls, cache: dict) -> None:
    async def fake_events(**kwargs):
        calls.events += 1
        return copy.deepcopy(_RECORDED)

    async def fake_gateway(*args, **kwargs):
        calls.gateway += 1
        return {"bookmakers": []}

    async def fake_event_odds(*args, **kwargs):
        calls.event_odds += 1
        return {}

    async def fake_get(key):
        return cache.get(key)

    async def fake_set(key, value, ttl):
        cache[key] = value
        return True

    async def fake_peek(date):
        return {}

    monkeypatch.setattr("app.api.nba.odds_provider.get_events", fake_events)
    monkeypatch.setattr("app.api.nba.odds_provider.get_event_odds", fake_event_odds)
    monkeypatch.setattr(
        "app.api.nba.odds_provider.get_event_odds_with_usage", fake_event_odds
    )
    monkeypatch.setattr("app.api.nba.odds_gateway.get_market_snapshot", fake_gateway)
    monkeypatch.setattr("app.api.nba.cache_service.get", fake_get)
    monkeypatch.setattr("app.api.nba.cache_service.set", fake_set)
    monkeypatch.setattr("app.api.nba.lineup_service.peek_lineups", fake_peek)


def _assert_no_odds_gateway(calls: _Calls) -> None:
    assert calls.gateway == 0
    assert calls.event_odds == 0


def _assert_found_body(body: dict, raw: dict) -> None:
    assert set(body) == set(NBAEvent.model_fields)
    assert body["event_id"] == raw["id"]
    assert body["sport_key"] == raw["sport_key"]
    assert body["home_team"] == raw["home_team"]
    assert body["away_team"] == raw["away_team"]
    assert datetime.fromisoformat(body["commence_time"].replace("Z", "+00:00")) == (
        datetime.fromisoformat(raw["commence_time"].replace("Z", "+00:00"))
    )
    assert body["commence_time_et"] == "2026-11-09T19:10:00-05:00"
    assert body["display_tz"] == "ET"
    assert body["lineup_status"] == {"home": None, "away": None}
    assert body["top_read"] is None


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


def test_event_detail_uses_the_props_rate_limit():
    """Same slowapi limit as GET /api/nba/events/{event_id}/props."""
    detail = limiter._route_limits["app.api.nba.get_event"]
    props = limiter._route_limits["app.api.nba.get_event_props"]
    assert [str(item.limit) for item in detail] == [str(item.limit) for item in props]
    assert settings.rate_limit_props == "20/minute"
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/nba/events/{event_id}" in paths
    assert "/api/nba/events/{event_id}/props" in paths


@pytest.mark.asyncio
async def test_found_event_comes_from_the_recorded_list(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    assert event_id_is_well_formed(_FOUND_ID)

    response = await client.get(f"/api/nba/events/{_FOUND_ID}", params=_QUERY)

    assert response.status_code == 200
    _assert_found_body(response.json(), _FOUND)
    assert calls.events == 1
    _assert_no_odds_gateway(calls)


@pytest.mark.asyncio
async def test_unknown_event_id_is_404(client, monkeypatch):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    event_id = _OTHER_DAY["id"]
    assert event_id != _FOUND_ID
    assert event_id_is_well_formed(event_id)

    response = await client.get(f"/api/nba/events/{event_id}", params=_QUERY)

    assert response.status_code == 404
    assert response.json()["detail"] == "Event not found"
    assert calls.events == 1
    _assert_no_odds_gateway(calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("event_id", ["!!!", "bad id", "a.b", "a..b"])
async def test_malformed_event_id_is_404(client, monkeypatch, event_id):
    calls = _Calls()
    _install(monkeypatch, calls, {})
    assert not event_id_is_well_formed(event_id)

    response = await client.get(f"/api/nba/events/{event_id}", params=_QUERY)

    assert response.status_code == 404
    assert response.json()["detail"] == "Malformed event_id"
    assert calls.events == 0
    _assert_no_odds_gateway(calls)


@pytest.mark.asyncio
async def test_cache_hit_does_not_call_the_gateway(client, monkeypatch):
    calls = _Calls()
    cache = {_events_cache_key(): _cached_list()}
    _install(monkeypatch, calls, cache)

    response = await client.get(f"/api/nba/events/{_FOUND_ID}", params=_QUERY)

    assert response.status_code == 200
    _assert_found_body(response.json(), _FOUND)
    assert calls.events == 0
    _assert_no_odds_gateway(calls)
