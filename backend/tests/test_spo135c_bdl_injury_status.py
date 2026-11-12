"""SPO-135c: NBA DailyPick injury_status comes from the BDL cache.

Bodies are the recorded player_injuries page and the recorded standings
file, or a copy that clears or advances ``next_cursor``. Odds shells are
the recorded player_points capture with a description relabeled to a
name that page already contains. No test calls the network.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr

import fakeredis.aioredis

from app.services.bdl_client import BdlClient
from app.services.daily_analysis import DailyAnalysisService
from app.services.nba_injuries import (
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    NBA_INJURY_PAGE_INTERVAL_SECONDS,
    get_cached_nba_injuries,
    load_nba_pick_injuries,
    load_recorded_team_id_map,
    normalize_bdl_injuries,
    refresh_nba_injuries,
    refresh_nba_injuries_from_bdl,
    team_id_to_code_from_standings,
)
from app.services.pick_signals import injury_blocks_combined
from app.services.scheduler import (
    NBA_INJURY_REFRESH_CRON_HOUR,
    NBA_INJURY_REFRESH_CRON_MINUTE,
    NBA_INJURY_REFRESH_TZ,
    SchedulerService,
    nba_injury_refresh_in_window,
)
from app.settings import settings
from tests.fixtures.odds_api import load_odds_fixture
from tests.test_spo131_bdl_injuries import (
    INJURY_PAGE,
    STANDINGS,
    _cache,
    _recorded_page,
)

_CHICAGO = ZoneInfo("America/Chicago")
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
_RATE_HEADERS = json.loads((_FIXTURE_DIR / "injuries.json").read_text())["rate_headers"]


def _entry(status: str, *, raw: str | None = None) -> dict:
    """One normalized row from the recorded page with this stored status."""
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at="2026-11-11T18:00:00+00:00",
    )
    wanted = raw if raw is not None else status
    for row in entries:
        if row["status"] == status and row["raw_status"] == wanted:
            return row
    raise AssertionError(f"recorded page has no status={status!r} raw={wanted!r}")


def _board_for(*names: str) -> list[dict]:
    """Recorded bookmakers, plus a copy of one player's prices under each name.

    The source player is whoever the capture lists first. Prices, the
    bookmaker key, and the market key stay recorded. Only ``description``
    changes, and only on the copied outcomes.
    """
    event = load_odds_fixture("odds_api_event_odds__player_points.json")
    books = copy.deepcopy(event["bookmakers"])
    source = None
    for book in books:
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                if outcome.get("description"):
                    source = outcome["description"]
                    break
            if source:
                break
        if source:
            break
    assert source
    for book in books:
        for market in book.get("markets") or []:
            cloned = []
            for outcome in market.get("outcomes") or []:
                if outcome.get("description") != source:
                    continue
                for name in names:
                    row = copy.deepcopy(outcome)
                    row["description"] = name
                    cloned.append(row)
            market["outcomes"] = cloned
    return books


def _service(player_names: list[str]):
    service = DailyAnalysisService()
    service._get_props_for_market = _async_return(_board_for(*player_names))
    service.csv_service = _Csv(
        {
            "p_over": 0.72,
            "p_under": 0.21,
            "n_games": 20,
            "game_logs": [{"team": "Hawks", "value": 18}],
        }
    )
    return service


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


class _Csv:
    def __init__(self, stats: dict) -> None:
        self._stats = stats

    def get_player_stats(self, **_kwargs):
        return self._stats

    def latest_position(self, _name: str) -> str:
        return "G"


def _picks_for(names: list[str], entries: list[dict] | None):
    service = _service(names)
    picks, _players, _props = asyncio.run(
        service._analyze_single_event(
            event_id="evt-1",
            home_team="Atlanta Hawks",
            away_team="Los Angeles Lakers",
            commence_time="2026-11-10T00:10:00Z",
            league="nba",
            injury_entries=entries,
        )
    )
    return picks


def _named(picks, name: str):
    rows = [pick for pick in picks if pick.player_name == name]
    assert rows
    return rows


class _Clock:
    """Sleep moves the clock forward. Nothing waits on the wall clock."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _terminal_page() -> dict:
    page = _recorded_page(next_cursor=None)
    return page


