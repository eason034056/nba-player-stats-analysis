"""
opening.py - backfill BALLDONTLIE opening game odds and opening player props.

Odds are one shard per game date. Props are one shard per game. A shard's
checkpoint moves in the same transaction as its rows, and a shard that
already reached its last page is not fetched again.

``snapshot_at`` is the row's ``opened_at``, unchanged. ``source_updated_at``
is null: an opening row has no ``updated_at``. The insert is
``ON CONFLICT DO NOTHING`` on the opening unique key, so a second run does
not replace the first stored line.

The live writer is not used. Its conflict target is the live/closing tick,
and its ``snapshot_at`` is the job time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import asyncpg

from app.backfill.raw_cache import RawCache
from app.backfill.walker import Shard
from app.backfill.writer import BackfillPageError, PageWrite, _move_checkpoint, season_label
from app.dsn import redact_secrets
from app.services.bdl_props_adapter import PAIRED_VENDORS, PROP_TYPE_TO_MARKET, BdlPropsAdapter
from app.services.odds_snapshot_service import (
    _live_prop_args,
    _optional_decimal,
    _optional_int,
    _parse_commence,
)

logger = logging.getLogger(__name__)

DATA_ODDS = "opening_odds"
DATA_PROPS = "opening_props"

# BDL opening odds begin in December 2020. Earlier dates are not requested.
ODDS_NOT_BEFORE = date(2020, 12, 1)
# Opening props in the recorded bodies start in 2024-25. Earlier seasons are empty.
PROPS_FROM_SEASON = 2024

# Defaults when the command names no season. 2026-27 is left out; pass 2026 to walk it.
ODDS_DEFAULT_FIRST = 2020
ODDS_DEFAULT_LAST = 2025
PROPS_DEFAULT_FIRST = 2024
PROPS_DEFAULT_LAST = 2025

_FINAL_SEASON_TYPES = ("regular_season", "playoffs", "play_in", "cup_championship")
_MARKET_TO_PROP = {market: prop_type for prop_type, market in PROP_TYPE_TO_MARKET.items()}
_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ERROR_TEXT_LIMIT = 500
_BUCKETS = ("NULL", "< T", "= T", "T..tip", "= tip", "> tip")

_WORKLIST = """
SELECT bdl_game_id, season, date, datetime_utc
FROM games
WHERE league = $1
  AND season = $2
  AND status_state = 'final'
  AND season_type = ANY($3::text[])
  AND ($4::date IS NULL OR date >= $4::date)
  AND ($5::int IS NULL OR season >= $5)
ORDER BY date, bdl_game_id
"""
_BOOKS = "SELECT book_key FROM books WHERE league = $1"
_PRESENT_GAMES = """
SELECT bdl_game_id FROM games
WHERE league = $1 AND bdl_game_id = ANY($2::bigint[])
"""
_PRESENT_PLAYERS = """
SELECT bdl_player_id FROM players
WHERE league = $1 AND bdl_player_id = ANY($2::int[])
"""
_INSERT_ODDS = """
INSERT INTO game_odds_snapshots (
    league, snapshot_kind, bdl_game_id, book_key, snapshot_at, source_updated_at,
    spread_home_value, spread_home_odds, spread_away_value, spread_away_odds,
    moneyline_home_odds, moneyline_away_odds,
    total_value, total_over_odds, total_under_odds
) VALUES (
    $1, 'opening', $2, $3, $4, NULL,
    $5, $6, $7, $8,
    $9, $10,
    $11, $12, $13
)
ON CONFLICT (league, bdl_game_id, book_key) WHERE snapshot_kind = 'opening'
DO NOTHING
"""
_INSERT_PROPS = """
INSERT INTO player_prop_snapshots (
    league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
    line, over_odds, under_odds, milestone_odds, snapshot_at, source_updated_at
) VALUES (
    $1, 'opening', $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11, NULL
)
ON CONFLICT (league, bdl_game_id, bdl_player_id, book_key, market)
    WHERE snapshot_kind = 'opening'
