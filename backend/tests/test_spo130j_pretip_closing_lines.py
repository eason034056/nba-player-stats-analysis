"""SPO-130j: pre-tip closing lines, ten minutes before tip.

The planner reads the SPO-144 tip cache. The DateTrigger job talks to
BALLDONTLIE only. Bodies are the recorded files under tests/fixtures/bdl/.
One postponed test flips the recorded ``postponed`` boolean on a copy.
No other field is invented.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import SecretStr

from app.services.bdl_odds_provider import BdlOddsProvider
from app.services.bdl_player_directory import BdlPlayerDirectory, bdl_player_name
from app.services.cache import cache_service
from app.services.db import db_service
from app.services.odds_snapshot_service import odds_snapshot_service
from app.services.scheduler import (
    NBA_LINEUP_TIPS_CACHE_TTL_SECONDS,
    ODDS_PRETIP_MISFIRE_GRACE_SECONDS,
    ODDS_PRETIP_PLANNER_INTERVAL_MINUTES,
    SchedulerService,
    _dump_tips,
    nba_lineup_tips_cache_key,
    pretip_job_id,
    tips_from_games_payload,
)
from app.settings import Settings, settings

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
EASTERN = ZoneInfo("America/New_York")
SLATE = "2026-11-11"
SLATE_NOV10 = "2026-11-10"
WAS_GAME_ID = 21718081
OKC_GAME_ID = 21718080
# 6:00 PM Eastern on the recorded slate. The first tip is 7:00 PM Eastern.
PLAN_NOW = datetime(2026, 11, 11, 18, 0, tzinfo=EASTERN)
TIP_0000 = datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
BEFORE_0000 = TIP_0000 - timedelta(minutes=10)
# Before every tip on the recorded 2026-11-10 slate.
BEFORE_NOV10 = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
OKC_TIP = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)
IN_PROGRESS_TIP = datetime(2026, 11, 11, 2, 0, tzinfo=timezone.utc)
_TEST_KEY = "unit-test-bdl-key-spo130j"
_SCHEDULER_DEFAULT_GRACE = 3600


def _load(name: str) -> dict:
    """One recorded capture. The file is ``{request, status, response}``."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _response(name: str) -> dict:
    """The ``response`` object ``list_games`` or ``list_odds`` returns."""
    return copy.deepcopy(_load(name)["response"])


def _only_game(name: str, game_id: int) -> dict:
    """Recorded games page filtered to one id. No field is changed."""
    payload = _response(name)
    payload["data"] = [game for game in payload["data"] if game.get("id") == game_id]
    assert len(payload["data"]) == 1
    return payload