def _transport(pages: list[dict]):
    cursor = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/player_injuries"
        page = pages[min(cursor["n"], len(pages) - 1)]
        cursor["n"] += 1
        return httpx.Response(200, json=page, headers=dict(_RATE_HEADERS))

    return httpx.MockTransport(handler), cursor


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_refresh_writes_the_snapshot() -> None:
    service, _fake = _cache()
    clock = _Clock()
    transport, cursor = _transport([INJURY_PAGE, _terminal_page()])
    client = BdlClient(
        api_key="unit-test-bdl-key",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        transport=transport,
        sleep=clock.sleep,
        clock=clock.time,
        rate_limit_per_min=5,
    )
    try:
        stored = await refresh_nba_injuries_from_bdl(
            client,
            service,
            team_id_to_code=load_recorded_team_id_map(),
            sleep=clock.sleep,
            clock=clock.time,
        )
    finally:
        await client.aclose()
    assert stored is not None
    assert stored["entries"]
    assert cursor["n"] == 2
    snapshot = await get_cached_nba_injuries(cache=service)
    assert snapshot["stale"] is False
    assert snapshot["entries"][0]["source"] == "balldontlie"
    assert any(row["status"] == "Out" for row in snapshot["entries"])


@pytest.mark.asyncio
async def test_partial_page_cap_does_not_overwrite() -> None:
    service, _fake = _cache()
    previous = {"fetched_at": "2026-11-11T12:00:00+00:00", "entries": [{"player": "kept"}]}
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)
    pages = []
    for index in range(25):
        page = copy.deepcopy(INJURY_PAGE)
        page["meta"] = dict(page["meta"])
        page["meta"]["next_cursor"] = int(page["meta"]["next_cursor"]) + index + 1
        pages.append(page)
    clock = _Clock()
    transport, _cursor = _transport(pages)
    acquires: list[int] = []
    original = BdlClient._acquire_budget

    async def _spy(self):
        acquires.append(1)
        return await original(self)

    client = BdlClient(
        api_key="unit-test-bdl-key",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        transport=transport,
        sleep=clock.sleep,
        clock=clock.time,
        rate_limit_per_min=5,
    )
    client._acquire_budget = _spy.__get__(client, BdlClient)
    try:
        stored = await refresh_nba_injuries_from_bdl(
            client,
            service,
            team_id_to_code=load_recorded_team_id_map(),
            sleep=clock.sleep,
            clock=clock.time,
        )
    finally:
        await client.aclose()
    assert stored is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    assert len(acquires) == 20


@pytest.mark.asyncio
async def test_rows_that_normalize_to_nothing_do_not_overwrite() -> None:
    """An empty result that is not a real empty league leaves the old body."""
    service, _fake = _cache()
    previous = {"fetched_at": "2026-11-11T12:00:00+00:00", "entries": [{"player": "kept"}]}
    await service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS)
    stored = await refresh_nba_injuries(
        _Protocol([_terminal_page()]),
        service,
        {},
    )
    assert stored is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous


class _Protocol:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self.calls = 0

    async def list_player_injuries(self, *, cursor=None, per_page=100) -> dict:
        page = self._pages[self.calls]
        self.calls += 1
        return page


