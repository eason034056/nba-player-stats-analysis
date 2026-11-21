"""SPO-144: NBA 5-minute lineup refresh follows the night's first tip.

The window is ``[first_tip - 2 hours, first_tip)``. Clocks are fixed.
Nothing here sleeps or calls the network. Game rows come from the
recorded BALLDONTLIE captures under ``tests/fixtures/bdl/``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import pytest
from pydantic import SecretStr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cache import cache_service
from app.services.scheduler import (
    NBA_INJURY_REFRESH_CRON_HOUR,
    NBA_INJURY_REFRESH_CRON_MINUTE,
    NBA_INJURY_REFRESH_HOURS,
    NBA_LINEUP_FIRST_TIP_CACHE_TTL_SECONDS,
    NBA_LINEUP_PRETIPOFF_CRON_HOUR,
    NBA_LINEUP_PRETIPOFF_CRON_MINUTE,
    SchedulerService,
    first_tip_from_games_payload,
    nba_lineup_first_tip_cache_key,
    nba_lineup_pretipoff_in_window,
)
from app.settings import settings

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
SCHEDULER_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "scheduler.py"
CHICAGO = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
EVERY_FIVE = "0,5,10,15,20,25,30,35,40,45,50,55"
_TEST_KEY = "unit-test-bdl-key-spo144"


def _load(name: str) -> dict:
    """One recorded capture. The file is ``{request, status, response}``."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _chicago(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """A Chicago wall time. Tests pass this as ``now``."""
    return datetime(year, month, day, hour, minute, tzinfo=CHICAGO)


def _eastern_tip(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """UTC instant of a clock time in America/New_York."""
    return datetime(year, month, day, hour, minute, tzinfo=EASTERN).astimezone(timezone.utc)


def _recorded_nov11_tip() -> datetime:
    """Earliest tip on the recorded 2026-11-11 slate. 7:00 PM ET."""
    payload = _load("games_2026-11-11.json")["response"]
    status, tip = first_tip_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert tip is not None
    return tip


# 7:00 PM ET on a standard-time night and on a daylight-time night.
# Chicago stays one hour behind Eastern on both.
_STANDARD_TIP = _eastern_tip(2026, 1, 15, 19, 0)
_DAYLIGHT_TIP = _eastern_tip(2026, 7, 15, 19, 0)
_MATINEE_TIP = _eastern_tip(2026, 12, 25, 12, 30)


class _GamesClient:
    """Stand-in for ``BdlClient``. ``list_games`` is the only method used."""

    def __init__(self, *, payload: dict | None = None, error: BaseException | None = None):
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []
        self.closed = 0
        self.init_kwargs: list[dict] = []

    def __call__(self, **kwargs: object) -> "_GamesClient":
        self.init_kwargs.append(dict(kwargs))
        return self

    async def list_games(self, **kwargs: object) -> dict:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload

    async def aclose(self) -> None:
        self.closed += 1


def _install_cache(monkeypatch: pytest.MonkeyPatch) -> fakeredis.aioredis.FakeRedis:
    """Point the process cache at an in-memory Redis. No socket is opened."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_service, "_client", fake)
    return fake


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _GamesClient) -> None:
    monkeypatch.setattr("app.services.bdl_client.BdlClient", client)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(_TEST_KEY))


def _registered(service: SchedulerService) -> dict[str, tuple[object, dict]]:
    """Job id to ``(func, kwargs)`` from one ``start()`` against a fake scheduler."""
    with patch("app.services.scheduler.AsyncIOScheduler") as mock_sched:
        instance = MagicMock()
        instance.get_jobs.return_value = []
        mock_sched.return_value = instance
        service.start()
    found: dict[str, tuple[object, dict]] = {}
    for call in instance.add_job.call_args_list:
        args, kwargs = call
        found[str(kwargs["id"])] = (args[0], kwargs)
    return found