DO NOTHING
"""
_COUNT_ODDS = """
SELECT count(*) FROM game_odds_snapshots o
JOIN games g ON g.league = o.league AND g.bdl_game_id = o.bdl_game_id
WHERE o.league = $1 AND o.snapshot_kind = 'opening' AND g.season = $2 AND g.date = $3
"""
_COUNT_PROPS = """
SELECT count(*) FROM player_prop_snapshots
WHERE league = $1 AND snapshot_kind = 'opening' AND bdl_game_id = $2
"""
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
_RESET = """
DELETE FROM bdl_backfill_checkpoints
WHERE league = $1 AND data_type = $2 AND season = $3
"""
_CHECKPOINTS = """
SELECT shard_key, cursor, pages_fetched
FROM bdl_backfill_checkpoints
WHERE league = $1 AND data_type = $2 AND season = $3
"""
_MARK_DONE = """
UPDATE bdl_backfill_checkpoints
SET status = 'done', last_error = NULL, updated_at = now()
WHERE league = $1 AND data_type = $2 AND season = $3
"""
_MARK_FAILED = """
UPDATE bdl_backfill_checkpoints
SET status = 'error', last_error = $5, updated_at = now()
WHERE league = $1 AND data_type = $2 AND season = $3 AND shard_key = $4
"""
_COVERAGE_ODDS = """
SELECT count(*) AS final_games,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM game_odds_snapshots o
           WHERE o.league = g.league AND o.bdl_game_id = g.bdl_game_id
             AND o.snapshot_kind = 'opening'
       )) AS games_with_odds
FROM games g
WHERE g.league = $1 AND g.season = $2 AND g.status_state = 'final'
"""
_COVERAGE_PROPS = """
SELECT count(*) AS player_games,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM player_prop_snapshots p
           WHERE p.league = s.league AND p.bdl_game_id = s.bdl_game_id
             AND p.bdl_player_id = s.bdl_player_id AND p.snapshot_kind = 'opening'
       )) AS with_props
FROM player_game_stats s
WHERE s.league = $1 AND s.season = $2 AND NOT s.dnp
"""
_BUCKETS_SQL = """
SELECT
    count(*) FILTER (WHERE snapshot_at IS NULL OR tip IS NULL) AS null_ts,
    count(*) FILTER (WHERE tip IS NOT NULL AND snapshot_at < tip - interval '3 hours') AS before_t,
    count(*) FILTER (WHERE tip IS NOT NULL AND snapshot_at = tip - interval '3 hours') AS at_t,
    count(*) FILTER (
        WHERE tip IS NOT NULL AND snapshot_at > tip - interval '3 hours' AND snapshot_at < tip
    ) AS t_to_tip,
    count(*) FILTER (WHERE tip IS NOT NULL AND snapshot_at = tip) AS at_tip,
    count(*) FILTER (WHERE tip IS NOT NULL AND snapshot_at > tip) AS after_tip
