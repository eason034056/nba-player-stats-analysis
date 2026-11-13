"""SPO-130b QA: WNBA_JOBS_ENABLED parsing, NBA job shape, compose passthrough, and the lineup read.

The compose line and the lineup read used to be xfail(strict=True). Both gaps
are fixed, so those tests run for real.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.scheduler import SchedulerService
from app.settings import Settings, settings

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Recorder:
    """Stand-in for AsyncIOScheduler that keeps each registration's id, name, and trigger text."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.jobs: list[tuple[str, str, str]] = []

    def add_job(self, func: object, trigger: object = None, **kwargs: object) -> None:
        self.jobs.append((str(kwargs["id"]), str(kwargs.get("name", "")), str(trigger)))

    def start(self) -> None:
        return None

    def get_jobs(self) -> list[object]:
        return []


def _registrations() -> list[tuple[str, str, str]]:
    service = SchedulerService()
    with patch("app.services.scheduler.AsyncIOScheduler", _Recorder):
        service.start()
    return list(service._scheduler.jobs)


@pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off"])
def test_false_spellings_turn_the_flag_off(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("WNBA_JOBS_ENABLED", raw)
    assert Settings(_env_file=None).wnba_jobs_enabled is False


@pytest.mark.parametrize("raw", ["true", "True", "1", "yes", "on"])
def test_true_spellings_keep_the_flag_on(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("WNBA_JOBS_ENABLED", raw)
    assert Settings(_env_file=None).wnba_jobs_enabled is True


@pytest.mark.parametrize("raw", ["", " false", "flase", "disabled"])
def test_unreadable_values_stop_settings_instead_of_meaning_true(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """An empty or mistyped value must not silently keep the WNBA jobs on."""
    monkeypatch.setenv("WNBA_JOBS_ENABLED", raw)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_nba_jobs_keep_their_ids_names_and_triggers_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "wnba_jobs_enabled", True)
    on = _registrations()
    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    off = _registrations()

    nba_on = [job for job in on if not job[0].startswith("wnba")]
    assert off == nba_on
    assert len(on) - len(off) == 4
    assert {job[0] for job in on if job[0].startswith("wnba")} == {
        "wnba_daily_analysis_job",
        "wnba_lineup_fetch_opening",
        "wnba_lineup_fetch_active_window",
        "wnba_lineup_fetch_pre_tipoff",
    }


def _compose_backend_env() -> set[str]:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = text.split("\n  backend:\n", 1)[1]
    block = re.split(r"\n  [a-z][\w-]*:\n", block, maxsplit=1)[0]
    return set(re.findall(r"^\s+-\s+([A-Z][A-Z0-9_]*)=", block, flags=re.M))


def test_compose_passes_wnba_jobs_enabled_to_the_backend() -> None:
    names = _compose_backend_env()
    assert "DATABASE_REQUIRED" in names
    assert "WNBA_JOBS_ENABLED" in names


def test_wnba_lineups_read_does_not_refetch_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.lineup_service as lineup_module
    from app.main import app

    monkeypatch.setattr(settings, "wnba_jobs_enabled", False)
    fetch = AsyncMock(return_value={})
    monkeypatch.setattr(lineup_module.wnba_lineup_service, "fetch_and_store", fetch)
    monkeypatch.setattr(lineup_module.cache_service, "get", AsyncMock(return_value=None))

    TestClient(app).get("/api/wnba/lineups?date=2026-07-01")

    assert fetch.await_count == 0
