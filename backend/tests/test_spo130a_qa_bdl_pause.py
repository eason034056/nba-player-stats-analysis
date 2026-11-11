"""SPO-130a QA: the shared ``pause_until`` key, against recorded captures.

Bodies and rate headers come from ``tests/fixtures/bdl/`` unchanged; only
the injected clock moves.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fakeredis.aioredis

from app.services.bdl_client import BdlClient

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
_PAUSE_KEY = "bdl:ratelimit:v1:pause_until"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _recorded(capture: dict) -> httpx.Response:
    return httpx.Response(
        capture["status"], json=capture["response"], headers=dict(capture["rate_headers"])
    )


class ManualClock:
    def __init__(self, start: float) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(handler, clock: ManualClock, redis) -> BdlClient:
    return BdlClient(
        api_key="qa-pause-key",
        redis=redis,
        rate_limit_per_min=5,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )


@pytest.mark.asyncio
async def test_recorded_remaining_zero_pauses_another_client_on_the_same_redis():
    """Client A sees the recorded remaining 0; client B, which never saw it, waits too."""
    lineups = _load("projected_lineups_21718080.json")
    games = _load("games_2026-11-11.json")
    reset = int(lineups["rate_headers"]["x-ratelimit-reset"])
    clock = ManualClock(float(reset - 20))
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    seen: list[tuple[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, clock.now))
        if request.url.path == "/nba/v1/projected_lineups":
            return _recorded(lineups)
        return _recorded(games)

    first = _client(handler, clock, redis)
    second = _client(handler, clock, redis)
    try:
        await first.list_projected_lineups(game_ids=[21718080])
        assert await redis.get(_PAUSE_KEY) == str(reset)
        assert 0 < await redis.ttl(_PAUSE_KEY) <= 65
        await second.list_games(dates=["2026-11-11"])
    finally:
        await first.aclose()
        await second.aclose()
    assert clock.sleeps == [20.0]
    assert seen[-1] == ("/v1/games", float(reset))


@pytest.mark.asyncio
async def test_garbage_pause_value_does_not_block():
    games = _load("games_2026-11-11.json")
    clock = ManualClock(1_800_000_000.0)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis.set(_PAUSE_KEY, "not-a-number", ex=60)
    client = _client(lambda request: _recorded(games), clock, redis)
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert body == games["response"]
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_far_future_pause_value_sleeps_once_then_proceeds():
    """A pause an hour away (another host's skewed clock) costs one capped wait, not a loop."""
    games = _load("games_2026-11-11.json")
    start = 1_800_000_000.0
    clock = ManualClock(start)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis.set(_PAUSE_KEY, str(int(start) + 3600), ex=65)
    client = _client(lambda request: _recorded(games), clock, redis)
    try:
        await client.list_games(dates=["2026-11-11"])
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert clock.sleeps == [65.0]


@pytest.mark.asyncio
async def test_recorded_429_publishes_pause_with_capped_ttl():
    denied = _load("lineups_18447393_2026-01-15_agents_429.json")
    games = _load("games_2026-11-11.json")
    reset = int(denied["rate_headers"]["x-ratelimit-reset"])
    clock = ManualClock(float(reset - 30))
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = [
        httpx.Response(
            429, content=denied["response"]["_raw"].encode(), headers=dict(denied["rate_headers"])
        ),
        _recorded(games),
    ]
    ttls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    client = _client(handler, clock, redis)
    original = client._sleep

    async def sleep_and_probe(seconds: float) -> None:
        ttls.append(await redis.ttl(_PAUSE_KEY))
        await original(seconds)

    client._sleep = sleep_and_probe
    try:
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    # One 30 s wait: the retry backoff, not a second pause in acquire.
    assert clock.sleeps == [30.0]
    assert ttls and 0 < ttls[0] <= 30


@pytest.mark.asyncio
async def test_window_key_ttl_is_set_in_the_same_transaction_as_incr():
    games = _load("games_2026-11-11.json")
    clock = ManualClock(1_800_000_000.0)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = _client(lambda request: _recorded(games), clock, redis)
    try:
        for _ in range(3):
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    key = "bdl:ratelimit:v1:window:1800000000"
    assert await redis.get(key) == "3"
    assert 0 < await redis.ttl(key) <= 120