FROM (
    SELECT o.snapshot_at, g.datetime_utc AS tip
    FROM game_odds_snapshots o
    JOIN games g ON g.league = o.league AND g.bdl_game_id = o.bdl_game_id
    WHERE o.league = $1 AND o.snapshot_kind = 'opening' AND g.season = $2 AND $3 = 'opening_odds'
    UNION ALL
    SELECT p.snapshot_at, g.datetime_utc
    FROM player_prop_snapshots p
    JOIN games g ON g.league = p.league AND g.bdl_game_id = p.bdl_game_id
    WHERE p.league = $1 AND p.snapshot_kind = 'opening' AND g.season = $2 AND $3 = 'opening_props'
) lines
"""


@dataclass
class SkipCounts:
    """Rows that were not inserted, by the reason the report prints."""

    unknown_book: int = 0
    unknown_prop_type: int = 0
    missing_game: int = 0
    missing_player: int = 0

    @property
    def dropped(self) -> int:
        """Rows the checkpoint stores as dropped: unknown book or prop type."""
        return self.unknown_book + self.unknown_prop_type

    @property
    def rejected(self) -> int:
        """Rows the checkpoint stores as rejected: no game or player parent."""
        return self.missing_game + self.missing_player

    def add(self, other: SkipCounts) -> None:
        self.unknown_book += other.unknown_book
        self.unknown_prop_type += other.unknown_prop_type
        self.missing_game += other.missing_game
        self.missing_player += other.missing_player


@dataclass(frozen=True)
class PageResult:
    """One page after the insert.

    ``written`` is rows this call inserted. A replay is 0 because the
    conflict clause does nothing.
    """

    written: int
    skips: SkipCounts
    stored: int


@dataclass(frozen=True)
class WorkGame:
    """One final game the work list will shard."""

    bdl_game_id: int
    season: int
    game_date: date
    tip: datetime | None


@dataclass(frozen=True)
class OpeningShard:
    """One checkpoint: a date for odds, or one game for props."""

    data_type: str
    season: int
    shard_key: str
    game_ids: tuple[int, ...]
    game_date: date | None = None


@dataclass(frozen=True)
class OpeningReport:
    """The end-of-run line for one season."""

    season: int
    data_type: str
    current: bool
    written: int
    skips: SkipCounts
    final_games: int
    games_with_odds: int
    player_games: int
    player_games_with_props: int
    odds_buckets: Mapping[str, int]
    prop_buckets: Mapping[str, int]
    problems: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class OpeningPreview:
    """What a dry run would insert. Nothing was written."""

    season: int
    data_type: str
    would_write: int
    skips: SkipCounts


def default_seasons(data_type: str) -> list[int]:
    """Start years used when the command names no season.

    Odds: 2020-21 through 2025-26. Props: 2024-25 through 2025-26.
    2026 is not included. Pass that year on the command line to walk it.
    """
    if data_type == DATA_ODDS:
        return list(range(ODDS_DEFAULT_FIRST, ODDS_DEFAULT_LAST + 1))
    if data_type == DATA_PROPS:
        return list(range(PROPS_DEFAULT_FIRST, PROPS_DEFAULT_LAST + 1))
    raise ValueError(f"unknown backfill data {data_type!r}")


def prepare_game_odds(
    rows: Sequence[Mapping[str, Any]],
    *,
    league: str,
    game_ids: set[int],
    book_keys: set[str],
) -> tuple[list[tuple[Any, ...]], SkipCounts]:
    """One opening odds tuple per game and book, plus the skips.

    ``snapshot_at`` is ``opened_at`` parsed as UTC. A missing timestamp is
    stored as null, which the opening check allows. The first row wins when
    the same game and book appear twice on a page.
    """
    skips = SkipCounts()
    kept: list[tuple[Any, ...]] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        vendor = row.get("vendor")
        game_id = row.get("game_id")
        # Unknown-book skip: vendors that are not in the books seed (polymarket, kalshi).
        if not isinstance(vendor, str) or vendor not in book_keys:
            skips.unknown_book += 1
            continue
        if not isinstance(game_id, int) or game_id not in game_ids:
            skips.missing_game += 1
            continue
        if (game_id, vendor) in seen:
            continue
        seen.add((game_id, vendor))
        kept.append(
            (
                league,
                game_id,
                vendor,
                _parse_commence(row.get("opened_at")),
                _optional_decimal(row.get("spread_home_value")),
                _optional_int(row.get("spread_home_odds")),
                _optional_decimal(row.get("spread_away_value")),
                _optional_int(row.get("spread_away_odds")),
                _optional_int(row.get("moneyline_home_odds")),
                _optional_int(row.get("moneyline_away_odds")),
                _optional_decimal(row.get("total_value")),
                _optional_int(row.get("total_over_odds")),
                _optional_int(row.get("total_under_odds")),
            )
        )
    return kept, skips


def prepare_prop_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    league: str,
    game_ids: set[int],
    player_ids: set[int],
    book_keys: set[str],
) -> tuple[list[tuple[Any, ...]], SkipCounts]:
    """One main line per player, book, and market.

    The adapter and ``_live_prop_args`` pick the line. ``game_datetime`` is
    not passed: these rows have ``opened_at``, not ``updated_at``. A line
    whose ``opened_at`` is after tip is kept. The report warns about it.
    ``snapshot_at`` is that group's ``opened_at``. ``source_updated_at`` is
    not copied onto the tuple; the insert writes null.
    """
    skips = SkipCounts()
    kept_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        vendor = row.get("vendor")
        # Unknown-book skip, same rule as game odds.
        if not isinstance(vendor, str) or vendor not in book_keys:
            skips.unknown_book += 1
            continue
        prop_type = row.get("prop_type")
        if not isinstance(prop_type, str) or prop_type not in PROP_TYPE_TO_MARKET:
            skips.unknown_prop_type += 1
            continue
        kept_rows.append(row)

    by_game: dict[int, list[dict[str, Any]]] = {}
    for row in kept_rows:
        game_id = row.get("game_id")
        if isinstance(game_id, int):
            by_game.setdefault(game_id, []).append(row)

    tuples: list[tuple[Any, ...]] = []
    seen: set[tuple[int, int, str, str]] = set()
    for game_id, game_rows in by_game.items():
        names = {
            row["player_id"]: str(row["player_id"])
            for row in game_rows
            if isinstance(row.get("player_id"), int)
        }
        adapter = BdlPropsAdapter()
        books = adapter.to_bookmakers(game_rows, names)
        opened = _opened_index(game_rows)
        for raw in _live_prop_args(game_id, books, adapter.last_player_ids, _SENTINEL):
            player_id = raw[1]
            book_key = raw[2]
            market = raw[3]
            if not isinstance(player_id, int) or player_id not in player_ids:
                skips.missing_player += 1
                continue
            if game_id not in game_ids:
                skips.missing_game += 1
                continue
            identity = (game_id, player_id, book_key, market)
            if identity in seen:
                continue
            seen.add(identity)
            tuples.append(
                (
                    league,
                    game_id,
                    player_id,
                    book_key,
                    market,
                    raw[4],
                    raw[5],
                    raw[6],
                    raw[7],
                    raw[8],
                    _opened_at(opened, game_id, player_id, book_key, market),
                )
            )
    return tuples, skips


def _opened_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[int, int, str, str], datetime | None]:
    """``(game, player, vendor, prop_type)`` to the row's ``opened_at``."""
    found: dict[tuple[int, int, str, str], datetime | None] = {}
    for row in rows:
        game_id = row.get("game_id")
        player_id = row.get("player_id")
        vendor = row.get("vendor")
        prop_type = row.get("prop_type")
        if not isinstance(game_id, int) or not isinstance(player_id, int):
            continue
        if not isinstance(vendor, str) or not isinstance(prop_type, str):
            continue
        found[(game_id, player_id, vendor, prop_type)] = _parse_commence(row.get("opened_at"))
    return found


