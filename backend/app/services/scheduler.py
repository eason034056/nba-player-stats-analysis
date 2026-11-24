"""
scheduler.py - Scheduled Job Scheduler

Implements scheduled jobs using APScheduler for daily automation

APScheduler (Advanced Python Scheduler) is a lightweight Python scheduling library.
Advantages:
- No need for external services (such as Celery + Redis/RabbitMQ)
- Supports multiple triggers (cron, interval, date)
- Suitable for single-machine deployment

Main features:
- Run daily analysis at a fixed time every day
- Download the latest NBA player stats CSV daily
- Supports manual trigger
- Error handling and retry

Scheduling strategy:
- Daily analysis: Run every day at UTC 12:00 (7:00 AM US Eastern / 20:00 Taipei)
- CSV download: Run every day at 10:00 Chicago time (handles DST automatically)
- NBA games are usually at night US Eastern, by this time odds have stabilized
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import ConflictingIdError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.daily_analysis import daily_analysis_service
from app.services.csv_downloader import csv_downloader_service
from app.services.odds_gateway import odds_gateway
from app.services.odds_snapshot_service import odds_snapshot_service
from app.services.lineup_service import lineup_service
from app.services.slate_date import nba_slate_date
from app.services.nba_injuries import (
    NBA_INJURIES_CACHE_KEY,
    injury_snapshot_is_fresh,
    refresh_nba_injuries_from_bdl,
)
from app.settings import settings

logger = logging.getLogger(__name__)

# NBA injury refresh window. These hours belong to this job.
# They are 11:00 through 00:59 America/Chicago.
# nba_slate_date uses America/New_York. Chicago stays one hour behind
# Eastern in both standard and daylight time, so the same window is
# 12:00 through 01:59 America/New_York.
# Minutes are :07 and :37 so the job does not land on :00, :05, :15,
# :30, :35, or :45, which the other jobs already use. Two ticks an hour
# is one refresh every 30 minutes, which is the cap. Those marks stay.
# A daily snapshot on another machine uses the same key, cannot see this
# Redis limiter, and runs once between 4:45 and 5:30 PM CT. It makes at
# most 5 calls, 20 seconds apart, and can land on :07. The injury client
# answers that 429 with one bounded retry. See BdlClient rate_limit_policy.
NBA_INJURY_REFRESH_TZ = ZoneInfo("America/Chicago")
NBA_INJURY_REFRESH_HOURS = frozenset(
    {0, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
)
NBA_INJURY_REFRESH_CRON_HOUR = "11-23,0"
NBA_INJURY_REFRESH_CRON_MINUTE = "7,37"
# A restart that misses :07 or :37 by less than 25 minutes runs that
# tick once. coalesce is set on the job, so several missed ticks become
# one run and the job does not burst. One second dropped a tick the
# process had just missed. 25 minutes is inside the 30-minute gap, so
# the next scheduled tick is not also due.
NBA_INJURY_REFRESH_MISFIRE_GRACE_SECONDS = 25 * 60

# Official injury-report PDFs. Registered only when
# INJURY_PDF_FETCH_ENABLED is true. The handler returns before any HTTP
# call unless today's Eastern date has a non-postponed NBA game.
INJURY_PDF_FETCH_CRON_MINUTE = "0,15,30,45"


def nba_injury_refresh_in_window(now: datetime | None = None) -> bool:
    """True when ``now`` falls in the NBA injury slate window.

    ``now`` defaults to the current time. A naive datetime is read as
    UTC. The window is 11:00 through 00:59 America/Chicago. Outside
    that window the scheduled job must not call BALLDONTLIE.

    Args:
        now: Instant to test. None means the current time.

    Returns:
        True during the slate window, including 11:00 and 00:59 Chicago.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(NBA_INJURY_REFRESH_TZ)
    return local.hour in NBA_INJURY_REFRESH_HOURS


# Outer cron for the NBA 5-minute pre-tipoff job. The handler
# returns before the scrape unless now is in [tip - 2 hours, tip) for
# some game on the slate. 09:00 Chicago covers a 12:30 PM ET matinee,
# whose window opens at 09:30 CT. 22:55 is the last tick. No window
# reaches 23:00 Chicago. The 15-minute registration below uses
# LINEUP_ACTIVE_WINDOW_* and runs through 21:45.
NBA_LINEUP_PRETIPOFF_TZ = ZoneInfo("America/Chicago")
NBA_LINEUP_PRETIPOFF_LOOKBACK = timedelta(hours=2)
NBA_LINEUP_PRETIPOFF_CRON_HOUR = "9-22"
NBA_LINEUP_PRETIPOFF_CRON_MINUTE = "0,5,10,15,20,25,30,35,40,45,50,55"
# lineup_fetch_active_window uses these fields. The 5-minute handler
# skips a tick these fields already cover.
LINEUP_ACTIVE_WINDOW_TZ = ZoneInfo("America/Chicago")
LINEUP_ACTIVE_WINDOW_CRON_HOUR = "11-21"
LINEUP_ACTIVE_WINDOW_CRON_MINUTE = "0,15,30,45"
# One Eastern slate, including a restart later that same night. The next
# slate date is a different key, so this does not have to expire at midnight.
NBA_LINEUP_TIPS_CACHE_TTL_SECONDS = 36 * 60 * 60

# Pre-tip closing line. The alarm is ten minutes before tip. The memory
# job store forgets alarms when the process stops, so the planner builds
# them again on start. Eight minutes of grace is inside that ten-minute
# gap. The scheduler default is one hour. Leaving the default in place
# would run a missed alarm after tip and store in-game prices as the close.
ODDS_PRETIP_LEAD = timedelta(minutes=10)
ODDS_PRETIP_MISFIRE_GRACE_SECONDS = 8 * 60
ODDS_PRETIP_LOCK_TTL_SECONDS = 8 * 60
# Once a day, before the evening slate, on a minute the other jobs do not use.
ODDS_PRETIP_PLANNER_DAILY_HOUR = 8
ODDS_PRETIP_PLANNER_DAILY_MINUTE = 2
ODDS_PRETIP_PLANNER_DAILY_TZ = "America/New_York"
ODDS_PRETIP_PLANNER_INTERVAL_MINUTES = 30


