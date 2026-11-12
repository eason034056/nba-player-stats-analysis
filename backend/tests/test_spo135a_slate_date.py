"""SPO-135a: US slate date on jobs and API defaults, and league on fetch logs.

The evening instant is 2026-11-11T00:30:00Z, which is 18:30 CST on
2026-11-10 and still 2026-11-10 in America/New_York. The later instant
is 2026-11-11T05:30:00Z, which is 23:30 CST on 2026-11-11 and 00:30 EST
on 2026-11-11. An omitted date resolves to that Eastern calendar day.
An explicit date is left alone. Projection jobs stay on the UTC date.
"""

from __future__ import annotations

import sys
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
for _path in (_BACKEND, _REPO / "scripts" / "agents"):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from app.main import app  # noqa: E402
from app.middleware.rate_limit import limiter  # noqa: E402
from app.models.schemas import DailyPicksResponse  # noqa: E402
from app.services.daily_analysis import daily_analysis_service  # noqa: E402
from app.services.db import db_service  # noqa: E402
from app.services.lineup_service import wnba_lineup_service  # noqa: E402
from app.services.odds_snapshot_service import odds_snapshot_service  # noqa: E402
from app.services.scheduler import SchedulerService  # noqa: E402
from app.services.slate_date import nba_slate_date  # noqa: E402
from app.settings import settings  # noqa: E402

# 6:30 PM CST on 2026-11-10. UTC has already rolled to 2026-11-11.
_EVENING = datetime(2026, 11, 11, 0, 30, tzinfo=timezone.utc)
# 11:30 PM CST on 2026-11-11, which is 00:30 EST on 2026-11-11.
_AFTER_ET_MIDNIGHT = datetime(2026, 11, 11, 5, 30, tzinfo=timezone.utc)
_SLATE_CASES = (
    (_EVENING, "2026-11-10"),
    (_AFTER_ET_MIDNIGHT, "2026-11-11"),
)
_LOG_DATE = "2099-11-10"


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


def _freeze_slate(monkeypatch, moment: datetime) -> None:
    """Freeze the clock inside ``nba_slate_date``.

    The helper reads ``datetime.now`` from its own module. Callers pass
    no instant, so one patch covers the jobs and the API defaults.
    """

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return moment
            return moment.astimezone(tz)

    monkeypatch.setattr("app.services.slate_date.datetime", FrozenDateTime)


def _analysis(date: str) -> DailyPicksResponse:
    return DailyPicksResponse(
        date=date,
        analyzed_at="2026-11-10T00:30:00+00:00",
        total_picks=0,
        picks=[],
    )


def _lineup(team: str, date: str) -> dict:
    return {
        "date": date,
        "team": team,
        "opponent": "LAL",
        "home_or_away": "HOME",
        "status": "projected",
        "starters": ["A", "B", "C", "D", "E"],
        "bench_candidates": [],
        "sources": ["rotowire"],
        "source_disagreement": False,
        "confidence": "low",
        "updated_at": "2026-11-10T23:00:00+00:00",
        "source_snapshots": {},
    }


@pytest.mark.parametrize(("moment", "expected"), _SLATE_CASES)
def test_helper_pins_the_eastern_boundary(moment, expected):
    assert nba_slate_date(moment)[0] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("moment", "expected"), _SLATE_CASES)