def _opened_at(
    index: Mapping[tuple[int, int, str, str], datetime | None],
    game_id: int,
    player_id: int,
    book_key: str,
    market: str,
) -> datetime | None:
    """The ``opened_at`` for the book that survived the adapter.

    BetParx and Bally Bet collapse to one book. Prefer the surviving key's
    own timestamp, then the other side of the pair.
    """
    prop_type = _MARKET_TO_PROP.get(market)
    if prop_type is None:
        return None
    vendors = (book_key,)
    if book_key in PAIRED_VENDORS:
        vendors = (book_key, *(name for name in ("betparx", "ballybet") if name != book_key))
    for vendor in vendors:
        key = (game_id, player_id, vendor, prop_type)
        if key in index:
            return index[key]
    return None


async def load_work_games(
    conn: asyncpg.Connection, *, league: str, season: int, data_type: str
) -> list[WorkGame]:
    """Final games for one season, after the odds date floor or the props season floor."""
    if data_type == DATA_ODDS:
        floor: date | None = ODDS_NOT_BEFORE
        minimum: int | None = None
    elif data_type == DATA_PROPS:
        floor = None
        minimum = PROPS_FROM_SEASON
    else:
        raise ValueError(f"unknown backfill data {data_type!r}")
    rows = await conn.fetch(_WORKLIST, league, season, list(_FINAL_SEASON_TYPES), floor, minimum)
    return [
        WorkGame(row["bdl_game_id"], row["season"], row["date"], row["datetime_utc"])
        for row in rows
    ]