class _ClosingClient:
    """Recorded responses plus a call log. It does not build a body."""

    def __init__(
        self,
        *,
        games_name: str = "games_2026-11-11.json",
        props_name: str = "props_live_21718081_WAS@IND_upcoming.json",
        props_game_id: int = WAS_GAME_ID,
        games_payload: dict | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self.games = games_payload if games_payload is not None else _response(games_name)
        self.props = _load(props_name)["response"]
        self.props_game_id = props_game_id
        self.empty_props = _load("props_empty.json")["response"]
        self.players = _load("backend_players_batch45.json")["response"]
        self.odds = _load("odds_2026-11-11.json")["response"]

    async def list_games(self, *, dates: list[str], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_games", tuple(dates), per_page))
        return self.games

    async def get_player_props(self, *, game_id: int):
        self.calls.append(("get_player_props", game_id))
        if game_id == self.props_game_id:
            return self.props
        return self.empty_props

    async def list_players(self, *, player_ids: list[int], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_players", tuple(player_ids)))
        wanted = set(player_ids)
        data = [player for player in self.players["data"] if player["id"] in wanted]
        return {"data": data, "meta": dict(self.players.get("meta") or {})}

    async def get_game(self, *, game_id: int):
        self.calls.append(("get_game", game_id))
        raise AssertionError(f"closing job must not fetch game {game_id} on its own")

    async def list_odds(self, *, dates: list[str], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_odds", tuple(dates), cursor))
        return self.odds


class _GamesClient:
    """Stand-in for ``BdlClient`` when the planner has to read the slate."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []
        self.closed = 0
        self.init_kwargs: list[dict] = []

    def __call__(self, **kwargs: object) -> "_GamesClient":
        self.init_kwargs.append(dict(kwargs))
        return self

    async def list_games(self, **kwargs: object) -> dict:
        self.calls.append(dict(kwargs))
        return self.payload

    async def aclose(self) -> None:
        self.closed += 1


def _kinds(client: _ClosingClient) -> list[str]:
    return [call[0] for call in client.calls]


def _props_ids(client: _ClosingClient) -> list[int]:
    return [call[1] for call in client.calls if call[0] == "get_player_props"]


async def _close_cache() -> None:
    """Close the client this test put on the process cache, on this loop."""
    client = cache_service._client
    cache_service._client = None
    if client is None:
        return
    close = getattr(client, "aclose", None)
    if close is None:
        return
    await close()


def _install_cache(monkeypatch: pytest.MonkeyPatch) -> fakeredis.aioredis.FakeRedis:
    """Point the process cache at an in-memory Redis. No socket is opened."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_service, "_client", fake)
    return fake


def _install_closing(
    monkeypatch: pytest.MonkeyPatch,
    client: _ClosingClient | None = None,
) -> tuple[_ClosingClient, BdlOddsProvider]:
    """BALLDONTLIE fixture provider. The active odds provider stays The Odds API."""
    fixture = client or _ClosingClient()
    provider = BdlOddsProvider(fixture, directory=BdlPlayerDirectory(fixture, aliases={}))
    monkeypatch.setattr(settings, "nba_odds_provider", "theoddsapi")
    monkeypatch.setattr(
        "app.services.bdl_odds_provider.get_bdl_odds_provider",
        lambda: provider,
    )
    gateway_calls: list[str] = []

    async def _gateway(*args: object, **kwargs: object) -> None:
        gateway_calls.append("called")
        raise AssertionError("closing job must not use the odds gateway")

    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway.get_market_snapshot", _gateway)
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway.list_events", _gateway)
    fixture.gateway_calls = gateway_calls  # type: ignore[attr-defined]
    return fixture, provider


def _scheduler_with_hour_default() -> AsyncIOScheduler:
    """A paused scheduler whose default grace is one hour.

    Closing jobs must pass their own grace. ``add_job`` only replaces an
    id after ``start``. Paused means the recorded tips, which are already
    in the past, are stored and not fired.
    """
    sched = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": _SCHEDULER_DEFAULT_GRACE,
        },
    )
    sched.start(paused=True)
    return sched


def _stop_scheduler(sched: AsyncIOScheduler | None) -> None:
    if sched is not None and getattr(sched, "running", False):
        sched.shutdown(wait=False)


def _registered(service: SchedulerService) -> dict[str, dict]:
    """Job id to ``add_job`` kwargs from one ``start()`` against a fake scheduler."""
    from unittest.mock import MagicMock, patch

    with patch("app.services.scheduler.AsyncIOScheduler") as mock_sched:
        instance = MagicMock()
        instance.get_jobs.return_value = []
        mock_sched.return_value = instance
        service.start()
    found: dict[str, dict] = {}
    for call in instance.add_job.call_args_list:
        _args, kwargs = call
        found[str(kwargs["id"])] = kwargs
    return found


async def _scalar(sql: str, *args: object) -> object:
    row = await db_service.fetchrow(sql, *args)
    if row is None:
        return None
    return next(iter(row.values()))


async def _upgrade(dsn: str) -> None:
    import asyncpg

    from app.migrations.runner import upgrade

    conn = await asyncpg.connect(dsn)
    try:
        applied = await upgrade(conn)
    finally:
        await conn.close()
    assert applied[:5] == ["001", "002", "003", "004", "005"]


async def _seed_was_parents(dsn: str) -> None:
    """Insert the scheduled 2026-11-11 game and the players named in its props."""
    import asyncpg

    game = next(item for item in _load("games_2026-11-11.json")["response"]["data"] if item["id"] == WAS_GAME_ID)
    prop_ids = {
        row["player_id"]
        for row in _load("props_live_21718081_WAS@IND_upcoming.json")["response"]["data"]
        if isinstance(row.get("player_id"), int)
    }
    players = [
        player
        for player in _load("backend_players_batch45.json")["response"]["data"]
        if player["id"] in prop_ids
    ]
    tip = datetime.fromisoformat(game["datetime"].replace("Z", "+00:00"))
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO seasons (league, season_start_year, label) VALUES ('nba', $1, $2)",
            game["season"],
            str(game["season"]),
        )
        for side in ("home_team", "visitor_team"):
            team = game[side]
            await conn.execute(
                """
                INSERT INTO teams (league, bdl_team_id, abbreviation, full_name)
                VALUES ('nba', $1, $2, $3)
                """,
                team["id"],
                team["abbreviation"],
                team["full_name"],
            )
        await conn.execute(
            """
            INSERT INTO games (
                league, bdl_game_id, season, date, datetime_utc, status, season_type,
                home_team_id, visitor_team_id
            ) VALUES ('nba', $1, $2, $3, $4, $5, 'regular_season', $6, $7)
            """,
            game["id"],
            game["season"],
            date.fromisoformat(game["date"]),
            tip,
            game["status_state"],
            game["home_team"]["id"],
            game["visitor_team"]["id"],
        )
        await conn.executemany(
            """
            INSERT INTO players (league, bdl_player_id, display_name)
            VALUES ('nba', $1, $2)
            """,
            [(player["id"], bdl_player_name(player)) for player in players],
        )
    finally:
        await conn.close()


async def _use_database(monkeypatch: pytest.MonkeyPatch, dsn: str) -> None:
    monkeypatch.setattr(settings, "database_url", dsn)
    if db_service.is_connected:
        await db_service.close()
    await db_service.init()
    assert db_service.is_connected


def test_code_defaults_stay_the_odds_api_and_five_per_minute() -> None:
    """This job does not flip the provider and does not change the rate limit."""
    assert Settings.model_fields["nba_odds_provider"].default == "theoddsapi"
    assert Settings.model_fields["bdl_rate_limit_per_min"].default == 5


def test_start_registers_daily_interval_and_startup_planner() -> None:
    """Process start, every 30 minutes, and once a day all call the same planner."""
    found = _registered(SchedulerService())
    daily = found["odds_pretip_planner_daily"]
    assert daily["replace_existing"] is True
    assert isinstance(daily["trigger"], CronTrigger)
    assert str(daily["trigger"].timezone) == "America/New_York"
    interval = found["odds_pretip_planner"]
    assert interval["replace_existing"] is True
    assert isinstance(interval["trigger"], IntervalTrigger)
    assert interval["trigger"].interval == timedelta(minutes=ODDS_PRETIP_PLANNER_INTERVAL_MINUTES)
    startup = found["odds_pretip_planner_startup"]
    assert startup["replace_existing"] is True
    assert isinstance(startup["trigger"], DateTrigger)
    assert startup["misfire_grace_time"] == 60
    assert found["odds_snapshot_early"]["replace_existing"] is True
    assert found["odds_snapshot_mid"]["replace_existing"] is True
    assert found["odds_snapshot_final"]["replace_existing"] is True


@pytest.mark.asyncio
async def test_planner_schedules_one_alarm_per_tip_minute_and_replaces_on_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five recorded tip minutes become five DateTriggers at tip minus 10 minutes.

    Grace is 8 minutes, not the scheduler's one-hour default. A second pass
    and a new scheduler (a restart) keep the same ids.
    """
    fake = _install_cache(monkeypatch)

    class _Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("fresh tip cache must not call list_games")

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Boom)
    payload = _response("games_2026-11-11.json")
    status, tips = tips_from_games_payload(payload, SLATE)
    assert status == "ok"
    assert len(tips) == 5

    service = SchedulerService()
    service._scheduler = _scheduler_with_hour_default()
    restarted = SchedulerService()
    restarted._scheduler = _scheduler_with_hour_default()
    try:
        await cache_service.set(
            nba_lineup_tips_cache_key(SLATE),
            _dump_tips(status, tips),
            NBA_LINEUP_TIPS_CACHE_TTL_SECONDS,
        )
        first = await service.plan_odds_pretip_closes(now=PLAN_NOW)
        second = await service.plan_odds_pretip_closes(now=PLAN_NOW)
        rebuilt = await restarted.plan_odds_pretip_closes(now=PLAN_NOW)
        jobs = [job for job in service._scheduler.get_jobs() if str(job.id).startswith("odds_pretip:")]
        captured = {
            job.id: (job.trigger, job.trigger.run_date, job.misfire_grace_time, dict(job.kwargs))
            for job in jobs
        }
    finally:
        _stop_scheduler(service._scheduler)
        _stop_scheduler(restarted._scheduler)
        await _close_cache()

    assert fake is not None
    assert first == second == rebuilt
    assert first == [pretip_job_id(SLATE, tip) for tip in tips]
    assert len(captured) == len(first) == 5
    for tip in tips:
        trigger, run_at, grace, kwargs = captured[pretip_job_id(SLATE, tip)]
        assert isinstance(trigger, DateTrigger)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        assert run_at.astimezone(timezone.utc) == (tip - timedelta(minutes=10)).astimezone(timezone.utc)
        assert grace == 8 * 60
        assert grace == ODDS_PRETIP_MISFIRE_GRACE_SECONDS
        assert grace != _SCHEDULER_DEFAULT_GRACE
        assert kwargs["slate_date"] == SLATE


@pytest.mark.asyncio
async def test_missing_tip_cache_uses_the_lineup_reader_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cold cache is one list_games through the existing reader, then Redis."""
    _install_cache(monkeypatch)
    client = _GamesClient(_response("games_2026-11-11.json"))
    monkeypatch.setattr("app.services.bdl_client.BdlClient", client)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr(_TEST_KEY))
    service = SchedulerService()
    service._scheduler = _scheduler_with_hour_default()
    again = SchedulerService()
    again._scheduler = _scheduler_with_hour_default()
    try:
        first = await service.plan_odds_pretip_closes(now=PLAN_NOW)
        second = await service.plan_odds_pretip_closes(now=PLAN_NOW)
        third = await again.plan_odds_pretip_closes(now=PLAN_NOW)
    finally:
        _stop_scheduler(service._scheduler)
        _stop_scheduler(again._scheduler)
        await _close_cache()

    assert first == second == third
    assert len(first) == 5
    assert client.calls == [{"dates": [SLATE], "per_page": 100}]
    assert client.closed == 1