# ---------------------------------------------------------------------------
# Pure window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_chicago(2026, 1, 15, 15, 55), False),
        (_chicago(2026, 1, 15, 16, 0), True),
        (_chicago(2026, 1, 15, 17, 55), True),
        (_chicago(2026, 1, 15, 18, 0), False),
        (_chicago(2026, 1, 15, 18, 5), False),
    ],
)
def test_standard_time_7pm_et_window_is_4pm_to_6pm_ct(now: datetime, expected: bool) -> None:
    """January 15 is Eastern Standard Time. 7:00 PM ET is 6:00 PM CT."""
    assert now.tzinfo == CHICAGO
    assert nba_lineup_pretipoff_in_window(now, _STANDARD_TIP) is expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_chicago(2026, 7, 15, 15, 55), False),
        (_chicago(2026, 7, 15, 16, 0), True),
        (_chicago(2026, 7, 15, 17, 55), True),
        (_chicago(2026, 7, 15, 18, 0), False),
    ],
)
def test_daylight_time_7pm_et_window_is_4pm_to_6pm_ct(now: datetime, expected: bool) -> None:
    """July 15 is Eastern Daylight Time. The Chicago hours match January."""
    assert nba_lineup_pretipoff_in_window(now, _DAYLIGHT_TIP) is expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_chicago(2026, 12, 25, 9, 25), False),
        (_chicago(2026, 12, 25, 9, 30), True),
        (_chicago(2026, 12, 25, 11, 25), True),
        (_chicago(2026, 12, 25, 11, 30), False),
    ],
)
def test_matinee_1230pm_et_window_is_930_to_1130_ct(now: datetime, expected: bool) -> None:
    """12:30 PM ET is 11:30 AM CT. The window opens two hours earlier."""
    assert nba_lineup_pretipoff_in_window(now, _MATINEE_TIP) is expected


def test_recorded_nov11_slate_opens_at_4pm_ct() -> None:
    """The captured 2026-11-11 board's first tip is 7:00 PM ET."""
    tip = _recorded_nov11_tip()
    eastern = tip.astimezone(EASTERN)
    assert eastern.hour == 19 and eastern.minute == 0
    assert eastern.date().isoformat() == "2026-11-11"
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 15, 55), tip) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 16, 0), tip) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 18, 0), tip) is False


def test_missing_tip_is_outside_the_window() -> None:
    """No game, or a schedule that could not be read, does not open the window."""
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 16, 0), None) is False


def test_naive_now_is_read_as_utc() -> None:
    """4:00 PM CST on 2026-11-11 is 22:00 UTC. A naive clock is that UTC instant."""
    tip = _recorded_nov11_tip()
    naive = datetime(2026, 11, 11, 22, 0)
    assert naive.tzinfo is None
    assert nba_lineup_pretipoff_in_window(naive, tip) is True


# ---------------------------------------------------------------------------
# Recorded schedule bodies
# ---------------------------------------------------------------------------


def test_empty_recorded_page_is_no_games() -> None:
    payload = _load("games__season1900_empty.json")["response"]
    status, tip = first_tip_from_games_payload(payload, "2026-11-11")
    assert status == "no_games"
    assert tip is None


def test_non_object_payload_is_unreadable() -> None:
    status, tip = first_tip_from_games_payload(None, "2026-11-11")
    assert status == "unreadable"
    assert tip is None


def test_postponed_earliest_games_do_not_set_the_tip() -> None:
    """Flip ``postponed`` on a copy of the recorded rows. The next tip wins."""
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    earliest = min(game["datetime"] for game in payload["data"])
    for game in payload["data"]:
        if game["datetime"] == earliest:
            game["postponed"] = True
    status, tip = first_tip_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert tip == datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)


def test_all_postponed_recorded_games_are_no_games() -> None:
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    for game in payload["data"]:
        game["postponed"] = True
    status, tip = first_tip_from_games_payload(payload, "2026-11-11")
    assert status == "no_games"
    assert tip is None


def test_recorded_game_on_another_date_is_ignored() -> None:
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    earliest = min(game["datetime"] for game in payload["data"])
    for game in payload["data"]:
        if game["datetime"] == earliest:
            game["date"] = "2026-11-10"
    status, tip = first_tip_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert tip == datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Job handler
# ---------------------------------------------------------------------------


async def _run_pre_tipoff(service: SchedulerService, now: datetime) -> None:
    await service._run_lineup_fetch_pre_tipoff_job(now=now)


