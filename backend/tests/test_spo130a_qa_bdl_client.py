"""
test_spo130a_qa_bdl_client.py - QA cases for the BALLDONTLIE client.

Bodies and 429 headers come from backend/tests/fixtures/bdl/. No test
here calls the network. The review patch that named this file was not
attached; these cases lock the same behavior that review described.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fakeredis.aioredis
import redis.asyncio as redis_async

from app.services.bdl_client import (
    BdlApiError,
    BdlClient,
    BdlError,
    iter_pages,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
_MINUTE = 1_800_000_000.0
_API_KEY = "unit-test-bdl-key-spo130a"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


class ManualClock:
    """Sleep moves this clock forward and records the delay."""

    def __init__(self, start: float) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SetFails:
    """Redis whose SET raises. GET, INCR, and pipelines still work.

    Publishing the observed limit must not throw away a 200 the server
    already counted.
    """

    def __init__(self, inner: redis_async.Redis) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def set(self, *args, **kwargs):
        raise redis_async.RedisError("set failed")


def _client(handler, clock: ManualClock, *, redis=None, api_key: str = _API_KEY) -> BdlClient:
    if redis is None:
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return BdlClient(
        api_key=api_key,
        redis=redis,
        rate_limit_per_min=5,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )


def _json_response(capture: dict, headers: dict[str, str] | None = None) -> httpx.Response:
    rate = dict(capture["rate_headers"])
    if headers:
        rate.update(headers)
    return httpx.Response(capture["status"], json=capture["response"], headers=rate)


def _recorded_429() -> httpx.Response:
    capture = _load("lineups_18447393_2026-01-15_agents_429.json")
    return httpx.Response(
        429,
        content=str(capture["response"]["_raw"]).encode(),
        headers=dict(capture["rate_headers"]),
    )


@pytest.mark.asyncio
async def test_repr_log_and_errors_do_not_contain_the_key(caplog):
    """The key is not in repr, a log line, or an error message."""
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(404, content=b"")
        return _json_response(games)

    client = _client(handler, clock)
    try:
        assert _API_KEY not in repr(client)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(BdlApiError, match="HTTP 404") as raised:
                await client.list_games(dates=["2026-11-11"])
        assert _API_KEY not in str(raised.value)
        assert _API_KEY not in caplog.text
        assert "authorization" not in caplog.text.lower()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_list_players_sends_exactly_100_ids():
    """100 ids are one call. 101 is refused before HTTP."""
    capture = _load("backend_players_batch45.json")
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(capture)

    client = _client(handler, clock)
    try:
        await client.list_players(player_ids=list(range(1, 101)))
        assert len(seen) == 1
        assert seen[0].url.params.get_list("player_ids[]") == [str(i) for i in range(1, 101)]
        with pytest.raises(BdlError, match="100"):
            await client.list_players(player_ids=list(range(101)))
        assert len(seen) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_other_4xx_is_not_retried():
    """A 404 is one request and a BdlApiError. No backoff."""
    clock = ManualClock(_MINUTE)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(404)
        return httpx.Response(404, content=b"")

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlApiError) as raised:
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert raised.value.status_code == 404
    assert seen == [404]
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_transport_error_retries_then_succeeds():
    """A connection error waits 60 seconds and then returns the recorded body."""
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(clock.now)
        if len(seen) == 1:
            raise httpx.ConnectError("connection refused")
        return _json_response(games)

    client = _client(handler, clock)
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert body == games["response"]
    assert clock.sleeps == [60.0]
    assert seen == [_MINUTE, _MINUTE + 60.0]


@pytest.mark.asyncio
async def test_three_transport_errors_raise_bdl_error():
    """Three connection errors raise BdlError. The message has no API key."""
    clock = ManualClock(_MINUTE)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        raise httpx.ConnectError("connection refused")

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlError, match="ConnectError") as raised:
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert len(seen) == 3
    assert clock.sleeps == [60.0, 60.0]
    assert _API_KEY not in str(raised.value)
    assert not isinstance(raised.value, BdlApiError)


@pytest.mark.asyncio
async def test_iter_pages_stops_when_the_injuries_cursor_repeats():
    """The same injuries body twice stops. No second page was recorded."""
    injuries = _load("injuries.json")
    cursor = injuries["response"]["meta"]["next_cursor"]
    assert cursor == 15504814
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=injuries["response"], headers=dict(injuries["rate_headers"]))

    client = _client(handler, clock)
    try:
        pages = [page async for page in iter_pages(client.list_player_injuries)]
    finally:
        await client.aclose()
    assert len(pages) == 2
    assert len(seen) == 2
    assert seen[1].url.params.get_list("cursor") == [str(cursor)]
    assert pages[0] == pages[1] == injuries["response"]


@pytest.mark.asyncio
async def test_far_future_reset_is_clamped_to_one_window(caplog):
    """A reset an hour ahead sleeps 65 seconds, then the retry can succeed.

    The recorded 429 reset is 1794370905. The clock starts 3600 seconds
    earlier, which is what a slow local clock looks like.
    """
    denied = _load("lineups_18447393_2026-01-15_agents_429.json")
    reset = int(denied["rate_headers"]["x-ratelimit-reset"])
    games = _load("games_2026-11-11.json")
    clock = ManualClock(float(reset - 3600))
    seen: list[int] = []
    responses = [_recorded_429(), _json_response(games)]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses[len(seen)]
        seen.append(response.status_code)
        return response

    client = _client(handler, clock)
    try:
        with caplog.at_level(logging.WARNING):
            body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert body == games["response"]
    assert clock.sleeps == [65.0]
    assert seen == [429, 200]
    assert "bdl_rate_limit_clock_skew" in caplog.text
    assert "x-ratelimit" not in caplog.text
    assert _API_KEY not in caplog.text


@pytest.mark.asyncio
async def test_remaining_zero_pause_is_clamped_and_shared(caplog):
    """remaining 0 with a far reset pauses the next process for 65 seconds."""
    games = _load("games_2026-11-11.json")
    reset = int(_MINUTE) + 3600
    headers = {
        "x-ratelimit-limit": "5",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": str(reset),
    }
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(clock.now)
        return _json_response(games, headers=headers)

    first = _client(handler, clock, redis=redis)
    second = _client(handler, clock, redis=redis)
    try:
        with caplog.at_level(logging.WARNING):
            await first.list_games(dates=["2026-11-11"])
            assert clock.sleeps == []
            await second.list_games(dates=["2026-11-11"])
    finally:
        await first.aclose()
        await second.aclose()
    assert clock.sleeps == [65.0]
    assert seen == [_MINUTE, _MINUTE + 65.0]
    assert "bdl_rate_limit_clock_skew" in caplog.text
    assert await redis.get("bdl:ratelimit:v1:pause_until") == str(reset)


@pytest.mark.asyncio
async def test_observed_limit_publish_failure_still_returns_the_body():
    """A Redis SET error after HTTP 200 still returns the recorded body."""
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    redis = SetFails(fakeredis.aioredis.FakeRedis(decode_responses=True))

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(games)

    client = _client(handler, clock, redis=redis)
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert body == games["response"]
    assert client.rate_status()["limit"] == 5


@pytest.mark.asyncio
async def test_observed_limit_expires_after_one_day():
    """The shared limit key has a one-day TTL, not a permanent one."""
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = _client(lambda request: _json_response(games), clock, redis=redis)
    try:
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    ttl = await redis.ttl("bdl:ratelimit:v1:observed_limit")
    assert ttl == 86400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("list_games", {"dates": []}),
        ("list_players", {"player_ids": []}),
        ("list_odds", {"dates": []}),
        ("list_projected_lineups", {"game_ids": []}),
    ],
)
async def test_empty_filter_raises_before_a_request(method, kwargs):
    """An empty filter is not sent. The API would return an unfiltered page."""
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        raise AssertionError("empty filter must not call the API")

    client = _client(handler, clock, redis=redis)
    try:
        with pytest.raises(BdlError, match="at least one"):
            await getattr(client, method)(**kwargs)
    finally:
        await client.aclose()
    assert seen == []
    assert await redis.keys("bdl:ratelimit:v1:window:*") == []


@pytest.mark.asyncio
async def test_reserve_window_key_has_a_ttl():
    """The per-minute counter expires. INCR and EXPIRE are one transaction."""
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = _client(lambda request: _json_response(games), clock, redis=redis)
    try:
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    keys = await redis.keys("bdl:ratelimit:v1:window:*")
    assert len(keys) == 1
    ttl = await redis.ttl(keys[0])
    assert 0 < ttl <= 120
