"""SPO-143: odds snapshot crons stay on Eastern wall-clock time.

The three jobs used to inherit the scheduler's UTC timezone. Under
daylight time that moves the final run to 7:35 PM Eastern, after
7:00 and 7:30 PM tip-offs. These tests ask each trigger for its next
fire time. They do not sleep and they do not open a network socket.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.scheduler import SchedulerService

EASTERN = ZoneInfo("America/New_York")

# Same Eastern clock in July (EDT, UTC-4) and January (EST, UTC-5).
WALL_CLOCK = {
    "odds_snapshot_early": (11, 5),
    "odds_snapshot_mid": (17, 5),
    "odds_snapshot_final": (18, 35),
}

JULY = datetime(2026, 7, 15, 0, 0, tzinfo=EASTERN)
JANUARY = datetime(2026, 1, 15, 0, 0, tzinfo=EASTERN)

_COMMENT_PHRASES = (
    "11:05",
    "17:05",
    "18:35",
    "America/New_York",
)
_COMMENT_FORBIDDEN = (
    "UTC 16:00",
    "UTC 22:00",
    "UTC 23:30",
)


def _comment_block() -> str:
    """The note above the three odds snapshot registrations."""
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "scheduler.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("# Add odds snapshot jobs")
    end = text.index("self._scheduler.add_job(", start)
    return text[start:end]


@pytest.fixture
def started():
    """Register jobs on a stand-in scheduler and return the three triggers.

    ``AsyncIOScheduler.start`` is not the real one, so nothing waits for
    a fire time. The ``CronTrigger`` objects are the ones ``start()`` built.
    """
    with patch("app.services.scheduler.AsyncIOScheduler") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.get_jobs.return_value = []
        mock_cls.return_value = mock_instance
        service = SchedulerService()
        service.start()
        triggers: dict[str, CronTrigger] = {}
        for call in mock_instance.add_job.call_args_list:
            job_id = call.kwargs.get("id")
            if job_id in WALL_CLOCK:
                triggers[job_id] = call.kwargs["trigger"]
        yield triggers, mock_cls.call_args.kwargs


class TestOddsSnapshotEasternWallClock:
    def test_scheduler_default_stays_utc(self, started):
        _, init_kwargs = started
        assert init_kwargs["timezone"] == "UTC"

    @pytest.mark.parametrize(
        "when",
        [JULY, JANUARY],
        ids=["july", "january"],
    )
    def test_next_fire_is_eastern_wall_clock(self, started, when):
        triggers, _ = started
        assert set(triggers) == set(WALL_CLOCK)
        for job_id, (hour, minute) in WALL_CLOCK.items():
            trigger = triggers[job_id]
            assert isinstance(trigger, CronTrigger)
            nxt = trigger.get_next_fire_time(None, when)
            assert nxt is not None
            local = nxt.astimezone(EASTERN)
            assert local.date() == when.date()
            assert (local.hour, local.minute, local.second) == (hour, minute, 0), (
                f"{job_id} next fire from {when.isoformat()} is "
                f"{local.isoformat()}, expected {hour:02d}:{minute:02d} "
                "America/New_York"
            )

    def test_final_run_is_before_7pm_et_on_a_daylight_date(self, started):
        triggers, _ = started
        nxt = triggers["odds_snapshot_final"].get_next_fire_time(None, JULY)
        assert nxt is not None
        local = nxt.astimezone(EASTERN)
        seven_pm = datetime(2026, 7, 15, 19, 0, tzinfo=EASTERN)
        assert local < seven_pm, (
            f"final run {local.isoformat()} is not before 7:00 PM ET on {JULY.date()}"
        )

    def test_comment_matches_the_eastern_schedule(self):
        comment = _comment_block()
        for phrase in _COMMENT_PHRASES:
            assert phrase in comment
        for phrase in _COMMENT_FORBIDDEN:
            assert phrase not in comment

    def test_startup_line_names_the_eastern_clock(self, capsys, started):
        out = capsys.readouterr().out
        assert "Odds Snapshot: Daily 11:05, 17:05, 18:35 America/New_York" in out
        assert "Odds Snapshot: Daily UTC 16:05, 22:05, 23:35" not in out