def test_handler_fires_only_inside_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed clocks. The scrape runs only while the helper says the window is open."""
    import asyncio

    _install_cache(monkeypatch)
    client = _GamesClient(payload=_load("games_2026-11-11.json")["response"])
    _patch_client(monkeypatch, client)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)
    odds = AsyncMock(side_effect=AssertionError("odds events must not be called"))
    monkeypatch.setattr("app.services.scheduler.odds_gateway.list_events", odds)

    service = SchedulerService()
    tip = _recorded_nov11_tip()
    samples = [
        _chicago(2026, 11, 11, 15, 55),
        _chicago(2026, 11, 11, 16, 0),
        _chicago(2026, 11, 11, 17, 55),
        _chicago(2026, 11, 11, 18, 0),
        _chicago(2026, 7, 15, 16, 0),
        _chicago(2026, 7, 15, 18, 0),
        _chicago(2026, 12, 25, 9, 30),
        _chicago(2026, 12, 25, 11, 30),
    ]

    async def _go() -> None:
        for moment in samples:
            slate = moment.astimezone(EASTERN).date().isoformat()
            service._nba_first_tip_memory[slate] = ("ok", _tip_for_moment(moment))
            await _run_pre_tipoff(service, moment)

    asyncio.run(_go())

    fired = [call.args[0] for call in fetch.await_args_list]
    assert fired == [
        "2026-11-11",
        "2026-11-11",
        "2026-07-15",
        "2026-12-25",
    ]
    assert client.calls == []
    odds.assert_not_awaited()
    assert tip == datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)


def _tip_for_moment(moment: datetime) -> datetime:
    """The acceptance tip for the slate that ``moment`` falls on."""
    day = moment.astimezone(EASTERN).date().isoformat()
    if day == "2026-11-11":
        return _recorded_nov11_tip()
    if day == "2026-07-15":
        return _DAYLIGHT_TIP
    if day == "2026-12-25":
        return _MATINEE_TIP
    raise AssertionError(day)


def test_recorded_slate_is_read_once_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two ticks, and a second process, share one ``list_games`` call."""
    import asyncio

    fake = _install_cache(monkeypatch)
    client = _GamesClient(payload=_load("games_2026-11-11.json")["response"])
    _patch_client(monkeypatch, client)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)

    inside = _chicago(2026, 11, 11, 16, 0)
    outside = _chicago(2026, 11, 11, 15, 55)
    at_tip = _chicago(2026, 11, 11, 18, 0)
    seen: dict[str, object] = {}

    async def _go() -> None:
        first = SchedulerService()
        await _run_pre_tipoff(first, outside)
        await _run_pre_tipoff(first, inside)
        await _run_pre_tipoff(first, at_tip)
        second = SchedulerService()
        await _run_pre_tipoff(second, inside)
        key = nba_lineup_first_tip_cache_key("2026-11-11")
        seen["key"] = key
        seen["stored"] = await fake.get(key)
        seen["ttl"] = await fake.ttl(key)

    asyncio.run(_go())

    assert client.calls == [{"dates": ["2026-11-11"], "per_page": 100}]
    assert client.closed == 1
    assert client.init_kwargs[0]["api_key"] == _TEST_KEY
    assert [call.args[0] for call in fetch.await_args_list] == ["2026-11-11", "2026-11-11"]
    assert seen["key"] == "lineup:v1:nba:first_tip:2026-11-11"
    assert seen["stored"] is not None
    assert seen["ttl"] == NBA_LINEUP_FIRST_TIP_CACHE_TTL_SECONDS
    assert NBA_LINEUP_FIRST_TIP_CACHE_TTL_SECONDS >= 24 * 60 * 60


def test_no_games_does_not_run_the_five_minute_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    _install_cache(monkeypatch)
    client = _GamesClient(payload=_load("games__season1900_empty.json")["response"])
    _patch_client(monkeypatch, client)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)

    async def _go() -> None:
        service = SchedulerService()
        moment = _chicago(2026, 11, 11, 16, 0)
        await _run_pre_tipoff(service, moment)
        await _run_pre_tipoff(service, moment)

    asyncio.run(_go())
    assert len(client.calls) == 1
    fetch.assert_not_awaited()