async def test_jobs_use_the_us_slate_date(monkeypatch, moment, expected):
    _freeze_slate(monkeypatch, moment)
    daily = AsyncMock(return_value=MagicMock(date=expected, total_picks=0, stats=None))
    lineup = AsyncMock(return_value={})
    wnba_lineup = AsyncMock(return_value={})
    monkeypatch.setattr(
        "app.services.scheduler.daily_analysis_service.run_daily_analysis",
        daily,
    )
    monkeypatch.setattr(
        "app.services.scheduler.lineup_service.fetch_and_store",
        lineup,
    )
    monkeypatch.setattr(
        "app.services.scheduler.wnba_lineup_service.fetch_and_store",
        wnba_lineup,
    )

    service = SchedulerService()
    await service._run_lineup_fetch_job()
    await service._run_wnba_lineup_fetch_job()
    await service._run_daily_analysis_job()
    await service._run_wnba_daily_analysis_job()
    await service.trigger_lineup_fetch_now()

    assert lineup.await_args_list[0].args == (expected,)
    assert lineup.await_args_list[1].args == (expected,)
    assert wnba_lineup.await_args_list[0].args == (expected,)
    assert daily.await_args_list[0].kwargs["date"] == expected
    assert "league" not in daily.await_args_list[0].kwargs
    assert daily.await_args_list[1].kwargs["date"] == expected
    assert daily.await_args_list[1].kwargs["league"] == "wnba"


@pytest.mark.asyncio
@pytest.mark.parametrize(("moment", "expected"), _SLATE_CASES)
async def test_run_daily_analysis_omitted_date_is_the_us_slate(
    monkeypatch, moment, expected
):
    _freeze_slate(monkeypatch, moment)
    monkeypatch.setattr(
        "app.services.daily_analysis.cache_service.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        daily_analysis_service,
        "_get_events_for_date",
        AsyncMock(return_value=[]),
    )

    nba = await daily_analysis_service.run_daily_analysis()
    wnba = await daily_analysis_service.run_daily_analysis(league="wnba")

    assert nba.date == expected
    assert wnba.date == expected


@pytest.mark.parametrize(("moment", "expected"), _SLATE_CASES)
def test_agent_lineup_date_is_the_us_slate(monkeypatch, moment, expected):
    import tools.historical as historical

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return moment
            return moment.astimezone(tz)

    monkeypatch.setattr(historical, "datetime", FrozenDateTime)
    assert historical._today_date_string() == expected


def _patch_http(monkeypatch) -> list[tuple[str, str]]:
    """Replace network and storage behind the omitted-date routes."""
    calls: list[tuple[str, str]] = []

    async def nba_lineups(date: str):
        calls.append(("nba_lineups", date))
        from app.services.lineup_service import LineupReadResult

        return LineupReadResult(
            date=date, lineups={"BOS": _lineup("BOS", date)}, fetched_at=None, cache_state="fresh"
        )

    async def nba_team(date: str, team: str):
        calls.append(("nba_team", date))
        return _lineup(team, date), "fresh", None

    async def nba_refresh(date: str):
        calls.append(("nba_refresh", date))
        return {"BOS": _lineup("BOS", date)}

    async def wnba_lineups(date: str):
        calls.append(("wnba_lineups", date))
        from app.services.lineup_service import LineupReadResult

        return LineupReadResult(
            date=date, lineups={"MIN": _lineup("MIN", date)}, fetched_at=None, cache_state="fresh"
        )

    async def wnba_team(date: str, team: str):
        calls.append(("wnba_team", date))
        return _lineup(team, date), "fresh", None

    async def wnba_refresh(date: str):
        calls.append(("wnba_refresh", date))
        return {"MIN": _lineup("MIN", date)}

    async def analysis(**kwargs):
        calls.append((kwargs.get("league", "nba") + "_analysis", kwargs["date"]))
        return _analysis(kwargs["date"])

    async def events(**kwargs):
        return []

    async def cache_get(_key):
        return None

    async def cache_set(*_args, **_kwargs):
        return True

    async def cache_delete(_key):
        return True

    async def join_reads(response, _offset):
        return response

    monkeypatch.setattr("app.api.lineups.lineup_service.get_lineups", nba_lineups)
    monkeypatch.setattr("app.api.lineups.lineup_service.get_team_lineup", nba_team)
    monkeypatch.setattr("app.api.lineups.lineup_service.fetch_and_store", nba_refresh)
    monkeypatch.setattr("app.api.wnba.wnba_lineup_service.get_lineups", wnba_lineups)
    monkeypatch.setattr("app.api.wnba.wnba_lineup_service.get_team_lineup", wnba_team)
    monkeypatch.setattr("app.api.wnba.wnba_lineup_service.fetch_and_store", wnba_refresh)
    monkeypatch.setattr(
        "app.api.daily_picks.daily_analysis_service.run_daily_analysis",
        analysis,
    )
    monkeypatch.setattr(
        "app.api.wnba.daily_analysis_service.run_daily_analysis",
        analysis,
    )
    monkeypatch.setattr(
        "app.api.picks.daily_analysis_service.run_daily_analysis",
        analysis,
    )
    monkeypatch.setattr("app.api.nba.cache_service.get", cache_get)
    monkeypatch.setattr("app.api.nba.cache_service.set", cache_set)
    monkeypatch.setattr("app.api.nba.odds_provider.get_events", events)
    monkeypatch.setattr("app.api.nba._with_reads_and_event_fields", join_reads)
    monkeypatch.setattr("app.api.wnba.cache_service.get", cache_get)
    monkeypatch.setattr("app.api.wnba.cache_service.set", cache_set)
    monkeypatch.setattr("app.api.wnba.odds_provider.get_events", events)
    monkeypatch.setattr("app.api.daily_picks.cache_service.delete", cache_delete)
    monkeypatch.setattr(settings, "bot_api_keys", "slate-test-key")
    return calls


