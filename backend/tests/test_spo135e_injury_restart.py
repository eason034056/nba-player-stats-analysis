"""SPO-135e: startup refill and a missed injury tick.

A stale key is refilled once at startup only inside the slate window.
Outside the window a missing key still refreshes, and a stale key does
not. That leaves injury_status null until the next in-window :07 or
:37 (11:07 America/Chicago after an overnight restart). The cron grace
is 25 minutes with coalesce, so one missed tick runs once and a burst
does not. A fill on the analysis run was not added: that function is
also the HTTP handler, and a request-path BALLDONTLIE call spends the
shared budget.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.scheduler import (
    NBA_INJURY_REFRESH_MISFIRE_GRACE_SECONDS,
    SchedulerService,
)


def _spy(monkeypatch):
    calls: list[bool | None] = []

    async def _run(self, **kwargs):
        calls.append(kwargs.get("force"))
        return {"entries": []}

    monkeypatch.setattr(SchedulerService, "_run_nba_injuries_refresh_job", _run)
    return calls


def _body(*, stale: bool, entries: object | None = None) -> dict:
    age = timedelta(hours=7) if stale else timedelta(minutes=5)
    fetched_at = (datetime.now(timezone.utc) - age).isoformat()
    return {
        "fetched_at": fetched_at,
        "entries": [] if entries is None else entries,
    }


def _install(monkeypatch, *, inside: bool, raw):
    async def _get(_key):
        return raw

    monkeypatch.setattr(
        "app.services.scheduler.nba_injury_refresh_in_window",
        lambda now=None: inside,
    )
    monkeypatch.setattr("app.services.cache.cache_service.get", _get)


def test_misfire_grace_runs_one_missed_tick() -> None:
    from apscheduler.triggers.cron import CronTrigger

    scheduler = SchedulerService()
    with patch("app.services.scheduler.AsyncIOScheduler") as mock_sched:
        instance = MagicMock()
        instance.get_jobs.return_value = []
        mock_sched.return_value = instance
        scheduler.start()
    found = None
    for call in instance.add_job.call_args_list:
        _args, kwargs = call
        if kwargs.get("id") == "nba_injuries_refresh":
            found = kwargs
    assert found is not None
    assert isinstance(found["trigger"], CronTrigger)
    assert found["misfire_grace_time"] == NBA_INJURY_REFRESH_MISFIRE_GRACE_SECONDS
    assert NBA_INJURY_REFRESH_MISFIRE_GRACE_SECONDS == 25 * 60
    assert found["coalesce"] is True
    assert found["max_instances"] == 1


def test_startup_refills_a_stale_key_inside_the_window(monkeypatch) -> None:
    calls = _spy(monkeypatch)
    _install(monkeypatch, inside=True, raw=_body(stale=True))
    asyncio.run(SchedulerService()._fill_nba_injuries_if_missing())
    assert calls == [True]


def test_startup_does_not_refill_a_stale_key_outside_the_window(monkeypatch) -> None:
    calls = _spy(monkeypatch)
    _install(monkeypatch, inside=False, raw=_body(stale=True))
    asyncio.run(SchedulerService()._fill_nba_injuries_if_missing())
    assert calls == []


def test_startup_still_fills_a_missing_key_outside_the_window(monkeypatch) -> None:
    calls = _spy(monkeypatch)
    _install(monkeypatch, inside=False, raw=None)
    asyncio.run(SchedulerService()._fill_nba_injuries_if_missing())
    assert calls == [True]


def test_startup_leaves_a_fresh_key_in_place(monkeypatch) -> None:
    calls = _spy(monkeypatch)
    _install(monkeypatch, inside=True, raw=_body(stale=False))
    asyncio.run(SchedulerService()._fill_nba_injuries_if_missing())
    assert calls == []


def test_startup_refills_a_malformed_key_inside_the_window(monkeypatch) -> None:
    """Readers already refuse a non-list entries body. Startup replaces it."""
    calls = _spy(monkeypatch)
    _install(monkeypatch, inside=True, raw=_body(stale=False, entries="nope"))
    asyncio.run(SchedulerService()._fill_nba_injuries_if_missing())
    assert calls == [True]
