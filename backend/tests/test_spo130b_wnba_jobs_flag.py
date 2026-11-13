"""SPO-130b: WNBA_JOBS_ENABLED gates the four WNBA scheduler jobs.

``TODAY_JOB_IDS`` is the registration order of ``SchedulerService.start()``
with the flag true or unset. False must drop every id that starts with
``wnba`` and keep the other ids in that same order. The stand-in
scheduler only stores those ids. ``start()`` does not fire a trigger.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.scheduler import SchedulerService
from app.settings import Settings, settings

# Snapshot of today's add_job order in scheduler.py.
TODAY_JOB_IDS = [
    "daily_analysis_job",
    "wnba_daily_analysis_job",
    "csv_download_job",
    "odds_snapshot_early",
    "odds_snapshot_mid",
    "odds_snapshot_final",
    "odds_hot_key_prewarm",
    "lineup_fetch_opening",
    "lineup_fetch_active_window",
    "lineup_fetch_pre_tipoff",
    "wnba_lineup_fetch_opening",
    "wnba_lineup_fetch_active_window",
    "wnba_lineup_fetch_pre_tipoff",
    "nba_injuries_refresh",
    "nba_injuries_startup_fill",
]

SKIP_LOG = (
    "WNBA_JOBS_ENABLED is false; skipping WNBA jobs: "
    "wnba_daily_analysis_job, wnba_lineup_fetch_opening, "
    "wnba_lineup_fetch_active_window, wnba_lineup_fetch_pre_tipoff"
)


class _StoredJob:
    """One recorded registration. The callable is never invoked."""

    def __init__(self, job_id: str, name: str) -> None:
        self.id = job_id
        self.name = name
        self.next_run_time = None


class _NoOpScheduler:
    """Fake job store used in place of AsyncIOScheduler.

    ``add_job`` appends the id. ``start`` does not run interval, cron,
    or date triggers. ``get_jobs`` is what ``SchedulerService.start``
    prints after the real scheduler would have started.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._jobs: list[_StoredJob] = []

    def add_job(self, func: object, trigger: object = None, **kwargs: object) -> None:
        job_id = kwargs["id"]
        name = kwargs.get("name", "")
        self._jobs.append(_StoredJob(str(job_id), str(name)))

    def start(self) -> None:
        return None

    def get_jobs(self) -> list[_StoredJob]:
        return list(self._jobs)


def _registered_ids() -> list[str]:
    """Start a fresh scheduler against the no-op store and return job ids."""
    service = SchedulerService()
    with patch("app.services.scheduler.AsyncIOScheduler", _NoOpScheduler):
        service.start()
    return [job.id for job in service._scheduler.get_jobs()]


def _skip_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and record.getMessage() == SKIP_LOG
    ]


def test_setting_defaults_true_when_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No WNBA_JOBS_ENABLED means the field default, which is true."""
    monkeypatch.delenv("WNBA_JOBS_ENABLED", raising=False)
    fresh = Settings(_env_file=None)
    assert Settings.model_fields["wnba_jobs_enabled"].default is True
    assert fresh.wnba_jobs_enabled is True


def test_setting_reads_env_true_and_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env name is WNBA_JOBS_ENABLED. Both spellings reach the field."""
    monkeypatch.setenv("WNBA_JOBS_ENABLED", "true")
    assert Settings(_env_file=None).wnba_jobs_enabled is True
    monkeypatch.setenv("WNBA_JOBS_ENABLED", "false")
    assert Settings(_env_file=None).wnba_jobs_enabled is False


