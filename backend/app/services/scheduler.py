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
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.daily_analysis import daily_analysis_service
from app.services.csv_downloader import csv_downloader_service
from app.services.odds_gateway import odds_gateway
from app.services.projection_service import projection_service
from app.services.odds_snapshot_service import odds_snapshot_service
from app.services.cache import cache_service
from app.services.lineup_service import lineup_service


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
        
        # Add daily analysis job
        # CronTrigger: Similar to Linux cron
        # hour=12, minute=0: Run at UTC 12:00 every day
        self._scheduler.add_job(
            self._run_daily_analysis_job,
            trigger=CronTrigger(hour=12, minute=0),
            id='daily_analysis_job',
            name='Daily High Probability Player Analysis',
            replace_existing=True  # Replace if job already exists
        )
        
        # Add projection data prefetch jobs (3 times a day)
        # 
        # Projection fetch strategy:
        # - Early (UTC 16:00 ≈ US Eastern 11AM): Initial projections, ~8 hours before games
        # - Mid (UTC 22:00 ≈ US Eastern 5PM): Updated projections, after most starters confirmed
        # - Final (UTC 23:30 ≈ US Eastern 6:30PM): Final projections, right before games
        #
        # SportsDataIO's Projection API is a bulk endpoint,
        # a single call returns projection data for all players of the day,
        # so calling 3 times covers all needs.
        self._scheduler.add_job(
            self._run_projection_fetch_job,
            trigger=CronTrigger(hour=16, minute=0),
            id='projection_fetch_early',
            name='Projection Data Prefetch (Early - Initial)',
            replace_existing=True
        )
        
        self._scheduler.add_job(
            self._run_projection_fetch_job,
            trigger=CronTrigger(hour=22, minute=0),
            id='projection_fetch_mid',
            name='Projection Data Prefetch (Mid - After Starters Confirmed)',
            replace_existing=True
        )
        
        self._scheduler.add_job(
            self._run_projection_fetch_final_job,
            trigger=CronTrigger(hour=23, minute=30),
            id='projection_fetch_final',
            name='Projection Data Prefetch (Final + Clear Daily Picks Cache)',
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
        
        # Add odds snapshot jobs (3 times, same times as projection prefetch)
        #
        # Odds snapshot strategy (Line Movement Tracking):
        # - Early (UTC 16:00 ≈ US Eastern 11AM): Early line, after injury reports
        # - Mid (UTC 22:00 ≈ US Eastern 5PM): Late afternoon, after sharp money
        # - Final (UTC 23:30 ≈ US Eastern 6:30PM): Pre-lock, final line
        #
        # Each snapshot calls odds API once per event for 4 markets,
        # calculates no-vig for all bookmaker/player/market, and batch writes to PostgreSQL.
        # Failure does not affect projection prefetch or daily analysis.
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
        
        # Start the scheduler
        self._scheduler.start()
        self._is_running = True
        
        print("✅ Scheduler started")
        print("📅 Scheduled Jobs:")
        print("   - Free Lineup Refresh: 09:30 (baseline) / 11:00-22:00 every 15min / 22:00-00:30 every 5min")
        print("   - Projection Data Prefetch: Daily UTC 16:00, 22:00, 23:30")
        print("   - Odds Snapshot: Daily UTC 16:05, 22:05, 23:35")
        print("   - Hot Odds Key Prewarm: Every 30 seconds")
        print("   - Daily Analysis: Daily UTC 12:00")
        print("   - CSV Download: Daily 10:00 Chicago time")
        
        # List all scheduled jobs
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            print(f"   📌 {job.id}: {job.name}")
            print(f"      Next run: {job.next_run_time}")
    
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
                print(f"⚠️ CSV download job failed, please check network or URL")
                
        except Exception as e:
            print(f"❌ CSV download job exception: {e}")
            import traceback
            traceback.print_exc()
        
        print("=" * 50 + "\n")
    
    async def _run_projection_fetch_job(self):
        """
        Run projection data prefetch job
        
        Calls projection_service.fetch_and_store() to get today's projections.
        Data is written to Redis and PostgreSQL.
        """
        print("\n" + "=" * 50)
        print(f"📊 Starting projection data prefetch: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)
        
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            projections = await projection_service.fetch_and_store(today)
            
            print(f"✅ Projection data prefetch completed! {len(projections)} players")
        
        except Exception as e:
            print(f"❌ Projection data prefetch failed: {e}")
            import traceback
            traceback.print_exc()
        
        print("=" * 50 + "\n")
    
    async def _run_projection_fetch_final_job(self):
        """
        Run final projection data prefetch
        
        Same as _run_projection_fetch_job, but also clears daily picks cache,
        so the next request for daily picks will use the latest projections.
        """
        print("\n" + "=" * 50)
        print(f"📊 Starting final projection data prefetch: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)
        
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            projections = await projection_service.fetch_and_store(today)
            
            print(f"✅ Final projection data prefetch completed! {len(projections)} players")
            
            # Clear daily picks cache so the next analysis uses new projections
            deleted = await cache_service.clear_daily_picks_cache()
            if deleted > 0:
                print(f"🗑️ Cleared {deleted} daily picks cache")
        
        except Exception as e:
            print(f"❌ Final projection data prefetch failed: {e}")
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
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = await odds_snapshot_service.take_snapshot(today)

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

    async def trigger_odds_snapshot_now(self, date: Optional[str] = None) -> dict:
        """
        Manually trigger odds snapshot

        Named "trigger_odds_snapshot_now" because it allows you to "trigger" an odds snapshot immediately,
        without waiting for the scheduled time. Used in API endpoints for manual triggering.

        Args:
            date: Date (YYYY-MM-DD), None means today

        Returns:
            Snapshot result dict (contains date, event_count, total_lines, duration_ms)
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return await odds_snapshot_service.take_snapshot(date)

    async def trigger_projection_fetch_now(self, date: Optional[str] = None) -> dict:
        """
        Manually trigger projection data prefetch
        
        Args:
            date: Date (YYYY-MM-DD), None means today
        
        Returns:
            Projections dict
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return await projection_service.fetch_and_store(date)

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