@pytest.mark.asyncio
async def test_every_injury_page_takes_a_limiter_slot() -> None:
    """The shared Redis budget is acquired once per page the refresh sends."""
    clock = _Clock()
    transport, _cursor = _transport([INJURY_PAGE, _terminal_page()])
    acquires: list[str] = []
    original = BdlClient._acquire_budget

    async def _spy(self):
        acquires.append(str(self._http.base_url))
        return await original(self)

    client = BdlClient(
        api_key="unit-test-bdl-key",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        transport=transport,
        sleep=clock.sleep,
        clock=clock.time,
        rate_limit_per_min=5,
    )
    client._acquire_budget = _spy.__get__(client, BdlClient)
    service, _fake = _cache()
    try:
        stored = await refresh_nba_injuries_from_bdl(
            client,
            service,
            team_id_to_code=team_id_to_code_from_standings(STANDINGS),
            sleep=clock.sleep,
            clock=clock.time,
        )
    finally:
        await client.aclose()
    assert stored is not None
    assert len(acquires) == 2
    assert NBA_INJURY_PAGE_INTERVAL_SECONDS == 15
    assert 60 / NBA_INJURY_PAGE_INTERVAL_SECONDS == 4
    assert clock.sleeps == [15.0]


def _recorded_429_response() -> httpx.Response:
    """The recorded 429. Body and rate-limit headers are copied unchanged."""
    capture = json.loads(
        (_FIXTURE_DIR / "lineups_18447393_2026-01-15_agents_429.json").read_text()
    )
    raw = capture["response"]["_raw"]
    return httpx.Response(429, content=raw.encode(), headers=dict(capture["rate_headers"]))


@pytest.mark.asyncio
async def test_recorded_429_keeps_the_previous_snapshot_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One recorded 429 is retried once. The second 429 does not replace the cache.

    The fixture's ``x-ratelimit-reset`` is 40 seconds ahead of the clock,
    so the single wait is that header. There is no third HTTP call. The
    warning names ``BdlRateLimitError`` and nothing from the response.
    An empty cache stays empty, which is what leaves ``injury_status`` null.
    """
    capture = json.loads(
        (_FIXTURE_DIR / "lineups_18447393_2026-01-15_agents_429.json").read_text()
    )
    reset = int(capture["rate_headers"]["x-ratelimit-reset"])
    previous = {
        "fetched_at": "2026-11-11T18:00:00+00:00",
        "entries": [{"player": "Kept Player", "status": "Out", "raw_status": "Out"}],
    }

    async def _run(seed: dict | None) -> tuple[object, list[float], int, object]:
        clock = _Clock()
        clock.now = float(reset - 40)
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return _recorded_429_response()

        client = BdlClient(
            api_key="unit-test-bdl-key",
            redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
            transport=httpx.MockTransport(handler),
            sleep=clock.sleep,
            clock=clock.time,
            rate_limit_per_min=5,
            rate_limit_policy="injury",
        )
        service, _fake = _cache()
        if seed is not None:
            await service.set(NBA_INJURIES_CACHE_KEY, seed, NBA_INJURIES_CACHE_TTL_SECONDS)
        try:
            stored = await refresh_nba_injuries_from_bdl(
                client,
                service,
                team_id_to_code=load_recorded_team_id_map(),
                sleep=clock.sleep,
                clock=clock.time,
            )
        finally:
            await client.aclose()
        left = await service.get(NBA_INJURIES_CACHE_KEY)
        return stored, clock.sleeps, calls["n"], left

    with caplog.at_level(logging.WARNING):
        stored, sleeps, calls, left = await _run(previous)
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert stored is None
    assert left == previous
    assert calls == 2
    assert sleeps == [40.0]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert message == (
        "NBA injury refresh failed (BdlRateLimitError); previous cache left in place"
    )
    lowered = message.lower()
    assert "unit-test-bdl-key" not in message
    assert "http" not in lowered
    assert "balldontlie" not in lowered
    assert "too many requests" not in lowered
    assert "player_injuries" not in lowered

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        stored, sleeps, calls, left = await _run(None)
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert stored is None
    assert left is None
    assert calls == 2
    assert sleeps == [40.0]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == message


@pytest.mark.asyncio
async def test_a_later_429_does_not_take_a_second_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one retry is for the whole refresh. The next 429 does not sleep again.

    Page one is the recorded 429, then the recorded injury page. Page two
    is the recorded 429 again. A per-page retry would sleep another 40
    seconds and send a fourth request. This refresh stops instead.
    """
    capture = json.loads(
        (_FIXTURE_DIR / "lineups_18447393_2026-01-15_agents_429.json").read_text()
    )
    reset = int(capture["rate_headers"]["x-ratelimit-reset"])
    previous = {
        "fetched_at": "2026-11-11T18:00:00+00:00",
        "entries": [{"player": "Kept Player", "status": "Out"}],
    }
    clock = _Clock()
    clock.now = float(reset - 40)
    calls = {"n": 0}
    pages = [None, INJURY_PAGE]

    def handler(_request: httpx.Request) -> httpx.Response:
        index = calls["n"]
        calls["n"] += 1
        if index < len(pages) and pages[index] is not None:
            return httpx.Response(200, json=pages[index], headers=dict(_RATE_HEADERS))
        return _recorded_429_response()

    client = BdlClient(
        api_key="unit-test-bdl-key",
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
        rate_limit_per_min=5,
        rate_limit_policy="injury",
    )
    service, _fake = _cache()
    await service.set(NBA_INJURIES_CACHE_KEY, previous, NBA_INJURIES_CACHE_TTL_SECONDS)
    with caplog.at_level(logging.WARNING):
        try:
            stored = await refresh_nba_injuries_from_bdl(
                client,
                service,
                team_id_to_code=load_recorded_team_id_map(),
                sleep=clock.sleep,
                clock=clock.time,
            )
        finally:
            await client.aclose()
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert stored is None
    assert await service.get(NBA_INJURIES_CACHE_KEY) == previous
    assert calls["n"] == 3
    # The 40 second retry already covers the 15 second page gap, so the
    # pace adds no second wait. A per-page retry would sleep 40 again.
    assert clock.sleeps == [40.0]
    assert len(warnings) == 1


