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
from unittest.mock import patch

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