def shards_for(data_type: str, season: int, games: Sequence[WorkGame]) -> list[OpeningShard]:
    """Odds: one shard per date. Props: one shard per game. Both in date order."""
    if data_type == DATA_ODDS:
        by_date: dict[date, list[int]] = {}
        for game in games:
            by_date.setdefault(game.game_date, []).append(game.bdl_game_id)
        return [
            OpeningShard(DATA_ODDS, season, day.isoformat(), tuple(ids), day)
            for day, ids in sorted(by_date.items())
        ]
    return [
        OpeningShard(DATA_PROPS, season, str(game.bdl_game_id), (game.bdl_game_id,), game.game_date)
        for game in games
    ]


async def write_opening_odds_page(
    conn: asyncpg.Connection,
    *,
    league: str,
    season: int,
    game_date: date,
    rows: Sequence[Mapping[str, Any]],
    next_cursor: int | None,
) -> PageResult:
    """Insert one opening-odds page and point the date's checkpoint past it."""
    game_ids = await _ids(conn, _PRESENT_GAMES, league, _int_ids(rows, "game_id"), "bdl_game_id")
    book_keys = await _book_keys(conn, league)
    prepared, skips = prepare_game_odds(rows, league=league, game_ids=game_ids, book_keys=book_keys)
    async with conn.transaction():
        before = await conn.fetchval(_COUNT_ODDS, league, season, game_date)
        if prepared:
            await conn.executemany(_INSERT_ODDS, prepared)
        stored = await conn.fetchval(_COUNT_ODDS, league, season, game_date)
        result = PageResult(written=stored - before, skips=skips, stored=stored)
        await _move_checkpoint(
            conn, league, DATA_ODDS, season, game_date.isoformat(), next_cursor, len(rows),
            PageWrite(written=result.written, shard_rows=stored, dropped=skips.dropped, rejected=skips.rejected),
        )
    return result


async def write_opening_props_page(
    conn: asyncpg.Connection,
    *,
    league: str,
    season: int,
    game_id: int,
    rows: Sequence[Mapping[str, Any]],
) -> PageResult:
    """Insert one game's opening props and mark that game's shard complete."""
    game_ids = await _ids(conn, _PRESENT_GAMES, league, [game_id], "bdl_game_id")
    player_ids = await _ids(conn, _PRESENT_PLAYERS, league, _int_ids(rows, "player_id"), "bdl_player_id")
    book_keys = await _book_keys(conn, league)
    prepared, skips = prepare_prop_rows(
        rows, league=league, game_ids=game_ids, player_ids=player_ids, book_keys=book_keys
    )
    async with conn.transaction():
        before = await conn.fetchval(_COUNT_PROPS, league, game_id)
        if prepared:
            await conn.executemany(_INSERT_PROPS, prepared)
        stored = await conn.fetchval(_COUNT_PROPS, league, game_id)
        result = PageResult(written=stored - before, skips=skips, stored=stored)
        await _move_checkpoint(
            conn, league, DATA_PROPS, season, str(game_id), None, len(rows),
            PageWrite(written=result.written, shard_rows=stored, dropped=skips.dropped, rejected=skips.rejected),
        )
    return result


async def run_opening(
    conn: asyncpg.Connection,
    client: Any,
    *,
    league: str,
    data_type: str,
    seasons: Sequence[int],
    restart: frozenset[int] | set[int],
    current: int,
    raw: RawCache | None = None,
    secrets: tuple[str, ...] = (),
) -> AsyncIterator[OpeningReport]:
    """Walk each season and yield its report.

    The current season, and any season in ``restart``, lose their checkpoints
    for this data type first. Stored odds and props stay. A failed page stops
    the run after the shard is marked ``error``.
    """
    for season in seasons:
        if season == current or season in restart:
            await conn.execute(_RESET, league, data_type, season)
        written, skips, shard_keys = await _walk_season(
            conn, client, league=league, data_type=data_type, season=season, raw=raw, secrets=secrets
        )
        report = await season_opening_report(
            conn, league=league, season=season, data_type=data_type, written=written, skips=skips,
            current=season == current, shard_keys=shard_keys,
        )
        if season != current:
            await _finish(conn, league, data_type, season, report.problems)
        yield report