def test_job_builds_the_injury_rate_limit_client(monkeypatch) -> None:
    """The :07 tick uses the one-retry policy. The schedule itself stays :07 and :37."""
    seen: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def aclose(self):
            return None

    async def _refresh(_client, _cache):
        return None

    async def _empty(_key):
        return None

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Client)
    monkeypatch.setattr("app.services.scheduler.refresh_nba_injuries_from_bdl", _refresh)
    monkeypatch.setattr("app.services.cache.cache_service.get", _empty)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr("unit-test-bdl-key"))
    inside = datetime(2026, 11, 11, 17, 7, tzinfo=_CHICAGO)
    asyncio.run(SchedulerService()._run_nba_injuries_refresh_job(now=inside))
    assert seen.get("rate_limit_policy") == "injury"
    assert NBA_INJURY_REFRESH_CRON_MINUTE == "7,37"


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


def test_window_matches_the_lineup_hours() -> None:
    """11:00 through 00:59 Chicago. :07 and :37 are inside those hours."""
    inside = (
        datetime(2026, 11, 11, 11, 7, tzinfo=_CHICAGO),
        datetime(2026, 11, 11, 17, 37, tzinfo=_CHICAGO),
        datetime(2026, 11, 12, 0, 37, tzinfo=_CHICAGO),
    )
    outside = (
        datetime(2026, 11, 11, 10, 37, tzinfo=_CHICAGO),
        datetime(2026, 11, 11, 1, 7, tzinfo=_CHICAGO),
        datetime(2026, 11, 11, 2, 7, tzinfo=_CHICAGO),
    )
    for moment in inside:
        assert nba_injury_refresh_in_window(moment) is True
    for moment in outside:
        assert nba_injury_refresh_in_window(moment) is False


