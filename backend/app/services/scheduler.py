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

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.daily_analysis import daily_analysis_service
from app.services.csv_downloader import csv_downloader_service
from app.services.odds_gateway import odds_gateway
from app.services.odds_snapshot_service import odds_snapshot_service
from app.services.lineup_service import lineup_service, wnba_lineup_service
from app.services.nba_injuries import (
    NBA_INJURIES_CACHE_KEY,
    refresh_nba_injuries_from_bdl,
)
from app.settings import settings

logger = logging.getLogger(__name__)

# NBA injury refresh shares the Chicago hours already used by the NBA
# lineup jobs in this file:
#   lineup_fetch_active_window  hour 11-21
#   lineup_fetch_pre_tipoff     hour 22, 23, and 0
# Together that is 11:00 through 00:59 America/Chicago.
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


def nba_injury_refresh_in_window(now: datetime | None = None) -> bool:
    """True when ``now`` falls in the NBA injury slate window.

    ``now`` defaults to the current time. A naive datetime is read as
    UTC. The window is the Chicago hours of the existing NBA lineup
    crons (11:00 through 00:59 America/Chicago). Outside that window
    the scheduled job must not call BALLDONTLIE.

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
        # The startup fill runs at most once per process, and only when
        # the injury key is missing. A later start() on the same
        # instance does not schedule it again.
        self._injury_startup_fill_done = False
    
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

        # SPO-35: WNBA daily analysis job.
        #
        # Independent from the NBA job — different `id` so APScheduler
        # tracks instances separately, different handler so a WNBA crash
        # is caught locally and never reaches the NBA job (and vice
        # versa). Same UTC 12:00 cron cadence; each call writes to its
        # own cache namespace (`daily_picks:nba:...` vs
        # `daily_picks:wnba:...`), no shared mutable state.
        self._scheduler.add_job(
            self._run_wnba_daily_analysis_job,
            trigger=CronTrigger(hour=12, minute=0),
            id='wnba_daily_analysis_job',
            name='Daily High Probability Player Analysis (WNBA)',
            replace_existing=True
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
        
        # Add odds snapshot jobs (3 times a day)
        #
        # Odds snapshot strategy (Line Movement Tracking):
        # - Early (UTC 16:00 ≈ US Eastern 11AM): Early line, after injury reports
        # - Mid (UTC 22:00 ≈ US Eastern 5PM): Late afternoon, after sharp money
        # - Final (UTC 23:30 ≈ US Eastern 6:30PM): Pre-lock, final line
        #
        # Each snapshot calls odds API once per event for 4 markets,
        # calculates no-vig for all bookmaker/player/market, and batch writes to PostgreSQL.
        # Failure does not affect daily analysis.
        self._scheduler.add_job(
            self._run_odds_snapshot_job,
            trigger=CronTrigger(hour=16, minute=5),
            id='odds_snapshot_early',
            name='Odds Snapshot (Early Line)',
            replace_existing=True
        )
        
        self._scheduler.add_job(
            self._run_odds_snapshot_job,
            trigger=CronTrigger(hour=22, minute=5),
            id='odds_snapshot_mid',
            name='Odds Snapshot (Mid Line)',
            replace_existing=True
        )
        
        self._scheduler.add_job(
            self._run_odds_snapshot_job,
            trigger=CronTrigger(hour=23, minute=35),
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
                hour="11-21",
                minute="0,15,30,45",
                timezone="America/Chicago",
            ),
            id='lineup_fetch_active_window',
            name='Free Lineup Refresh (every 15 minutes)',
            replace_existing=True
        )

        self._scheduler.add_job(
            self._run_lineup_fetch_job,
            trigger=CronTrigger(
                hour="22,23,0",
                minute="0,5,10,15,20,25,30,35,40,45,50,55",
                timezone="America/Chicago",
            ),
            id='lineup_fetch_pre_tipoff',
            name='Free Lineup Refresh (every 5 minutes)',
            replace_existing=True
        )

        # SPO-34: WNBA lineup jobs.
        #
        # Cadence mirrors the NBA jobs above so WNBA tip-off boundaries
        # (typically earlier than NBA — many 7:00pm ET starts) and the
        # pre-tip refresh window are both covered. Independent job IDs
        # ensure WNBA failures don't block NBA refreshes and vice versa.
        #
        # The handler is a dedicated method (_run_wnba_lineup_fetch_job)
        # rather than parameterising _run_lineup_fetch_job because the
        # latter is wired to the NBA lineup_service singleton and changing
        # it is out of "NBA path unchanged" scope.
        self._scheduler.add_job(
            self._run_wnba_lineup_fetch_job,
            trigger=CronTrigger(
                hour=9,
                minute=30,
                timezone="America/Chicago",
            ),
            id='wnba_lineup_fetch_opening',
            name='WNBA Lineup Prefetch (baseline)',
            replace_existing=True
        )

        self._scheduler.add_job(
            self._run_wnba_lineup_fetch_job,
            trigger=CronTrigger(
                hour="11-21",
                minute="0,15,30,45",
                timezone="America/Chicago",
            ),
            id='wnba_lineup_fetch_active_window',
            name='WNBA Lineup Refresh (every 15 minutes)',
            replace_existing=True
        )

        self._scheduler.add_job(
            self._run_wnba_lineup_fetch_job,
            trigger=CronTrigger(
                hour="17,18,19",
                minute="0,5,10,15,20,25,30,35,40,45,50,55",
                timezone="America/Chicago",
            ),
            id='wnba_lineup_fetch_pre_tipoff',
            name='WNBA Lineup Refresh (every 5 minutes, pre-tipoff)',
            replace_existing=True
        )

        # NBA injury snapshot. Cron only fires inside the slate window,
        # at :07 and :37 Chicago (every 30 minutes). misfire_grace_time
        # is 1 second so a process that boots later does not catch up
        # a missed tick. The one startup fill is a separate date job.
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
            misfire_grace_time=1,
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
                name='NBA Injury Snapshot Fill If Missing',
                replace_existing=True,
                misfire_grace_time=60,
                max_instances=1,
                coalesce=True,
            )

        # Start the scheduler
        self._scheduler.start()
        self._is_running = True
        
        print("✅ Scheduler started")
        print("📅 Scheduled Jobs:")
        print("   - Free Lineup Refresh: 09:30 (baseline) / 11:00-22:00 every 15min / 22:00-00:30 every 5min")
        print("   - Projection Data Prefetch: Daily UTC 16:00, 22:00, 23:30")
        print("   - Odds Snapshot: Daily UTC 16:05, 22:05, 23:35")
        print("   - Hot Odds Key Prewarm: Every 30 seconds")
        print("   - Daily Analysis (NBA): Daily UTC 12:00")
        print("   - Daily Analysis (WNBA): Daily UTC 12:00 (independent of NBA)")
        print("   - CSV Download: Daily 10:00 Chicago time")
        print(
            "   - NBA Injury Refresh: Chicago 11:00-00:59 at :07 and :37"
        )
        
        # List all scheduled jobs
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            print(f"   📌 {job.id}: {job.name}")
            print(f"      Next run: {job.next_run_time}")
    
    async def _fill_nba_injuries_if_missing(self) -> None:
        """Refresh once when ``injuries:nba:latest`` is absent.

        A present key, including a stale one, does not call. The
        scheduled cron covers the stale case inside the slate window.
        This is the only path that may call outside that window, and
        it runs at most once per process.
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
        if raw is not None:
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
        built. ``force`` is only the one startup fill for a missing key.
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
            force: True only for the missing-key startup fill.

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
            # Run today's analysis
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    
    async def _run_wnba_daily_analysis_job(self):
        """SPO-35: WNBA daily analysis job.

        Mirror of `_run_daily_analysis_job` but with `league="wnba"` so
        the analysis hits `basketball_wnba` events, uses
        `wnba_csv_player_service` for history, skips projections (not
        wired today — graceful-degrade per SPO-35 audit §6 step 1), and
        caches under `daily_picks:wnba:{date}:tz{offset}`.

        Failure isolation: any exception is caught here. The NBA job is
        registered with a separate `id` and runs through its own
        coroutine, so a crash here cannot interfere with NBA picks (and
        vice versa).
        """
        print("\n" + "=" * 50)
        print(f"🚀 [WNBA] Starting daily analysis job: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)

        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = await daily_analysis_service.run_daily_analysis(
                date=today,
                use_cache=False,  # Forced re-analysis in scheduled jobs
                league="wnba",
            )

            print(f"\n✅ [WNBA] Daily analysis completed!")
            print(f"   Date: {result.date}")
            print(f"   Found {result.total_picks} high-probability picks")

            if result.stats:
                print(f"   Events analyzed: {result.stats.total_events}")
                print(f"   Players analyzed: {result.stats.total_players}")
                print(f"   Duration: {result.stats.analysis_duration_seconds:.2f} seconds")

        except Exception as e:
            # Caught locally so the WNBA job never bubbles into the
            # scheduler loop and never affects the NBA job.
            print(f"\n❌ [WNBA] Daily analysis job failed: {e}")
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

    async def _run_lineup_fetch_job(self):
        print("\n" + "=" * 50)
        print(f"🧾 Starting free lineup refresh: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)

        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            lineups = await lineup_service.fetch_and_store(today)
            print(f"✅ Free lineup refresh completed! {len(lineups)} teams")
        except Exception as e:
            print(f"❌ Free lineup refresh failed: {e}")
            import traceback
            traceback.print_exc()

        print("=" * 50 + "\n")

    async def _run_wnba_lineup_fetch_job(self):
        """SPO-34: WNBA lineup refresh.

        Independent from the NBA job so a failure here does not block
        NBA refreshes. RotoWire WNBA only (RotoGrinders WNBA is a JS-only
        SPA — see comparison doc §3).
        """
        print("\n" + "=" * 50)
        print(f"🧾 Starting WNBA lineup refresh: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)

        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            lineups = await wnba_lineup_service.fetch_and_store(today)
            print(f"✅ WNBA lineup refresh completed! {len(lineups)} teams")
        except Exception as e:
            print(f"❌ WNBA lineup refresh failed: {e}")
            import traceback
            traceback.print_exc()

        print("=" * 50 + "\n")

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
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
