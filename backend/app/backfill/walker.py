"""
walker.py - walk one season's BALLDONTLIE pages into the core tables.

A season is five shards walked in order: games once per season_type in
``bdl_client.SEASON_TYPES``, then stats, whose rows need their games stored.
``writer.py`` commits each page with the checkpoint that points past it, so
a crash or a failed page loses no stored page: the next run asks for the
page that did not commit.

A shard's checkpoint says where to start:

- no row, or ``pages_fetched = 0``: page one.
- a cursor: that page, whether the status is ``in_progress`` or ``error``.
- pages but no cursor: every page is stored, so no request is sent. The
  status says whether the shard still waits for verification
  (``in_progress``) or passed it (``done``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import asyncpg

from app.backfill.writer import PageWrite, write_games_page, write_stats_page
from app.services.bdl_client import SEASON_TYPES, BdlClient
from app.services.bdl_stats import BdlStatRowError, normalize_stat_row

if TYPE_CHECKING:
    from app.backfill.raw_cache import RawCache

logger = logging.getLogger(__name__)

_PER_PAGE = 100
_ERROR_TEXT_LIMIT = 500

_LOAD_CHECKPOINT = """
SELECT status, cursor, pages_fetched FROM bdl_backfill_checkpoints
WHERE league = $1 AND data_type = $2 AND season = $3 AND shard_key = $4
"""
_MARK_ERROR = """
INSERT INTO bdl_backfill_checkpoints (league, data_type, season, shard_key, status, last_error)
VALUES ($1, $2, $3, $4, 'error', $5)
ON CONFLICT (league, data_type, season, shard_key) DO UPDATE SET
    status = 'error',
    last_error = EXCLUDED.last_error,
    updated_at = now()
"""


@dataclass(frozen=True)
class Shard:
    """One checkpoint row's worth of walking: a data type for one season.

    ``shard_key`` is the BALLDONTLIE ``season_type`` for games and ``""``
    for stats, which ``/v1/stats`` cannot filter by type.
    """

    data_type: str
    season: int
    shard_key: str

    @property
    def label(self) -> str:
        """``"games regular"`` or ``"stats"``."""
        return f"{self.data_type} {self.shard_key}".strip()


@dataclass(frozen=True)
class ShardWalk:
    """What this run did for one shard. All zero when the shard sent no request."""

    shard: Shard
    pages: int = 0
    written: int = 0
    dropped: int = 0
    rejected: int = 0


@dataclass(frozen=True)
class ShardPreview:
    """What a dry run read for one shard. ``refused`` counts stats lines ``normalize_stat_row`` refuses."""

    shard: Shard
    pages: int = 0
    rows: int = 0
    refused: int = 0


@dataclass(frozen=True)
class Page:
    """One response: the cursor it was asked for, its rows, and the cursor of the page after it.

    ``next_cursor`` is ``None`` on the last page, and on an empty page even
    when BALLDONTLIE sends a cursor, because asking again could loop forever.
    """

    cursor: int | None
    rows: list[dict[str, Any]]
    next_cursor: int | None


def season_shards(season: int) -> list[Shard]:
    """The shards of one season in walking order."""
    games = [Shard("games", season, season_type) for season_type in SEASON_TYPES]
    return [*games, Shard("stats", season, "")]


async def iter_pages(
    client: BdlClient, shard: Shard, cursor: int | None, raw: RawCache | None = None
) -> AsyncIterator[Page]:
    """Fetch the shard's pages from ``cursor`` (``None`` is page one) to its last page.

    Each page is saved to ``raw`` before it is yielded, so it is kept even
    when the caller fails to store it.
    """
    while True:
        response = await _fetch(client, shard, cursor)
        if raw is not None:
            raw.save(shard, cursor, response)
        rows = response["data"]
        next_cursor = response["meta"].get("next_cursor") if rows else None
        yield Page(cursor, rows, next_cursor)
        if next_cursor is None:
            return
        cursor = next_cursor


async def walk_season(
    conn: asyncpg.Connection,
    client: BdlClient,
    *,
    league: str,
    season: int,
    raw: RawCache | None = None,
) -> list[ShardWalk]:
    """Walk every shard of ``season`` that is not stored yet, in order.

    Returns one ``ShardWalk`` per shard, in ``season_shards`` order. Every
    fetched page is also saved to ``raw`` when one is given.

    Raises:
        Exception: whatever failed a page. The shard's checkpoint is marked
            ``error`` with the message, its cursor still names the failed
            page, and no later shard is walked.
    """
    return [await _walk_shard(conn, client, league, shard, raw) for shard in season_shards(season)]


async def preview_season(
    client: BdlClient, *, season: int, raw: RawCache | None = None
) -> list[ShardPreview]:
    """Read every page of every shard of ``season`` from page one, and store nothing.

    No checkpoint is read or written, so a dry run needs no database and
    leaves a later real run exactly where it was.
    """
    previews: list[ShardPreview] = []
    for shard in season_shards(season):
        pages = rows = refused = 0
        async for page in iter_pages(client, shard, None, raw):
            pages += 1
            rows += len(page.rows)
            if shard.data_type == "stats":
                refused += sum(1 for row in page.rows if _refused(row))
        previews.append(ShardPreview(shard, pages, rows, refused))
    return previews


def _refused(row: dict[str, Any]) -> bool:
    try:
        normalize_stat_row(row)
    except BdlStatRowError:
        return True
    return False


async def _walk_shard(
    conn: asyncpg.Connection, client: BdlClient, league: str, shard: Shard, raw: RawCache | None
) -> ShardWalk:
    state = await conn.fetchrow(_LOAD_CHECKPOINT, league, shard.data_type, shard.season, shard.shard_key)
    started = state is not None and state["pages_fetched"] > 0
    if started and state["cursor"] is None:
        return ShardWalk(shard)
    cursor = int(state["cursor"]) if started else None

    pages = written = dropped = rejected = 0
    try:
        async for page in iter_pages(client, shard, cursor, raw):
            result = await _write(conn, league, shard, page.rows, page.next_cursor)
            pages += 1
            written += result.written
            dropped += result.dropped
            rejected += result.rejected
            logger.info(
                "bdl_backfill_page data_type=%s season=%s shard=%s rows=%s next_cursor=%s",
                shard.data_type, shard.season, shard.shard_key, len(page.rows), page.next_cursor,
            )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:_ERROR_TEXT_LIMIT]
        await conn.execute(_MARK_ERROR, league, shard.data_type, shard.season, shard.shard_key, message)
        raise
    return ShardWalk(shard, pages, written, dropped, rejected)


async def _fetch(client: BdlClient, shard: Shard, cursor: int | None) -> dict[str, Any]:
    if shard.data_type == "games":
        return await client.list_games(
            seasons=[shard.season], season_type=shard.shard_key, per_page=_PER_PAGE, cursor=cursor
        )
    return await client.list_stats(seasons=[shard.season], per_page=_PER_PAGE, cursor=cursor)


async def _write(
    conn: asyncpg.Connection,
    league: str,
    shard: Shard,
    rows: list[dict[str, Any]],
    next_cursor: int | None,
) -> PageWrite:
    if shard.data_type == "games":
        return await write_games_page(
            conn, league=league, season=shard.season, season_type=shard.shard_key,
            games=rows, next_cursor=next_cursor,
        )
    return await write_stats_page(
        conn, league=league, season=shard.season, rows=rows, next_cursor=next_cursor
    )