def test_schedule_error_warns_once_and_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The 15-minute handler still scrapes. It does not read the schedule."""
    import asyncio

    _install_cache(monkeypatch)
    client = _GamesClient(error=RuntimeError("schedule down"))
    _patch_client(monkeypatch, client)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)
    caplog.set_level(logging.WARNING, logger="app.services.scheduler")

    async def _go() -> None:
        service = SchedulerService()
        moment = _chicago(2026, 11, 11, 16, 0)
        await _run_pre_tipoff(service, moment)
        await _run_pre_tipoff(service, moment)
        await service._run_lineup_fetch_job(now=moment)

    asyncio.run(_go())

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "schedule unreadable" in record.getMessage()
    ]
    assert warnings == [
        "lineup_fetch_pre_tipoff schedule unreadable (RuntimeError); skipping the 5-minute window"
    ]
    assert len(client.calls) == 1
    assert client.closed == 1
    fetch.assert_awaited_once_with("2026-11-11")
    assert _TEST_KEY not in caplog.text


def test_missing_bdl_key_warns_once_and_does_not_build_a_client(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    _install_cache(monkeypatch)
    constructed: list[object] = []

    class _Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed.append(kwargs)
            raise AssertionError("client built without a key")

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Boom)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr("   "))
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)
    caplog.set_level(logging.WARNING, logger="app.services.scheduler")

    async def _go() -> None:
        service = SchedulerService()
        moment = _chicago(2026, 11, 11, 16, 0)
        await _run_pre_tipoff(service, moment)
        await _run_pre_tipoff(service, moment)

    asyncio.run(_go())
    assert constructed == []
    fetch.assert_not_awaited()
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings == [
        "lineup_fetch_pre_tipoff schedule unreadable (BALLDONTLIE_API_KEY is unset); skipping the 5-minute window"
    ]


# ---------------------------------------------------------------------------
# Triggers: NBA dynamic, WNBA unchanged, injury hours unchanged
# ---------------------------------------------------------------------------


def test_nba_and_wnba_pre_tipoff_triggers() -> None:
    """NBA cron is the wide 5-minute grid. WNBA stays at 17, 18, and 19 CT."""
    jobs = _registered(SchedulerService())
    nba_func, nba = jobs["lineup_fetch_pre_tipoff"]
    wnba_func, wnba = jobs["wnba_lineup_fetch_pre_tipoff"]
    active_func, _active = jobs["lineup_fetch_active_window"]

    assert nba_func.__name__ == "_run_lineup_fetch_pre_tipoff_job"
    assert active_func.__name__ == "_run_lineup_fetch_job"
    assert wnba_func.__name__ == "_run_wnba_lineup_fetch_job"

    nba_trigger = str(nba["trigger"])
    wnba_trigger = str(wnba["trigger"])
    assert f"hour='{NBA_LINEUP_PRETIPOFF_CRON_HOUR}'" in nba_trigger
    assert f"minute='{NBA_LINEUP_PRETIPOFF_CRON_MINUTE}'" in nba_trigger
    assert NBA_LINEUP_PRETIPOFF_CRON_HOUR == "9-23"
    assert NBA_LINEUP_PRETIPOFF_CRON_MINUTE == EVERY_FIVE
    assert "hour='22,23,0'" not in nba_trigger
    assert str(nba["trigger"].timezone) == "America/Chicago"

    assert "hour='17,18,19'" in wnba_trigger
    assert f"minute='{EVERY_FIVE}'" in wnba_trigger
    assert str(wnba["trigger"].timezone) == "America/Chicago"
    assert wnba_func.__name__ != nba_func.__name__


def test_injury_hours_and_comment_stay_independent_of_the_lineup_job() -> None:
    """The injury window is still 11:00 through 00:59. The comment does not copy a lineup cron."""
    assert NBA_INJURY_REFRESH_CRON_HOUR == "11-23,0"
    assert NBA_INJURY_REFRESH_CRON_MINUTE == "7,37"
    assert NBA_INJURY_REFRESH_HOURS == frozenset(
        {0, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
    )
    source = SCHEDULER_PATH.read_text()
    start = source.index("# NBA injury refresh")
    end = source.index("NBA_INJURY_REFRESH_TZ")
    block = source[start:end]
    assert "lineup_fetch_pre_tipoff" not in block
    assert "lineup_fetch_active_window" not in block
    assert "shares the Chicago hours" not in block
    assert "11:00" in block and "00:59" in block


def test_lookback_constant_is_two_hours() -> None:
    """Shifting this duration moves the Chicago edges the cases above lock."""
    from app.services.scheduler import NBA_LINEUP_PRETIPOFF_LOOKBACK

    assert NBA_LINEUP_PRETIPOFF_LOOKBACK == timedelta(hours=2)
