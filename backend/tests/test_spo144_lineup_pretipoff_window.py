"""SPO-144: 5-minute lineup refresh follows each game's own tip.

The window for a game is ``[that tip - 2 hours, that tip)``. A slate
with several tips is open when ``now`` sits in any one of them. NBA
and WNBA use the same gate. Clocks are fixed. Nothing here sleeps or
calls the network. NBA rows come from the recorded BALLDONTLIE
captures. WNBA rows copy fields from the recorded Odds API events list.
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
    NBA_LINEUP_PRETIPOFF_CRON_HOUR,
    NBA_LINEUP_PRETIPOFF_CRON_MINUTE,
    NBA_LINEUP_TIPS_CACHE_TTL_SECONDS,
    SchedulerService,
    nba_lineup_pretipoff_in_window,
    nba_lineup_tips_cache_key,
    tips_from_events_payload,
    tips_from_games_payload,
    wnba_lineup_tips_cache_key,
)
from app.settings import settings

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
ODDS_EVENTS_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "odds_api_events__basketball_nba.json"
)
SCHEDULER_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "scheduler.py"
CHICAGO = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
EVERY_FIVE = "0,5,10,15,20,25,30,35,40,45,50,55"
_TEST_KEY = "unit-test-bdl-key-spo144"
_ODDS_KEY = "unit-test-odds-key-spo144"


def _load(name: str) -> dict:
    """One recorded capture. The file is ``{request, status, response}``."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _load_odds_events() -> list:
    """Recorded Odds API events list. Each object has ``commence_time``."""
    payload = json.loads(ODDS_EVENTS_FIXTURE.read_text())
    assert isinstance(payload, list) and payload
    assert "commence_time" in payload[0]
    return payload


def _wnba_events_at(*stamps: str) -> list[dict]:
    """Recorded event rows with ``commence_time`` set to ``stamps``.

    ``sport_key`` becomes ``basketball_wnba``. Every other field stays
    on the recorded object. ``stamps`` use the recorded ``Z`` form.
    """
    recorded = _load_odds_events()
    assert len(recorded) >= len(stamps)
    events: list[dict] = []
    for stamp, row in zip(stamps, recorded):
        event = deepcopy(row)
        event["sport_key"] = "basketball_wnba"
        event["commence_time"] = stamp
        events.append(event)
    return events


def _chicago(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """A Chicago wall time. Tests pass this as ``now``."""
    return datetime(year, month, day, hour, minute, tzinfo=CHICAGO)


def _eastern_tip(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """UTC instant of a clock time in America/New_York."""
    return datetime(year, month, day, hour, minute, tzinfo=EASTERN).astimezone(timezone.utc)


def _recorded_nov11_tips() -> tuple[datetime, ...]:
    """Every usable tip on the recorded 2026-11-11 slate, oldest first."""
    payload = _load("games_2026-11-11.json")["response"]
    status, tips = tips_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert len(tips) > 1
    return tips


def _recorded_nov11_tip() -> datetime:
    """Earliest tip on the recorded 2026-11-11 slate. 7:00 PM ET."""
    return _recorded_nov11_tips()[0]


def _recorded_rows_at(*stamps: str) -> dict:
    """Copy of the recorded page, keeping only rows with these ``datetime`` values.

    The stamps are copied from ``games_2026-11-11.json``. This does not
    invent a new response shape.
    """
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    wanted = set(stamps)
    payload["data"] = [game for game in payload["data"] if game.get("datetime") in wanted]
    assert payload["data"]
    assert {game["datetime"] for game in payload["data"]} == wanted
    return payload


# 7:00 PM ET on a standard-time night and on a daylight-time night.
# Chicago stays one hour behind Eastern on both. The second tip is
# 9:30 PM ET, so the two windows are 4:00-6:00 PM CT and 6:30-8:30 PM CT.
_STANDARD_TIP = _eastern_tip(2026, 1, 15, 19, 0)
_STANDARD_LATE_TIP = _eastern_tip(2026, 1, 15, 21, 30)
_DAYLIGHT_TIP = _eastern_tip(2026, 7, 15, 19, 0)
_DAYLIGHT_LATE_TIP = _eastern_tip(2026, 7, 15, 21, 30)
_MATINEE_TIP = _eastern_tip(2026, 12, 25, 12, 30)
_MATINEE_NIGHT_TIP = _eastern_tip(2026, 12, 25, 19, 0)
_RECORDED_EARLY = "2026-11-12T00:00:00.000Z"
_RECORDED_LATE = "2026-11-12T02:30:00.000Z"


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
    """One recorded tip is a one-game night: open at 4:00 PM CT, closed at that tip."""
    tip = _recorded_nov11_tip()
    eastern = tip.astimezone(EASTERN)
    assert eastern.hour == 19 and eastern.minute == 0
    assert eastern.date().isoformat() == "2026-11-11"
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 15, 55), tip) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 16, 0), tip) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 18, 0), tip) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 16, 0), (tip,)) is True


