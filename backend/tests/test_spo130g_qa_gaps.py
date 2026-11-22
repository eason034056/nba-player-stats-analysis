"""QA gaps for SPO-130g. Bodies stay the recorded fixture files.

These tests lock behaviors the SPO-130g suite left green under mutation:
the local-date half of the pre-tip filter, unseeded game-odds vendors
counted as parent misses, the per-row insert after a batch failure, an
unexpected live-write error leaving the line-table snapshot intact, the
metrics quota object, the Odds API snapshot staying off the live writer,
and a non-NBA date request staying off the BALLDONTLIE games list.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.api.metrics import get_metrics
from app.services.daily_analysis import DailyAnalysisService, _bookmakers_for_market
from app.services.db import db_service
from app.services.odds_provider import ProviderEvent, RateStatus
from app.services.odds_snapshot_service import (
    SNAPSHOT_MARKETS,
    OddsSnapshotService,
    bdl_event_is_open,
)
from app.settings import settings
from tests.fixtures.odds_api import RECORDED_NBA_EVENTS, load_odds_fixture
from tests.test_spo130g_nba_jobs_bdl import (
    BEFORE_TIP,
    OKC_GAME_ID,
    SLATE,
    _install,
    _kinds,
    _load,
    _scalar,
    _seed_okc_parents,
    _upgrade,
    _use_database,
)

EASTERN = -300


def _okc_game() -> dict:
    """The recorded 2026-11-10 OKC at Portland game object."""
    return next(
        item
        for item in _load("games_2026-11-10.json")["response"]["data"]
        if item["id"] == OKC_GAME_ID
    )


def _provider_event(game: dict, commence: datetime) -> ProviderEvent:
    """Internal event built from one recorded game. ``commence`` is the tip under test."""
    return ProviderEvent(
        event_id=str(game["id"]),
        commence_time=commence.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        home_team=game["home_team"]["full_name"],
        away_team=game["visitor_team"]["full_name"],
        home_code=game["home_team"]["abbreviation"],
        away_code=game["visitor_team"]["abbreviation"],
        status="scheduled",
        slate_date=game["date"],
    )


def test_open_game_on_the_next_local_date_is_skipped():
    """Status and tip can both pass and the game still belongs to another local date.

    The recorded OKC tip is 2026-11-11T04:00:00Z, which is 23:00 on
    2026-11-10 in Eastern time. Three hours later is 02:00 on 2026-11-11.
    ``bdl_event_is_open`` for 2026-11-10 must reject that later tip.
    """
    game = _okc_game()
    recorded_tip = datetime.fromisoformat(game["datetime"].replace("Z", "+00:00"))
    assert game["status_state"] == "scheduled"
    assert bdl_event_is_open(
        _provider_event(game, recorded_tip),
        date=SLATE,
        tz_offset_minutes=EASTERN,
        now=BEFORE_TIP,
    )
    later = _provider_event(game, recorded_tip + timedelta(hours=3))
    assert not bdl_event_is_open(
        later,
        date=SLATE,
        tz_offset_minutes=EASTERN,
        now=BEFORE_TIP,
    )


@pytest.mark.asyncio
async def test_unseeded_game_odds_vendors_are_counted_misses(scratch_dsn, monkeypatch, caplog):
    """polymarket and kalshi are on the recorded odds page and absent from the books seed.

    The client copies those 21718081 rows onto 21718080 and changes only
    ``game_id``. Both vendors must stay out of ``game_odds_snapshots``
    and the miss log must count them. Seeded books still insert.
    """
    await _upgrade(scratch_dsn)
    await _seed_okc_parents(scratch_dsn)
    _install(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    caplog.set_level(logging.INFO)
    try:
        result = await OddsSnapshotService().take_snapshot(SLATE, now=BEFORE_TIP)
        stored = await db_service.fetch(
            "SELECT book_key FROM game_odds_snapshots WHERE bdl_game_id = $1",
            OKC_GAME_ID,
        )
        stored_books = {row["book_key"] for row in stored}
        seeded = {
            row["book_key"]
            for row in await db_service.fetch(
                "SELECT book_key FROM books WHERE league = 'nba'"
            )
        }
        assert "polymarket" not in stored_books
        assert "kalshi" not in stored_books
        assert "polymarket" not in seeded
        assert "kalshi" not in seeded
        assert stored_books
        assert stored_books <= seeded
        assert "draftkings" in stored_books
        assert "bdl_live_parent_miss kind=game_odds count=2" in caplog.text
        assert result["bdl_parent_misses"] >= 2
        assert result["total_lines"] > 0
    finally:
        await db_service.close()


@pytest.mark.asyncio
async def test_prop_batch_failure_retries_each_row(scratch_dsn, monkeypatch, caplog):
    """``executemany`` raising on the live prop insert falls back to one ``execute`` per row."""
    await _upgrade(scratch_dsn)
    await _seed_okc_parents(scratch_dsn)
    _install(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    caplog.set_level(logging.INFO)
    original_many = db_service.executemany
    original_one = db_service.execute
    per_row: list[tuple] = []

    async def executemany(query: str, args_list: list[tuple]) -> None:
        if "player_prop_snapshots" in query:
            raise RuntimeError("batch down")
        await original_many(query, args_list)

    async def execute(query: str, *args):
        if "player_prop_snapshots" in query:
            per_row.append(args)
        return await original_one(query, *args)

    monkeypatch.setattr(db_service, "executemany", executemany)
    monkeypatch.setattr(db_service, "execute", execute)
    try:
        result = await OddsSnapshotService().take_snapshot(SLATE, now=BEFORE_TIP)
        stored = await _scalar("SELECT count(*) AS n FROM player_prop_snapshots")
        assert result["total_lines"] > 0
        assert stored > 0
        assert len(per_row) == stored
        assert "retrying per row" in caplog.text
    finally:
        await db_service.close()


@pytest.mark.asyncio
async def test_one_prop_row_failure_is_a_miss_and_snapshot_returns(scratch_dsn, monkeypatch, caplog):
    """A single row that raises is counted. The other books and the snapshot still land."""
    await _upgrade(scratch_dsn)
    await _seed_okc_parents(scratch_dsn)
    _install(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    caplog.set_level(logging.INFO)
    original_many = db_service.executemany
    original_one = db_service.execute

    async def executemany(query: str, args_list: list[tuple]) -> None:
        if "player_prop_snapshots" in query:
            raise RuntimeError("batch down")
        await original_many(query, args_list)

    async def execute(query: str, *args):
        if "player_prop_snapshots" in query and len(args) > 2 and args[2] == "draftkings":
            raise RuntimeError("row down")
        return await original_one(query, *args)

    monkeypatch.setattr(db_service, "executemany", executemany)
    monkeypatch.setattr(db_service, "execute", execute)
    try:
        result = await OddsSnapshotService().take_snapshot(SLATE, now=BEFORE_TIP)
        draftkings = await _scalar(
            "SELECT count(*) AS n FROM player_prop_snapshots WHERE book_key = 'draftkings'"
        )
        fanduel = await _scalar(
            "SELECT count(*) AS n FROM player_prop_snapshots WHERE book_key = 'fanduel'"
        )
        assert result["total_lines"] > 0
        assert draftkings == 0
        assert fanduel > 0
        assert "row skipped" in caplog.text
        assert result["bdl_parent_misses"] > 0
    finally:
        await db_service.close()


@pytest.mark.asyncio
async def test_live_write_error_does_not_fail_the_line_snapshot(scratch_dsn, monkeypatch, caplog):
    """A parent lookup that raises is a miss. ``take_snapshot`` still returns the line write."""
    await _upgrade(scratch_dsn)
    _install(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    caplog.set_level(logging.INFO)

    async def _boom(self, args: list[tuple]) -> tuple[list[tuple], int]:
        raise RuntimeError("parents unavailable")

    monkeypatch.setattr(OddsSnapshotService, "_props_with_parents", _boom)
    try:
        result = await OddsSnapshotService().take_snapshot(SLATE, now=BEFORE_TIP)
        lines = await _scalar("SELECT count(*) AS n FROM odds_line_snapshots")
        props = await _scalar("SELECT count(*) AS n FROM player_prop_snapshots")
        assert result["total_lines"] > 0
        assert lines == result["total_lines"]
        assert props == 0
        assert result["bdl_parent_misses"] >= 1
        assert "dual-write skipped" in caplog.text
    finally:
        await db_service.close()


@pytest.mark.asyncio
async def test_metrics_quota_comes_from_providers_nba(monkeypatch):
    """The handler reads the object at ``PROVIDERS['nba']``, not a parallel branch."""

    class Sentinel:
        async def rate_status(self) -> RateStatus:
            return RateStatus(provider="sentinel", remaining=7, used=1, recorded=True)

    class Other:
        async def rate_status(self) -> RateStatus:
            return RateStatus(provider="other", remaining=4, used=1, recorded=True)

    monkeypatch.setattr(settings, "nba_odds_provider", "balldontlie")
    monkeypatch.setattr("app.api.metrics.PROVIDERS", {"nba": Sentinel()})
    monkeypatch.setattr(
        "app.services.bdl_odds_provider.get_bdl_odds_provider",
        lambda: Other(),
    )
    body = await get_metrics()
    assert body["odds_api_quota"]["remaining"] == 7
    assert body["odds_api_quota"]["used"] == 1
    assert body["odds_api_quota"]["total"] == 8


@pytest.mark.asyncio
async def test_theoddsapi_snapshot_does_not_write_live_rows(scratch_dsn, monkeypatch):
    """A connected database on the default provider does not enter the 002 live writer."""
    await _upgrade(scratch_dsn)
    await _use_database(monkeypatch, scratch_dsn)
    monkeypatch.setattr(settings, "nba_odds_provider", "theoddsapi")
    recorded = load_odds_fixture(RECORDED_NBA_EVENTS)
    event = copy.deepcopy(recorded[0])
    commence = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
    slate = (commence + timedelta(minutes=EASTERN)).strftime("%Y-%m-%d")
    calls: list[str] = []

    async def get_events(**kwargs):
        calls.append("get_events")
        return [event]

    async def no_rows(self, **kwargs):
        return []

    live_calls: list[str] = []

    async def live(self, *args, **kwargs):
        live_calls.append("live")
        return 0

    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_provider.get_events",
        get_events,
    )
    monkeypatch.setattr(OddsSnapshotService, "_process_event", no_rows)
    monkeypatch.setattr(OddsSnapshotService, "_write_bdl_live", live)
    try:
        result = await OddsSnapshotService().take_snapshot(slate, tz_offset_minutes=EASTERN)
        assert calls == ["get_events"]
        assert result["event_count"] == 1
        assert live_calls == []
        assert "bdl_parent_misses" not in result
        assert await _scalar("SELECT count(*) AS n FROM player_prop_snapshots") == 0
        assert await _scalar("SELECT count(*) AS n FROM game_odds_snapshots") == 0
    finally:
        await db_service.close()


@pytest.mark.asyncio
async def test_non_nba_date_request_does_not_list_bdl_games(monkeypatch):
    """With the NBA flag on balldontlie, a wnba date request still does not call ``list_games``."""
    client, _provider, _gateway = _install(monkeypatch)
    service = DailyAnalysisService()
    with pytest.raises(ValueError, match="Unsupported league"):
        await service._get_events_for_date(
            SLATE,
            tz_offset_minutes=EASTERN,
            league="wnba",
            now=BEFORE_TIP,
        )
    assert "list_games" not in _kinds(client)


@pytest.mark.asyncio
async def test_market_slice_keeps_one_market_from_the_recorded_board(monkeypatch):
    """One BALLDONTLIE props body is sliced per market. The cached board is left intact."""
    _client, provider, _gateway = _install(monkeypatch)
    body = await provider.get_event_odds(
        event_id=str(OKC_GAME_ID),
        markets=SNAPSHOT_MARKETS,
        league="nba",
    )
    books = body["bookmakers"]
    original_sizes = [len(book.get("markets") or []) for book in books]
    market_keys = {
        market.get("key")
        for book in books
        for market in (book.get("markets") or [])
        if isinstance(market, dict)
    }
    assert "player_points" in market_keys
    assert len(market_keys) > 1
    sliced = _bookmakers_for_market(books, "player_points")
    assert sliced
    for book in sliced:
        assert [market["key"] for market in book["markets"]] == ["player_points"]
    assert [len(book.get("markets") or []) for book in books] == original_sizes
