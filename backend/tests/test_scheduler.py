"""
Tests for SchedulerService

Covers:
- Initialization and start/stop lifecycle
- Job configuration (all expected jobs are registered)
- Manual trigger methods
- get_next_run_time helpers
- is_running property
- Idempotent start (double-start guard)
- Stop when not running (no-op)

All APScheduler and downstream service interactions are mocked
to avoid real scheduling or network access.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# We patch all imported services so the module can be loaded without
# needing real connections (Redis, Postgres, HTTP, etc.)
# ---------------------------------------------------------------------------

SERVICES_TO_PATCH = [
    "app.services.scheduler.daily_analysis_service",
    "app.services.scheduler.csv_downloader_service",
    "app.services.scheduler.odds_gateway",
    "app.services.scheduler.projection_service",
    "app.services.scheduler.odds_snapshot_service",
    "app.services.scheduler.cache_service",
    "app.services.scheduler.lineup_service",
]


@pytest.fixture
def mock_services():
    """Patch every external service used by the scheduler module."""
    patchers = [patch(target, new_callable=MagicMock) for target in SERVICES_TO_PATCH]
    mocks = [p.start() for p in patchers]
    yield dict(zip(SERVICES_TO_PATCH, mocks))
    for p in patchers:
        p.stop()


@pytest.fixture
def scheduler_cls(mock_services):
    """Import SchedulerService after services are patched."""
    from app.services.scheduler import SchedulerService
    return SchedulerService


@pytest.fixture
def scheduler(scheduler_cls):
    """Return a fresh SchedulerService instance (not started)."""
    return scheduler_cls()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:

    def test_initial_state(self, scheduler):
        assert scheduler._scheduler is None
        assert scheduler._is_running is False
        assert scheduler.is_running is False

    def test_is_running_property(self, scheduler):
        assert scheduler.is_running is False


# ---------------------------------------------------------------------------
# Start / Stop lifecycle
# ---------------------------------------------------------------------------


class TestStartStop:

    def test_start_creates_scheduler_and_sets_running(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            assert scheduler._is_running is True
            assert scheduler.is_running is True
            mock_instance.start.assert_called_once()

    def test_start_adds_expected_jobs(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            # Collect all job ids from add_job calls
            job_ids = set()
            for call in mock_instance.add_job.call_args_list:
                _, kwargs = call
                if "id" in kwargs:
                    job_ids.add(kwargs["id"])

            expected_ids = {
                "daily_analysis_job",
                "projection_fetch_early",
                "projection_fetch_mid",
                "projection_fetch_final",
                "csv_download_job",
                "odds_snapshot_early",
                "odds_snapshot_mid",
                "odds_snapshot_final",
                "odds_hot_key_prewarm",
                "lineup_fetch_opening",
                "lineup_fetch_active_window",
                "lineup_fetch_pre_tipoff",
            }
            assert expected_ids.issubset(job_ids), (
                f"Missing jobs: {expected_ids - job_ids}"
            )

    def test_start_idempotent(self, scheduler):
        """Starting twice should not create a second scheduler."""
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()
            scheduler.start()  # second call should be a no-op

            # AsyncIOScheduler constructed only once
            assert MockSched.call_count == 1

    def test_stop_shuts_down(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()
            scheduler.stop()

            mock_instance.shutdown.assert_called_once_with(wait=True)
            assert scheduler._is_running is False
            assert scheduler.is_running is False

    def test_stop_when_not_running_is_noop(self, scheduler):
        # Should not raise
        scheduler.stop()
        assert scheduler.is_running is False


# ---------------------------------------------------------------------------
# Job configuration details
# ---------------------------------------------------------------------------


class TestJobConfiguration:

    def test_daily_analysis_cron_at_utc_12(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            # Find daily_analysis_job call
            for call in mock_instance.add_job.call_args_list:
                _, kwargs = call
                if kwargs.get("id") == "daily_analysis_job":
                    trigger = kwargs["trigger"]
                    # CronTrigger with hour=12, minute=0
                    assert isinstance(trigger, object)
                    assert kwargs["replace_existing"] is True
                    break
            else:
                pytest.fail("daily_analysis_job not found in add_job calls")

    def test_csv_download_job_uses_chicago_tz(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            for call in mock_instance.add_job.call_args_list:
                _, kwargs = call
                if kwargs.get("id") == "csv_download_job":
                    trigger = kwargs["trigger"]
                    # Verify timezone is set to Chicago
                    assert str(trigger.timezone) == "America/Chicago"
                    break
            else:
                pytest.fail("csv_download_job not found in add_job calls")

    def test_all_jobs_have_replace_existing(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            for call in mock_instance.add_job.call_args_list:
                _, kwargs = call
                assert kwargs.get("replace_existing") is True, (
                    f"Job {kwargs.get('id')} missing replace_existing=True"
                )

    def test_hot_key_prewarm_uses_interval_trigger(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            for call in mock_instance.add_job.call_args_list:
                _, kwargs = call
                if kwargs.get("id") == "odds_hot_key_prewarm":
                    from apscheduler.triggers.interval import IntervalTrigger
                    assert isinstance(kwargs["trigger"], IntervalTrigger)
                    break
            else:
                pytest.fail("odds_hot_key_prewarm not found in add_job calls")

    def test_scheduler_timezone_is_utc(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            _, init_kwargs = MockSched.call_args
            assert init_kwargs["timezone"] == "UTC"

    def test_scheduler_coalesce_and_max_instances(self, scheduler):
        with patch("app.services.scheduler.AsyncIOScheduler") as MockSched:
            mock_instance = MagicMock()
            mock_instance.get_jobs.return_value = []
            MockSched.return_value = mock_instance

            scheduler.start()

            _, init_kwargs = MockSched.call_args
            defaults = init_kwargs["job_defaults"]
            assert defaults["coalesce"] is True
            assert defaults["max_instances"] == 1
            assert defaults["misfire_grace_time"] == 3600


# ---------------------------------------------------------------------------
# get_next_run_time
# ---------------------------------------------------------------------------


class TestGetNextRunTime:

    def test_returns_none_when_no_scheduler(self, scheduler):
        assert scheduler.get_next_run_time() is None

    def test_returns_iso_string_when_job_exists(self, scheduler):
        fake_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_job = MagicMock()
        mock_job.next_run_time = fake_time

        mock_sched = MagicMock()
        mock_sched.get_job.return_value = mock_job

        scheduler._scheduler = mock_sched
        result = scheduler.get_next_run_time()
        assert result == fake_time.isoformat()
        mock_sched.get_job.assert_called_with("daily_analysis_job")

    def test_returns_none_when_job_not_found(self, scheduler):
        mock_sched = MagicMock()
        mock_sched.get_job.return_value = None
        scheduler._scheduler = mock_sched
        assert scheduler.get_next_run_time() is None

    def test_returns_none_when_job_has_no_next_run(self, scheduler):
        mock_job = MagicMock()
        mock_job.next_run_time = None
        mock_sched = MagicMock()
        mock_sched.get_job.return_value = mock_job
        scheduler._scheduler = mock_sched
        assert scheduler.get_next_run_time() is None


# ---------------------------------------------------------------------------
# get_csv_download_next_run_time
# ---------------------------------------------------------------------------


class TestGetCSVDownloadNextRunTime:

    def test_returns_none_when_no_scheduler(self, scheduler):
        assert scheduler.get_csv_download_next_run_time() is None

    def test_returns_iso_string(self, scheduler):
        fake_time = datetime(2025, 6, 15, 16, 0, 0, tzinfo=timezone.utc)
        mock_job = MagicMock()
        mock_job.next_run_time = fake_time

        mock_sched = MagicMock()
        mock_sched.get_job.return_value = mock_job

        scheduler._scheduler = mock_sched
        result = scheduler.get_csv_download_next_run_time()
        assert result == fake_time.isoformat()
        mock_sched.get_job.assert_called_with("csv_download_job")

    def test_returns_none_when_job_missing(self, scheduler):
        mock_sched = MagicMock()
        mock_sched.get_job.return_value = None
        scheduler._scheduler = mock_sched
        assert scheduler.get_csv_download_next_run_time() is None


# ---------------------------------------------------------------------------
# Manual trigger methods
# ---------------------------------------------------------------------------


class TestManualTriggers:

    @pytest.mark.asyncio
    async def test_trigger_now_calls_daily_analysis(self, scheduler_cls, mock_services):
        svc = scheduler_cls()
        mock_daily = mock_services["app.services.scheduler.daily_analysis_service"]
        mock_daily.run_daily_analysis = AsyncMock(
            return_value=MagicMock(
                date="2025-06-15",
                total_picks=5,
                stats=MagicMock(
                    total_events=10,
                    total_players=50,
                    analysis_duration_seconds=2.5,
                ),
            )
        )
        await svc.trigger_now()
        mock_daily.run_daily_analysis.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_csv_download_now(self, scheduler_cls, mock_services):
        svc = scheduler_cls()
        mock_csv = mock_services["app.services.scheduler.csv_downloader_service"]
        mock_csv.download = AsyncMock(return_value=True)
        result = await svc.trigger_csv_download_now()
        assert result is True
        mock_csv.download.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_projection_fetch_now_default_date(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_proj = mock_services["app.services.scheduler.projection_service"]
        mock_proj.fetch_and_store = AsyncMock(return_value={"players": []})
        result = await svc.trigger_projection_fetch_now()
        mock_proj.fetch_and_store.assert_awaited_once()
        # Verify it was called with today's date
        call_date = mock_proj.fetch_and_store.call_args[0][0]
        assert call_date == datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @pytest.mark.asyncio
    async def test_trigger_projection_fetch_now_custom_date(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_proj = mock_services["app.services.scheduler.projection_service"]
        mock_proj.fetch_and_store = AsyncMock(return_value={"players": []})
        await svc.trigger_projection_fetch_now(date="2025-01-01")
        mock_proj.fetch_and_store.assert_awaited_once_with("2025-01-01")

    @pytest.mark.asyncio
    async def test_trigger_odds_snapshot_now_default_date(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_snap = mock_services["app.services.scheduler.odds_snapshot_service"]
        mock_snap.take_snapshot = AsyncMock(
            return_value={
                "date": "2025-06-15",
                "event_count": 5,
                "total_lines": 100,
                "duration_ms": 1234,
            }
        )
        result = await svc.trigger_odds_snapshot_now()
        assert result["event_count"] == 5
        mock_snap.take_snapshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_odds_snapshot_now_custom_date(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_snap = mock_services["app.services.scheduler.odds_snapshot_service"]
        mock_snap.take_snapshot = AsyncMock(return_value={"date": "2025-01-01"})
        await svc.trigger_odds_snapshot_now(date="2025-01-01")
        mock_snap.take_snapshot.assert_awaited_once_with("2025-01-01")

    @pytest.mark.asyncio
    async def test_trigger_lineup_fetch_now_default_date(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_lineup = mock_services["app.services.scheduler.lineup_service"]
        mock_lineup.fetch_and_store = AsyncMock(return_value=[])
        await svc.trigger_lineup_fetch_now()
        mock_lineup.fetch_and_store.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_lineup_fetch_now_custom_date(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_lineup = mock_services["app.services.scheduler.lineup_service"]
        mock_lineup.fetch_and_store = AsyncMock(return_value=[])
        await svc.trigger_lineup_fetch_now(date="2025-02-20")
        mock_lineup.fetch_and_store.assert_awaited_once_with("2025-02-20")


# ---------------------------------------------------------------------------
# Internal job methods - error handling
# ---------------------------------------------------------------------------


class TestJobErrorHandling:

    @pytest.mark.asyncio
    async def test_daily_analysis_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_daily = mock_services["app.services.scheduler.daily_analysis_service"]
        mock_daily.run_daily_analysis = AsyncMock(
            side_effect=RuntimeError("connection failed")
        )
        # Should not raise
        await svc._run_daily_analysis_job()

    @pytest.mark.asyncio
    async def test_csv_download_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_csv = mock_services["app.services.scheduler.csv_downloader_service"]
        mock_csv.download = AsyncMock(side_effect=RuntimeError("network error"))
        # Should not raise
        await svc._run_csv_download_job()

    @pytest.mark.asyncio
    async def test_projection_fetch_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_proj = mock_services["app.services.scheduler.projection_service"]
        mock_proj.fetch_and_store = AsyncMock(side_effect=RuntimeError("API down"))
        # Should not raise
        await svc._run_projection_fetch_job()

    @pytest.mark.asyncio
    async def test_projection_fetch_final_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_proj = mock_services["app.services.scheduler.projection_service"]
        mock_proj.fetch_and_store = AsyncMock(side_effect=RuntimeError("fail"))
        # Should not raise
        await svc._run_projection_fetch_final_job()

    @pytest.mark.asyncio
    async def test_odds_snapshot_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_snap = mock_services["app.services.scheduler.odds_snapshot_service"]
        mock_snap.take_snapshot = AsyncMock(side_effect=RuntimeError("timeout"))
        # Should not raise
        await svc._run_odds_snapshot_job()

    @pytest.mark.asyncio
    async def test_hot_key_prewarm_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_gw = mock_services["app.services.scheduler.odds_gateway"]
        mock_gw.prewarm_hot_keys = AsyncMock(side_effect=RuntimeError("redis down"))
        # Should not raise
        await svc._run_hot_key_prewarm_job()

    @pytest.mark.asyncio
    async def test_lineup_fetch_job_handles_exception(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_lineup = mock_services["app.services.scheduler.lineup_service"]
        mock_lineup.fetch_and_store = AsyncMock(side_effect=RuntimeError("fail"))
        # Should not raise
        await svc._run_lineup_fetch_job()


# ---------------------------------------------------------------------------
# Internal job methods - success paths
# ---------------------------------------------------------------------------


class TestJobSuccessPaths:

    @pytest.mark.asyncio
    async def test_csv_download_job_success(self, scheduler_cls, mock_services):
        svc = scheduler_cls()
        mock_csv = mock_services["app.services.scheduler.csv_downloader_service"]
        mock_csv.download = AsyncMock(return_value=True)
        # Should not raise
        await svc._run_csv_download_job()
        mock_csv.download.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_csv_download_job_returns_false(self, scheduler_cls, mock_services):
        """download() returning False is a soft failure, not an exception."""
        svc = scheduler_cls()
        mock_csv = mock_services["app.services.scheduler.csv_downloader_service"]
        mock_csv.download = AsyncMock(return_value=False)
        await svc._run_csv_download_job()

    @pytest.mark.asyncio
    async def test_projection_fetch_final_clears_cache(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_proj = mock_services["app.services.scheduler.projection_service"]
        mock_proj.fetch_and_store = AsyncMock(return_value=[{"player": "A"}])
        mock_cache = mock_services["app.services.scheduler.cache_service"]
        mock_cache.clear_daily_picks_cache = AsyncMock(return_value=3)

        await svc._run_projection_fetch_final_job()

        mock_proj.fetch_and_store.assert_awaited_once()
        mock_cache.clear_daily_picks_cache.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hot_key_prewarm_success_nonzero(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_gw = mock_services["app.services.scheduler.odds_gateway"]
        mock_gw.prewarm_hot_keys = AsyncMock(return_value=5)
        await svc._run_hot_key_prewarm_job()
        mock_gw.prewarm_hot_keys.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hot_key_prewarm_success_zero(
        self, scheduler_cls, mock_services
    ):
        svc = scheduler_cls()
        mock_gw = mock_services["app.services.scheduler.odds_gateway"]
        mock_gw.prewarm_hot_keys = AsyncMock(return_value=0)
        await svc._run_hot_key_prewarm_job()

    @pytest.mark.asyncio
    async def test_odds_snapshot_job_success(self, scheduler_cls, mock_services):
        svc = scheduler_cls()
        mock_snap = mock_services["app.services.scheduler.odds_snapshot_service"]
        mock_snap.take_snapshot = AsyncMock(
            return_value={
                "date": "2025-06-15",
                "event_count": 8,
                "total_lines": 200,
                "duration_ms": 456,
            }
        )
        await svc._run_odds_snapshot_job()
        mock_snap.take_snapshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lineup_fetch_job_success(self, scheduler_cls, mock_services):
        svc = scheduler_cls()
        mock_lineup = mock_services["app.services.scheduler.lineup_service"]
        mock_lineup.fetch_and_store = AsyncMock(return_value=["team1", "team2"])
        await svc._run_lineup_fetch_job()
        mock_lineup.fetch_and_store.assert_awaited_once()