@pytest.mark.parametrize(
    ("tips", "closed_before", "early_open", "gap", "late_open", "late_closed"),
    [
        (
            (_STANDARD_TIP, _STANDARD_LATE_TIP),
            _chicago(2026, 1, 15, 15, 55),
            _chicago(2026, 1, 15, 16, 0),
            _chicago(2026, 1, 15, 18, 15),
            _chicago(2026, 1, 15, 18, 30),
            _chicago(2026, 1, 15, 20, 30),
        ),
        (
            (_DAYLIGHT_TIP, _DAYLIGHT_LATE_TIP),
            _chicago(2026, 7, 15, 15, 55),
            _chicago(2026, 7, 15, 16, 0),
            _chicago(2026, 7, 15, 18, 15),
            _chicago(2026, 7, 15, 18, 30),
            _chicago(2026, 7, 15, 20, 30),
        ),
    ],
)
def test_each_game_keeps_its_own_two_hour_window(
    tips: tuple[datetime, datetime],
    closed_before: datetime,
    early_open: datetime,
    gap: datetime,
    late_open: datetime,
    late_closed: datetime,
) -> None:
    """7:00 PM ET and 9:30 PM ET. The gap between them does not scrape."""
    assert nba_lineup_pretipoff_in_window(closed_before, tips) is False
    assert nba_lineup_pretipoff_in_window(early_open, tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(early_open.year, early_open.month, early_open.day, 17, 55), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(early_open.year, early_open.month, early_open.day, 18, 0), tips) is False
    assert nba_lineup_pretipoff_in_window(gap, tips) is False
    assert nba_lineup_pretipoff_in_window(late_open, tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(late_open.year, late_open.month, late_open.day, 20, 25), tips) is True
    assert nba_lineup_pretipoff_in_window(late_closed, tips) is False
    assert nba_lineup_pretipoff_in_window(late_open, tips[0]) is False


def test_matinee_and_evening_game_each_open_their_own_window() -> None:
    """12:30 PM ET still opens 9:30 AM CT. The 7:00 PM ET game is a second window."""
    tips = (_MATINEE_TIP, _MATINEE_NIGHT_TIP)
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 12, 25, 9, 25), tips) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 12, 25, 9, 30), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 12, 25, 11, 30), tips) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 12, 25, 15, 55), tips) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 12, 25, 16, 0), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 12, 25, 18, 0), tips) is False


def test_recorded_two_tip_subset_has_a_gap() -> None:
    """Keep the recorded 7:00 PM ET and 9:30 PM ET rows. The gap is closed."""
    payload = _recorded_rows_at(_RECORDED_EARLY, _RECORDED_LATE)
    status, tips = tips_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert len(tips) == 2
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 16, 0), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 18, 0), tips) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 18, 15), tips) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 18, 30), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 20, 30), tips) is False


def test_full_recorded_slate_stays_open_after_the_first_tip() -> None:
    """Later recorded tips cover 6:00 PM CT. The last tip, 9:00 PM CT, is closed."""
    tips = _recorded_nov11_tips()
    assert tips[0] == datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
    assert tips[-1] == datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 15, 55), tips) is False
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 16, 0), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 18, 0), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 20, 55), tips) is True
    assert nba_lineup_pretipoff_in_window(_chicago(2026, 11, 11, 21, 0), tips) is False


def test_missing_tip_is_outside_the_window() -> None:
    """No game, or a schedule that could not be read, does not open the window."""
    now = _chicago(2026, 11, 11, 16, 0)
    assert nba_lineup_pretipoff_in_window(now, None) is False
    assert nba_lineup_pretipoff_in_window(now, ()) is False
    assert nba_lineup_pretipoff_in_window(now, []) is False


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
    status, tips = tips_from_games_payload(payload, "2026-11-11")
    assert status == "no_games"
    assert tips == ()


