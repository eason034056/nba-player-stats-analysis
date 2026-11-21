"""SPO-144 QA recheck: failed schedule reads, the 15-minute overlap, the 9-22 grid.

Every HTTP body is a recorded capture from ``tests/fixtures/``:
``bdl/games_2026-11-11.json``, ``bdl/games__season1900_empty.json`` and
``bdl/lineups_18447393_2026-01-15_agents_429.json`` for BALLDONTLIE. A 5xx
carries no body.

The real BALLDONTLIE client runs, so retry counts are the client's own.
Trigger fire times come from the real
``CronTrigger`` objects ``SchedulerService.start()`` registers. No network.

Recovery clocks are 16:05 CT and later, never a quarter hour, so the failure
really happens on the 5-minute job rather than being skipped by the 15-minute gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import httpx
import pytest
from pydantic import SecretStr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import bdl_client as bdl_module
from app.services.cache import cache_service
from app.services.scheduler import (
    SchedulerService,
    lineup_active_window_covers,
    nba_lineup_tips_cache_key,
    nba_slate_date,
)
from app.settings import settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHICAGO = ZoneInfo("America/Chicago")
_BDL_KEY = "unit-test-bdl-key-spo144i"
_REAL_BDL_CLIENT = bdl_module.BdlClient
_START = 1_800_000_000.0  # later than the recorded x-ratelimit-reset


def _bdl(name: str) -> dict:
    return json.loads((FIXTURES / "bdl" / name).read_text())


def _chicago(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=CHICAGO)


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


class _BdlServer:
    """Fails with ``status`` until ``healthy``; then serves the recorded page ``ok_fixture``."""

    def __init__(self, status: int, ok_fixture: str = "games_2026-11-11.json") -> None:
        self.status = status
        self.ok_fixture = ok_fixture
        self.healthy = False
        self.dates: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/games"
        self.dates.append(request.url.params.get("dates[]"))
        if self.healthy:
            return httpx.Response(200, json=_bdl(self.ok_fixture)["response"])
        if self.status == 429:
            capture = _bdl("lineups_18447393_2026-01-15_agents_429.json")
            return httpx.Response(429, content=str(capture["response"]).encode(),
                                  headers=dict(capture["rate_headers"]))
        return httpx.Response(self.status)


def _install_bdl(monkeypatch: pytest.MonkeyPatch, server: _BdlServer) -> fakeredis.aioredis.FakeRedis:
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_service, "_client", fake)
    clock = _Clock()

    def _factory(**kwargs: object) -> object:
        return _REAL_BDL_CLIENT(**kwargs, redis=fake, rate_limit_per_min=600,
                                transport=httpx.MockTransport(server.handler),
                                sleep=clock.sleep, clock=clock.time)

    monkeypatch.setattr(bdl_module, "BdlClient", _factory)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(_BDL_KEY))
    return fake


def _app_warnings(caplog: pytest.LogCaptureFixture, needle: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name.startswith("app.") and r.levelno == logging.WARNING and needle in r.getMessage()]


def _triggers(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    with patch("app.services.scheduler.AsyncIOScheduler") as mock_sched:
        instance = MagicMock()
        instance.get_jobs.return_value = []
        mock_sched.return_value = instance
        SchedulerService().start()
    return {str(c.kwargs["id"]): c.kwargs["trigger"] for c in instance.add_job.call_args_list}


def _fires(trigger: object, start: datetime, end: datetime) -> list[datetime]:
    """Every fire time of a real CronTrigger in [start, end)."""
    out: list[datetime] = []
    prev = None
    now = start
    while True:
        nxt = trigger.get_next_fire_time(prev, now)
        if nxt is None or nxt >= end:
            return out
        out.append(nxt)
        prev = nxt
        now = nxt + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# M1: a failed call is retried (real clients, recorded fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 503])
def test_nba_failed_read_retries_next_tick_warns_once_and_is_not_stored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    server = _BdlServer(status)
    fake = _install_bdl(monkeypatch, server)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)
    caplog.set_level(logging.DEBUG)
    seen: dict[str, object] = {}

    async def _go() -> None:
        service = SchedulerService()
        await service._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 5))
        seen["after_one"] = len(server.dates)
        await service._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 10))
        seen["after_two"] = len(server.dates)
        seen["stored"] = await fake.get(nba_lineup_tips_cache_key("2026-11-11"))
        server.healthy = True
        await service._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 20))

    asyncio.run(_go())

    assert seen["after_one"] == 3  # BdlClient's own three attempts
    assert seen["after_two"] == 6  # the next tick read again
    assert seen["stored"] is None
    assert len(_app_warnings(caplog, "schedule unreadable")) == 1
    fetch.assert_awaited_once_with("2026-11-11")
    assert _BDL_KEY not in caplog.text


def test_nba_restart_sharing_redis_rereads_after_failed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _BdlServer(429)
    _install_bdl(monkeypatch, server)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)

    async def _go() -> None:
        await SchedulerService()._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 5))
        server.healthy = True
        await SchedulerService()._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 10))

    asyncio.run(_go())
    assert len(server.dates) == 4
    fetch.assert_awaited_once_with("2026-11-11")


def test_nba_recorded_empty_page_still_pins_the_slate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real body with no game is ``no_games`` and is kept: the next tick does not call."""
    server = _BdlServer(429, ok_fixture="games__season1900_empty.json")
    server.healthy = True
    fake = _install_bdl(monkeypatch, server)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)
    seen: dict[str, object] = {}

    async def _go() -> None:
        service = SchedulerService()
        await service._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 5))
        await service._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 10))
        await SchedulerService()._run_lineup_fetch_pre_tipoff_job(now=_chicago(2026, 11, 11, 16, 20))
        seen["stored"] = await fake.get(nba_lineup_tips_cache_key("2026-11-11"))

    asyncio.run(_go())
    assert len(server.dates) == 1
    assert json.loads(str(seen["stored"]))["status"] == "no_games"
    fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# One read per slate on success; quarter-hour ticks scrape once
