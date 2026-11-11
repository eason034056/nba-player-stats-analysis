"""SPO-130a QA: BALLDONTLIE client edges against the recorded captures.

Every response body comes from ``tests/fixtures/bdl/`` unchanged. Where a
case needs no body at all (a transport error, a status-only 4xx), the
test says so. ``xfail(strict=True)`` cases lock a review finding: they
fail today and start passing once the client is changed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import redis.asyncio as redis_async

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fakeredis.aioredis

from app.services.bdl_client import BdlApiError, BdlClient, BdlError, iter_pages

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
_KEY = "qa-bdl-key-must-not-leak-130a"
_MINUTE = 1_800_000_000.0


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _recorded(capture: dict) -> httpx.Response:
    """Recorded status, recorded rate headers, recorded JSON body."""
    return httpx.Response(
        capture["status"],
        json=capture["response"],
        headers=dict(capture["rate_headers"]),
    )


def _recorded_429() -> httpx.Response:
    capture = _load("lineups_18447393_2026-01-15_agents_429.json")
    return httpx.Response(
        429,
        content=capture["response"]["_raw"].encode(),
        headers=dict(capture["rate_headers"]),
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
        await asyncio.sleep(0)


def _client(handler, clock: ManualClock, *, redis=None, limit: int = 5) -> BdlClient:
    return BdlClient(
        api_key=_KEY,
        redis=redis if redis is not None else fakeredis.aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=limit,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )


class _SetFailsRedis(fakeredis.aioredis.FakeRedis):
    """Budget calls work; publishing the observed limit fails."""

    async def set(self, *args, **kwargs):  # type: ignore[override]
        raise redis_async.ConnectionError("redis went away")


# ---------------------------------------------------------------------------
# Server window: recorded "remaining 0"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recorded_remaining_zero_waits_until_recorded_reset():
    """projected_lineups was recorded with remaining 0. The next call waits for its reset."""
    capture = _load("projected_lineups_21718080.json")
    assert capture["rate_headers"]["x-ratelimit-remaining"] == "0"
    reset = int(capture["rate_headers"]["x-ratelimit-reset"])
    clock = ManualClock(float(reset - 20))
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(clock.now)
        return _recorded(capture)

    client = _client(handler, clock)
    try:
        await client.list_projected_lineups(game_ids=[21718080])
        await client.list_projected_lineups(game_ids=[21718080])
    finally:
        await client.aclose()
    assert clock.sleeps == [20.0]
    assert seen == [float(reset - 20), float(reset)]


@pytest.mark.xfail(strict=True, reason="should-fix: x-ratelimit-reset wait is not clamped")
@pytest.mark.asyncio
async def test_far_future_reset_is_clamped_to_one_window():
    """A local clock an hour behind the server must not sleep an hour on one 429.

    Body and headers are the recorded 429; only the local clock moves.
    """
    capture = _load("lineups_18447393_2026-01-15_agents_429.json")
    reset = int(capture["rate_headers"]["x-ratelimit-reset"])
    games = _load("games_2026-11-11.json")
    clock = ManualClock(float(reset - 3600))
    queue = [_recorded_429(), _recorded(games)]

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    client = _client(handler, clock)
    try:
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert max(clock.sleeps) <= 61.0


# ---------------------------------------------------------------------------
# Transport errors and status-only 4xx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transport_error_retries_then_raises_without_the_key():
    """No response exists for a refused connection, so there is no body to load."""
    clock = ManualClock(_MINUTE)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlError) as raised:
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert len(calls) == 3
    assert clock.sleeps == [60.0, 60.0]
    assert type(raised.value) is BdlError
    for text in (str(raised.value), repr(raised.value), repr(client), str(raised.value.__cause__)):
        assert _KEY not in text
    assert _KEY not in str(calls[0].url)


@pytest.mark.asyncio
async def test_timeout_then_recorded_success():
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return _recorded(games)

    client = _client(handler, clock)
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert body == games["response"]
    assert clock.sleeps == [60.0]


@pytest.mark.asyncio
async def test_non_429_4xx_raises_once_with_status():
    """Status-only 401 (no 401 was recorded; the client never reads an error body)."""
    clock = ManualClock(_MINUTE)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, content=b"")

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlApiError) as raised:
            await client.list_player_injuries()
    finally:
        await client.aclose()
    assert calls == [1]
    assert raised.value.status_code == 401
    assert clock.sleeps == []
    assert _KEY not in str(raised.value)


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_down_raises_bdl_error_before_any_http():
    clock = ManualClock(_MINUTE)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _recorded(_load("games_2026-11-11.json"))

    down = fakeredis.aioredis.FakeRedis(decode_responses=True, connected=False)
    client = _client(handler, clock, redis=down)
    try:
        with pytest.raises(BdlError, match="Redis"):
            await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert calls == []


@pytest.mark.xfail(strict=True, reason="should-fix: a failed observed-limit publish discards a 200")
@pytest.mark.asyncio
async def test_observed_limit_publish_failure_keeps_the_recorded_200():
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    client = _client(lambda request: _recorded(games), clock, redis=_SetFailsRedis(decode_responses=True))
    try:
        body = await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert body == games["response"]


@pytest.mark.asyncio
async def test_minute_key_gets_a_ttl_on_first_incr():
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = _client(lambda request: _recorded(games), clock, redis=redis)
    try:
        await client.list_games(dates=["2026-11-11"])
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    keys = [key async for key in redis.scan_iter("bdl:ratelimit:v1:window:*")]
    assert keys == [f"bdl:ratelimit:v1:window:{int(_MINUTE)}"]
    assert await redis.get(keys[0]) == "2"
    assert 0 < await redis.ttl(keys[0]) <= 120


@pytest.mark.xfail(strict=True, reason="should-fix: observed_limit is stored with no TTL (CLAUDE.md Redis rule)")
@pytest.mark.asyncio
async def test_observed_limit_key_has_an_explicit_ttl():
    games = _load("games_2026-11-11.json")
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = _client(lambda request: _recorded(games), clock, redis=redis)
    try:
        await client.list_games(dates=["2026-11-11"])
    finally:
        await client.aclose()
    assert await redis.ttl("bdl:ratelimit:v1:observed_limit") > 0


@pytest.mark.asyncio
async def test_concurrent_callers_never_exceed_the_recorded_limit():
    """Seven concurrent calls on one Redis at the recorded limit of 5: five now, two later."""
    capture = _load("games_2026-11-10.json")
    assert capture["rate_headers"]["x-ratelimit-limit"] == "5"
    assert capture["rate_headers"]["x-ratelimit-remaining"] != "0"
    clock = ManualClock(_MINUTE)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(clock.now)
        return _recorded(capture)

    clients = [_client(handler, clock, redis=redis) for _ in range(2)]
    try:
        await asyncio.gather(
            *(clients[i % 2].list_games(dates=["2026-11-10"]) for i in range(7))
        )
    finally:
        for client in clients:
            await client.aclose()
    assert len(seen) == 7
    assert seen.count(_MINUTE) == 5
    assert all(at >= _MINUTE + 60 for at in seen if at != _MINUTE)


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_players_accepts_exactly_100_ids_in_one_call():
    capture = _load("backend_players_batch45.json")
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _recorded(capture)

    client = _client(handler, clock)
    try:
        await client.list_players(player_ids=list(range(1, 101)))
    finally:
        await client.aclose()
    assert len(seen) == 1
    assert len(seen[0].url.params.get_list("player_ids[]")) == 100
    assert "player_ids%5B%5D=1&" in str(seen[0].url)


@pytest.mark.xfail(strict=True, reason="should-fix: an empty filter list sends an unfiltered request")
@pytest.mark.parametrize(
    "method, kwargs",
    [
        ("list_players", {"player_ids": []}),
        ("list_games", {"dates": []}),
        ("list_odds", {"dates": []}),
        ("list_projected_lineups", {"game_ids": []}),
    ],
)
@pytest.mark.asyncio
async def test_empty_filter_list_is_refused_before_http(method, kwargs):
    """With no ``player_ids[]`` the API returns every player (report.md 2.3)."""
    capture = _load("backend_players_batch45.json")
    clock = ManualClock(_MINUTE)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _recorded(capture)

    client = _client(handler, clock)
    try:
        with pytest.raises(BdlError):
            await getattr(client, method)(**kwargs)
    finally:
        await client.aclose()
    assert calls == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iter_pages_stops_when_the_recorded_cursor_repeats():
    """The recorded injuries page always points at 15504814; a repeat ends the loop."""
    injuries = _load("injuries.json")
    cursor = injuries["response"]["meta"]["next_cursor"]
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _recorded(injuries)

    client = _client(handler, clock)
    try:
        pages = [page async for page in iter_pages(client.list_player_injuries)]
    finally:
        await client.aclose()
    assert len(pages) == 2
    assert [r.url.params.get("cursor") for r in seen] == [None, str(cursor)]


@pytest.mark.asyncio
async def test_iter_pages_starts_at_a_given_cursor_and_forwards_per_page():
    injuries = _load("injuries.json")
    cursor = injuries["response"]["meta"]["next_cursor"]
    clock = ManualClock(_MINUTE)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _recorded(injuries)

    client = _client(handler, clock)
    try:
        pages = [
            page
            async for page in iter_pages(client.list_player_injuries, cursor=cursor, per_page=50)
        ]
    finally:
        await client.aclose()
    assert len(pages) == 1
    assert seen[0].url.params.get("cursor") == str(cursor)
    assert seen[0].url.params.get("per_page") == "50"


@pytest.mark.asyncio
async def test_props_are_yielded_once_by_iter_pages():
    capture = _load("props_live_21718081_WAS@IND_upcoming.json")
    clock = ManualClock(_MINUTE)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _recorded(capture)

    client = _client(handler, clock)
    try:
        pages = [page async for page in iter_pages(client.get_player_props, game_id=21718081)]
    finally:
        await client.aclose()
    assert pages == [capture["response"]]
    assert calls == [1]
