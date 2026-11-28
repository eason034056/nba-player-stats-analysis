"""
test_spo138_opening_backfill.py - opening odds and opening props from recorded BDL bodies.

HTTP is answered from the recorded captures. Nothing in this file calls BALLDONTLIE.
The database is the scratch database from conftest.py.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio

from app.backfill import cli
from app.backfill.opening import (
    DATA_ODDS,
    DATA_PROPS,
    SkipCounts,
    default_seasons,
    describe_opening,
    load_work_games,
    run_opening,
    season_opening_report,
    write_opening_odds_page,
    write_opening_props_page,
)
from app.migrations.runner import upgrade
from app.services.bdl_client import BdlClient
from app.services.bdl_props_adapter import PROP_TYPE_TO_MARKET
from app.services.odds_snapshot_service import _parse_commence
from tests.backfill_support import InstantClock

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
DSN_ENV = "SPO138_OPENING_TEST_DSN"
TODAY = date(2026, 11, 28)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _games_on(name: str, day: str) -> list[dict]:
    return [game for game in _load(name)["response"]["data"] if game["date"] == day]


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    await upgrade(scratch_conn)
    return scratch_conn


async def _seed_games(conn: asyncpg.Connection, games: list[dict]) -> None:
    """Store the recorded games as final regular-season parents."""
    for season in sorted({game["season"] for game in games}):
        label = f"{season}-{(season + 1) % 100:02d}"
        await conn.execute(
            """
            INSERT INTO seasons (league, season_start_year, label)
            VALUES ('nba', $1, $2)
            ON CONFLICT DO NOTHING
            """,
            season,
            label,
        )
    teams: dict[int, dict] = {}
    for game in games:
        for side in ("home_team", "visitor_team"):
            team = game[side]
            teams[team["id"]] = team
    for team in teams.values():
        await conn.execute(
            """
            INSERT INTO teams (
                league, bdl_team_id, abbreviation, name, full_name, city, conference, division
            ) VALUES ('nba', $1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT DO NOTHING
            """,
            team["id"],
            team["abbreviation"],
            team["name"],
            team["full_name"],
            team["city"],
            team["conference"],
            team["division"],
        )
    for game in games:
        await conn.execute(
            """
            INSERT INTO games (
                league, bdl_game_id, season, date, datetime_utc, status, status_state,
                postponed, season_type, home_team_id, visitor_team_id, home_score, visitor_score
            ) VALUES (
                'nba', $1, $2, $3, $4, $5, $6, $7, 'regular_season', $8, $9, $10, $11
            )
            """,
            game["id"],
            game["season"],
            date.fromisoformat(game["date"]),
            _parse_commence(game["datetime"]),
            game["status"],
            game["status_state"],
            game["postponed"],
            game["home_team"]["id"],
            game["visitor_team"]["id"],
            game["home_team_score"],
            game["visitor_team_score"],
        )


async def _seed_players(conn: asyncpg.Connection, player_ids: set[int]) -> None:
    for player_id in sorted(player_ids):
        await conn.execute(
            """
            INSERT INTO players (league, bdl_player_id, first_name, last_name, display_name, position)
            VALUES ('nba', $1, 'P', $2, $3, 'G')
            ON CONFLICT DO NOTHING
            """,
            player_id,
            str(player_id),
            f"P {player_id}",
        )


async def _seed_stat(
    conn: asyncpg.Connection,
    *,
    stat_id: int,
    game: dict,
    player_id: int,
    dnp: bool,
) -> None:
    await conn.execute(
        """
        INSERT INTO player_game_stats (
            league, bdl_stat_id, bdl_game_id, bdl_player_id, bdl_team_id, season, date,
            min_raw, seconds_played, dnp
        ) VALUES ('nba', $1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        stat_id,
        game["id"],
        player_id,
        game["home_team"]["id"],
        game["season"],
        date.fromisoformat(game["date"]),
        None if dnp else "10:00",
        None if dnp else 600,
        dnp,
    )


class _OpeningHttp:
    """Answers with a recorded body chosen by path and date or game id."""

    def __init__(self, routes: dict[tuple[str, str], dict], *, fail: set[str] | None = None) -> None:
        self.routes = routes
        self.fail = fail or set()
        self.seen: list[tuple[str, str | None, str | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        key = params.get("dates[]") or params.get("game_id")
        cursor = params.get("cursor")
        self.seen.append((request.url.path, key, cursor))
        if key in self.fail or (cursor and f"cursor:{cursor}" in self.fail):
            return httpx.Response(400, content=b"")
        recorded = self.routes[(request.url.path, key or "")]
        return httpx.Response(
            recorded["status"],
            json=recorded["response"],
            headers=recorded["rate_headers"],
        )


def _client(handler: _OpeningHttp) -> BdlClient:
    clock = InstantClock()
    return BdlClient(
        api_key="unit-test-backfill-key",
        redis=__import__("fakeredis").aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=500,
        rate_limit_ceiling=500,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )


# ---------------------------------------------------------------------------
# Defaults and the client paths
# ---------------------------------------------------------------------------


def test_default_ranges_stop_before_2026() -> None:
    """2026-27 is off unless the command names it."""
    assert default_seasons(DATA_ODDS) == list(range(2020, 2026))
    assert default_seasons(DATA_PROPS) == list(range(2024, 2026))
    assert 2026 not in default_seasons(DATA_ODDS)
    assert 2026 not in default_seasons(DATA_PROPS)


def test_omitted_seasons_use_the_defaults_and_2026_is_reachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    async def fake(dsn: str, api_key: str, **kwargs: object) -> bool:
        seen["seasons"] = list(kwargs["seasons"])  # type: ignore[arg-type]
        seen["data_type"] = kwargs["data_type"]
        return True

    monkeypatch.setattr(cli, "_run_opening", fake)
    monkeypatch.setenv(DSN_ENV, "postgresql://nba:pw-must-not-leak@127.0.0.1:1/nba_history")
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "unit-test-backfill-key")

    assert main_code(["--data", "opening_odds", "--dsn-env", DSN_ENV]) == 0
    assert seen == {"seasons": list(range(2020, 2026)), "data_type": DATA_ODDS}
    assert main_code(["--data", "opening_props", "--dsn-env", DSN_ENV]) == 0
    assert seen["seasons"] == list(range(2024, 2026))
    assert main_code(["2026", "--data", "opening_odds", "--dsn-env", DSN_ENV]) == 0
    assert seen["seasons"] == [2026]
    assert "pw-must-not-leak" not in capsys.readouterr().out + capsys.readouterr().err


def main_code(argv: list[str]) -> int:
    return cli.main(argv, today=TODAY)


@pytest.mark.asyncio
async def test_opening_client_uses_the_recorded_paths() -> None:
    """The request path and query keys are the ones in the recorded URL."""
    odds = _load("odds_opening_2024-11-20.json")
    props = _load("props_opening_15907655_2024-11-20.json")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        recorded = odds if request.url.path.endswith("/odds/opening") else props
        return httpx.Response(200, json=recorded["response"], headers=recorded["rate_headers"])

    clock = InstantClock()
    client = BdlClient(
        api_key="unit-test-backfill-key",
        redis=__import__("fakeredis").aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=500,
        rate_limit_ceiling=500,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
    )
    try:
        odds_body = await client.list_opening_odds(dates=["2024-11-20"])
        cursor = _load("odds_opening_2026-03-10.json")["response"]["meta"]["next_cursor"]
        await client.list_opening_odds(dates=["2026-03-10"], cursor=cursor)
        props_body = await client.get_opening_props(game_id=15907655)
    finally:
        await client.aclose()

    assert odds_body == odds["response"]
    assert props_body == props["response"]
    assert seen[0].url.path == "/nba/v2/odds/opening"
    assert seen[0].url.params.get_list("dates[]") == ["2024-11-20"]
    assert seen[0].url.params["per_page"] == "100"
    assert seen[0].url.params.get("cursor") is None
    assert seen[1].url.params["cursor"] == str(cursor)
    assert seen[2].url.path == "/nba/v2/odds/player_props/opening"
    assert seen[2].url.params["game_id"] == "15907655"
    assert "per_page" not in seen[2].url.params
    assert "cursor" not in seen[2].url.params


@pytest.mark.asyncio
async def test_429_backoff_honors_retry_after() -> None:
    """A 429 waits for Retry-After, not for the longer x-ratelimit-reset."""
    odds = _load("odds_opening_2024-11-20.json")
    clock = InstantClock()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                content=b"",
                headers={
                    "Retry-After": "12",
                    "x-ratelimit-limit": "500",
                    "x-ratelimit-remaining": "100",
                    "x-ratelimit-reset": str(int(clock.now + 30)),
                },
            )
        return httpx.Response(200, json=odds["response"], headers=odds["rate_headers"])

    client = BdlClient(
        api_key="unit-test-backfill-key",
        redis=__import__("fakeredis").aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=500,
        rate_limit_ceiling=500,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        clock=clock.time,
    )
    try:
        body = await client.list_opening_odds(dates=["2024-11-20"])
    finally:
        await client.aclose()

    assert body["data"]
    assert sleeps == [12.0]
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


async def _odds_count(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM game_odds_snapshots")


async def _props_count(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM player_prop_snapshots")


@pytest.mark.asyncio
async def test_recorded_odds_load_and_a_rerun_writes_nothing(db: asyncpg.Connection) -> None:
    """The second pass hits the same insert. DO NOTHING leaves the count and the line alone."""
    games = _games_on("games_hist_dates3.json", "2024-11-20")
    await _seed_games(db, games)
    recorded = _load("odds_opening_2024-11-20.json")
    rows = recorded["response"]["data"]
    books = {row["book_key"] for row in await db.fetch("SELECT book_key FROM books WHERE league = 'nba'")}
    game_ids = {game["id"] for game in games}
    expected = [row for row in rows if row["vendor"] in books and row["game_id"] in game_ids]
    assert expected

    first = await write_opening_odds_page(
        db, league="nba", season=2024, game_date=date(2024, 11, 20), rows=rows, next_cursor=None
    )
    stored = await db.fetchrow(
        """
        SELECT snapshot_at, source_updated_at, spread_home_value, spread_home_odds
        FROM game_odds_snapshots
        WHERE bdl_game_id = $1 AND book_key = 'betmgm'
        """,
        15907655,
    )
    sample = next(row for row in rows if row["game_id"] == 15907655)
    assert first.written == len(expected)
    assert await _odds_count(db) == len(expected)
    assert stored["snapshot_at"] == _parse_commence(sample["opened_at"])
    assert stored["source_updated_at"] is None
    assert stored["spread_home_value"] == Decimal(sample["spread_home_value"])
    assert stored["spread_home_odds"] == sample["spread_home_odds"]

    second = await write_opening_odds_page(
        db, league="nba", season=2024, game_date=date(2024, 11, 20), rows=rows, next_cursor=None
    )
    assert second.written == 0
    assert await _odds_count(db) == len(expected)
    again = await db.fetchrow(
        "SELECT spread_home_value FROM game_odds_snapshots WHERE bdl_game_id = $1",
        15907655,
    )
    assert again["spread_home_value"] == Decimal(sample["spread_home_value"])


@pytest.mark.asyncio
async def test_polymarket_and_kalshi_are_skipped(db: asyncpg.Connection) -> None:
    """Those books are not seeded. The page is stored without a foreign-key error."""
    games = _games_on("games_hist_dates.json", "2026-03-10")
    await _seed_games(db, games)
    recorded = _load("odds_opening_2026-03-10.json")
    rows = recorded["response"]["data"]
    unknown = sum(1 for row in rows if row["vendor"] in {"polymarket", "kalshi"})
    assert unknown > 0

    result = await write_opening_odds_page(
        db,
        league="nba",
        season=2025,
        game_date=date(2026, 3, 10),
        rows=rows,
        next_cursor=recorded["response"]["meta"]["next_cursor"],
    )

    assert result.skips.unknown_book == unknown
    assert result.skips.missing_game == 0
    assert await db.fetchval(
        "SELECT count(*) FROM game_odds_snapshots WHERE book_key IN ('polymarket', 'kalshi')"
    ) == 0
    assert await _odds_count(db) == len(rows) - unknown


@pytest.mark.asyncio
async def test_recorded_props_keep_one_main_line_and_the_opened_at(db: asyncpg.Connection) -> None:
    games = _games_on("games_hist_dates3.json", "2024-11-20")
    game = next(item for item in games if item["id"] == 15907655)
    await _seed_games(db, [game])
    recorded = _load("props_opening_15907655_2024-11-20.json")
    rows = recorded["response"]["data"]
    player_ids = {row["player_id"] for row in rows}
    await _seed_players(db, player_ids)
    unknown = sum(1 for row in rows if row["prop_type"] not in PROP_TYPE_TO_MARKET)

    result = await write_opening_props_page(
        db, league="nba", season=2024, game_id=15907655, rows=rows
    )

    stored = await _props_count(db)
    assert result.skips.unknown_prop_type == unknown
    assert result.skips.unknown_book == 0
    assert result.skips.missing_player == 0
    assert result.written == stored
    assert 0 < stored < len(rows)
    keys = await db.fetch(
        """
        SELECT bdl_player_id, book_key, market, count(*) AS n
        FROM player_prop_snapshots
        GROUP BY 1, 2, 3
        HAVING count(*) > 1
        """
    )
    assert keys == []
    markets = {row["market"] for row in await db.fetch("SELECT DISTINCT market FROM player_prop_snapshots")}
    assert markets <= set(PROP_TYPE_TO_MARKET.values())
    opened = _parse_commence(rows[0]["opened_at"])
    stamps = await db.fetch("SELECT snapshot_at, source_updated_at FROM player_prop_snapshots")
    assert {row["snapshot_at"] for row in stamps} == {opened}
    assert {row["source_updated_at"] for row in stamps} == {None}

    second = await write_opening_props_page(
        db, league="nba", season=2024, game_id=15907655, rows=rows
    )
    assert second.written == 0
    assert await _props_count(db) == stored


@pytest.mark.asyncio
async def test_bucket_report_marks_tip_odds_and_tip_minus_3h_props(db: asyncpg.Connection) -> None:
    """A tip-stamped opener is `= tip`. A prop stamped at tip - 3h is `= T`."""
    games = _games_on("games_hist_dates3.json", "2024-11-20")
    game = next(item for item in games if item["id"] == 15907655)
    await _seed_games(db, games)
    odds_rows = _load("odds_opening_2024-11-20.json")["response"]["data"]
    await write_opening_odds_page(
        db, league="nba", season=2024, game_date=date(2024, 11, 20), rows=odds_rows, next_cursor=None
    )
    prop_rows = _load("props_opening_15907655_2024-11-20.json")["response"]["data"]
    await _seed_players(db, {row["player_id"] for row in prop_rows})
    await write_opening_props_page(db, league="nba", season=2024, game_id=15907655, rows=prop_rows)
    played = next(iter({row["player_id"] for row in prop_rows}))
    outsider = max(row["player_id"] for row in prop_rows) + 1
    dnp_player = outsider + 1
    await _seed_players(db, {outsider, dnp_player})
    await _seed_stat(db, stat_id=1, game=game, player_id=played, dnp=False)
    await _seed_stat(db, stat_id=2, game=game, player_id=outsider, dnp=False)
    await _seed_stat(db, stat_id=3, game=game, player_id=dnp_player, dnp=True)

    report = await season_opening_report(
        db,
        league="nba",
        season=2024,
        data_type=DATA_PROPS,
        written=0,
        skips=SkipCounts(),
        current=False,
        shard_keys=[],
    )
    odds_n = await _odds_count(db)
    props_n = await _props_count(db)
    assert report.odds_buckets["= tip"] == odds_n
    assert report.odds_buckets["= T"] == 0
    assert report.odds_buckets["> tip"] == 0
    assert report.odds_buckets["NULL"] == 0
    assert report.prop_buckets["= T"] == props_n
    assert report.prop_buckets["= tip"] == 0
    assert report.prop_buckets["> tip"] == 0
    assert sum(report.odds_buckets.values()) == odds_n
    assert sum(report.prop_buckets.values()) == props_n
    tip = _parse_commence(game["datetime"])
    assert tip is not None
    assert _parse_commence(prop_rows[0]["opened_at"]) == tip - timedelta(hours=3)
    line = describe_opening(report)
    assert "= tip" in line and "= T" in line
    assert "non-DNP player-games with props" in line
    assert report.player_games == 2
    assert report.player_games_with_props == 1


@pytest.mark.asyncio
async def test_resume_does_not_refetch_a_finished_shard(db: asyncpg.Connection) -> None:
    """The first date is stored. The second date fails. The next run asks only for the second."""
    first_games = _games_on("games_hist_dates.json", "2025-11-20")
    second_games = _games_on("games_hist_dates.json", "2026-01-15")
    await _seed_games(db, first_games + second_games)
    routes = {
        ("/nba/v2/odds/opening", "2025-11-20"): _load("odds_opening_2025-11-20.json"),
        ("/nba/v2/odds/opening", "2026-01-15"): _load("odds_opening_2026-01-15.json"),
    }
    stopped = _OpeningHttp(routes, fail={"2026-01-15"})
    client = _client(stopped)
    try:
        with pytest.raises(Exception):
            async for _report in run_opening(
                db, client, league="nba", data_type=DATA_ODDS, seasons=[2025],
                restart=frozenset(), current=2026,
            ):
                pass
    finally:
        await client.aclose()

    assert ("/nba/v2/odds/opening", "2025-11-20", None) in stopped.seen
    assert ("/nba/v2/odds/opening", "2026-01-15", None) in stopped.seen
    done = await db.fetchval(
        """
        SELECT cursor FROM bdl_backfill_checkpoints
        WHERE data_type = 'opening_odds' AND season = 2025 AND shard_key = '2025-11-20'
        """
    )
    assert done is None

    again = _OpeningHttp(routes)
    client = _client(again)
    try:
        reports = [
            report
            async for report in run_opening(
                db, client, league="nba", data_type=DATA_ODDS, seasons=[2025],
                restart=frozenset(), current=2026,
            )
        ]
    finally:
        await client.aclose()

    requested = [item[1] for item in again.seen]
    assert "2025-11-20" not in requested
    assert "2026-01-15" in requested
    assert reports[0].passed
    assert await db.fetchval(
        """
        SELECT status FROM bdl_backfill_checkpoints
        WHERE data_type = 'opening_odds' AND season = 2025 AND shard_key = '2025-11-20'
        """
    ) == "done"


@pytest.mark.asyncio
async def test_a_cursor_page_is_not_refetched_from_the_start(db: asyncpg.Connection) -> None:
    """Page one is committed with the recorded next_cursor. The resume asks for that cursor."""
    games = _games_on("games_hist_dates.json", "2026-03-10")
    await _seed_games(db, games)
    recorded = _load("odds_opening_2026-03-10.json")
    cursor = str(recorded["response"]["meta"]["next_cursor"])
    routes = {("/nba/v2/odds/opening", "2026-03-10"): recorded}
    stopped = _OpeningHttp(routes, fail={f"cursor:{cursor}"})
    client = _client(stopped)
    try:
        with pytest.raises(Exception):
            async for _report in run_opening(
                db, client, league="nba", data_type=DATA_ODDS, seasons=[2025],
                restart=frozenset(), current=2026,
            ):
                pass
    finally:
        await client.aclose()

    assert stopped.seen[0][2] is None
    assert cursor in {item[2] for item in stopped.seen}
    stored_cursor = await db.fetchval(
        """
        SELECT cursor FROM bdl_backfill_checkpoints
        WHERE data_type = 'opening_odds' AND shard_key = '2026-03-10'
        """
    )
    assert stored_cursor == cursor

    again = _OpeningHttp(routes, fail={f"cursor:{cursor}"})
    client = _client(again)
    try:
        with pytest.raises(Exception):
            async for _report in run_opening(
                db, client, league="nba", data_type=DATA_ODDS, seasons=[2025],
                restart=frozenset(), current=2026,
            ):
                pass
    finally:
        await client.aclose()
    assert all(item[2] == cursor for item in again.seen)
    assert await _odds_count(db) == sum(
        1 for row in recorded["response"]["data"] if row["vendor"] not in {"polymarket", "kalshi"}
    )


@pytest.mark.asyncio
async def test_props_resume_skips_a_finished_game(db: asyncpg.Connection) -> None:
    games = _games_on("games_hist_dates3.json", "2024-11-20")
    first = next(game for game in games if game["id"] == 15907655)
    second = next(game for game in games if game["id"] != 15907655)
    await _seed_games(db, [first, second])
    recorded = _load("props_opening_15907655_2024-11-20.json")
    await _seed_players(db, {row["player_id"] for row in recorded["response"]["data"]})
    routes = {("/nba/v2/odds/player_props/opening", "15907655"): recorded}
    stopped = _OpeningHttp(routes, fail={str(second["id"])})
    client = _client(stopped)
    try:
        with pytest.raises(Exception):
            async for _report in run_opening(
                db, client, league="nba", data_type=DATA_PROPS, seasons=[2024],
                restart=frozenset(), current=2026,
            ):
                pass
    finally:
        await client.aclose()

    again = _OpeningHttp(routes, fail={str(second["id"])})
    client = _client(again)
    try:
        with pytest.raises(Exception):
            async for _report in run_opening(
                db, client, league="nba", data_type=DATA_PROPS, seasons=[2024],
                restart=frozenset(), current=2026,
            ):
                pass
    finally:
        await client.aclose()
    assert all(item[1] == str(second["id"]) for item in again.seen)
    assert await _props_count(db) > 0


def test_dry_run_writes_no_rows(
    scratch_dsn: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main`` starts its own event loop, so this test stays synchronous."""
    games = _games_on("games_hist_dates3.json", "2024-11-20")

    async def prepare() -> None:
        conn = await asyncpg.connect(scratch_dsn)
        try:
            await upgrade(conn)
            await _seed_games(conn, games)
            await conn.execute(
                """
                INSERT INTO bdl_backfill_checkpoints (league, data_type, season, shard_key, status)
                VALUES ('nba', 'games', 2024, 'regular', 'done')
                """
            )
        finally:
            await conn.close()

    asyncio.run(prepare())
    recorded = _load("odds_opening_2024-11-20.json")
    handler = _OpeningHttp({("/nba/v2/odds/opening", "2024-11-20"): recorded})
    made: dict[str, object] = {}

    def factory(**kwargs: object) -> BdlClient:
        made.update(kwargs)
        clock = InstantClock()
        return BdlClient(
            transport=httpx.MockTransport(handler),
            sleep=clock.sleep,
            clock=clock.time,
            **kwargs,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(cli, "BdlClient", factory)
    monkeypatch.setenv(DSN_ENV, scratch_dsn)
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "unit-test-backfill-key")

    code = cli.main(
        ["2024", "--data", "opening_odds", "--dry-run", "--dsn-env", DSN_ENV],
        today=TODAY,
    )

    async def counts() -> tuple[int, int, str]:
        conn = await asyncpg.connect(scratch_dsn)
        try:
            odds = await conn.fetchval("SELECT count(*) FROM game_odds_snapshots")
            opening = await conn.fetchval(
                "SELECT count(*) FROM bdl_backfill_checkpoints WHERE data_type = 'opening_odds'"
            )
            games_status = await conn.fetchval(
                "SELECT status FROM bdl_backfill_checkpoints WHERE data_type = 'games'"
            )
            return odds, opening, games_status
        finally:
            await conn.close()

    odds, opening_checkpoints, games_status = asyncio.run(counts())
    output = capsys.readouterr().out
    assert code == 0
    assert "dry run" in output and "would write" in output
    assert odds == 0
    assert opening_checkpoints == 0
    assert games_status == "done"
    assert made["rate_limit_per_min"] == 500
    assert made["rate_limit_ceiling"] == 500
    assert handler.seen


@pytest.mark.asyncio
async def test_opening_run_leaves_games_checkpoints_alone(db: asyncpg.Connection) -> None:
    games = _games_on("games_hist_dates3.json", "2024-11-20")
    await _seed_games(db, games)
    await db.execute(
        """
        INSERT INTO bdl_backfill_checkpoints (league, data_type, season, shard_key, status, rows_written)
        VALUES ('nba', 'games', 2024, 'regular', 'done', 8)
        """
    )
    recorded = _load("odds_opening_2024-11-20.json")
    handler = _OpeningHttp({("/nba/v2/odds/opening", "2024-11-20"): recorded})
    client = _client(handler)
    try:
        reports = [
            report
            async for report in run_opening(
                db, client, league="nba", data_type=DATA_ODDS, seasons=[2024],
                restart=frozenset(), current=2026,
            )
        ]
    finally:
        await client.aclose()
    assert reports[0].passed
    assert await db.fetchval(
        "SELECT rows_written FROM bdl_backfill_checkpoints WHERE data_type = 'games' AND shard_key = 'regular'"
    ) == 8
    assert await db.fetchval("SELECT count(*) FROM games") == len(games)


@pytest.mark.asyncio
async def test_work_list_uses_the_date_floor_and_the_props_season_floor(db: asyncpg.Connection) -> None:
    """Odds skip a game before 2020-12-01. Props skip a season before 2024. A 2026 game is eligible."""
    early = {
        "id": 1, "season": 2020, "date": "2020-11-15", "datetime": "2020-11-15T00:00:00.000Z",
        "status": "Final", "status_state": "final", "postponed": False,
        "home_team_score": 1, "visitor_team_score": 2,
        "home_team": {"id": 10, "abbreviation": "A", "name": "A", "full_name": "A", "city": "A", "conference": "East", "division": "Atlantic"},
        "visitor_team": {"id": 11, "abbreviation": "B", "name": "B", "full_name": "B", "city": "B", "conference": "East", "division": "Atlantic"},
    }
    later = dict(early, id=2, date="2020-12-23", datetime="2020-12-23T00:00:00.000Z")
    props_old = dict(early, id=3, season=2023, date="2024-01-15", datetime="2024-01-15T00:00:00.000Z")
    current = dict(early, id=4, season=2026, date="2026-11-01", datetime="2026-11-01T00:00:00.000Z")
    await _seed_games(db, [early, later, props_old, current])
    odds_2020 = await load_work_games(db, league="nba", season=2020, data_type=DATA_ODDS)
    props_2023 = await load_work_games(db, league="nba", season=2023, data_type=DATA_PROPS)
    odds_2026 = await load_work_games(db, league="nba", season=2026, data_type=DATA_ODDS)
    props_2026 = await load_work_games(db, league="nba", season=2026, data_type=DATA_PROPS)
    assert [game.bdl_game_id for game in odds_2020] == [2]
    assert props_2023 == []
    assert [game.bdl_game_id for game in odds_2026] == [4]
    assert [game.bdl_game_id for game in props_2026] == [4]


def test_logs_and_errors_hide_the_dsn_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """A connect failure that logs the DSN and repeats it must not show the password."""
    password = "pw-must-not-leak"
    dsn = f"postgresql://nba:{password}@127.0.0.1:1/nba_history"
    api_key = "key-must-not-leak"

    async def loud_connect(dsn: str, **kwargs: object) -> None:
        logging.getLogger("app.backfill.cli").warning("connecting with %s", dsn)
        raise RuntimeError(f"could not use {dsn} with key {api_key}")

    monkeypatch.setattr(cli.asyncpg, "connect", loud_connect)
    monkeypatch.setenv(DSN_ENV, dsn)
    monkeypatch.setenv("BALLDONTLIE_API_KEY", api_key)
    caplog.set_level(logging.DEBUG)

    code = cli.main(
        ["2024", "--data", "opening_odds", "--dsn-env", DSN_ENV, "--verbose"],
        today=TODAY,
    )

    text = caplog.text + capsys.readouterr().out + capsys.readouterr().err
    assert code == 1
    assert password not in text
    assert api_key not in text


def test_scheduler_does_not_call_the_backfill() -> None:
    import app.services.scheduler as scheduler

    source = inspect.getsource(scheduler)
    assert "app.backfill" not in source
    assert "opening_odds" not in source
    assert "opening_props" not in source


def test_games_dry_run_still_needs_no_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The original dry run is unchanged: no DSN, and it still reads the games pages."""
    from tests.backfill_support import RecordedSeasons, recorded_client, season_2025_routes

    monkeypatch.setattr(
        cli, "BdlClient", lambda **_: recorded_client(RecordedSeasons({2025: season_2025_routes()}))
    )
    monkeypatch.delenv(DSN_ENV, raising=False)
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "unit-test-backfill-key")
    code = cli.main(["2025", "--dry-run", "--dsn-env", DSN_ENV], today=TODAY)
    assert code == 0
    assert "dry run" in capsys.readouterr().out
