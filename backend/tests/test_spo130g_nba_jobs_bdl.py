"""SPO-130g: NBA snapshot jobs and daily analysis on BALLDONTLIE.

Bodies are the recorded files under tests/fixtures/bdl/. The prewarm
stub loads ``odds_api_event_odds__player_points.json`` and sets only
``id``. One odds row is copied and its ``game_id`` is set to
the scheduled game on the 2026-11-10 slate, because the recorded odds
file is the next day's slate. Every other field stays as recorded.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.metrics import get_metrics
from app.services.bdl_odds_provider import BdlOddsProvider
from app.services.bdl_player_directory import BdlPlayerDirectory, bdl_player_name
from app.services.daily_analysis import SUPPORTED_MARKETS, DailyAnalysisService
from app.services.db import db_service
from app.services.odds_gateway import HOT_KEYS_ZSET_KEY, OddsMarketGateway
from app.services.odds_provider import RateStatus
from app.services.odds_snapshot_service import SNAPSHOT_MARKETS, OddsSnapshotService
from app.settings import settings
from tests.fixtures.odds_api import load_odds_fixture
from tests.test_odds_gateway import FakeCache

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
OKC_GAME_ID = 21718080
# Before every tip on the recorded 2026-11-10 slate, so a final or
# in-progress game is skipped because of its status, not because the
# tip is already in the past.
BEFORE_TIP = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
AFTER_TIP = datetime(2026, 11, 11, 5, 0, tzinfo=timezone.utc)
SLATE = "2026-11-10"
EASTERN = -300


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


class _JobsClient:
    """Recorded responses plus a call log. It does not build a body."""

    def __init__(self, props_name: str = "props_live_21718080_OKC@POR_pregame.json") -> None:
        self.calls: list[tuple] = []
        self.games = _load("games_2026-11-10.json")["response"]
        self.props = _load(props_name)["response"]
        self.players = _load("backend_players_batch45.json")["response"]
        odds = copy.deepcopy(_load("odds_2026-11-11.json")["response"])
        for row in odds["data"]:
            if row.get("game_id") == 21718081:
                row["game_id"] = OKC_GAME_ID
        self.odds = odds

    def rate_status(self) -> dict[str, int | None]:
        return {"limit": None, "remaining": None, "reset": None}

    async def list_games(self, *, dates: list[str], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_games", tuple(dates)))
        return self.games

    async def get_player_props(self, *, game_id: int):
        self.calls.append(("get_player_props", game_id))
        return self.props

    async def list_players(self, *, player_ids: list[int], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_players", tuple(player_ids)))
        wanted = set(player_ids)
        data = [player for player in self.players["data"] if player["id"] in wanted]
        return {"data": data, "meta": dict(self.players.get("meta") or {})}

    async def get_game(self, *, game_id: int):
        self.calls.append(("get_game", game_id))
        for game in self.games["data"]:
            if game["id"] == game_id:
                return {"data": game}
        raise AssertionError(f"recorded games file has no game {game_id}")

    async def list_odds(self, *, dates: list[str], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_odds", tuple(dates), cursor))
        return self.odds


def _kinds(client: _JobsClient) -> list[str]:
    return [call[0] for call in client.calls]


async def _scalar(sql: str, *args):
    """First column of the first row. ``db_service`` has no ``fetchval``."""
    row = await db_service.fetchrow(sql, *args)
    if row is None:
        return None
    return next(iter(row.values()))


def _install(monkeypatch, client: _JobsClient | None = None):
    """Point NBA at one fixture provider and one in-memory gateway cache."""
    fixture = client or _JobsClient()
    provider = BdlOddsProvider(fixture, directory=BdlPlayerDirectory(fixture, aliases={}))
    monkeypatch.setattr(settings, "nba_odds_provider", "balldontlie")
    monkeypatch.setattr(
        "app.services.bdl_odds_provider.get_bdl_odds_provider",
        lambda: provider,
    )
    gateway = OddsMarketGateway(
        cache=FakeCache(),
        fresh_ttl_seconds=600,
        stale_ttl_seconds=900,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=50,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", gateway)
    monkeypatch.setattr("app.services.daily_analysis.odds_gateway", gateway)
    monkeypatch.setattr(db_service, "_pool", None)
    return fixture, provider, gateway


def _quiet_csv() -> MagicMock:
    csv = MagicMock()
    csv.get_player_stats.return_value = {
        "p_over": None,
        "p_under": None,
        "n_games": 0,
        "game_logs": [],
    }
    return csv


@pytest.mark.asyncio
async def test_snapshot_calls_one_games_list_and_props_only_for_the_open_game(monkeypatch):
    """2026-11-10: one list_games, one props call, one players batch, one odds call."""
    client, _provider, _gateway = _install(monkeypatch)
    service = OddsSnapshotService()
    result = await service.take_snapshot(SLATE, now=BEFORE_TIP)

    assert result["event_count"] == 1
    assert result["total_lines"] > 0
    assert result["bdl_parent_misses"] == 0
    assert _kinds(client).count("list_games") == 1
    props = [call for call in client.calls if call[0] == "get_player_props"]
    assert props == [("get_player_props", OKC_GAME_ID)]
    assert _kinds(client).count("list_players") <= 1
    assert _kinds(client).count("list_odds") == 1
    assert ("list_odds", (SLATE,), None) in client.calls
    assert "get_game" not in _kinds(client)


@pytest.mark.asyncio
async def test_started_and_non_scheduled_games_are_not_fetched(monkeypatch):
    """A tip at or before now is skipped, and so is every final or in-progress game."""
    client, _provider, _gateway = _install(monkeypatch)
    service = OddsSnapshotService()
    result = await service.take_snapshot(SLATE, now=AFTER_TIP)

    assert result["event_count"] == 0
    assert result["total_lines"] == 0
    assert _kinds(client).count("list_games") == 1
    assert "get_player_props" not in _kinds(client)
    assert "list_odds" not in _kinds(client)


@pytest.mark.asyncio
async def test_props_updated_after_tip_are_not_stored(monkeypatch):
    """The t2 capture is entirely after tip, so the snapshot stores no lines."""
    client, provider, _gateway = _install(
        monkeypatch,
        _JobsClient("props_live_21718080_OKC@POR_t2.json"),
    )
    service = OddsSnapshotService()
    result = await service.take_snapshot(SLATE, now=BEFORE_TIP)

    assert result["event_count"] == 1
    assert result["total_lines"] == 0
    assert provider._adapter.post_tip_dropped == len(client.props["data"])
    assert _kinds(client).count("get_player_props") == 1


@pytest.mark.asyncio
async def test_daily_analysis_uses_one_props_fetch_and_then_the_cache(monkeypatch):
    """The first pass is one props call. A fresh snapshot cache adds zero."""
    client, _provider, _gateway = _install(monkeypatch)
    service = OddsSnapshotService()
    await service.take_snapshot(SLATE, now=BEFORE_TIP)
    assert _kinds(client).count("get_player_props") == 1

    analysis = DailyAnalysisService()
    analysis.csv_service = _quiet_csv()
    await analysis._analyze_single_event(
        str(OKC_GAME_ID),
        "Portland Trail Blazers",
        "Oklahoma City Thunder",
        "2026-11-11T04:00:00.000Z",
        league="nba",
    )
    assert _kinds(client).count("get_player_props") == 1

    await analysis._analyze_single_event(
        str(OKC_GAME_ID),
        "Portland Trail Blazers",
        "Oklahoma City Thunder",
        "2026-11-11T04:00:00.000Z",
        league="nba",
    )
    assert _kinds(client).count("get_player_props") == 1


@pytest.mark.asyncio
async def test_daily_analysis_lists_only_the_open_game(monkeypatch):
    client, _provider, _gateway = _install(monkeypatch)
    service = DailyAnalysisService()
    events = await service._get_events_for_date(SLATE, tz_offset_minutes=EASTERN, now=BEFORE_TIP)
    assert [event["id"] for event in events] == [str(OKC_GAME_ID)]
    assert _kinds(client).count("list_games") == 1
    assert "get_player_props" not in _kinds(client)


@pytest.mark.asyncio
async def test_theoddsapi_daily_analysis_still_requests_each_market(monkeypatch):
    """The default provider keeps one snapshot call per supported market."""
    monkeypatch.setattr(settings, "nba_odds_provider", "theoddsapi")
    calls: list[str] = []

    async def snap(**kwargs):
        calls.append(kwargs.get("markets") or "")
        return SimpleNamespace(data={"bookmakers": []})

    monkeypatch.setattr("app.services.daily_analysis.odds_gateway.get_market_snapshot", snap)
    service = DailyAnalysisService()
    service.csv_service = _quiet_csv()
    await service._analyze_single_event(
        "evt",
        "Home",
        "Away",
        "2026-03-30T12:00:00Z",
        league="nba",
    )
    assert calls == [market for market, _metric in SUPPORTED_MARKETS]
    assert len(calls) == 11


@pytest.mark.asyncio
async def test_balldontlie_daily_analysis_requests_the_snapshot_market_set_once(monkeypatch):
    monkeypatch.setattr(settings, "nba_odds_provider", "balldontlie")
    calls: list[str] = []

    async def snap(**kwargs):
        calls.append(kwargs.get("markets") or "")
        return SimpleNamespace(data={"bookmakers": []})

    monkeypatch.setattr("app.services.daily_analysis.odds_gateway.get_market_snapshot", snap)
    service = DailyAnalysisService()
    service.csv_service = _quiet_csv()
    await service._analyze_single_event(
        str(OKC_GAME_ID),
        "Portland Trail Blazers",
        "Oklahoma City Thunder",
        "2026-11-11T04:00:00.000Z",
        league="nba",
    )
    assert calls == [SNAPSHOT_MARKETS]


class _NamedProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict] = []

    async def get_event_odds_with_usage(self, **kwargs):
        self.calls.append(kwargs)
        # Recorded player-points board. Only ``id`` changes, so the
        # warmed event id is the one this call was asked for.
        body = load_odds_fixture("odds_api_event_odds__player_points.json")
        body["id"] = kwargs.get("event_id")
        return body, None


def _hot_member(provider_name: str, event_id: str) -> str:
    return json.dumps(
        {
            "bookmakers": None,
            "event_id": event_id,
            "league": "nba",
            "markets": "player_points",
            "odds_format": "american",
            "provider": provider_name,
            "regions": "us",
        },
        sort_keys=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active", "warmed_id", "skipped_provider"),
    [
        ("balldontlie", "21718080", "theoddsapi"),
        ("theoddsapi", "abc123", "balldontlie"),
    ],
)
async def test_prewarm_skips_a_hot_key_from_the_other_provider(active, warmed_id, skipped_provider):
    cache = FakeCache()
    provider = _NamedProvider(active)
    gateway = OddsMarketGateway(
        provider=provider,
        cache=cache,
        fresh_ttl_seconds=1,
        stale_ttl_seconds=30,
        lock_ttl_seconds=10,
        wait_for_refresh_ms=50,
        quota_protect_percent=15,
        hot_keys_limit=10,
    )
    seen = datetime.now(timezone.utc).isoformat()
    kept = _hot_member(active, warmed_id)
    skipped = _hot_member(skipped_provider, "other-event")
    cache.zsets[HOT_KEYS_ZSET_KEY] = {skipped: 5.0, kept: 4.0}
    cache.values[f"odds:hot_seen:v1:{kept}"] = {"seen_at": seen}
    cache.values[f"odds:hot_seen:v1:{skipped}"] = {"seen_at": seen}

    warmed = await gateway.prewarm_hot_keys()

    assert warmed == 1
    assert [call["event_id"] for call in provider.calls] == [warmed_id]
    assert skipped in cache.zsets[HOT_KEYS_ZSET_KEY]
    assert kept in cache.zsets[HOT_KEYS_ZSET_KEY]


@pytest.mark.asyncio
async def test_metrics_reads_rate_status_from_the_active_nba_provider(monkeypatch):
    class OddsProvider:
        name = "theoddsapi"

        async def rate_status(self):
            return RateStatus(provider=self.name, remaining=80, used=20, recorded=True)

    class BdlProvider:
        name = "balldontlie"

        async def rate_status(self):
            return RateStatus(provider=self.name, remaining=4, used=1, recorded=True)

    monkeypatch.setattr(settings, "nba_odds_provider", "theoddsapi")
    monkeypatch.setattr("app.services.odds_gateway.odds_provider", OddsProvider())
    odds_body = await get_metrics()
    assert odds_body["odds_api_quota"]["remaining"] == 80
    assert odds_body["odds_api_quota"]["used"] == 20
    assert odds_body["odds_api_quota"]["total"] == 100
    assert set(odds_body["odds_api_quota"]) == {
        "remaining",
        "used",
        "total",
        "remaining_ratio",
        "quota_protected",
    }

    monkeypatch.setattr(settings, "nba_odds_provider", "balldontlie")
    monkeypatch.setattr(
        "app.services.bdl_odds_provider.get_bdl_odds_provider",
        lambda: BdlProvider(),
    )
    bdl_body = await get_metrics()
    assert bdl_body["odds_api_quota"]["remaining"] == 4
    assert bdl_body["odds_api_quota"]["used"] == 1
    assert bdl_body["odds_api_quota"]["total"] == 5


async def _upgrade(dsn: str) -> None:
    import asyncpg

    from app.migrations.runner import upgrade

    conn = await asyncpg.connect(dsn)
    try:
        applied = await upgrade(conn)
    finally:
        await conn.close()
    assert applied[:5] == ["001", "002", "003", "004", "005"]


async def _seed_okc_parents(dsn: str) -> None:
    """Insert the scheduled game and the players named in the recorded props."""
    import asyncpg

    game = next(item for item in _load("games_2026-11-10.json")["response"]["data"] if item["id"] == OKC_GAME_ID)
    prop_ids = {
        row["player_id"]
        for row in _load("props_live_21718080_OKC@POR_pregame.json")["response"]["data"]
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


async def _use_database(monkeypatch, dsn: str) -> None:
    monkeypatch.setattr(settings, "database_url", dsn)
    if db_service.is_connected:
        await db_service.close()
    await db_service.init()
    assert db_service.is_connected


@pytest.mark.asyncio
async def test_missing_parents_still_write_digit_line_rows(scratch_dsn, monkeypatch, caplog):
    """Empty games and players: the line table writes, and 002 does not raise."""
    await _upgrade(scratch_dsn)
    client, _provider, _gateway = _install(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    caplog.set_level(logging.INFO)
    try:
        service = OddsSnapshotService()
        result = await service.take_snapshot(SLATE, now=BEFORE_TIP)
        assert result["total_lines"] > 0
        assert result["bdl_parent_misses"] > 0
        event_ids = await db_service.fetch("SELECT DISTINCT event_id FROM odds_line_snapshots")
        assert {row["event_id"] for row in event_ids} == {str(OKC_GAME_ID)}
        assert await _scalar("SELECT count(*) AS n FROM player_prop_snapshots") == 0
        assert await _scalar("SELECT count(*) AS n FROM game_odds_snapshots") == 0
        assert "bdl_live_parent_miss" in caplog.text
        assert "batch skipped" not in caplog.text
        assert _kinds(client).count("get_player_props") == 1
        assert _kinds(client).count("list_odds") == 1
    finally:
        await db_service.close()


@pytest.mark.asyncio
async def test_live_rows_insert_when_parents_exist_and_a_retry_does_not_duplicate(
    scratch_dsn, monkeypatch
):
    """Parents present: live props and game odds pass 002 and the 005 trigger."""
    await _upgrade(scratch_dsn)
    await _seed_okc_parents(scratch_dsn)
    _client, _provider, _gateway = _install(monkeypatch)
    await _use_database(monkeypatch, scratch_dsn)
    try:
        service = OddsSnapshotService()
        result = await service.take_snapshot(SLATE, now=BEFORE_TIP)
        assert result["total_lines"] > 0

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
        assert points["snapshot_kind"] == "live"
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
            if row["game_id"] == 21718081 and row["vendor"] == "draftkings"
        )
        stored = await db_service.fetchrow(
            """
            SELECT snapshot_kind, league, spread_home_value, spread_home_odds,
                   total_value, total_over_odds, total_under_odds
            FROM game_odds_snapshots
            WHERE bdl_game_id = $1 AND book_key = 'draftkings'
            """,
            OKC_GAME_ID,
        )
        assert stored["snapshot_kind"] == "live"
        assert stored["league"] == "nba"
        assert stored["spread_home_value"] == Decimal(recorded["spread_home_value"])
        assert stored["spread_home_odds"] == recorded["spread_home_odds"]
        assert stored["total_value"] == Decimal(recorded["total_value"])
        assert stored["total_over_odds"] == recorded["total_over_odds"]
        assert stored["total_under_odds"] == recorded["total_under_odds"]
        assert await _scalar(
            "SELECT count(*) AS n FROM game_odds_snapshots WHERE book_key IN ('polymarket', 'kalshi')"
        ) == 0

        stamp = await _scalar(
            "SELECT snapshot_at AS n FROM player_prop_snapshots LIMIT 1"
        )
        await service._write_bdl_live([{"id": str(OKC_GAME_ID)}], SLATE, stamp)
        assert await _scalar("SELECT count(*) AS n FROM player_prop_snapshots") == props
    finally:
        await db_service.close()