@pytest.mark.parametrize(("moment", "expected"), _SLATE_CASES)
def test_api_omitted_date_is_the_us_slate(monkeypatch, moment, expected):
    _freeze_slate(monkeypatch, moment)
    calls = _patch_http(monkeypatch)

    with TestClient(app) as client:
        lineups = client.get("/api/nba/lineups")
        team = client.get("/api/nba/lineups/BOS")
        refresh = client.post("/api/nba/lineups/refresh")
        picks = client.get("/api/nba/daily-picks")
        trigger = client.post("/api/nba/daily-picks/trigger")
        cleared = client.delete("/api/nba/daily-picks/cache")
        events = client.get("/api/nba/events")
        wnba_events = client.get("/api/wnba/events")
        wnba_picks = client.get("/api/wnba/daily-picks")
        wnba_trigger = client.post("/api/wnba/daily-picks/trigger")
        wnba_lineups = client.get("/api/wnba/lineups")
        wnba_team = client.get("/api/wnba/lineups/MIN")
        wnba_refresh = client.post("/api/wnba/lineups/refresh")
        bot = client.get("/api/picks/today", headers={"X-API-Key": "slate-test-key"})

    bodies = {
        "GET /api/nba/lineups": lineups,
        "GET /api/nba/lineups/BOS": team,
        "POST /api/nba/lineups/refresh": refresh,
        "GET /api/nba/daily-picks": picks,
        "POST /api/nba/daily-picks/trigger": trigger,
        "GET /api/nba/events": events,
        "GET /api/wnba/events": wnba_events,
        "GET /api/wnba/daily-picks": wnba_picks,
        "POST /api/wnba/daily-picks/trigger": wnba_trigger,
        "GET /api/wnba/lineups": wnba_lineups,
        "GET /api/wnba/lineups/MIN": wnba_team,
        "POST /api/wnba/lineups/refresh": wnba_refresh,
        "GET /api/picks/today": bot,
    }
    for label, response in bodies.items():
        assert response.status_code == 200, (label, response.status_code, response.text)
        assert response.json()["date"] == expected, label
    assert cleared.status_code == 200
    assert expected in cleared.json()["message"]
    labels = {label for label, _date in calls}
    assert labels == {
        "nba_lineups",
        "nba_team",
        "nba_refresh",
        "wnba_lineups",
        "wnba_team",
        "wnba_refresh",
        "nba_analysis",
        "wnba_analysis",
    }
    assert {called_date for _label, called_date in calls} == {expected}


