"""SPO-135g QA: request-time Out skip, detail route, and ranking.

The events Redis cache stores the Odds list without top_read. Each
request joins a fresh snapshot. GET /api/nba/events/{event_id} uses
that same list. A Jr. Out row does not skip the stem, and the stem
does not skip the Jr. name. Skipping an Out candidate keeps the
original historical-probability order among the rest, including the
earlier-row tie. An injury-key Redis error does not skip and does
not raise. The injury key is read once per events request.
"""

from __future__ import annotations

import asyncio

from app.models.schemas import EventsResponse, NBAEvent
from app.services.cache import CacheService, cache_service
from app.services.daily_analysis import (
    best_top_reads,
    daily_picks_cache_key,
)
from app.services.nba_injuries import NBA_INJURIES_CACHE_KEY
from tests.test_spo111_read_data import _EMPTY_EVENT_ID, _EVENT_ID, _RECORDED_EVENTS
from tests.test_spo135c_bdl_injury_status import _entry
from tests.test_spo135e_event_reads_injuries import _fresh
from tests.test_spo135e_injury_name_match import _renamed
from tests.test_spo135g_top_read_out import (
    _DATE,
    _OFFSET,
    _analyze,
    _books,
    _cache,
    _pair,
    _recorded_event,
    _sources,
)


def _events_payload():
    events = []
    for event_id in (_EVENT_ID, _EMPTY_EVENT_ID):
        raw = next(event for event in _RECORDED_EVENTS if event["id"] == event_id)
        events.append(
            NBAEvent(
                event_id=raw["id"],
                sport_key=raw["sport_key"],
                home_team=raw["home_team"],
                away_team=raw["away_team"],
                commence_time=raw["commence_time"],
            )
        )
    return EventsResponse(date=_DATE, events=events).model_dump(mode="json")


def _install(monkeypatch, store):
    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, value, ttl):
        store[key] = value
        return True

    monkeypatch.setattr(cache_service, "get", fake_get)
    monkeypatch.setattr(cache_service, "set", fake_set)


def test_cached_events_list_rejoins_a_later_out_snapshot(monkeypatch) -> None:
    """top_read is joined on the way out. The events cache does not bake it.

    The first request has no snapshot, so the Out candidate is chosen.
    The same cached events list, after a fresh Out snapshot is stored,
    returns the next player on that game.
    """
    out = _entry("Out")
    cached, nxt, _healthy = _pair(out["player"])
    store = {
        f"{CacheService.build_events_key(_DATE, 'us')}:tz{_OFFSET}": _events_payload(),
        daily_picks_cache_key("nba", _DATE, _OFFSET): cached,
    }
    _install(monkeypatch, store)

    from app.api.nba import get_events

    first = asyncio.run(get_events(date=_DATE, regions="us", tz_offset=_OFFSET))
    by_id = {event.event_id: event for event in first.events}
    assert by_id[_EVENT_ID].top_read is not None
    assert by_id[_EVENT_ID].top_read.player == out["player"]

    store[NBA_INJURIES_CACHE_KEY] = _fresh([out])
    second = asyncio.run(get_events(date=_DATE, regions="us", tz_offset=_OFFSET))
    by_id = {event.event_id: event for event in second.events}
    assert by_id[_EVENT_ID].top_read is not None
    assert by_id[_EVENT_ID].top_read.player == nxt


def test_event_detail_route_skips_out_the_same_way(monkeypatch) -> None:
    """GET /api/nba/events/{event_id} calls the list and keeps the skip."""
    out = _entry("Out")
    cached, nxt, _healthy = _pair(out["player"])
    store = {
        f"{CacheService.build_events_key(_DATE, 'us')}:tz{_OFFSET}": _events_payload(),
        daily_picks_cache_key("nba", _DATE, _OFFSET): cached,
        NBA_INJURIES_CACHE_KEY: _fresh([out]),
    }
    _install(monkeypatch, store)

    from app.api.nba import get_event

    detail = asyncio.run(
        get_event.__wrapped__(
            request=None,
            event_id=_EVENT_ID,
            date=_DATE,
            regions="us",
            tz_offset=_OFFSET,
        )
    )
    assert detail.event_id == _EVENT_ID
    assert detail.top_read is not None
    assert detail.top_read.player == nxt
    assert detail.top_read.player != out["player"]


