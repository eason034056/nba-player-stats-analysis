"""
test_backfill_walker.py - one season walked from recorded BALLDONTLIE pages.

The client is the real ``BdlClient`` answered from recorded captures
(``backfill_support.py``); a request with no recorded answer fails the test. The database tests
apply the shipped migrations to a scratch database (``conftest.py``).
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.backfill.raw_cache import RawCache
from app.backfill.walker import Shard, ShardPreview, ShardWalk, preview_season, season_shards, walk_season
from app.backfill.writer import BackfillPageError
from app.migrations.runner import upgrade
from tests.backfill_support import (
    RecordedBdl,
    capture,
    next_cursor,
    recorded_client,
    season_2025_routes,
    with_bad_season,
)


@pytest_asyncio.fixture
async def db(scratch_conn: asyncpg.Connection) -> asyncpg.Connection:
    await upgrade(scratch_conn)
    return scratch_conn


async def _walk(conn: asyncpg.Connection, bdl: RecordedBdl, raw: RawCache | None = None) -> list[ShardWalk]:
    client = recorded_client(bdl)
    try:
        return await walk_season(conn, client, league="nba", season=2025, raw=raw)
    finally:
        await client.aclose()


async def _checkpoints(conn: asyncpg.Connection) -> dict[tuple[str, str], asyncpg.Record]:
    rows = await conn.fetch("SELECT * FROM bdl_backfill_checkpoints WHERE season = 2025")
    return {(row["data_type"], row["shard_key"]): row for row in rows}


def test_a_season_is_games_by_type_then_stats() -> None:
    """Stats rows need their games stored, so stats come last."""
    assert season_shards(2025) == [
        Shard("games", 2025, "regular"),
        Shard("games", 2025, "playoffs"),
        Shard("games", 2025, "playin"),
        Shard("games", 2025, "ist"),
        Shard("stats", 2025, ""),
    ]


@pytest.mark.asyncio
async def test_a_fresh_season_walks_every_page_of_every_shard(db: asyncpg.Connection) -> None:
    routes = season_2025_routes()
    bdl = RecordedBdl(routes)

    walks = await _walk(db, bdl)

    assert bdl.seen == list(routes)
    assert bdl.seasons == {("2025",)}
    assert walks == [
        ShardWalk(Shard("games", 2025, "regular"), pages=2, written=100),
        ShardWalk(Shard("games", 2025, "playoffs"), pages=1, written=85),
        ShardWalk(Shard("games", 2025, "playin"), pages=1, written=6),
        ShardWalk(Shard("games", 2025, "ist"), pages=1, written=1),
        ShardWalk(Shard("stats", 2025, ""), pages=2, written=100),
    ]
    checkpoints = await _checkpoints(db)
    assert {key: (row["status"], row["cursor"], row["pages_fetched"]) for key, row in checkpoints.items()} == {
        ("games", "regular"): ("in_progress", None, 2),
        ("games", "playoffs"): ("in_progress", None, 1),
        ("games", "playin"): ("in_progress", None, 1),
        ("games", "ist"): ("in_progress", None, 1),
        ("stats", ""): ("in_progress", None, 2),
    }


@pytest.mark.asyncio
async def test_a_failed_page_is_recorded_and_stops_the_walk(db: asyncpg.Connection) -> None:
    """The cursor still points at the page that failed. No later shard is asked for."""
    routes = season_2025_routes()
    regular = routes[("/v1/games", "regular", None)]
    routes[("/v1/games", "regular", next_cursor(regular))] = with_bad_season(regular)
    bdl = RecordedBdl(routes)

    with pytest.raises(BackfillPageError):
        await _walk(db, bdl)

    assert bdl.seen == [("/v1/games", "regular", None), ("/v1/games", "regular", next_cursor(regular))]
    checkpoint = (await _checkpoints(db))[("games", "regular")]
    assert (checkpoint["status"], checkpoint["cursor"], checkpoint["pages_fetched"]) == (
        "error", next_cursor(regular), 1,
    )
    assert checkpoint["last_error"].startswith("BackfillPageError: ")
    assert "2024" in checkpoint["last_error"]


@pytest.mark.asyncio
async def test_a_rerun_resumes_at_the_failed_page(db: asyncpg.Connection) -> None:
    routes = season_2025_routes()
    regular = routes[("/v1/games", "regular", None)]
    failing = dict(routes)
    failing[("/v1/games", "regular", next_cursor(regular))] = with_bad_season(regular)
    with pytest.raises(BackfillPageError):
        await _walk(db, RecordedBdl(failing))

    bdl = RecordedBdl(routes)
    await _walk(db, bdl)

    assert bdl.seen[0] == ("/v1/games", "regular", next_cursor(regular))
    assert ("/v1/games", "regular", None) not in bdl.seen
    checkpoint = (await _checkpoints(db))[("games", "regular")]
    assert (checkpoint["status"], checkpoint["cursor"], checkpoint["pages_fetched"], checkpoint["last_error"]) == (
        "in_progress", None, 2, None,
    )


@pytest.mark.asyncio
async def test_a_failure_on_the_first_page_starts_over_from_page_one(db: asyncpg.Connection) -> None:
    """No page was stored, so the error row has no cursor and no pages. The rerun asks for page one again."""
    routes = season_2025_routes()
    failing = dict(routes)
    failing[("/v1/games", "regular", None)] = with_bad_season(routes[("/v1/games", "regular", None)])
    with pytest.raises(BackfillPageError):
        await _walk(db, RecordedBdl(failing))
    checkpoint = (await _checkpoints(db))[("games", "regular")]
    assert (checkpoint["status"], checkpoint["cursor"], checkpoint["pages_fetched"]) == ("error", None, 0)

    bdl = RecordedBdl(routes)
    await _walk(db, bdl)

    assert bdl.seen[0] == ("/v1/games", "regular", None)


@pytest.mark.asyncio
async def test_done_and_fully_walked_shards_send_no_request(db: asyncpg.Connection) -> None:
    """``done`` is verified. ``in_progress`` with pages and no cursor is walked and waits for verification."""
    await db.execute(
        """
        INSERT INTO bdl_backfill_checkpoints (league, data_type, season, shard_key, cursor, status, pages_fetched)
        VALUES ('nba', 'games', 2025, 'regular', NULL, 'done', 2),
               ('nba', 'games', 2025, 'playoffs', NULL, 'in_progress', 1),
               ('nba', 'stats', 2025, '', NULL, 'done', 2)
        """
    )
    bdl = RecordedBdl(season_2025_routes())

    walks = await _walk(db, bdl)

    assert bdl.seen == [("/v1/games", "playin", None), ("/v1/games", "ist", None)]
    assert walks[0] == ShardWalk(Shard("games", 2025, "regular"))
    assert walks[1] == ShardWalk(Shard("games", 2025, "playoffs"))


@pytest.mark.asyncio
async def test_an_empty_page_ends_the_shard_even_with_a_cursor(db: asyncpg.Connection) -> None:
    """Asking again after an empty page could loop forever, so the walk stops and stores no cursor."""
    routes = season_2025_routes()
    empty_with_cursor = copy.deepcopy(capture("games__season1900_empty.json"))
    empty_with_cursor["response"]["meta"]["next_cursor"] = 12345
    routes[("/v1/games", "regular", None)] = empty_with_cursor
    bdl = RecordedBdl(routes)

    walks = await _walk(db, bdl)

    assert ("/v1/games", "regular", "12345") not in bdl.seen
    assert walks[0] == ShardWalk(Shard("games", 2025, "regular"), pages=1, written=0)
    checkpoint = (await _checkpoints(db))[("games", "regular")]
    assert (checkpoint["cursor"], checkpoint["pages_fetched"]) == (None, 1)


# ---------------------------------------------------------------------------
# Raw pages and dry runs
# ---------------------------------------------------------------------------


def _raw_path(route: tuple[str, str | None, str | None]) -> str:
    path, season_type, cursor = route
    data_type = "games" if path == "/v1/games" else "stats"
    return f"nba/{data_type}/2025/{season_type or 'all'}/{cursor or 'first'}.json.gz"


def _kept(root: Path) -> dict[str, dict[str, Any]]:
    return {
        str(file.relative_to(root)): json.loads(gzip.decompress(file.read_bytes()))
        for file in root.rglob("*") if file.is_file()
    }


@pytest.mark.asyncio
async def test_every_fetched_page_is_kept_gzipped(db: asyncpg.Connection, tmp_path: Path) -> None:
    """One file per request, named by the cursor it asked for, so a resumed walk rewrites the same file."""
    routes = season_2025_routes()

    await _walk(db, RecordedBdl(routes), RawCache(tmp_path, "nba"))

    kept = _kept(tmp_path)
    assert {name: page["response"] for name, page in kept.items()} == {
        _raw_path(route): recorded["response"] for route, recorded in routes.items()
    }
    assert all(page["fetched_at"] for page in kept.values())


@pytest.mark.asyncio
async def test_a_page_that_fails_to_write_is_still_kept(db: asyncpg.Connection, tmp_path: Path) -> None:
    """The raw page is saved before the write, so the page that broke the walk can be read afterwards."""
    routes = season_2025_routes()
    regular = routes[("/v1/games", "regular", None)]
    failing_route = ("/v1/games", "regular", next_cursor(regular))
    routes[failing_route] = with_bad_season(regular)

    with pytest.raises(BackfillPageError):
        await _walk(db, RecordedBdl(routes), RawCache(tmp_path, "nba"))

    kept = _kept(tmp_path)
    assert kept[_raw_path(failing_route)]["response"] == routes[failing_route]["response"]


async def _preview(bdl: RecordedBdl) -> list[ShardPreview]:
    client = recorded_client(bdl)
    try:
        return await preview_season(client, season=2025)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_dry_run_reads_every_page_without_a_database() -> None:
    bdl = RecordedBdl(season_2025_routes())

    previews = await _preview(bdl)

    assert bdl.seen == list(season_2025_routes())
    assert previews == [
        ShardPreview(Shard("games", 2025, "regular"), pages=2, rows=100),
        ShardPreview(Shard("games", 2025, "playoffs"), pages=1, rows=85),
        ShardPreview(Shard("games", 2025, "playin"), pages=1, rows=6),
        ShardPreview(Shard("games", 2025, "ist"), pages=1, rows=1),
        ShardPreview(Shard("stats", 2025, ""), pages=2, rows=100),
    ]


@pytest.mark.asyncio
async def test_a_dry_run_counts_the_lines_the_normalizer_would_refuse() -> None:
    routes = season_2025_routes()
    stats = copy.deepcopy(routes[("/v1/stats", None, None)])
    stats["response"]["data"][3]["min"] = "3 minutes"
    routes[("/v1/stats", None, None)] = stats

    previews = await _preview(RecordedBdl(routes))

    assert previews[-1] == ShardPreview(Shard("stats", 2025, ""), pages=2, rows=100, refused=1)