def test_explicit_date_is_unchanged_during_the_evening_window(monkeypatch):
    _freeze_slate(monkeypatch, _EVENING)
    calls = _patch_http(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/nba/lineups", params={"date": "2026-01-02"})

    assert response.status_code == 200
    assert response.json()["date"] == "2026-01-02"
    assert ("nba_lineups", "2026-01-02") in calls


async def _connect_or_skip() -> None:
    """Open the pool, or skip when this machine has no Postgres.

    ``init`` catches a refused connection and leaves the pool unset.
    CI runs these tests. A checkout without a database skips them.
    """
    await db_service.init()
    if not db_service.is_connected:
        pytest.skip("Postgres is not available")


@pytest.mark.asyncio
async def test_wnba_lineup_fetch_log_stores_league_wnba(monkeypatch):
    def fake_rotowire(date, league="nba"):
        assert date == _LOG_DATE
        assert league == "wnba"
        return {"MIN": _lineup("MIN", date)}

    monkeypatch.setattr(
        "app.services.lineup_service.fetch_rotowire_lineups",
        fake_rotowire,
    )
    monkeypatch.setattr(wnba_lineup_service, "_write_to_redis", AsyncMock())
    monkeypatch.setattr(
        "app.services.lineup_service.cache_service.clear_daily_picks_cache",
        AsyncMock(return_value=0),
    )

    await _connect_or_skip()
    started = datetime.now(timezone.utc)
    try:
        await db_service.execute(
            "DELETE FROM lineup_fetch_logs WHERE date = $1",
            date_type.fromisoformat(_LOG_DATE),
        )
        await db_service.execute(
            "DELETE FROM team_lineup_snapshots WHERE date = $1",
            date_type.fromisoformat(_LOG_DATE),
        )
        stored = await wnba_lineup_service.fetch_and_store(_LOG_DATE)
        assert "MIN" in stored

        logs = await db_service.fetch(
            """
            SELECT league, status, team_count
            FROM lineup_fetch_logs
            WHERE date = $1 AND fetched_at >= $2
            ORDER BY fetched_at
            """,
            date_type.fromisoformat(_LOG_DATE),
            started,
        )
        assert len(logs) == 1
        assert logs[0]["league"] == "wnba"
        assert logs[0]["status"] == "success"
        assert logs[0]["team_count"] == 1

        snapshots = await db_service.fetch(
            """
            SELECT league FROM team_lineup_snapshots
            WHERE date = $1 AND league = 'wnba'
            """,
            date_type.fromisoformat(_LOG_DATE),
        )
        assert snapshots == []
    finally:
        if db_service.is_connected:
            await db_service.execute(
                "DELETE FROM lineup_fetch_logs WHERE date = $1",
                date_type.fromisoformat(_LOG_DATE),
            )
            await db_service.execute(
                "DELETE FROM team_lineup_snapshots WHERE date = $1",
                date_type.fromisoformat(_LOG_DATE),
            )
            await db_service.close()


@pytest.mark.asyncio
async def test_nba_odds_snapshot_log_stores_league_nba():
    await _connect_or_skip()
    started = datetime.now(timezone.utc)
    try:
        await odds_snapshot_service._log_snapshot(
            date=_LOG_DATE,
            snapshot_at=started,
            event_count=0,
            total_lines=0,
            status="success",
            error_message="spo135a",
            duration_ms=1,
        )
        logs = await db_service.fetch(
            """
            SELECT league, status, event_count
            FROM odds_snapshot_logs
            WHERE snapshot_at = $1
            """,
            started,
        )
        assert len(logs) == 1
        assert logs[0]["league"] == "nba"
        assert logs[0]["status"] == "success"
        assert logs[0]["event_count"] == 0
    finally:
        if db_service.is_connected:
            await db_service.execute(
                "DELETE FROM odds_snapshot_logs WHERE snapshot_at = $1",
                started,
            )
            await db_service.close()