def _expand_cron_field(expr: str) -> frozenset[int]:
    """Every integer a cron hour or minute field names.

    ``11-21`` is 11 through 21. ``0,15,30,45`` is those four minutes.
    A comma may mix ranges and single numbers. The 15-minute lineup
    registration and ``lineup_active_window_covers`` both read the
    expanded form of ``LINEUP_ACTIVE_WINDOW_CRON_HOUR`` and
    ``LINEUP_ACTIVE_WINDOW_CRON_MINUTE``.

    Args:
        expr: One cron field, as passed to ``CronTrigger``.

    Returns:
        The values that field matches.
    """
    values: set[int] = set()
    for part in expr.split(","):
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            values.update(range(int(start_s), int(end_s) + 1))
        else:
            values.add(int(part))
    return frozenset(values)


LINEUP_ACTIVE_WINDOW_HOURS = _expand_cron_field(LINEUP_ACTIVE_WINDOW_CRON_HOUR)
LINEUP_ACTIVE_WINDOW_MINUTES = _expand_cron_field(LINEUP_ACTIVE_WINDOW_CRON_MINUTE)


def lineup_active_window_covers(now: datetime) -> bool:
    """True when the 15-minute lineup job already fires at this Chicago tick.

    ``lineup_active_window_covers`` is the gate that keeps the 5-minute
    pre-tipoff handler from scraping a minute the 15-minute job scrapes.
    That job is registered with ``LINEUP_ACTIVE_WINDOW_CRON_HOUR`` and
    ``LINEUP_ACTIVE_WINDOW_CRON_MINUTE``. A tick at 22:00 Chicago is
    outside those hours, so the 5-minute job still scrapes it.

    A naive ``now`` is read as UTC.

    Args:
        now: Instant to test.

    Returns:
        True when the Chicago hour and minute are both in the 15-minute cron.
    """
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = moment.astimezone(LINEUP_ACTIVE_WINDOW_TZ)
    return local.hour in LINEUP_ACTIVE_WINDOW_HOURS and local.minute in LINEUP_ACTIVE_WINDOW_MINUTES


def nba_lineup_tips_cache_key(slate_date: str) -> str:
    """Redis key for every usable NBA tip on one Eastern slate date.

    ``slate_date`` is ``nba_slate_date()[0]`` (``YYYY-MM-DD``). The value
    is the status and the UTC tips, not the games payload. The key is
    ``tips``, not ``first_tip``, so an older single-tip value is not read.

    Args:
        slate_date: Eastern game date.

    Returns:
        ``lineup:v1:nba:tips:<slate_date>``.
    """
    return f"lineup:v1:nba:tips:{slate_date}"


def _as_utc(moment: datetime) -> datetime:
    """UTC form of ``moment``. A naive datetime is read as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def nba_lineup_pretipoff_in_window(
    now: datetime,
    tips_utc: datetime | None | tuple[datetime, ...] | list[datetime],
) -> bool:
    """True when ``now`` is in ``[tip - 2 hours, tip)`` for any tip.

    ``nba_lineup_pretipoff_in_window`` is the gate for the 5-minute NBA
    lineup scrape. Call it with the clock you are deciding for and every
    tip on that slate. One datetime is a one-game night. ``None`` or an
    empty list is outside the window. Each end is exclusive, so the tick
    at a tip does not scrape for that game. A later game on the same
    night still opens its own window.

    The 2 hours are ``NBA_LINEUP_PRETIPOFF_LOOKBACK``. A naive ``now``
    or tip is read as UTC.
    This function does not read a schedule.

    Args:
        now: Instant to test.
        tips_utc: One tip, or every tip, UTC. None skips the scrape.

    Returns:
        True when ``now`` sits in at least one half-open window.
    """
    if tips_utc is None:
        return False
    if isinstance(tips_utc, datetime):
        tips: tuple[datetime, ...] | list[datetime] = (tips_utc,)
    else:
        tips = tips_utc
    moment = _as_utc(now)
    for tip in tips:
        tip_utc = _as_utc(tip)
        start = tip_utc - NBA_LINEUP_PRETIPOFF_LOOKBACK
        if start <= moment < tip_utc:
            return True
    return False


def _parse_tip(value: object) -> datetime | None:
    """Parse one ISO tip. ``Z`` means UTC. None when the text is unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def tips_from_games_payload(
    payload: object,
    slate_date: str,
) -> tuple[str, tuple[datetime, ...]]:
    """Every usable tip on ``slate_date`` from one ``GET /v1/games`` body.

    ``tips_from_games_payload`` reads the ``data`` list. A postponed game
    does not count. A game whose ``date`` is a different Eastern day does
    not count. The tip is the game's ``datetime``. Duplicate instants
    collapse to one, oldest first.

    Args:
        payload: The JSON object ``list_games`` returns (``data`` plus ``meta``).
        slate_date: Eastern game date that was requested.

    Returns:
        ``("ok", tips)`` when at least one game will tip.
        ``("no_games", ())`` when ``data`` is a list and nothing will tip.
        ``("unreadable", ())`` when the body is not that object, or a
        game that is not postponed has no usable tip and no other game does.
    """
    if not isinstance(payload, dict):
        return ("unreadable", ())
    data = payload.get("data")
    if not isinstance(data, list):
        return ("unreadable", ())
    tips: list[datetime] = []
    saw_unusable = False
    for game in data:
        if not isinstance(game, dict):
            saw_unusable = True
            continue
        if game.get("postponed") is True:
            continue
        tip = _parse_tip(game.get("datetime"))
        if tip is None:
            saw_unusable = True
            continue
        game_date = game.get("date")
        if isinstance(game_date, str) and game_date != slate_date:
            continue
        if nba_slate_date(tip)[0] != slate_date:
            continue
        tips.append(tip)
    if tips:
        return ("ok", tuple(sorted(set(tips))))
    if saw_unusable:
        return ("unreadable", ())
    return ("no_games", ())


def _cached_tips(raw: object) -> tuple[str, tuple[datetime, ...]] | None:
    """Decode a cached tip list. None means the caller should read again.

    A body that only has ``first_tip_utc`` is not this shape, so it is
    not used.
    """
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status == "ok":
        raw_tips = raw.get("tips_utc")
        if not isinstance(raw_tips, list) or not raw_tips:
            return None
        tips: list[datetime] = []
        for item in raw_tips:
            tip = _parse_tip(item)
            if tip is None:
                return None
            tips.append(tip)
        return ("ok", tuple(sorted(set(tips))))
    if status in {"no_games", "unreadable"}:
        return (status, ())
    return None