def test_flag_true_matches_today_job_ids(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Explicit true registers the snapshot and does not log a skip."""
    monkeypatch.setattr(settings, "wnba_jobs_enabled", True)
    caplog.set_level(logging.INFO, logger="app.services.scheduler")
    assert _registered_ids() == TODAY_JOB_IDS
    assert _skip_logs(caplog) == []


def test_flag_unset_matches_today_job_ids(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An unset env uses the default true and the same job-id list."""
    monkeypatch.delenv("WNBA_JOBS_ENABLED", raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.wnba_jobs_enabled is True
    monkeypatch.setattr(settings, "wnba_jobs_enabled", fresh.wnba_jobs_enabled)
    caplog.set_level(logging.INFO, logger="app.services.scheduler")
    assert _registered_ids() == TODAY_JOB_IDS
    assert _skip_logs(caplog) == []


def test_flag_false_drops_wnba_jobs_and_logs_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """False keeps every non-wnba id from the true set and logs one line."""
    monkeypatch.setattr(settings, "wnba_jobs_enabled", True)
    true_ids = _registered_ids()
    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    caplog.set_level(logging.INFO, logger="app.services.scheduler")
    false_ids = _registered_ids()

    assert true_ids == TODAY_JOB_IDS
    assert false_ids == [job_id for job_id in true_ids if not job_id.startswith("wnba")]
    assert all(not job_id.startswith("wnba") for job_id in false_ids)
    assert any(job_id.startswith("wnba") for job_id in true_ids)
    assert len(_skip_logs(caplog)) == 1


def test_compose_passes_wnba_jobs_enabled_to_the_backend() -> None:
    """Root compose lists env vars by name. .env only fills names on that list.

    The default inside ``:-true`` keeps an unset variable from becoming
    an empty string. An empty string makes Settings fail at startup.
    """
    root = Path(__file__).resolve().parents[2]
    text = (root / "docker-compose.yml").read_text()
    backend = text.split("container_name: no-vig-nba-backend", 1)[1]
    backend = backend.split("container_name:", 1)[0]
    assert "- WNBA_JOBS_ENABLED=${WNBA_JOBS_ENABLED:-true}" in backend


@pytest.mark.asyncio
async def test_wnba_fetch_and_store_does_not_write_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scrape, Redis, and Postgres all sit inside fetch_and_store."""
    from app.services.lineup_service import wnba_lineup_service

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    scrape = AsyncMock(side_effect=AssertionError("scrape"))
    monkeypatch.setattr("app.services.lineup_service.fetch_rotowire_lineups", scrape)
    monkeypatch.setattr(
        "app.services.lineup_service.cache_service.set",
        AsyncMock(side_effect=AssertionError("redis")),
    )
    monkeypatch.setattr(
        "app.services.lineup_service.db_service.execute",
        AsyncMock(side_effect=AssertionError("postgres")),
    )
    monkeypatch.setattr(
        "app.services.lineup_service.db_service.executemany",
        AsyncMock(side_effect=AssertionError("postgres")),
    )

    assert await wnba_lineup_service.fetch_and_store("2026-07-01") == {}
    scrape.assert_not_called()


@pytest.mark.asyncio
async def test_nba_fetch_and_store_still_scrapes_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.lineup_service import lineup_service

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    called = {"nba": False}

    def _rotowire(date: str) -> dict:
        called["nba"] = True
        return {}

    monkeypatch.setattr("app.services.lineup_service.fetch_rotowire_lineups", _rotowire)
    monkeypatch.setattr(
        "app.services.lineup_service.fetch_rotogrinders_lineups",
        lambda date: {},
    )
    monkeypatch.setattr(lineup_service, "_log_fetch", AsyncMock())

    with pytest.raises(RuntimeError):
        await lineup_service.fetch_and_store("2026-07-01")
    assert called["nba"] is True


@pytest.mark.asyncio
async def test_wnba_daily_analysis_does_not_call_odds_or_write_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.daily_analysis import daily_analysis_service

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    events = AsyncMock(side_effect=AssertionError("odds"))
    monkeypatch.setattr(daily_analysis_service, "_get_events_for_date", events)
    monkeypatch.setattr(
        "app.services.daily_analysis.cache_service.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.daily_analysis.cache_service.set",
        AsyncMock(side_effect=AssertionError("redis")),
    )

    result = await daily_analysis_service.run_daily_analysis(
        date="2026-07-01",
        use_cache=True,
        league="wnba",
    )
    assert result.total_picks == 0
    assert result.picks == []
    assert result.message == "WNBA jobs are paused (WNBA_JOBS_ENABLED=false)"
    events.assert_not_awaited()


@pytest.mark.asyncio
async def test_wnba_daily_analysis_returns_a_stored_board_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.schemas import DailyPicksResponse
    from app.services.daily_analysis import daily_analysis_service

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    stored = DailyPicksResponse(
        date="2026-07-01",
        analyzed_at="2026-07-01T16:00:00+00:00",
        total_picks=0,
        picks=[],
    )
    monkeypatch.setattr(
        "app.services.daily_analysis.cache_service.get",
        AsyncMock(return_value=stored.model_dump()),
    )
    events = AsyncMock(side_effect=AssertionError("odds"))
    monkeypatch.setattr(daily_analysis_service, "_get_events_for_date", events)

    result = await daily_analysis_service.run_daily_analysis(
        date="2026-07-01",
        use_cache=True,
        league="wnba",
    )
    assert result.date == "2026-07-01"
    assert result.message is None
    events.assert_not_awaited()


@pytest.mark.asyncio
async def test_nba_daily_analysis_still_fetches_events_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.daily_analysis import daily_analysis_service

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    events = AsyncMock(return_value=[])
    monkeypatch.setattr(daily_analysis_service, "_get_events_for_date", events)

    result = await daily_analysis_service.run_daily_analysis(
        date="2026-07-01",
        use_cache=False,
        league="nba",
    )
    assert result.total_picks == 0
    events.assert_awaited()


def test_wnba_trigger_posts_return_409_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware.rate_limit import limiter

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    analysis = AsyncMock(side_effect=AssertionError("analysis"))
    fetch = AsyncMock(side_effect=AssertionError("lineup"))
    monkeypatch.setattr("app.api.wnba.daily_analysis_service.run_daily_analysis", analysis)
    monkeypatch.setattr("app.api.wnba.wnba_lineup_service.fetch_and_store", fetch)
    limiter.enabled = False
    try:
        client = TestClient(app)
        picks = client.post("/api/wnba/daily-picks/trigger?date=2026-07-01")
        lineups = client.post("/api/wnba/lineups/refresh?date=2026-07-01")
    finally:
        limiter.enabled = True

    assert picks.status_code == 409
    assert lineups.status_code == 409
    assert picks.json()["detail"] == "WNBA jobs are paused (WNBA_JOBS_ENABLED=false)"
    assert lineups.json()["detail"] == "WNBA jobs are paused (WNBA_JOBS_ENABLED=false)"
    analysis.assert_not_called()
    fetch.assert_not_called()