def test_job_is_registered_on_the_half_hour_marks(monkeypatch) -> None:
    from unittest.mock import MagicMock, patch

    from apscheduler.triggers.cron import CronTrigger

    scheduler = SchedulerService()
    with patch("app.services.scheduler.AsyncIOScheduler") as mock_sched:
        instance = MagicMock()
        instance.get_jobs.return_value = []
        mock_sched.return_value = instance
        scheduler.start()
    found = None
    startup = None
    for call in instance.add_job.call_args_list:
        _args, kwargs = call
        if kwargs.get("id") == "nba_injuries_refresh":
            found = kwargs
        if kwargs.get("id") == "nba_injuries_startup_fill":
            startup = kwargs
    assert found is not None
    trigger = found["trigger"]
    assert isinstance(trigger, CronTrigger)
    text = str(trigger)
    assert NBA_INJURY_REFRESH_CRON_MINUTE in text
    assert "7" in text and "37" in text
    assert NBA_INJURY_REFRESH_CRON_HOUR in text
    assert str(trigger.timezone) == str(NBA_INJURY_REFRESH_TZ) == "America/Chicago"
    assert found["misfire_grace_time"] == 1
    assert found["max_instances"] == 1
    assert found["coalesce"] is True
    assert startup is not None
    assert startup["misfire_grace_time"] == 60


def test_job_does_not_call_outside_the_window(monkeypatch) -> None:
    constructed: list[str] = []

    class _Boom:
        def __init__(self, *args, **kwargs):
            constructed.append("built")
            raise AssertionError("BDL client built outside the window")

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Boom)
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr("unit-test-bdl-key"))
    outside = datetime(2026, 11, 11, 2, 7, tzinfo=_CHICAGO)
    result = asyncio.run(
        SchedulerService()._run_nba_injuries_refresh_job(now=outside)
    )
    assert result is None
    assert constructed == []


def test_startup_fill_runs_once_only_when_the_key_is_missing(monkeypatch) -> None:
    service = SchedulerService()
    calls: list[bool] = []

    async def _spy(self, **kwargs):
        calls.append(kwargs.get("force"))
        return {"entries": []}

    monkeypatch.setattr(SchedulerService, "_run_nba_injuries_refresh_job", _spy)

    async def _missing(_key):
        return None

    monkeypatch.setattr("app.services.cache.cache_service.get", _missing)
    asyncio.run(service._fill_nba_injuries_if_missing())
    assert calls == [True]

    async def _present(_key):
        return {"fetched_at": "2026-11-11T18:00:00+00:00", "entries": []}

    monkeypatch.setattr("app.services.cache.cache_service.get", _present)
    asyncio.run(service._fill_nba_injuries_if_missing())
    assert calls == [True]


# ---------------------------------------------------------------------------
# DailyPick
# ---------------------------------------------------------------------------


def test_doubtful_raw_status_blocks_and_questionable_does_not() -> None:
    """#60 stores Doubtful as Questionable and keeps raw_status.

    injury_blocks_combined fires for Out on the normalized word, and for
    Doubtful by reading raw_status. A real Questionable does not block.
    """
    assert injury_blocks_combined("Out") is True
    assert injury_blocks_combined("Questionable", "Doubtful") is True
    assert injury_blocks_combined("Questionable", "Questionable") is False
    assert injury_blocks_combined("Questionable") is False


def test_out_pick_has_no_combined_probability() -> None:
    out = _entry("Out")
    healthy = "Dyson Daniels"
    picks = _picks_for([out["player"], healthy], [out])
    blocked = _named(picks, out["player"])
    open_rows = _named(picks, healthy)
    assert {row.injury_status for row in blocked} == {"Out"}
    assert {row.combined_probability for row in blocked} == {None}
    assert {row.lineup_confirmed for row in blocked} == {None}
    assert {row.injury_status for row in open_rows} == {None}
    assert all(row.combined_probability is not None for row in open_rows)


def test_questionable_keeps_a_probability_and_raw_doubtful_does_not() -> None:
    questionable = _entry("Questionable")
    doubtful = _entry("Questionable", raw="Doubtful")
    picks = _picks_for(
        [questionable["player"], doubtful["player"]],
        [questionable, doubtful],
    )
    q_rows = _named(picks, questionable["player"])
    d_rows = _named(picks, doubtful["player"])
    assert {row.injury_status for row in q_rows} == {"Questionable"}
    assert all(row.combined_probability is not None for row in q_rows)
    assert {row.injury_status for row in d_rows} == {"Questionable"}
    assert {row.combined_probability for row in d_rows} == {None}
    assert {row.lineup_confirmed for row in d_rows} == {None}