def _schedule_is_durable(status: str) -> bool:
    """True when a slate status is kept for the rest of that slate.

    ``ok``, ``no_games``, and ``unreadable`` are kept. ``unreadable`` is
    a missing key or a body with no usable tip. ``transient`` is a failed
    call. It is not kept, so the next tick reads again.

    Args:
        status: The status half of a tips result.

    Returns:
        True when the caller should write memory and Redis.
    """
    return status in {"ok", "no_games", "unreadable"}


def _dump_tips(status: str, tips: tuple[datetime, ...]) -> dict[str, str | list[str] | None]:
    """JSON-ready cache body. Each tip is UTC ISO text."""
    return {
        "status": status,
        "tips_utc": [tip.isoformat() for tip in tips],
    }


def pretip_hhmm(tip: datetime) -> str:
    """UTC ``HHMM`` of one tip.

    ``pretip_hhmm`` is the minute written on the pre-tip job id and on
    the Redis lock. ``HHMM`` means hour and minute, zero-padded, in UTC.
    Games that tip in that same UTC minute share one alarm. A naive
    ``tip`` is read as UTC.

    Args:
        tip: The game's tip instant.

    Returns:
        Four characters, such as ``0000`` for 00:00 UTC.
    """
    return _as_utc(tip).strftime("%H%M")


def pretip_job_id(slate_date: str, tip: datetime) -> str:
    """Scheduler id for one slate minute.

    ``pretip_job_id`` builds ``odds_pretip:<date>:<HHMM>``. The date is
    the Eastern slate date, not the UTC date of the tip. Replacing a job
    with this id updates the alarm instead of adding a second one.

    Args:
        slate_date: Eastern game date, ``YYYY-MM-DD``.
        tip: Any tip in that UTC minute. The minute comes from ``pretip_hhmm``.

    Returns:
        The job id string.
    """
    return f"odds_pretip:{slate_date}:{pretip_hhmm(tip)}"


def pretip_lock_key(slate_date: str, tip: datetime) -> str:
    """Redis lock for one slate minute.

    ``pretip_lock_key`` is ``odds:v1:pretip-lock:<date>:<HHMM>``. ``v1``
    is the key version. Two replicas that run the same minute both try
    this key. Only the replica that sets it writes the close.

    Args:
        slate_date: Eastern game date, ``YYYY-MM-DD``.
        tip: Any tip in that UTC minute.

    Returns:
        The lock key. The caller chooses the TTL.
    """
    return f"odds:v1:pretip-lock:{slate_date}:{pretip_hhmm(tip)}"