async def preview_opening(
    conn: asyncpg.Connection,
    client: Any,
    *,
    league: str,
    data_type: str,
    seasons: Sequence[int],
    raw: RawCache | None = None,
) -> list[OpeningPreview]:
    """Fetch every shard from page one and insert nothing."""
    previews: list[OpeningPreview] = []
    for season in seasons:
        games = await load_work_games(conn, league=league, season=season, data_type=data_type)
        book_keys = await _book_keys(conn, league)
        would_write = 0
        skips = SkipCounts()
        for shard in shards_for(data_type, season, games):
            if data_type == DATA_ODDS:
                assert shard.game_date is not None
                async for _cursor, rows, _nxt in _iter_odds_pages(client, shard.game_date, None, raw, season):
                    page_rows, page_skips = await _prepare_odds(conn, league, rows, book_keys)
                    would_write += len(page_rows)
                    skips.add(page_skips)
            else:
                game_id = shard.game_ids[0]
                rows = await _fetch_props(client, game_id, raw, season)
                page_rows, page_skips = await _prepare_props(conn, league, game_id, rows, book_keys)
                would_write += len(page_rows)
                skips.add(page_skips)
        previews.append(OpeningPreview(season, data_type, would_write, skips))
    return previews


async def season_opening_report(
    conn: asyncpg.Connection,
    *,
    league: str,
    season: int,
    data_type: str,
    written: int,
    skips: SkipCounts,
    current: bool,
    shard_keys: Sequence[str],
) -> OpeningReport:
    """Coverage, buckets, and any shard that did not reach its last page."""
    odds = await conn.fetchrow(_COVERAGE_ODDS, league, season)
    props = await conn.fetchrow(_COVERAGE_PROPS, league, season)
    odds_buckets = await _buckets(conn, league, season, DATA_ODDS)
    prop_buckets = await _buckets(conn, league, season, DATA_PROPS)
    problems = await _unfinished(conn, league, data_type, season, shard_keys)
    return OpeningReport(
        season=season,
        data_type=data_type,
        current=current,
        written=written,
        skips=skips,
        final_games=odds["final_games"],
        games_with_odds=odds["games_with_odds"],
        player_games=props["player_games"],
        player_games_with_props=props["with_props"],
        odds_buckets=odds_buckets,
        prop_buckets=prop_buckets,
        problems=tuple(problems),
    )


def describe_opening(report: OpeningReport) -> str:
    """One season line: writes, skips, coverage, and ``snapshot_at`` buckets."""
    if not report.passed:
        state = "FAILED"
    elif report.current:
        state = "current season, not marked done"
    else:
        state = "done"
    parts = [
        f"{season_label(report.season)} {report.data_type} {state}",
        f"written {report.written}",
        (
            "skipped "
            f"unknown_book {report.skips.unknown_book}, "
            f"unknown_prop_type {report.skips.unknown_prop_type}, "
            f"missing_game {report.skips.missing_game}, "
            f"missing_player {report.skips.missing_player}"
        ),
        (
            "final games with odds "
            f"{_pct(report.games_with_odds, report.final_games)} "
            f"({report.games_with_odds}/{report.final_games})"
        ),
        (
            "non-DNP player-games with props "
            f"{_pct(report.player_games_with_props, report.player_games)} "
            f"({report.player_games_with_props}/{report.player_games})"
        ),
        f"odds buckets {_fmt_buckets(report.odds_buckets)}",
        f"props buckets {_fmt_buckets(report.prop_buckets)}",
    ]
    after_tip = report.odds_buckets.get("> tip", 0) + report.prop_buckets.get("> tip", 0)
    if after_tip:
        parts.append(f"warning: snapshot_at after tip on {after_tip} rows")
    parts.extend(report.problems)
    return " | ".join(parts)


def describe_preview(preview: OpeningPreview) -> str:
    """One dry-run line. ``would write`` is the row count a real run would insert into an empty table."""
    skips = preview.skips
    return (
        f"{season_label(preview.season)} {preview.data_type} dry run | "
        f"would write {preview.would_write} | "
        "skipped "
        f"unknown_book {skips.unknown_book}, "
        f"unknown_prop_type {skips.unknown_prop_type}, "
        f"missing_game {skips.missing_game}, "
        f"missing_player {skips.missing_player}"
    )