# ---------------------------------------------------------------------------


def test_nba_full_day_one_read_and_one_scrape_per_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real fire times of both NBA jobs on 2026-11-11: BDL read once, never two scrapes on one tick."""
    trig = _triggers(monkeypatch)
    server = _BdlServer(429)
    server.healthy = True
    _install_bdl(monkeypatch, server)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)
    day0, day1 = _chicago(2026, 11, 11, 0, 0), _chicago(2026, 11, 12, 0, 0)
    five = set(_fires(trig["lineup_fetch_pre_tipoff"], day0, day1))
    fifteen = set(_fires(trig["lineup_fetch_active_window"], day0, day1))
    scrapes: dict[datetime, int] = {}

    async def _go() -> None:
        service = SchedulerService()
        for tick in sorted(five | fifteen):
            before = fetch.await_count
            if tick in five:
                await service._run_lineup_fetch_pre_tipoff_job(now=tick)
            if tick in fifteen:
                await service._run_lineup_fetch_job(now=tick)
            scrapes[tick] = fetch.await_count - before

    asyncio.run(_go())

    assert server.dates == ["2026-11-11"]
    assert max(scrapes.values()) == 1
    # Recorded tips 7:00-10:00 PM ET: every 5-minute tick 16:00-20:55 CT scrapes exactly once.
    window = [t for t in five if _chicago(2026, 11, 11, 16, 0) <= t < _chicago(2026, 11, 11, 21, 0)]
    assert len(window) == 60 and all(scrapes[t] == 1 for t in window)


# ---------------------------------------------------------------------------
# The gate and the grid against the real registered triggers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("day", [(2026, 1, 15), (2026, 3, 8), (2026, 7, 15), (2026, 11, 1)])
def test_gate_matches_the_registered_fifteen_minute_triggers(
    monkeypatch: pytest.MonkeyPatch, day: tuple[int, int, int]
) -> None:
    """Standard, spring-forward, daylight, fall-back days: gate == real CronTrigger fire set."""
    trig = _triggers(monkeypatch)
    day0 = _chicago(*day, 0, 0)
    day1 = day0 + timedelta(days=1)
    five = _fires(trig["lineup_fetch_pre_tipoff"], day0, day1)
    fifteen = set(_fires(trig["lineup_fetch_active_window"], day0, day1))
    assert fifteen
    assert {t for t in five if lineup_active_window_covers(t)} == fifteen


def test_five_minute_grid_is_9_to_22_and_first_read_of_a_slate_is_9am_that_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trig = _triggers(monkeypatch)
    fires = _fires(trig["lineup_fetch_pre_tipoff"], _chicago(2026, 11, 10, 0, 0), _chicago(2026, 11, 12, 0, 0))
    local = [t.astimezone(CHICAGO) for t in fires]
    assert {t.hour for t in local} == set(range(9, 23))
    assert (local[-1].hour, local[-1].minute) == (22, 55)
    first_for_slate = min(t for t in fires if nba_slate_date(t)[0] == "2026-11-11")
    assert first_for_slate.astimezone(CHICAGO) == _chicago(2026, 11, 11, 9, 0)


def test_registered_jobs_include_no_removed_lineup_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    trig = _triggers(monkeypatch)
    assert not [job for job in trig if "wnba" in job]
    assert {"lineup_fetch_pre_tipoff", "lineup_fetch_active_window", "lineup_fetch_opening"} <= set(trig)