def _snapshot_is_younger_than(raw: object, minutes: int) -> bool:
    """True when ``raw`` is a snapshot stored less than ``minutes`` ago.

    A missing body, a body without an ``entries`` list, and an unreadable
    ``fetched_at`` are not young, so the refresh is allowed to replace them.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        return False
    fetched_at = raw.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        return False
    try:
        parsed = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return age < timedelta(minutes=minutes)


class SchedulerService:
    """
    Scheduled Job Scheduler Service
    
    Manages all scheduled tasks, including starting, stopping, and running
    
    Usage:
        scheduler = SchedulerService()
        scheduler.start()  # Start the scheduler
        scheduler.stop()   # Stop the scheduler
    
    Scheduled Jobs:
    - daily_analysis_job: Runs daily analysis at UTC 12:00 every day
    """
    
    def __init__(self):
        """
        Initialize the scheduler
        
        AsyncIOScheduler: Scheduler for asyncio
        - Can run async functions
        - Compatible with FastAPI's async architecture
        """
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._is_running = False
        # The startup fill runs at most once per process. It refreshes a
        # missing key, and a stale key when the process is inside the
        # slate window. A later start() on the same instance does not
        # schedule it again.
        self._injury_startup_fill_done = False
        # NBA tips already resolved in this process, keyed by Eastern
        # slate date. Keeps a Redis miss from calling again on the next
        # 5-minute tick.
        self._nba_tips_memory: dict[str, tuple[str, tuple[datetime, ...]]] = {}
        # A failed call is not stored. This set keeps that warning to
        # one line per slate in this process. The next tick still reads.
        self._nba_schedule_warned: set[str] = set()
        # Closing-line job ids this process has already handed to the
        # scheduler. A one-shot job is removed after it fires. The next
        # planner pass must not add that id again while it is still
        # inside the misfire grace, or the close runs twice.
        self._pretip_armed: set[str] = set()
    
    def start(self):
        """
        Start the scheduler
        
        Create AsyncIOScheduler instance and add scheduled jobs
        
        Note: Scheduler must run inside asyncio event loop.
        The FastAPI lifespan event is a suitable starting point.
        """
        if self._is_running:
            print("⚠️ Scheduler is already running")
            return
        
        # Create the scheduler
        self._scheduler = AsyncIOScheduler(
            timezone="UTC",  # Use UTC timezone
            job_defaults={
                'coalesce': True,      # Merge missed runs (run only once)
                'max_instances': 1,    # Only one instance of the same job can run at once
                'misfire_grace_time': 3600  # Jobs missed within 1 hour will still be run
            }
        )
        
        # Add daily analysis job (NBA)
        # CronTrigger: Similar to Linux cron
        # hour=12, minute=0: Run at UTC 12:00 every day
        self._scheduler.add_job(
            self._run_daily_analysis_job,
            trigger=CronTrigger(hour=12, minute=0),
            id='daily_analysis_job',
            name='Daily High Probability Player Analysis (NBA)',
            replace_existing=True  # Replace if job already exists
        )

        # Add CSV download job
        # Runs at 10:00 Chicago time
        # timezone="America/Chicago": APScheduler will handle daylight saving automatically
        # 10:00 Chicago time corresponds to:
        #   - Standard (CST, UTC-6): UTC 16:00
        #   - Daylight (CDT, UTC-5): UTC 15:00
        self._scheduler.add_job(
            self._run_csv_download_job,
            trigger=CronTrigger(
                hour=10, 
                minute=0, 
                timezone="America/Chicago"
            ),
            id='csv_download_job',
            name='Download NBA Player Stats CSV',
            replace_existing=True
        )
        
        # Add odds snapshot jobs (3 times a day).
        #
        # Eastern wall-clock time, year-round. Each CronTrigger passes
        # timezone="America/New_York", so 11:05, 17:05, and 18:35 stay on
        # the Eastern clock through daylight time. The scheduler default
        # stays UTC. Lineup jobs already pass timezone="America/Chicago".
        #
        # - Early, 11:05 America/New_York: early line, after injury reports.
        # - Mid, 17:05 America/New_York: late afternoon, after sharp money.
        # - Final, 18:35 America/New_York: pre-lock, before 7:00 PM tip-offs.
        #
        # Standard time (EST, UTC-5): 16:05, 22:05, and 23:35 UTC.
        # Daylight time (EDT, UTC-4): 15:05, 21:05, and 22:35 UTC.
        #
        # Each snapshot calls odds API once per event for 4 markets,
        # calculates no-vig for all bookmaker/player/market, and batch writes to PostgreSQL.
        # Failure does not affect daily analysis.
        self._scheduler.add_job(
            self._run_odds_snapshot_job,
            trigger=CronTrigger(
                hour=11,
                minute=5,
                timezone="America/New_York",
            ),
            id='odds_snapshot_early',
            name='Odds Snapshot (Early Line)',
            replace_existing=True
        )
        
        self._scheduler.add_job(
            self._run_odds_snapshot_job,
            trigger=CronTrigger(
                hour=17,
                minute=5,
                timezone="America/New_York",
            ),
            id='odds_snapshot_mid',
            name='Odds Snapshot (Mid Line)',
            replace_existing=True
        )
        
        self._scheduler.add_job(
            self._run_odds_snapshot_job,
            trigger=CronTrigger(
                hour=18,
                minute=35,
                timezone="America/New_York",
            ),
            id='odds_snapshot_final',
            name='Odds Snapshot (Final Pre-Lock)',
            replace_existing=True
        )

        self._scheduler.add_job(
            self._run_hot_key_prewarm_job,
            trigger=IntervalTrigger(seconds=30),
            id='odds_hot_key_prewarm',
            name='Hot Odds Key Prewarm',
            replace_existing=True
        )

        self._scheduler.add_job(
            self._run_lineup_fetch_job,
            trigger=CronTrigger(
                hour=9,
                minute=30,
                timezone="America/Chicago",
            ),
            id='lineup_fetch_opening',
            name='Free Lineup Prefetch (baseline)',
            replace_existing=True
        )

        self._scheduler.add_job(
            self._run_lineup_fetch_job,
            trigger=CronTrigger(
                hour=LINEUP_ACTIVE_WINDOW_CRON_HOUR,
                minute=LINEUP_ACTIVE_WINDOW_CRON_MINUTE,
                timezone=LINEUP_ACTIVE_WINDOW_TZ,
            ),
            id='lineup_fetch_active_window',
            name='Free Lineup Refresh (every 15 minutes)',
            replace_existing=True
        )

        # Wide 5-minute grid through 22:55. The handler returns unless
        # now is in [tip - 2h, tip) for some game, and it also returns
        # on a minute the 15-minute job above already scrapes.
        self._scheduler.add_job(
            self._run_lineup_fetch_pre_tipoff_job,
            trigger=CronTrigger(
                hour=NBA_LINEUP_PRETIPOFF_CRON_HOUR,
                minute=NBA_LINEUP_PRETIPOFF_CRON_MINUTE,
                timezone=NBA_LINEUP_PRETIPOFF_TZ,
            ),
            id='lineup_fetch_pre_tipoff',
            name='Free Lineup Refresh (every 5 minutes)',
            replace_existing=True
        )

        # NBA injury snapshot. Cron only fires inside the slate window,
        # at :07 and :37 Chicago (every 30 minutes). misfire_grace_time
        # is 25 minutes and coalesce is true, so a restart that just
        # missed :07 or :37 runs that tick once and does not burst.
        # The one startup fill is a separate date job.
        self._scheduler.add_job(
            self._run_nba_injuries_refresh_job,
            trigger=CronTrigger(
                hour=NBA_INJURY_REFRESH_CRON_HOUR,
                minute=NBA_INJURY_REFRESH_CRON_MINUTE,
                timezone=NBA_INJURY_REFRESH_TZ,
            ),
            id='nba_injuries_refresh',
            name='NBA Injury Snapshot Refresh',
            replace_existing=True,
            misfire_grace_time=NBA_INJURY_REFRESH_MISFIRE_GRACE_SECONDS,
            max_instances=1,
            coalesce=True,
        )
        if not self._injury_startup_fill_done:
            self._injury_startup_fill_done = True
            self._scheduler.add_job(
                self._fill_nba_injuries_if_missing,
                trigger=DateTrigger(
                    run_date=datetime.now(timezone.utc) + timedelta(seconds=1)
                ),
                id='nba_injuries_startup_fill',
                # The job fills a missing key, and a stale key inside
                # the slate window. The id stays the same job.
                name='NBA Injury Snapshot Startup Refill',
                replace_existing=True,
                misfire_grace_time=60,
                max_instances=1,
                coalesce=True,
            )

        # Pre-tip closing lines. The daily cron, the 30-minute interval,
        # and the one-second startup alarm all call the same planner.
        # The planner reads the slate tip cache and adds one DateTrigger
        # per tip minute. Those triggers set their own 8-minute grace.
        # They do not inherit the one-hour default above.
        self._scheduler.add_job(
            self.plan_odds_pretip_closes,
            trigger=CronTrigger(
                hour=ODDS_PRETIP_PLANNER_DAILY_HOUR,
                minute=ODDS_PRETIP_PLANNER_DAILY_MINUTE,
                timezone=ODDS_PRETIP_PLANNER_DAILY_TZ,
            ),
            id="odds_pretip_planner_daily",
            name="Odds closing-line planner (daily)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self.plan_odds_pretip_closes,
            trigger=IntervalTrigger(minutes=ODDS_PRETIP_PLANNER_INTERVAL_MINUTES),
            id="odds_pretip_planner",
            name="Odds closing-line planner (every 30 minutes)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self.plan_odds_pretip_closes,
            trigger=DateTrigger(
                run_date=datetime.now(timezone.utc) + timedelta(seconds=1)
            ),
            id="odds_pretip_planner_startup",
            name="Odds closing-line planner (process start)",
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=1,
            coalesce=True,
        )

        # Official injury-report PDF for the current slot. Off unless
        # INJURY_PDF_FETCH_ENABLED is set, so starting the process does
        # not fetch. On a tick, the handler checks the game date first.
        if settings.injury_pdf_fetch_enabled:
            self._scheduler.add_job(
                self._run_injury_pdf_fetch_job,
                trigger=CronTrigger(minute=INJURY_PDF_FETCH_CRON_MINUTE),
                id="injury_pdf_fetch_current",
                name="Official NBA injury-report PDF (current slot)",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        # Start the scheduler
        self._scheduler.start()
        self._is_running = True
        
        print("✅ Scheduler started")
        print("📅 Scheduled Jobs:")
        print("   - Free Lineup Refresh: 09:30 baseline / 11:00-21:45 every 15min / 5min in each game's last 2h")
        print("   - Projection Data Prefetch: Daily UTC 16:00, 22:00, 23:30")
        print("   - Odds Snapshot: Daily 11:05, 17:05, 18:35 America/New_York")
        print(
            "   - Odds closing line: 10 minutes before each tip "
            "(planner daily, every 30 minutes, and on start)"
        )
        print("   - Hot Odds Key Prewarm: Every 30 seconds")
        print("   - Daily Analysis (NBA): Daily UTC 12:00")
        print("   - CSV Download: Daily 10:00 Chicago time")
        print(
            "   - NBA Injury Refresh: Chicago 11:00-00:59 at :07 and :37"
        )
        if settings.injury_pdf_fetch_enabled:
            print(
                "   - Injury-report PDFs: every 15 minutes on an NBA game day"
            )
        else:
            print("   - Injury-report PDFs: off (INJURY_PDF_FETCH_ENABLED is false)")
        
        # List all scheduled jobs
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            print(f"   📌 {job.id}: {job.name}")
            print(f"      Next run: {job.next_run_time}")
    
    async def _fill_nba_injuries_if_missing(self) -> None:
        """Refresh once when the key is missing, or stale inside the window.

        A missing key refreshes even outside the slate window, so a
        cold process is not blind. A present key that readers would
        reject (older than six hours, or not an entries list) refreshes
        only while ``nba_injury_refresh_in_window`` is true. Outside
        the window that stale key is left in place. ``injury_status``
        then stays null until the next in-window :07 or :37, which is
        11:07 America/Chicago after an overnight restart. A tick missed
        by less than 25 minutes still runs once, because the cron grace
        was raised and coalesce is on. This is not called from the
        HTTP daily-picks or /reads path. It runs at most once per
        process. The 429 rule is unchanged: one retry, a wait of at
        most 60 seconds, and the previous snapshot stays.
        """
        from app.services.cache import cache_service

        try:
            raw = await cache_service.get(NBA_INJURIES_CACHE_KEY)
        except Exception as exc:
            logger.warning(
                "NBA injury startup read failed (%s); no refresh",
                type(exc).__name__,
            )
            return
        if raw is None:
            await self._run_nba_injuries_refresh_job(force=True)
            return
        if not nba_injury_refresh_in_window():
            return
        if injury_snapshot_is_fresh(raw):
            return
        await self._run_nba_injuries_refresh_job(force=True)

    async def _run_nba_injuries_refresh_job(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict | None:
        """Refresh the NBA injury snapshot, or skip without calling.

        The cron passes no arguments, so ``force`` is false and a tick
        outside the slate window returns before any HTTP client is
        built. ``force`` is the one startup fill, for a missing key or
        for a stale key inside the slate window.
        A snapshot younger than ``nba_injuries_refresh_minutes`` (30)
        is left in place so two ticks cannot land inside that gap.
        No API key means no call. Failures log the exception type only.
        The client uses the injury rate-limit policy: one 429 is retried
        after Retry-After, a future reset, or 30 to 59 seconds, and that
        wait is at most 60 seconds. A second 429 raises, the refresh
        writes nothing, and the previous snapshot stays. There is no
        second retry loop around the client, so this job cannot sleep
        through the next 30-minute tick.

        Args:
            now: Clock for the window check. None is the current time.
            force: True only for the startup fill. The caller has
                already decided the key is missing, or stale inside
                the slate window.

        Returns:
            The stored body, or None when nothing was written.
        """
        moment = now if now is not None else datetime.now(timezone.utc)
        if not force and not nba_injury_refresh_in_window(moment):
            logger.info("nba_injuries_refresh skipped outside the slate window")
            return None
        key = settings.balldontlie_api_key.get_secret_value().strip()
        if not key:
            logger.warning("nba_injuries_refresh skipped; BALLDONTLIE_API_KEY is unset")
            return None
        from app.services.bdl_client import BdlClient
        from app.services.cache import cache_service

        if not force:
            try:
                current = await cache_service.get(NBA_INJURIES_CACHE_KEY)
            except Exception as exc:
                logger.warning(
                    "NBA injury refresh read failed (%s); previous cache left in place",
                    type(exc).__name__,
                )
                return None
            if _snapshot_is_younger_than(current, settings.nba_injuries_refresh_minutes):
                logger.info("nba_injuries_refresh skipped; snapshot is inside the interval")
                return None
        # rate_limit_policy="injury": one 429 retry, wait at most 60s.
        # The other machine's daily snapshot cannot see this Redis limiter
        # and can land on :07. A second 429 keeps the previous snapshot.
        client = BdlClient(api_key=key, rate_limit_policy="injury")
        try:
            return await refresh_nba_injuries_from_bdl(client, cache_service)
        except Exception as exc:
            logger.warning(
                "nba_injuries_refresh failed (%s); previous cache left in place",
                type(exc).__name__,
            )
            return None
        finally:
            await client.aclose()

    def stop(self):
        """
        Stop the scheduler
        
        Gracefully shuts down the scheduler, waits for running jobs to finish
        """
        if not self._is_running or self._scheduler is None:
            return
        
        self._scheduler.shutdown(wait=True)
        self._is_running = False
        print("✅ Scheduler stopped")
    
    async def _run_daily_analysis_job(self):
        """
        Run daily analysis job
        
        This is the job function called by the scheduler.
        Includes error handling and logging.
        """
        print("\n" + "=" * 50)
        print(f"🚀 Starting daily analysis job: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)
        
        try:
            # US slate date (America/New_York), including after midnight UTC.
            today = nba_slate_date()[0]
            result = await daily_analysis_service.run_daily_analysis(
                date=today,
                use_cache=False  # Forced re-analysis in scheduled jobs
            )
            
            print(f"\n✅ Daily analysis completed!")
            print(f"   Date: {result.date}")
            print(f"   Found {result.total_picks} high-probability picks")
            
            if result.stats:
                print(f"   Events analyzed: {result.stats.total_events}")
                print(f"   Players analyzed: {result.stats.total_players}")
                print(f"   Duration: {result.stats.analysis_duration_seconds:.2f} seconds")
            
        except Exception as e:
            print(f"\n❌ Daily analysis job failed: {e}")
            # Notification mechanisms (such as email, Slack) can be added here
            import traceback
            traceback.print_exc()
        
        print("=" * 50 + "\n")
    
    async def _run_csv_download_job(self):
        """
        Run CSV download job
        
        Download the latest NBA player game log CSV from GitHub.
        This job runs every day at 10:00 Chicago time.
        
        Steps:
        1. Call csv_downloader_service.download()
        2. Log the result (success/failure)
        3. Error handling and logs
        """
        print("\n" + "=" * 50)
        print(f"📥 Starting CSV download job: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)
        
        try:
            # Call the download service
            success = await csv_downloader_service.download()
            
            if success:
                print(f"✅ CSV download job completed!")
            else:
                print("⚠️ CSV download job did not report success")
                
        except Exception as e:
            print(f"❌ CSV download job exception: {e}")
            import traceback
            traceback.print_exc()
        
        print("=" * 50 + "\n")
    
    async def _run_odds_snapshot_job(self):
        """
        Run odds snapshot job

        Named "_run_odds_snapshot_job" because it is called as a job handler by the scheduler,
        responsible for running a single "odds snapshot".
        Includes error handling; failures do not affect other jobs.
        """
        print("\n" + "=" * 50)
        print(f"📸 Starting odds snapshot: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)

        try:
            # US game date, not the UTC date. take_snapshot() applies the
            # America/New_York offset. Passing UTC today with the old
            # UTC+8 default matched no evening NBA slate.
            result = await odds_snapshot_service.take_snapshot()

            print(f"✅ Odds snapshot complete!")
            print(f"   Date: {result['date']}")
            print(f"   Number of events: {result['event_count']}")
            print(f"   Number of lines: {result['total_lines']}")
            print(f"   Duration: {result['duration_ms']}ms")

        except Exception as e:
            print(f"❌ Odds snapshot failed: {e}")
            import traceback
            traceback.print_exc()

        print("=" * 50 + "\n")

    async def _run_hot_key_prewarm_job(self):
        """
        Prewarm the most popular odds keys in the last 5 minutes.
        """
        try:
            warmed = await odds_gateway.prewarm_hot_keys()
            if warmed > 0:
                print(f"🔥 Hot Odds Key prewarm completed: {warmed}")
        except Exception as e:
            print(f"⚠️ Hot Odds Key prewarm failed: {e}")

    async def _run_lineup_fetch_job(self, *, now: datetime | None = None) -> None:
        """Scrape NBA lineups for the Eastern slate at ``now``.

        ``_run_lineup_fetch_job`` is the opening job and the 15-minute
        job. ``now`` defaults to the current time. A naive datetime is
        read as UTC. The pre-tipoff job calls this only after the window
        check passes, and passes the same clock.

        Args:
            now: Clock that picks ``nba_slate_date``. None is the current time.
        """
        print("\n" + "=" * 50)
        print(f"🧾 Starting free lineup refresh: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)

        try:
            # No clock: nba_slate_date() reads its own now, which is what
            # the opening job and the 15-minute job have always done.
            # A passed clock is the pre-tipoff decision instant.
            if now is None:
                today = nba_slate_date()[0]
            else:
                moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
                today = nba_slate_date(moment)[0]
            lineups = await lineup_service.fetch_and_store(today)
            print(f"✅ Free lineup refresh completed! {len(lineups)} teams")
        except Exception as e:
            print(f"❌ Free lineup refresh failed: {e}")
            import traceback
            traceback.print_exc()

        print("=" * 50 + "\n")

    async def _run_lineup_fetch_pre_tipoff_job(self, *, now: datetime | None = None) -> None:
        """Scrape NBA lineups inside ``[tip - 2 hours, tip)`` for any game.

        ``_run_lineup_fetch_pre_tipoff_job`` is the handler for
        ``lineup_fetch_pre_tipoff``. The cron fires every 5 minutes from
        09:00 through 22:55 Chicago. This method returns before
        ``fetch_and_store`` when the Chicago minute is one the 15-minute
        job already scrapes, when the clock is outside every game's
        window, when the slate has no games, or when the schedule cannot
        be read. The 15-minute job does not call this method, so it
        still runs.

        The slate's tips are read at most once per ``nba_slate_date``
        and stored under ``lineup:v1:nba:tips:<date>`` when the read
        returns a body. A failed call is not stored, so the next tick
        tries again. A missing key, or a body with no usable tip, is
        stored and skips the 5-minute window for the rest of that slate.
        The source is one ``BdlClient.list_games(dates=[slate])`` call.

        Args:
            now: Clock for the windows and the slate date. None is the current time.
        """
        if now is None:
            moment = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            moment = now.replace(tzinfo=timezone.utc)
        else:
            moment = now
        if lineup_active_window_covers(moment):
            return
        slate = nba_slate_date(moment)[0]
        _status, tips = await self._nba_tips_for_slate(slate)
        if not nba_lineup_pretipoff_in_window(moment, tips):
            return
        await self._run_lineup_fetch_job(now=moment)

    def _warn_schedule_once(
        self,
        seen: set[str],
        slate_date: str,
        message: str,
        *args: object,
    ) -> None:
        """Log ``message`` once per ``slate_date`` in this process.

        ``_warn_schedule_once`` is for a failed schedule call. The call
        is not stored, so later ticks would otherwise repeat the line.
        ``seen`` is the league's set. A new process warns again, once.

        Args:
            seen: Slate dates already warned in this process.
            slate_date: Eastern game date.
            message: Warning template. The key is not part of it.
            *args: Values for the template, such as an exception type name.
        """
        if slate_date in seen:
            return
        seen.add(slate_date)
        logger.warning(message, *args)

    async def _nba_tips_for_slate(
        self,
        slate_date: str,
    ) -> tuple[str, tuple[datetime, ...]]:
        """Every usable NBA tip on ``slate_date``, from memory, Redis, or one read.

        ``_nba_tips_for_slate`` is how the 5-minute job learns each
        game's window. A body is stored for the slate. A failed call
        is not stored in this process or in Redis, so the next tick,
        and another process, reads again.

        Args:
            slate_date: Eastern game date, ``YYYY-MM-DD``.

        Returns:
            ``("ok", tips)``, ``("no_games", ())``, ``("unreadable", ())``,
            or ``("transient", ())`` when the call failed.
        """
        remembered = self._nba_tips_memory.get(slate_date)
        if remembered is not None:
            return remembered
        from app.services.cache import cache_service

        key = nba_lineup_tips_cache_key(slate_date)
        cached = _cached_tips(await cache_service.get(key))
        if cached is not None:
            self._nba_tips_memory[slate_date] = cached
            return cached
        result = await self._read_nba_tips(slate_date)
        if not _schedule_is_durable(result[0]):
            return result
        self._nba_tips_memory[slate_date] = result
        await cache_service.set(
            key,
            _dump_tips(result[0], result[1]),
            NBA_LINEUP_TIPS_CACHE_TTL_SECONDS,
        )
        return result

    async def _read_nba_tips(self, slate_date: str) -> tuple[str, tuple[datetime, ...]]:
        """One ``GET /v1/games?dates[]=`` for ``slate_date``.

        An empty key logs one warning and returns ``unreadable``, which
        the caller stores for the slate. A failed call logs one warning
        per slate in this process and returns ``transient``, which the
        caller does not store. The warning names the exception type, not
        the key and not the response body. ``per_page`` is 100, which
        covers one NBA date, so this does not follow a later page.

        Args:
            slate_date: Eastern game date.

        Returns:
            The same pair as ``tips_from_games_payload``,
            ``("unreadable", ())`` when the key is missing or the body
            was not returned, or ``("transient", ())`` when the call failed.
        """
        api_key = settings.balldontlie_api_key.get_secret_value().strip()
        if not api_key:
            logger.warning(
                "lineup_fetch_pre_tipoff schedule unreadable (BALLDONTLIE_API_KEY is unset); "
                "skipping the 5-minute window"
            )
            return ("unreadable", ())
        from app.services.bdl_client import BdlClient

        client = BdlClient(api_key=api_key)
        payload: object = None
        failed = False
        try:
            try:
                payload = await client.list_games(dates=[slate_date], per_page=100)
            except Exception as exc:
                self._warn_schedule_once(
                    self._nba_schedule_warned,
                    slate_date,
                    "lineup_fetch_pre_tipoff schedule unreadable (%s); skipping the 5-minute window",
                    type(exc).__name__,
                )
                failed = True
        finally:
            try:
                await client.aclose()
            except Exception:
                pass
        if failed:
            return ("transient", ())
        if payload is None:
            return ("unreadable", ())
        status, tips = tips_from_games_payload(payload, slate_date)
        if status == "unreadable":
            logger.warning(
                "lineup_fetch_pre_tipoff schedule unreadable (games payload); "
                "skipping the 5-minute window"
            )
        return (status, tips)

    async def plan_odds_pretip_closes(self, *, now: datetime | None = None) -> list[str]:
        """Rebuild one closing-line alarm per tip minute on the current slate.

        ``plan_odds_pretip_closes`` is the planner. The daily cron, the
        30-minute interval, and the process-start alarm all call it.
        Call it again after a restart. The memory job store is empty
        then, so this method is what puts the alarms back.

        Tips come from ``_nba_tips_for_slate``. That reader uses
        ``lineup:v1:nba:tips:<date>`` when the key is present. It calls
        ``list_games`` only when the key is missing. A second pass leaves
        a job that is still waiting. It does not add again a job that
        has already fired.

        A failed read (``transient``) leaves alarms already on the
        scheduler in place. ``no_games`` and ``unreadable`` clear this
        slate's alarms, because there is nothing to close.

        Args:
            now: Clock for the Eastern slate date. None is the current time.
                A naive datetime is UTC.

        Returns:
            The job ids scheduled for this slate, in UTC ``HHMM`` order.
            An empty list when the scheduler is not running or the slate
            has no usable tip.
        """
        if self._scheduler is None:
            return []
        moment = now if now is not None else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        slate = nba_slate_date(moment)[0]
        status, tips = await self._nba_tips_for_slate(slate)
        if status == "transient":
            logger.info("odds_pretip planner left existing alarms in place")
            prefix = f"odds_pretip:{slate}:"
            return sorted(
                job.id for job in self._scheduler.get_jobs() if job.id.startswith(prefix)
            )
        if status != "ok":
            tips = ()
        return self.schedule_pretip_closes(slate, tips)

    def schedule_pretip_closes(
        self,
        slate_date: str,
        tips: tuple[datetime, ...],
    ) -> list[str]:
        """Add one ``DateTrigger`` per UTC tip minute that is not armed yet.

        ``schedule_pretip_closes`` is the part of the planner that talks
        to APScheduler. Each alarm fires at tip minus
        ``ODDS_PRETIP_LEAD`` (10 minutes). The id is
        ``pretip_job_id``. ``misfire_grace_time`` is
        ``ODDS_PRETIP_MISFIRE_GRACE_SECONDS`` (8 minutes). That argument
        is required. Without it the scheduler's one-hour default would
        run the alarm after tip.

        The first time this process sees an id, the job is added even
        when its ``run_date`` is already a few minutes in the past. That
        is how a restart still catches a close inside the grace window.
        A job that is already on the scheduler is left as it is. It is
        not replaced. After the one-shot job fires, APScheduler removes
        it. The id stays in ``_pretip_armed``, so the next pass does not
        add it again.

        Minutes that were scheduled earlier and are not in ``tips`` are
        removed, including ones whose ``run_date`` is already past. A
        tip that is still in the list stays in the wanted set, so this
        cleanup does not remove an in-grace job that has not fired yet.

        Args:
            slate_date: Eastern game date, ``YYYY-MM-DD``.
            tips: Usable tips for that slate. Empty clears this slate's alarms.

        Returns:
            The job ids for ``slate_date``, in UTC ``HHMM`` order. An id
            that already fired is included so the caller can see the
            minute is still part of this slate.
        """
        if self._scheduler is None:
            return []
        grouped: dict[str, datetime] = {}
        for tip in tips:
            utc = _as_utc(tip)
            hhmm = pretip_hhmm(utc)
            current = grouped.get(hhmm)
            if current is None or utc < current:
                grouped[hhmm] = utc
        ids: list[str] = []
        for hhmm in sorted(grouped):
            tip = grouped[hhmm]
            job_id = pretip_job_id(slate_date, tip)
            if self._scheduler.get_job(job_id) is not None:
                self._pretip_armed.add(job_id)
                ids.append(job_id)
                continue
            if job_id in self._pretip_armed:
                ids.append(job_id)
                continue
            try:
                self._scheduler.add_job(
                    self._run_odds_pretip_job,
                    trigger=DateTrigger(run_date=tip - ODDS_PRETIP_LEAD),
                    id=job_id,
                    name=f"Odds closing line {slate_date} {hhmm}",
                    replace_existing=False,
                    misfire_grace_time=ODDS_PRETIP_MISFIRE_GRACE_SECONDS,
                    max_instances=1,
                    coalesce=True,
                    kwargs={"slate_date": slate_date, "tip": tip.isoformat()},
                )
            except ConflictingIdError:
                pass
            self._pretip_armed.add(job_id)
            ids.append(job_id)
        wanted = set(ids)
        prefix = f"odds_pretip:{slate_date}:"
        for job in list(self._scheduler.get_jobs()):
            if job.id.startswith(prefix) and job.id not in wanted:
                self._scheduler.remove_job(job.id)
                self._pretip_armed.discard(job.id)
        return ids

    async def _run_odds_pretip_job(self, slate_date: str, tip: str) -> None:
        """Save the closing line for one tip minute.

        ``_run_odds_pretip_job`` is the function the ``DateTrigger``
        calls. ``tip`` is the UTC ISO text stored on the job. The
        snapshot service checks that each game is still scheduled and
        that the clock is still before tip. A failure logs the
        exception type only. The message does not include the response
        body or a database URL.

        Args:
            slate_date: Eastern game date, ``YYYY-MM-DD``.
            tip: ISO-8601 tip instant. ``Z`` is accepted by the parser
                used when the planner stored ``isoformat``.
        """
        parsed = _parse_tip(tip)
        if parsed is None:
            logger.warning("odds_pretip skipped; tip text is unusable")
            return
        try:
            result = await odds_snapshot_service.take_closing_snapshot(slate_date, parsed)
        except Exception as exc:
            logger.warning("odds_pretip failed (%s)", type(exc).__name__)
            return
        logger.info(
            "odds_pretip done slate=%s games=%s lines=%s misses=%s locked=%s",
            result.get("date"),
            result.get("event_count"),
            result.get("total_lines"),
            result.get("bdl_parent_misses"),
            result.get("locked"),
        )

    async def _run_injury_pdf_fetch_job(self, *, now: datetime | None = None) -> None:
        """Fetch the current official injury-report slot, on a game day only.

        The cron passes no arguments. ``INJURY_PDF_FETCH_ENABLED`` false
        returns before a database read and before any HTTP call. A day
        with no non-postponed NBA game does the same. A database problem
        or a fetch problem logs the exception type and does not raise,
        so the rest of the scheduler keeps running.

        Args:
            now: Clock for the slate date and the report slot. None is
                the current time. A naive datetime is read as UTC.
        """
        if not settings.injury_pdf_fetch_enabled:
            logger.info("injury pdf fetch skipped; INJURY_PDF_FETCH_ENABLED is off")
            return
        moment = now if now is not None else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        try:
            game_day = await self._injury_pdf_is_game_day(moment)
        except Exception as exc:
            logger.warning(
                "injury pdf fetch skipped; game-day read failed (%s)",
                type(exc).__name__,
            )
            return
        if not game_day:
            logger.info("injury pdf fetch skipped; not an NBA game day")
            return
        try:
            from app.services.injury_report_fetcher import fetch_current_slot

            report = await fetch_current_slot(moment)
        except Exception as exc:
            logger.warning("injury pdf fetch failed (%s)", type(exc).__name__)
            return
        if report.paused:
            logger.warning("injury pdf fetch paused")

    async def _injury_pdf_is_game_day(self, now: datetime) -> bool:
        """True when ``now`` falls on an Eastern date that has an NBA game.

        ``_injury_pdf_is_game_day`` is the gate for
        ``injury_pdf_fetch_current``. It reads ``games`` through the
        process pool. It does not call the NBA CDN.

        Args:
            now: Aware instant. The date is ``nba_slate_date``.

        Returns:
            True when that date has a non-postponed NBA row.
        """
        from app.services.injury_report_games import is_nba_game_day

        return await is_nba_game_day(now)

    async def trigger_odds_snapshot_now(self, date: Optional[str] = None) -> dict:
        """
        Manually trigger odds snapshot

        Named "trigger_odds_snapshot_now" because it allows you to "trigger" an odds snapshot immediately,
        without waiting for the scheduled time. Used in API endpoints for manual triggering.

        Args:
            date: US game date (YYYY-MM-DD). None means today in New York.

        Returns:
            Snapshot result dict (contains date, event_count, total_lines, duration_ms)
        """
        if date is None:
            return await odds_snapshot_service.take_snapshot()
        return await odds_snapshot_service.take_snapshot(date)

    async def trigger_lineup_fetch_now(self, date: Optional[str] = None) -> dict:
        if date is None:
            date = nba_slate_date()[0]
        return await lineup_service.fetch_and_store(date)
    
    async def trigger_now(self):
        """
        Manually trigger daily analysis job

        Used for manual testing or when needing immediate data refresh

        Returns:
            Analysis result
        """
        return await self._run_daily_analysis_job()

    async def trigger_csv_download_now(self) -> bool:
        """
        Manually trigger CSV download job
        
        Used for manual testing or when an immediate data refresh is needed.
        No need to wait for the scheduled time.
        
        Returns:
            bool: Whether download succeeded
        
        Usage:
            success = await scheduler_service.trigger_csv_download_now()
        """
        return await csv_downloader_service.download()
    
    def get_next_run_time(self) -> Optional[str]:
        """
        Get the next run time for daily analysis
        
        Returns:
            ISO formatted datetime string for next run, or None
        """
        if not self._scheduler:
            return None
        
        job = self._scheduler.get_job('daily_analysis_job')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None
    
    def get_csv_download_next_run_time(self) -> Optional[str]:
        """
        Get the next run time for CSV download
        
        Returns:
            ISO formatted datetime string for next run, or None
        """
        if not self._scheduler:
            return None
        
        job = self._scheduler.get_job('csv_download_job')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self._is_running


# Create global scheduler instance
scheduler_service = SchedulerService()