def test_ambiguous_and_missing_names_stay_null() -> None:
    out = _entry("Out")
    other = dict(out)
    other["bdl_player_id"] = (out["bdl_player_id"] or 0) + 1
    other["team"] = "BOS"
    picks = _picks_for([out["player"], "Dyson Daniels"], [out, other])
    assert {row.injury_status for row in _named(picks, out["player"])} == {None}
    assert all(row.combined_probability is not None for row in _named(picks, out["player"]))
    assert {row.injury_status for row in _named(picks, "Dyson Daniels")} == {None}


def test_missing_cache_warns_once_and_analysis_still_returns_picks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _fake = _cache()
    with caplog.at_level(logging.WARNING):
        loaded = asyncio.run(load_nba_pick_injuries(cache=service))
    picks = _picks_for(["Dyson Daniels"], loaded)
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert loaded is None
    assert len(warnings) == 1
    assert "missing" in warnings[0].getMessage()
    assert picks
    assert all(pick.injury_status is None for pick in picks)
    assert all(pick.combined_probability is not None for pick in picks)
    assert "http" not in warnings[0].getMessage().lower()


def test_stale_cache_warns_once_and_leaves_injury_status_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _fake = _cache()
    out = _entry("Out")
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": stale_at, "entries": [out]},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )

    async def _load():
        with caplog.at_level(logging.WARNING):
            return await load_nba_pick_injuries(cache=service)

    loaded = asyncio.run(_load())
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert loaded is None
    assert len(warnings) == 1
    assert "stale" in warnings[0].getMessage()
    picks = _picks_for([out["player"]], loaded)
    assert {pick.injury_status for pick in _named(picks, out["player"])} == {None}
    assert all(pick.combined_probability is not None for pick in picks)


def test_wnba_pick_ignores_the_nba_snapshot() -> None:
    out = _entry("Out")
    service = DailyAnalysisService()
    service._get_props_for_market = _async_return(_board_for(out["player"]))

    class _WnbaCsv:
        def get_player_stats(self, **_kwargs):
            return {
                "p_over": 0.7,
                "p_under": 0.2,
                "n_games": 20,
                "game_logs": [{"team": "Liberty", "value": 18}],
            }

    import app.services.daily_analysis as daily_analysis

    original = daily_analysis._resolve_csv_service
    daily_analysis._resolve_csv_service = lambda league: _WnbaCsv()
    try:
        picks, _players, _props = asyncio.run(
            service._analyze_single_event(
                event_id="evt-w",
                home_team="New York Liberty",
                away_team="Connecticut Sun",
                commence_time="2026-06-01T23:00:00Z",
                league="wnba",
                injury_entries=[out],
            )
        )
    finally:
        daily_analysis._resolve_csv_service = original
    assert picks
    assert all(pick.injury_status is None for pick in picks)
    assert all(pick.lineup_confirmed is None for pick in picks)
    assert all(pick.combined_probability is None for pick in picks)


def test_wnba_agent_injury_path_still_scrapes(monkeypatch) -> None:
    from tests.test_spo131_bdl_injuries import (
        _ScrapingFetcher,
        _expect_espn_cbs,
        _forbid_refresh,
        _historical,
        _set_dummy_key,
        _set_injury_source,
    )

    historical = _historical()
    _set_dummy_key(monkeypatch)
    _set_injury_source(monkeypatch, "bdl")
    _expect_espn_cbs(monkeypatch)
    _forbid_refresh(monkeypatch)
    result = asyncio.run(historical.get_official_injury_report("Liberty", league="wnba"))
    assert _ScrapingFetcher.calls == 1
    assert result["details"]["injuries"][0]["player"] == "Breanna Stewart"
    assert result["details"]["injuries"][0]["source"] == "espn"
    assert "bdl_player_id" not in result["details"]["injuries"][0]