def test_non_object_payload_is_unreadable() -> None:
    status, tips = tips_from_games_payload(None, "2026-11-11")
    assert status == "unreadable"
    assert tips == ()


def test_postponed_earliest_games_do_not_set_the_tip() -> None:
    """Flip ``postponed`` on a copy of the recorded rows. The next tip wins."""
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    earliest = min(game["datetime"] for game in payload["data"])
    for game in payload["data"]:
        if game["datetime"] == earliest:
            game["postponed"] = True
    status, tips = tips_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert tips[0] == datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)
    assert datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc) not in tips
    assert datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc) in tips


def test_all_postponed_recorded_games_are_no_games() -> None:
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    for game in payload["data"]:
        game["postponed"] = True
    status, tips = tips_from_games_payload(payload, "2026-11-11")
    assert status == "no_games"
    assert tips == ()


def test_recorded_game_on_another_date_is_ignored() -> None:
    payload = deepcopy(_load("games_2026-11-11.json")["response"])
    earliest = min(game["datetime"] for game in payload["data"])
    for game in payload["data"]:
        if game["datetime"] == earliest:
            game["date"] = "2026-11-10"
    status, tips = tips_from_games_payload(payload, "2026-11-11")
    assert status == "ok"
    assert tips[0] == datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)
    assert datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc) not in tips


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
            service._nba_tips_memory[slate] = ("ok", (_tip_for_moment(moment),))
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
    later_game = _chicago(2026, 11, 11, 18, 30)
    at_last_tip = _chicago(2026, 11, 11, 21, 0)
    seen: dict[str, object] = {}

    async def _go() -> None:
        first = SchedulerService()
        await _run_pre_tipoff(first, outside)
        await _run_pre_tipoff(first, inside)
        await _run_pre_tipoff(first, later_game)
        await _run_pre_tipoff(first, at_last_tip)
        second = SchedulerService()
        await _run_pre_tipoff(second, later_game)
        key = nba_lineup_tips_cache_key("2026-11-11")
        seen["key"] = key
        seen["stored"] = await fake.get(key)
        seen["ttl"] = await fake.ttl(key)
        seen["old"] = await fake.get("lineup:v1:nba:first_tip:2026-11-11")

    asyncio.run(_go())

    assert client.calls == [{"dates": ["2026-11-11"], "per_page": 100}]
    assert client.closed == 1
    assert client.init_kwargs[0]["api_key"] == _TEST_KEY
    assert [call.args[0] for call in fetch.await_args_list] == [
        "2026-11-11",
        "2026-11-11",
        "2026-11-11",
    ]
    assert seen["key"] == "lineup:v1:nba:tips:2026-11-11"
    assert seen["old"] is None
    stored = json.loads(str(seen["stored"]))
    assert stored["status"] == "ok"
    assert "first_tip_utc" not in stored
    assert stored["tips_utc"][0] == "2026-11-12T00:00:00+00:00"
    assert stored["tips_utc"][-1] == "2026-11-12T03:00:00+00:00"
    assert len(stored["tips_utc"]) == len(_recorded_nov11_tips())
    assert seen["ttl"] == NBA_LINEUP_TIPS_CACHE_TTL_SECONDS
    assert NBA_LINEUP_TIPS_CACHE_TTL_SECONDS >= 24 * 60 * 60