def test_gary_trent_out_does_not_skip_gary_trent_jr() -> None:
    """The stem Out row does not skip Gary Trent Jr."""
    senior = _renamed(_entry("Out"), "Gary Trent")
    best_source, nxt, _healthy = _sources("Gary Trent Jr.")
    game = _recorded_event(_EVENT_ID)
    picks = _analyze(
        game,
        _books({best_source: "Gary Trent Jr.", nxt: nxt}),
        {"Gary Trent Jr.": 0.91, nxt: 0.72},
    )
    reads = best_top_reads(_cache(picks), injury_entries=[senior])
    assert reads[_EVENT_ID].player == "Gary Trent Jr."


def test_skipping_out_keeps_the_earlier_row_on_a_historical_tie() -> None:
    """Among non-Out candidates, equal historical rates keep the earlier row.

    That is the existing top_read tie: the stored list order, not a
    new sort. The Out row has the highest historical rate and is
    skipped. The two healthy rows tie at 0.80. The earlier one wins.
    """
    out = _entry("Out")
    cached = {
        "picks": [
            {
                "event_id": "tie",
                "player_name": "First",
                "metric": "points",
                "direction": "over",
                "threshold": 10.5,
                "probability": 0.80,
            },
            {
                "event_id": "tie",
                "player_name": out["player"],
                "metric": "rebounds",
                "direction": "over",
                "threshold": 8.5,
                "probability": 0.95,
            },
            {
                "event_id": "tie",
                "player_name": "Second",
                "metric": "assists",
                "direction": "under",
                "threshold": 6.5,
                "probability": 0.80,
            },
        ]
    }
    assert best_top_reads(cached)["tie"].player == out["player"]
    reads = best_top_reads(cached, injury_entries=[out])
    assert reads["tie"].player == "First"
    assert reads["tie"].market == "player_points"
    assert reads["tie"].probability == 0.80


def test_injury_redis_error_does_not_skip_or_raise(monkeypatch) -> None:
    """A failed injury-key read leaves the Out candidate and does not 500."""
    out = _entry("Out")
    cached, _nxt, _healthy = _pair(out["player"])
    store = {
        f"{CacheService.build_events_key(_DATE, 'us')}:tz{_OFFSET}": _events_payload(),
        daily_picks_cache_key("nba", _DATE, _OFFSET): cached,
    }

    async def fake_get(key):
        if key == NBA_INJURIES_CACHE_KEY:
            raise RuntimeError("redis down")
        return store.get(key)

    monkeypatch.setattr(cache_service, "get", fake_get)

    from app.api.nba import get_events

    response = asyncio.run(get_events(date=_DATE, regions="us", tz_offset=_OFFSET))
    by_id = {event.event_id: event for event in response.events}
    assert by_id[_EVENT_ID].top_read is not None
    assert by_id[_EVENT_ID].top_read.player == out["player"]


def test_injury_snapshot_is_read_once_per_events_request(monkeypatch) -> None:
    """Two events on one list still read injuries:nba:latest once."""
    out = _entry("Out")
    cached, nxt, healthy = _pair(out["player"])
    store = {
        f"{CacheService.build_events_key(_DATE, 'us')}:tz{_OFFSET}": _events_payload(),
        daily_picks_cache_key("nba", _DATE, _OFFSET): cached,
        NBA_INJURIES_CACHE_KEY: _fresh([out]),
    }
    keys: list[str] = []

    async def fake_get(key):
        keys.append(key)
        return store.get(key)

    monkeypatch.setattr(cache_service, "get", fake_get)

    from app.api.nba import get_events

    response = asyncio.run(get_events(date=_DATE, regions="us", tz_offset=_OFFSET))
    assert keys.count(NBA_INJURIES_CACHE_KEY) == 1
    by_id = {event.event_id: event for event in response.events}
    assert by_id[_EVENT_ID].top_read.player == nxt
    assert by_id[_EMPTY_EVENT_ID].top_read.player == healthy