@pytest.mark.asyncio
async def test_dropped_tip_removes_that_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    """A minute that leaves the tip list does not keep its DateTrigger."""
    service = SchedulerService()
    service._scheduler = _scheduler_with_hour_default()
    early = TIP_0000
    late = datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)
    try:
        service.schedule_pretip_closes(SLATE, (early, late))
        left = service.schedule_pretip_closes(SLATE, (early,))
    finally:
        ids = [job.id for job in service._scheduler.get_jobs()]
        _stop_scheduler(service._scheduler)
    assert left == [pretip_job_id(SLATE, early)]
    assert pretip_job_id(SLATE, late) not in ids
    assert ids.count(pretip_job_id(SLATE, early)) == 1


@pytest.mark.asyncio
async def test_transient_slate_read_leaves_existing_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed schedule read must not delete alarms already on the scheduler."""
    service = SchedulerService()
    service._scheduler = _scheduler_with_hour_default()
    try:
        service.schedule_pretip_closes(SLATE, (TIP_0000,))

        async def _transient(slate_date: str) -> tuple[str, tuple]:
            assert slate_date == SLATE
            return ("transient", ())

        monkeypatch.setattr(service, "_nba_tips_for_slate", _transient)
        kept = await service.plan_odds_pretip_closes(now=PLAN_NOW)
    finally:
        _stop_scheduler(service._scheduler)
    assert kept == [pretip_job_id(SLATE, TIP_0000)]


@pytest.mark.asyncio
async def test_closing_fetches_props_once_per_remaining_game(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three games share 00:00Z. Each gets one props call. Odds are one slate call."""
    client, _provider = _install_closing(monkeypatch)
    _install_cache(monkeypatch)
    try:
        result = await _run_0000()
    finally:
        await _close_cache()

    assert settings.nba_odds_provider == "theoddsapi"
    assert client.gateway_calls == []  # type: ignore[attr-defined]
    assert result["locked"] is False
    assert result["event_count"] == 3
    assert result["total_lines"] > 0
    assert result["snapshot_at"] == BEFORE_0000.isoformat()
    assert result["skipped_postponed"] == 0
    assert _props_ids(client) == [21718081, 21718082, 21718083]
    assert _kinds(client).count("list_games") == 1
    assert _kinds(client).count("list_odds") == 1
    assert ("list_odds", (SLATE,), None) in client.calls
    assert "get_game" not in _kinds(client)


