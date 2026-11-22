"""A planner pass must not run a closing line twice.

The first alarm fires at tip minus 10 minutes. APScheduler then drops
that one-shot job. The daily, 30-minute, and startup planners call
``plan_odds_pretip_closes`` again and ``schedule_pretip_closes`` adds
every tip minute back, including a run_date that is already a few
minutes in the past. ``misfire_grace_time`` is 480 seconds, so a past
run_date inside that window is still eligible. This test uses a
scheduler that is running, not paused. A paused scheduler never fires
the alarm, so it cannot see the second pass.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.odds_snapshot_service import odds_snapshot_service
from app.services.scheduler import (
    ODDS_PRETIP_LEAD,
    ODDS_PRETIP_MISFIRE_GRACE_SECONDS,
    SchedulerService,
    pretip_job_id,
)
from app.services.slate_date import nba_slate_date


def _running_scheduler() -> AsyncIOScheduler:
    """The same defaults as ``SchedulerService.start``, and not paused.

    Closing jobs pass their own 480-second grace. The one-hour default
    is what a job inherits when it does not pass a grace of its own.
    """
    sched = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )
    sched.start()
    return sched


def _stop(sched: AsyncIOScheduler | None) -> None:
    if sched is not None and getattr(sched, "running", False):
        sched.shutdown(wait=False)


async def _until(ready, seconds: float) -> bool:
    """Poll ``ready`` until it is true or ``seconds`` have passed."""
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if ready():
            return True
        await asyncio.sleep(0.02)
    return ready()


@pytest.mark.asyncio
async def test_planner_rerun_does_not_refire_a_close_inside_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One close for a tip already inside the grace window, and the later alarm stays.

    The past tip's run_date is two minutes ago, which is inside the
    480-second grace, and the tip itself is still ahead. The other tip
    is forty-five minutes ahead, so its run_date is still in the future.
    The first planner pass lets the running scheduler fire the past
    alarm once. The second pass is the 30-minute planner again. That
    pass must not fetch or write the close a second time, and the
    future alarm must still be registered.
    """
    clock = datetime.now(timezone.utc)
    past_tip = clock + timedelta(minutes=8)
    future_tip = clock + timedelta(minutes=45)
    slate = nba_slate_date(clock)[0]
    past_id = pretip_job_id(slate, past_tip)
    future_id = pretip_job_id(slate, future_tip)
    assert past_id != future_id
    closes: list[datetime] = []

    async def _close(slate_date: str, tip: datetime, *, now: datetime | None = None) -> dict:
        # One call is one fetch of the board and one write of the close.
        closes.append(tip)
        return {
            "date": slate_date,
            "event_count": 1,
            "total_lines": 1,
            "bdl_parent_misses": 0,
            "locked": False,
        }

    monkeypatch.setattr(odds_snapshot_service, "take_closing_snapshot", _close)

    service = SchedulerService()
    service._scheduler = _running_scheduler()

    async def _tips(slate_date: str) -> tuple[str, tuple[datetime, ...]]:
        assert slate_date == slate
        return ("ok", (past_tip, future_tip))

    monkeypatch.setattr(service, "_nba_tips_for_slate", _tips)
    try:
        first = await service.plan_odds_pretip_closes(now=clock)
        assert first == sorted([past_id, future_id])
        fired = await _until(
            lambda: len(closes) == 1 and service._scheduler.get_job(past_id) is None,
            3,
        )
        assert fired, closes
        assert closes == [past_tip]
        # The executor drops its instance count on the task callback.
        await asyncio.sleep(0.05)

        again_at = datetime.now(timezone.utc)
        past_run = past_tip - ODDS_PRETIP_LEAD
        assert again_at < past_tip
        assert timedelta(0) < (again_at - past_run) <= timedelta(
            seconds=ODDS_PRETIP_MISFIRE_GRACE_SECONDS
        )
        future_before = service._scheduler.get_job(future_id)
        assert future_before is not None
        future_run_before = future_before.trigger.run_date

        second = await service.plan_odds_pretip_closes(now=clock)
        assert future_id in second
        await _until(lambda: len(closes) > 1, 2)

        future_after = service._scheduler.get_job(future_id)
        assert future_after is not None
        assert future_after.id == future_id
        assert future_after.trigger.run_date == future_run_before
        run_at = future_after.trigger.run_date
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        assert run_at.astimezone(timezone.utc) == (future_tip - ODDS_PRETIP_LEAD).astimezone(
            timezone.utc
        )
        assert run_at > datetime.now(timezone.utc)
        assert future_after.misfire_grace_time == ODDS_PRETIP_MISFIRE_GRACE_SECONDS
        assert future_tip not in closes
        assert closes == [past_tip]
    finally:
        _stop(service._scheduler)