def test_later_recorded_game_scrapes_after_the_first_tip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recorded 7:00 PM ET and 9:30 PM ET rows. The gap does not scrape."""
    import asyncio

    fake = _install_cache(monkeypatch)
    payload = _recorded_rows_at(_RECORDED_EARLY, _RECORDED_LATE)
    client = _GamesClient(payload=payload)
    _patch_client(monkeypatch, client)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.lineup_service.fetch_and_store", fetch)

    async def _go() -> None:
        await fake.set(
            "lineup:v1:nba:first_tip:2026-11-11",
            json.dumps(
                {
                    "status": "ok",
                    "first_tip_utc": "2026-11-12T00:00:00+00:00",
                }
            ),
        )
        service = SchedulerService()
        for moment in (
            _chicago(2026, 11, 11, 15, 55),
            _chicago(2026, 11, 11, 16, 0),
            _chicago(2026, 11, 11, 18, 0),
            _chicago(2026, 11, 11, 18, 15),
            _chicago(2026, 11, 11, 18, 30),
            _chicago(2026, 11, 11, 20, 25),
            _chicago(2026, 11, 11, 20, 30),
        ):
            await _run_pre_tipoff(service, moment)

    asyncio.run(_go())

    assert client.calls == [{"dates": ["2026-11-11"], "per_page": 100}]
    assert [call.args[0] for call in fetch.await_args_list] == [
        "2026-11-11",
        "2026-11-11",
        "2026-11-11",
    ]


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
    """Both 5-minute jobs use the wide Chicago grid. Opening and 15-minute stay put."""
    jobs = _registered(SchedulerService())
    nba_func, nba = jobs["lineup_fetch_pre_tipoff"]
    wnba_func, wnba = jobs["wnba_lineup_fetch_pre_tipoff"]
    active_func, _active = jobs["lineup_fetch_active_window"]
    wnba_opening, wnba_opening_job = jobs["wnba_lineup_fetch_opening"]
    wnba_active, wnba_active_job = jobs["wnba_lineup_fetch_active_window"]

    assert nba_func.__name__ == "_run_lineup_fetch_pre_tipoff_job"
    assert active_func.__name__ == "_run_lineup_fetch_job"
    assert wnba_func.__name__ == "_run_wnba_lineup_fetch_pre_tipoff_job"
    assert wnba_opening.__name__ == "_run_wnba_lineup_fetch_job"
    assert wnba_active.__name__ == "_run_wnba_lineup_fetch_job"

    nba_trigger = str(nba["trigger"])
    wnba_trigger = str(wnba["trigger"])
    assert f"hour='{NBA_LINEUP_PRETIPOFF_CRON_HOUR}'" in nba_trigger
    assert f"minute='{NBA_LINEUP_PRETIPOFF_CRON_MINUTE}'" in nba_trigger
    assert NBA_LINEUP_PRETIPOFF_CRON_HOUR == "9-23"
    assert NBA_LINEUP_PRETIPOFF_CRON_MINUTE == EVERY_FIVE
    assert "hour='22,23,0'" not in nba_trigger
    assert "hour='17,18,19'" not in nba_trigger
    assert str(nba["trigger"].timezone) == "America/Chicago"

    assert f"hour='{NBA_LINEUP_PRETIPOFF_CRON_HOUR}'" in wnba_trigger
    assert f"minute='{EVERY_FIVE}'" in wnba_trigger
    assert "hour='17,18,19'" not in wnba_trigger
    assert str(wnba["trigger"].timezone) == "America/Chicago"
    assert wnba_func.__name__ != nba_func.__name__

    assert "hour='11-21'" in str(wnba_active_job["trigger"])
    assert "minute='0,15,30,45'" in str(wnba_active_job["trigger"])
    opening_trigger = str(wnba_opening_job["trigger"])
    assert "hour='9'" in opening_trigger
    assert "minute='30'" in opening_trigger


# ---------------------------------------------------------------------------
# WNBA: same windows, events list, own cache key
# ---------------------------------------------------------------------------


def _patch_wnba_events(monkeypatch: pytest.MonkeyPatch, events: object) -> AsyncMock:
    """Stub ``get_events``. The recorded list is the only body shape used."""
    get_events = AsyncMock(return_value=events)
    monkeypatch.setattr("app.services.odds_theoddsapi.odds_provider.get_events", get_events)
    monkeypatch.setattr(settings, "odds_api_key", _ODDS_KEY)
    return get_events


async def _run_wnba_pre_tipoff(service: SchedulerService, now: datetime) -> None:
    await service._run_wnba_lineup_fetch_pre_tipoff_job(now=now)


def test_recorded_odds_events_keep_their_eastern_slate() -> None:
    """The captured events list. 2026-11-10T00:10:00Z is the evening of 2026-11-09."""
    payload = _load_odds_events()
    status, tips = tips_from_events_payload(payload, "2026-11-09")
    assert status == "ok"
    assert datetime(2026, 11, 10, 0, 10, tzinfo=timezone.utc) in tips
    empty_status, empty_tips = tips_from_events_payload(payload, "1900-01-01")
    assert empty_status == "no_games"
    assert empty_tips == ()
    bad_status, bad_tips = tips_from_events_payload({"data": []}, "2026-11-09")
    assert bad_status == "unreadable"
    assert bad_tips == ()


@pytest.mark.parametrize(
    ("early_stamp", "late_stamp", "day"),
    [
        ("2026-01-16T00:00:00Z", "2026-01-16T02:30:00Z", (2026, 1, 15)),
        ("2026-07-15T23:00:00Z", "2026-07-16T01:30:00Z", (2026, 7, 15)),
    ],
)
def test_wnba_each_game_keeps_its_own_two_hour_window(
    monkeypatch: pytest.MonkeyPatch,
    early_stamp: str,
    late_stamp: str,
    day: tuple[int, int, int],
) -> None:
    """7:00 PM ET and 9:30 PM ET. The gap does not scrape. One events call."""
    import asyncio

    year, month, date = day
    _install_cache(monkeypatch)
    events = _wnba_events_at(early_stamp, late_stamp)
    get_events = _patch_wnba_events(monkeypatch, events)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)
    bdl = AsyncMock(side_effect=AssertionError("nba games must not be called"))
    monkeypatch.setattr("app.services.bdl_client.BdlClient", bdl)

    clocks = [
        (_chicago(year, month, date, 15, 55), False),
        (_chicago(year, month, date, 16, 0), True),
        (_chicago(year, month, date, 17, 55), True),
        (_chicago(year, month, date, 18, 0), False),
        (_chicago(year, month, date, 18, 15), False),
        (_chicago(year, month, date, 18, 30), True),
        (_chicago(year, month, date, 20, 25), True),
        (_chicago(year, month, date, 20, 30), False),
    ]
    slate = clocks[1][0].astimezone(EASTERN).date().isoformat()

    async def _go() -> None:
        service = SchedulerService()
        for moment, _open in clocks:
            await _run_wnba_pre_tipoff(service, moment)
        second = SchedulerService()
        await _run_wnba_pre_tipoff(second, clocks[5][0])

    asyncio.run(_go())

    fired = [call.args[0] for call in fetch.await_args_list]
    assert fired == [slate, slate, slate, slate, slate]
    assert get_events.await_count == 1
    assert get_events.await_args.kwargs == {"league": "wnba"}
    assert _ODDS_KEY not in str(get_events.await_args)
    bdl.assert_not_called()


@pytest.mark.parametrize(
    ("matinee_stamp", "night_stamp", "day", "slate"),
    [
        ("2026-12-25T17:30:00Z", "2026-12-26T00:00:00Z", (2026, 12, 25), "2026-12-25"),
        ("2026-07-15T16:30:00Z", "2026-07-15T23:00:00Z", (2026, 7, 15), "2026-07-15"),
    ],
)
def test_wnba_matinee_and_evening_each_open(
    monkeypatch: pytest.MonkeyPatch,
    matinee_stamp: str,
    night_stamp: str,
    day: tuple[int, int, int],
    slate: str,
) -> None:
    """12:30 PM ET opens 9:30 AM CT. The 7:00 PM ET game is a second window."""
    import asyncio

    year, month, date = day
    _install_cache(monkeypatch)
    events = _wnba_events_at(matinee_stamp, night_stamp)
    get_events = _patch_wnba_events(monkeypatch, events)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)

    clocks = [
        (_chicago(year, month, date, 9, 25), False),
        (_chicago(year, month, date, 9, 30), True),
        (_chicago(year, month, date, 11, 25), True),
        (_chicago(year, month, date, 11, 30), False),
        (_chicago(year, month, date, 15, 55), False),
        (_chicago(year, month, date, 16, 0), True),
        (_chicago(year, month, date, 17, 55), True),
        (_chicago(year, month, date, 18, 0), False),
    ]

    async def _go() -> None:
        service = SchedulerService()
        for moment, _open in clocks:
            await _run_wnba_pre_tipoff(service, moment)

    asyncio.run(_go())
    assert [call.args[0] for call in fetch.await_args_list] == [slate] * 4
    assert get_events.await_count == 1


@pytest.mark.parametrize(
    ("stamp", "day", "slate"),
    [
        ("2026-01-16T00:00:00Z", (2026, 1, 15), "2026-01-15"),
        ("2026-07-15T23:00:00Z", (2026, 7, 15), "2026-07-15"),
    ],
)
def test_wnba_single_game_closes_at_that_tip(
    monkeypatch: pytest.MonkeyPatch,
    stamp: str,
    day: tuple[int, int, int],
    slate: str,
) -> None:
    """One recorded row, retimed to 7:00 PM ET. 6:00 PM CT does not scrape."""
    import asyncio

    year, month, date = day
    _install_cache(monkeypatch)
    events = _wnba_events_at(stamp)
    _patch_wnba_events(monkeypatch, events)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)

    async def _go() -> None:
        service = SchedulerService()
        await _run_wnba_pre_tipoff(service, _chicago(year, month, date, 15, 55))
        await _run_wnba_pre_tipoff(service, _chicago(year, month, date, 16, 0))
        await _run_wnba_pre_tipoff(service, _chicago(year, month, date, 18, 0))

    asyncio.run(_go())
    assert [call.args[0] for call in fetch.await_args_list] == [slate]


def test_wnba_tips_are_cached_apart_from_nba(monkeypatch: pytest.MonkeyPatch) -> None:
    """The WNBA key holds both tips. A value under the NBA key is not the slate."""
    import asyncio

    fake = _install_cache(monkeypatch)
    events = _wnba_events_at("2026-07-15T23:00:00Z", "2026-07-16T01:30:00Z")
    get_events = _patch_wnba_events(monkeypatch, events)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)
    seen: dict[str, object] = {}

    async def _go() -> None:
        await fake.set(
            nba_lineup_tips_cache_key("2026-07-15"),
            json.dumps({"status": "no_games", "tips_utc": []}),
        )
        service = SchedulerService()
        await _run_wnba_pre_tipoff(service, _chicago(2026, 7, 15, 18, 30))
        key = wnba_lineup_tips_cache_key("2026-07-15")
        seen["stored"] = await fake.get(key)
        seen["nba"] = await fake.get(nba_lineup_tips_cache_key("2026-07-15"))

    asyncio.run(_go())
    assert get_events.await_count == 1
    fetch.assert_awaited_once_with("2026-07-15")
    stored = json.loads(str(seen["stored"]))
    assert stored["status"] == "ok"
    assert stored["tips_utc"] == [
        "2026-07-15T23:00:00+00:00",
        "2026-07-16T01:30:00+00:00",
    ]
    assert json.loads(str(seen["nba"]))["status"] == "no_games"


def test_wnba_no_games_does_not_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    _install_cache(monkeypatch)
    get_events = _patch_wnba_events(monkeypatch, [])
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)

    async def _go() -> None:
        service = SchedulerService()
        moment = _chicago(2026, 7, 15, 16, 0)
        await _run_wnba_pre_tipoff(service, moment)
        await _run_wnba_pre_tipoff(service, moment)

    asyncio.run(_go())
    assert get_events.await_count == 1
    fetch.assert_not_awaited()


def test_wnba_schedule_error_warns_once_and_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The 15-minute WNBA handler still scrapes. It does not read events."""
    import asyncio

    _install_cache(monkeypatch)
    get_events = AsyncMock(side_effect=RuntimeError("schedule down"))
    monkeypatch.setattr("app.services.odds_theoddsapi.odds_provider.get_events", get_events)
    monkeypatch.setattr(settings, "odds_api_key", _ODDS_KEY)
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)
    caplog.set_level(logging.WARNING, logger="app.services.scheduler")

    async def _go() -> None:
        service = SchedulerService()
        moment = _chicago(2026, 7, 15, 16, 0)
        await _run_wnba_pre_tipoff(service, moment)
        await _run_wnba_pre_tipoff(service, moment)
        await service._run_wnba_lineup_fetch_job(now=moment)

    asyncio.run(_go())
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "schedule unreadable" in record.getMessage()
    ]
    assert warnings == [
        "wnba_lineup_fetch_pre_tipoff schedule unreadable (RuntimeError); skipping the 5-minute window"
    ]
    assert get_events.await_count == 1
    fetch.assert_awaited_once_with("2026-07-15")
    assert _ODDS_KEY not in caplog.text


def test_wnba_missing_odds_key_does_not_call_events(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    _install_cache(monkeypatch)
    get_events = AsyncMock(side_effect=AssertionError("events called without a key"))
    monkeypatch.setattr("app.services.odds_theoddsapi.odds_provider.get_events", get_events)
    monkeypatch.setattr(settings, "odds_api_key", "   ")
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.scheduler.wnba_lineup_service.fetch_and_store", fetch)
    caplog.set_level(logging.WARNING, logger="app.services.scheduler")

    async def _go() -> None:
        service = SchedulerService()
        moment = _chicago(2026, 1, 15, 16, 0)
        await _run_wnba_pre_tipoff(service, moment)
        await _run_wnba_pre_tipoff(service, moment)

    asyncio.run(_go())
    get_events.assert_not_awaited()
    fetch.assert_not_awaited()
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings == [
        "wnba_lineup_fetch_pre_tipoff schedule unreadable (ODDS_API_KEY is unset); skipping the 5-minute window"
    ]


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