def _pct(part: int, whole: int) -> str:
    if whole == 0:
        return "n/a"
    return f"{(100.0 * part / whole):.1f}%"


def _fmt_buckets(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{name} {counts.get(name, 0)}" for name in _BUCKETS)


async def _buckets(
    conn: asyncpg.Connection, league: str, season: int, data_type: str
) -> dict[str, int]:
    row = await conn.fetchrow(_BUCKETS_SQL, league, season, data_type)
    return {
        "NULL": row["null_ts"],
        "< T": row["before_t"],
        "= T": row["at_t"],
        "T..tip": row["t_to_tip"],
        "= tip": row["at_tip"],
        "> tip": row["after_tip"],
    }


async def _unfinished(
    conn: asyncpg.Connection,
    league: str,
    data_type: str,
    season: int,
    shard_keys: Sequence[str],
) -> list[str]:
    stored = {
        row["shard_key"]: row
        for row in await conn.fetch(_CHECKPOINTS, league, data_type, season)
    }
    problems: list[str] = []
    for key in shard_keys:
        row = stored.get(key)
        if row is None or row["pages_fetched"] == 0:
            problems.append(f"{key}: no page stored")
        elif row["cursor"] is not None:
            problems.append(f"{key}: not walked to the end; the next page is cursor {row['cursor']}")
    return problems


async def _finish(
    conn: asyncpg.Connection,
    league: str,
    data_type: str,
    season: int,
    problems: Sequence[str],
) -> None:
    """Mark a past season done, or mark each unfinished shard error."""
    if not problems:
        await conn.execute(_MARK_DONE, league, data_type, season)
        logger.info("bdl_opening_season_done data_type=%s season=%s", data_type, season)
        return
    for problem in problems:
        key, _sep, message = problem.partition(": ")
        text = f"verification: {message}"[:_ERROR_TEXT_LIMIT]
        await conn.execute(_MARK_FAILED, league, data_type, season, key, text)
        logger.warning(
            "bdl_opening_season_failed data_type=%s season=%s shard=%s %s",
            data_type, season, key, text,
        )


async def _walk_season(
    conn: asyncpg.Connection,
    client: Any,
    *,
    league: str,
    data_type: str,
    season: int,
    raw: RawCache | None,
    secrets: tuple[str, ...],
) -> tuple[int, SkipCounts, list[str]]:
    games = await load_work_games(conn, league=league, season=season, data_type=data_type)
    book_keys = await _book_keys(conn, league)
    written = 0
    skips = SkipCounts()
    shard_keys: list[str] = []
    for shard in shards_for(data_type, season, games):
        shard_keys.append(shard.shard_key)
        try:
            page_written, page_skips = await _walk_shard(
                conn, client, league=league, shard=shard, book_keys=book_keys, raw=raw
            )
        except Exception as exc:
            message = redact_secrets(f"{type(exc).__name__}: {exc}", secrets)[:_ERROR_TEXT_LIMIT]
            await conn.execute(
                _MARK_ERROR, league, shard.data_type, shard.season, shard.shard_key, message
            )
            raise
        written += page_written
        skips.add(page_skips)
    return written, skips, shard_keys


async def _walk_shard(
    conn: asyncpg.Connection,
    client: Any,
    *,
    league: str,
    shard: OpeningShard,
    book_keys: set[str],
    raw: RawCache | None,
) -> tuple[int, SkipCounts]:
    state = await conn.fetchrow(
        _LOAD_CHECKPOINT, league, shard.data_type, shard.season, shard.shard_key
    )
    started = state is not None and state["pages_fetched"] > 0
    if started and state["cursor"] is None:
        logger.info(
            "bdl_opening_shard_skip data_type=%s season=%s shard=%s",
            shard.data_type, shard.season, shard.shard_key,
        )
        return 0, SkipCounts()
    cursor = int(state["cursor"]) if started and state["cursor"] is not None else None
    written = 0
    skips = SkipCounts()
    if shard.data_type == DATA_ODDS:
        assert shard.game_date is not None
        async for _asked, rows, nxt in _iter_odds_pages(client, shard.game_date, cursor, raw, shard.season):
            result = await write_opening_odds_page(
                conn, league=league, season=shard.season, game_date=shard.game_date,
                rows=rows, next_cursor=nxt,
            )
            written += result.written
            skips.add(result.skips)
            logger.info(
                "bdl_opening_page data_type=%s season=%s shard=%s fetched=%s written=%s",
                shard.data_type, shard.season, shard.shard_key, len(rows), result.written,
            )
        return written, skips

    game_id = shard.game_ids[0]
    rows = await _fetch_props(client, game_id, raw, shard.season)
    result = await write_opening_props_page(
        conn, league=league, season=shard.season, game_id=game_id, rows=rows
    )
    logger.info(
        "bdl_opening_page data_type=%s season=%s shard=%s fetched=%s written=%s",
        shard.data_type, shard.season, shard.shard_key, len(rows), result.written,
    )
    return result.written, result.skips


async def _iter_odds_pages(
    client: Any,
    game_date: date,
    cursor: int | None,
    raw: RawCache | None,
    season: int,
) -> AsyncIterator[tuple[int | None, list[dict[str, Any]], int | None]]:
    """Pages from ``cursor`` onward. An empty page stops, even with a next cursor."""
    shard = Shard(DATA_ODDS, season, game_date.isoformat())
    while True:
        response = await client.list_opening_odds(dates=[game_date.isoformat()], cursor=cursor)
        if raw is not None:
            raw.save(shard, cursor, response)
        rows = _data_rows(response, "opening odds")
        nxt = _next_cursor(response)
        if not rows:
            nxt = None
        yield cursor, rows, nxt
        if nxt is None:
            return
        cursor = nxt


async def _fetch_props(
    client: Any, game_id: int, raw: RawCache | None, season: int
) -> list[dict[str, Any]]:
    response = await client.get_opening_props(game_id=game_id)
    if raw is not None:
        raw.save(Shard(DATA_PROPS, season, str(game_id)), None, response)
    return _data_rows(response, "opening props")


def _data_rows(response: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise BackfillPageError(f"{label} page has no data list")
    return [row for row in response["data"] if isinstance(row, dict)]


def _next_cursor(response: dict[str, Any]) -> int | None:
    meta = response.get("meta")
    nxt = meta.get("next_cursor") if isinstance(meta, dict) else None
    if isinstance(nxt, bool) or not isinstance(nxt, int):
        return None
    return nxt


async def _prepare_odds(
    conn: asyncpg.Connection,
    league: str,
    rows: Sequence[Mapping[str, Any]],
    book_keys: set[str],
) -> tuple[list[tuple[Any, ...]], SkipCounts]:
    game_ids = await _ids(conn, _PRESENT_GAMES, league, _int_ids(rows, "game_id"), "bdl_game_id")
    return prepare_game_odds(rows, league=league, game_ids=game_ids, book_keys=book_keys)


async def _prepare_props(
    conn: asyncpg.Connection,
    league: str,
    game_id: int,
    rows: Sequence[Mapping[str, Any]],
    book_keys: set[str],
) -> tuple[list[tuple[Any, ...]], SkipCounts]:
    game_ids = await _ids(conn, _PRESENT_GAMES, league, [game_id], "bdl_game_id")
    player_ids = await _ids(conn, _PRESENT_PLAYERS, league, _int_ids(rows, "player_id"), "bdl_player_id")
    return prepare_prop_rows(
        rows, league=league, game_ids=game_ids, player_ids=player_ids, book_keys=book_keys
    )


def _int_ids(rows: Sequence[Mapping[str, Any]], field: str) -> list[int]:
    return sorted({row[field] for row in rows if isinstance(row, dict) and isinstance(row.get(field), int)})


async def _ids(conn: asyncpg.Connection, sql: str, league: str, values: list[int], column: str) -> set[int]:
    if not values:
        return set()
    found = await conn.fetch(sql, league, values)
    return {row[column] for row in found}


async def _book_keys(conn: asyncpg.Connection, league: str) -> set[str]:
    return {row["book_key"] for row in await conn.fetch(_BOOKS, league)}