async def _run_0000(*, now: datetime = BEFORE_0000) -> dict:
    """Run the 00:00 UTC closing job for the recorded 2026-11-11 slate."""
    return await odds_snapshot_service.take_closing_snapshot(SLATE, TIP_0000, now=now)


@pytest.mark.asyncio
async def test_postponed_game_is_skipped_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A recorded game with ``postponed`` set true is not fetched."""
    payload = _response("games_2026-11-11.json")
    target = next(game for game in payload["data"] if game["id"] == 21718082)
    assert target["postponed"] is False
    assert target["datetime"] == "2026-11-12T00:00:00.000Z"
    target["postponed"] = True
    client, _provider = _install_closing(
        monkeypatch,
        _ClosingClient(games_payload=payload),
    )
    _install_cache(monkeypatch)
    caplog.set_level(logging.INFO)
    try:
        result = await _run_0000()
    finally:
        await _close_cache()

    assert result["skipped_postponed"] == 1
    assert result["event_count"] == 2
    assert 21718082 not in _props_ids(client)
    assert _props_ids(client) == [21718081, 21718083]
    assert "odds_pretip_skip game_id=21718082 reason=postponed" in caplog.text


@pytest.mark.asyncio
async def test_non_scheduled_games_are_skipped_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Recorded in-progress games at 02:00Z are not fetched."""
    client, _provider = _install_closing(
        monkeypatch,
        _ClosingClient(games_name="games_2026-11-10.json", props_game_id=OKC_GAME_ID),
    )
    _install_cache(monkeypatch)
    caplog.set_level(logging.INFO)
    try:
        result = await odds_snapshot_service.take_closing_snapshot(
            SLATE_NOV10,
            IN_PROGRESS_TIP,
            now=datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc),
        )
    finally:
        await _close_cache()

    assert result["event_count"] == 0
    assert result["total_lines"] == 0
    assert result["skipped_not_scheduled"] == 2
    assert _props_ids(client) == []
    assert "list_odds" not in _kinds(client)
    assert "odds_pretip_skip game_id=21718076 reason=not_scheduled status=in_progress" in caplog.text
    assert "odds_pretip_skip game_id=21718078 reason=not_scheduled status=in_progress" in caplog.text


@pytest.mark.asyncio
async def test_now_at_tip_skips_without_a_props_fetch(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """now >= tip writes nothing and does not fetch props."""
    client, _provider = _install_closing(monkeypatch)
    _install_cache(monkeypatch)
    caplog.set_level(logging.INFO)
    try:
        result = await _run_0000(now=TIP_0000)
    finally:
        await _close_cache()

    assert result["event_count"] == 0
    assert result["total_lines"] == 0
    assert result["skipped_tip_passed"] == 3
    assert _props_ids(client) == []
    assert "list_odds" not in _kinds(client)
    assert "odds_pretip_skip game_id=21718081 reason=tip_passed" in caplog.text


@pytest.mark.asyncio
async def test_props_updated_after_tip_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The t2 capture is entirely after tip, so the close stores no prop lines."""
    client, provider = _install_closing(
        monkeypatch,
        _ClosingClient(
            games_name="games_2026-11-10.json",
            props_name="props_live_21718080_OKC@POR_t2.json",
            props_game_id=OKC_GAME_ID,
        ),
    )
    _install_cache(monkeypatch)
    try:
        result = await odds_snapshot_service.take_closing_snapshot(
            SLATE_NOV10, OKC_TIP, now=BEFORE_NOV10
        )
    finally:
        await _close_cache()

    assert result["event_count"] == 1
    assert result["total_lines"] == 0
    assert _props_ids(client) == [OKC_GAME_ID]
    assert provider._adapter.post_tip_dropped == len(client.props["data"])


@pytest.mark.asyncio
async def test_overlapping_run_does_not_write_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The replica that loses the lock does not fetch or write."""
    import asyncio

    client, _provider = _install_closing(monkeypatch)
    _install_cache(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()
    original = client.get_player_props

    async def _slow(*, game_id: int):
        if not started.is_set():
            started.set()
            await release.wait()
        return await original(game_id=game_id)

    client.get_player_props = _slow  # type: ignore[method-assign]
    writes: list[str] = []

    async def _executemany(query: str, args_list: list) -> None:
        writes.append(query)

    monkeypatch.setattr(db_service, "executemany", _executemany)
    monkeypatch.setattr(db_service.__class__, "is_connected", property(lambda self: True))
    first_task = asyncio.create_task(
        odds_snapshot_service.take_closing_snapshot(SLATE, TIP_0000, now=BEFORE_0000)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        second = await asyncio.wait_for(
            odds_snapshot_service.take_closing_snapshot(SLATE, TIP_0000, now=BEFORE_0000),
            timeout=5,
        )
        assert second["locked"] is True
        assert second["total_lines"] == 0
        release.set()
        first = await asyncio.wait_for(first_task, timeout=10)
    finally:
        release.set()
        if not first_task.done():
            await first_task
        await _close_cache()

    assert first["locked"] is False
    assert first["total_lines"] > 0
    assert _props_ids(client) == [21718081, 21718082, 21718083]
    assert len(writes) == 1
    assert "odds_line_snapshots" in writes[0]


@pytest.mark.asyncio
async def test_missing_parents_still_write_line_rows_and_count_the_miss(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No games or players: the line table gets the close, and 002 does not raise."""
    await _upgrade(scratch_dsn)
    client, _provider = _install_closing(
        monkeypatch,
        _ClosingClient(games_payload=_only_game("games_2026-11-11.json", WAS_GAME_ID)),
    )
    _install_cache(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    caplog.set_level(logging.INFO)
    try:
        result = await _run_0000()
        assert result["total_lines"] > 0
        assert result["bdl_parent_misses"] > 0
        event_ids = await db_service.fetch("SELECT DISTINCT event_id FROM odds_line_snapshots")
        assert {row["event_id"] for row in event_ids} == {str(WAS_GAME_ID)}
        assert await _scalar("SELECT count(*) AS n FROM player_prop_snapshots") == 0
        assert await _scalar("SELECT count(*) AS n FROM game_odds_snapshots") == 0
        assert "bdl_live_parent_miss" in caplog.text
        assert "batch skipped" not in caplog.text
        assert _props_ids(client) == [WAS_GAME_ID]
        assert _kinds(client).count("list_odds") == 1
    finally:
        await db_service.close()
        await _close_cache()


@pytest.mark.asyncio
async def test_closing_rows_insert_when_parents_exist_and_a_retry_does_not_duplicate(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parents present: closing props and game odds pass 002 and the 005 trigger."""
    await _upgrade(scratch_dsn)
    await _seed_was_parents(scratch_dsn)
    _client, _provider = _install_closing(
        monkeypatch,
        _ClosingClient(games_payload=_only_game("games_2026-11-11.json", WAS_GAME_ID)),
    )
    _install_cache(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    try:
        result = await odds_snapshot_service.take_closing_snapshot(SLATE, TIP_0000, now=BEFORE_0000)
        assert result["total_lines"] > 0
        assert result["snapshot_at"] == BEFORE_0000.isoformat()

        props = await _scalar("SELECT count(*) AS n FROM player_prop_snapshots")
        assert props > 0
        distinct = await _scalar(
            """
            SELECT count(*) FROM (
                SELECT bdl_game_id, bdl_player_id, book_key, market, snapshot_at
                FROM player_prop_snapshots
            ) keyed
            """
        )
        assert distinct == props

        points = await db_service.fetchrow(
            """
            SELECT market_type, over_odds, under_odds, milestone_odds, snapshot_kind, league
            FROM player_prop_snapshots
            WHERE market = 'player_points'
            LIMIT 1
            """
        )
        assert points["market_type"] == "over_under"
        assert points["over_odds"] is not None and points["under_odds"] is not None
        assert points["milestone_odds"] is None
        assert points["snapshot_kind"] == "closing"
        assert points["league"] == "nba"

        double = await db_service.fetchrow(
            """
            SELECT market_type, over_odds, under_odds, milestone_odds, line
            FROM player_prop_snapshots
            WHERE market = 'player_double_double'
            LIMIT 1
            """
        )
        assert double is not None
        assert double["market_type"] == "milestone"
        assert double["milestone_odds"] is not None
        assert double["over_odds"] is None and double["under_odds"] is None
        assert double["line"] == Decimal("0.5")

        recorded = next(
            row
            for row in _load("odds_2026-11-11.json")["response"]["data"]
            if row["game_id"] == WAS_GAME_ID and row["vendor"] == "draftkings"
        )
        stored = await db_service.fetchrow(
            """
            SELECT snapshot_kind, league, spread_home_value, spread_home_odds,
                   total_value, total_over_odds, total_under_odds, snapshot_at
            FROM game_odds_snapshots
            WHERE bdl_game_id = $1 AND book_key = 'draftkings'
            """,
            WAS_GAME_ID,
        )
        assert stored["snapshot_kind"] == "closing"
        assert stored["league"] == "nba"
        assert stored["spread_home_value"] == Decimal(recorded["spread_home_value"])
        assert stored["spread_home_odds"] == recorded["spread_home_odds"]
        assert stored["total_value"] == Decimal(recorded["total_value"])
        assert stored["total_over_odds"] == recorded["total_over_odds"]
        assert stored["total_under_odds"] == recorded["total_under_odds"]
        assert stored["snapshot_at"] == BEFORE_0000
        assert await _scalar(
            "SELECT count(*) AS n FROM game_odds_snapshots WHERE book_key IN ('polymarket', 'kalshi')"
        ) == 0

        stamps = await db_service.fetch(
            """
            SELECT snapshot_at FROM player_prop_snapshots
            UNION
            SELECT snapshot_at FROM game_odds_snapshots
            UNION
            SELECT snapshot_at FROM odds_line_snapshots
            """
        )
        assert {row["snapshot_at"] for row in stamps} == {BEFORE_0000}

        game_odds = await _scalar("SELECT count(*) AS n FROM game_odds_snapshots")
        lines = await _scalar("SELECT count(*) AS n FROM odds_line_snapshots")
        again = await odds_snapshot_service.take_closing_snapshot(SLATE, TIP_0000, now=BEFORE_0000)
        assert again["snapshot_at"] == result["snapshot_at"]
        assert await _scalar("SELECT count(*) AS n FROM player_prop_snapshots") == props
        assert await _scalar("SELECT count(*) AS n FROM game_odds_snapshots") == game_odds
        assert await _scalar("SELECT count(*) AS n FROM odds_line_snapshots") == lines
    finally:
        await db_service.close()
        await _close_cache()
