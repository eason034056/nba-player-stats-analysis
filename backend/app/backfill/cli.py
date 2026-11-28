"""
cli.py - ``python -m app.backfill``: walk BALLDONTLIE seasons into the history tables.

    python -m app.backfill 2000 2025 --dsn-env NBA_HISTORY_DATABASE_URL
    python -m app.backfill 2000-2026 --dsn-env NBA_HISTORY_DATABASE_URL
    python -m app.backfill 2003 --restart-season 2003 --dsn-env NBA_HISTORY_DATABASE_URL
    python -m app.backfill 2025 --dry-run
    python -m app.backfill --data opening_odds --dsn-env NBA_HISTORY_DATABASE_URL
    python -m app.backfill 2024-2025 --data opening_props --dsn-env NBA_HISTORY_DATABASE_URL
    python -m app.backfill 2026 --data opening_odds --dsn-env NBA_HISTORY_DATABASE_URL

A season is its start year: 2025 is 2025-26. Each season is walked, resuming
from its checkpoints, and then verified. A past season that passes is marked
done and is not walked again. The current season is walked from page one on
every run, because its games are still being played, and is reported on but
never marked done. A failed check is printed and the run goes on to the next
season; a failed page stops the run, and the next run resumes at that page.

Every fetched page is kept gzipped under ``--raw-dir`` (``raw_cache.py``).
``--dry-run`` for games and stats reads every page from page one and prints
what it read, without a database: it needs no DSN and writes no checkpoint.
``--dry-run`` for opening odds or props reads the game list, fetches, and
prints the rows it would write. It writes no snapshot and no checkpoint.

``--data opening_odds`` defaults to 2020-21 through 2025-26 when no season
is given. ``--data opening_props`` defaults to 2024-25 through 2025-26.
Pass ``2026`` to include 2026-27. Games and stats still require a season.

The DSN comes from the variable ``--dsn-env`` names and the key from
``BALLDONTLIE_API_KEY``, so neither is on a command line; neither is printed.
Requests are capped at 500 a minute by an in-process limiter. The backend
stays stopped for the backfill, so no other process shares a Redis budget,
and the cap leaves the 600/min key's last 100 for callers outside this one.

Exit codes: 0 every season passed, 1 a check failed or the run stopped, 2 usage.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from collections.abc import AsyncIterator, Collection, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import fakeredis.aioredis

from app.backfill.opening import (
    describe_opening,
    describe_preview as describe_opening_preview,
    preview_opening,
    run_opening,
)
from app.backfill.raw_cache import RawCache
from app.backfill.verify import SeasonReport, finish_season, verify_season
from app.backfill.walker import ShardPreview, preview_season, walk_season
from app.backfill.writer import GAME_TYPE_BY_SEASON_TYPE, season_label
from app.dsn import redact_secrets
from app.services.bdl_client import BdlClient

_SEASONS = re.compile(r"(\d{4})(?:-(\d{4}))?")
_API_KEY_ENV = "BALLDONTLIE_API_KEY"
_REQUESTS_PER_MINUTE = 500
_RESET_SEASON = """
DELETE FROM bdl_backfill_checkpoints
WHERE league = $1 AND season = $2 AND data_type IN ('games', 'stats')
"""


@dataclass(frozen=True)
class SeasonOutcome:
    """One season's verification, and whether it was the current season (reported, not marked)."""

    season: int
    current: bool
    report: SeasonReport

    @property
    def passed(self) -> bool:
        return self.report.passed


def parse_seasons(tokens: Sequence[str]) -> list[int]:
    """Start years and inclusive ranges, sorted and without repeats.

    Raises:
        ValueError: a token is not ``YYYY`` or ``YYYY-YYYY`` with the first
            year not after the second. ``2000-01`` is a label, not a range.
    """
    seasons: set[int] = set()
    for token in tokens:
        match = _SEASONS.fullmatch(token)
        if match is None:
            raise ValueError(
                f"{token!r} is not a season: give its start year (2000 for 2000-01) or a range (2000-2026)"
            )
        first, last = int(match[1]), int(match[2] or match[1])
        if last < first:
            raise ValueError(f"{token!r} runs backwards")
        seasons.update(range(first, last + 1))
    return sorted(seasons)


def current_season(today: date) -> int:
    """The season whose games are still being played. The finals end in June."""
    return today.year if today.month >= 7 else today.year - 1


async def run_backfill(
    conn: asyncpg.Connection,
    client: BdlClient,
    *,
    league: str,
    seasons: Sequence[int],
    restart: Collection[int],
    current: int,
    raw: RawCache | None = None,
) -> AsyncIterator[SeasonOutcome]:
    """Walk and verify each season in order, yielding its outcome as it finishes.

    A season in ``restart``, and the current season, lose their games and
    stats checkpoints first, so they are walked from page one. Stored rows
    stay: every write is an upsert.

    Raises:
        Exception: whatever failed a page. The seasons after it are not walked.
    """
    for season in seasons:
        is_current = season == current
        if is_current or season in restart:
            await conn.execute(_RESET_SEASON, league, season)
        await walk_season(conn, client, league=league, season=season, raw=raw)
        if is_current:
            report = await verify_season(conn, league=league, season=season)
        else:
            report = await finish_season(conn, league=league, season=season)
        yield SeasonOutcome(season, is_current, report)


def describe(outcome: SeasonOutcome) -> str:
    """One summary line: the state, any failed check, and the counts to reconcile."""
    report = outcome.report
    if not report.passed:
        state = "FAILED"
    elif outcome.current:
        state = "current season, not marked done"
    else:
        state = "done"
    parts = [f"{season_label(outcome.season)} {state}"]
    parts += [f"{problem.shard.label}: {problem.message}" for problem in report.problems]
    games = ", ".join(
        f"{game_type} {report.games_by_type.get(game_type, 0)}" for game_type in GAME_TYPE_BY_SEASON_TYPE.values()
    )
    parts.append(f"games: {games}")
    parts.append(f"stats: {report.stat_rows} lines, {report.dnp_rows} dnp, {report.rejected_rows} rejected")
    parts.append(f"final games without stats: {len(report.final_games_without_stats)}")
    if report.stat_rows_per_final_game is not None:
        fewest, most = report.stat_rows_per_final_game
        parts.append(f"lines per final game: {fewest}-{most}")
    parts.append(f"points off the score: {len(report.final_games_points_off_score)} games")
    parts.append(f"under 230 minutes: {len(report.final_games_under_230_minutes)} games")
    return " | ".join(parts)


def describe_preview(season: int, previews: Sequence[ShardPreview]) -> str:
    """One dry-run line: pages and rows per shard, and the stats lines that would be refused."""
    parts = [f"{season_label(season)} dry run"]
    for preview in previews:
        part = f"{preview.shard.label}: {preview.pages} pages, {preview.rows} rows"
        if preview.shard.data_type == "stats":
            part += f", {preview.refused} refused"
        parts.append(part)
    return " | ".join(parts)


class _SecretFilter(logging.Filter):
    """Replace a DSN password and any extra secret before a log line is emitted."""

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage(), self._secrets)
        record.args = ()
        return True


def _install_secret_filter(redactor: _SecretFilter) -> None:
    """Attach the filter where records are actually formatted.

    A filter on the root logger is consulted only for records logged on
    that logger. Child loggers hand the record to the root handlers, so
    the filter has to sit on those handlers too.
    """
    root = logging.getLogger()
    root.addFilter(redactor)
    for handler in root.handlers:
        handler.addFilter(redactor)


def _remove_secret_filter(redactor: _SecretFilter) -> None:
    root = logging.getLogger()
    root.removeFilter(redactor)
    for handler in root.handlers:
        handler.removeFilter(redactor)


def _client(api_key: str) -> BdlClient:
    return BdlClient(
        api_key=api_key,
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        rate_limit_per_min=_REQUESTS_PER_MINUTE,
        rate_limit_ceiling=_REQUESTS_PER_MINUTE,
    )


async def _preview(api_key: str, *, league: str, seasons: Sequence[int], raw_dir: Path) -> None:
    client = _client(api_key)
    try:
        raw = RawCache(raw_dir, league)
        for season in seasons:
            print(describe_preview(season, await preview_season(client, season=season, raw=raw)), flush=True)
    finally:
        await client.aclose()


async def _preview_opening(
    dsn: str,
    api_key: str,
    *,
    league: str,
    data_type: str,
    seasons: Sequence[int],
    raw_dir: Path,
) -> None:
    """Read the game list and fetch. The session is read-only, so a write fails."""
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        await conn.execute("SET default_transaction_read_only = on")
        client = _client(api_key)
        try:
            previews = await preview_opening(
                conn, client, league=league, data_type=data_type, seasons=seasons,
                raw=RawCache(raw_dir, league),
            )
        finally:
            await client.aclose()
    finally:
        await conn.close()
    for preview in previews:
        print(describe_opening_preview(preview), flush=True)


async def _run_opening(
    dsn: str,
    api_key: str,
    *,
    league: str,
    data_type: str,
    seasons: Sequence[int],
    restart: Collection[int],
    current: int,
    raw_dir: Path,
    secrets: tuple[str, ...],
) -> bool:
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        client = _client(api_key)
        try:
            passed = True
            async for report in run_opening(
                conn, client, league=league, data_type=data_type, seasons=seasons,
                restart=frozenset(restart), current=current, raw=RawCache(raw_dir, league),
                secrets=secrets,
            ):
                print(describe_opening(report), flush=True)
                passed = passed and report.passed
            return passed
        finally:
            await client.aclose()
    finally:
        await conn.close()


async def _run(
    dsn: str,
    api_key: str,
    *,
    league: str,
    seasons: Sequence[int],
    restart: Collection[int],
    current: int,
    raw_dir: Path,
) -> bool:
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        client = _client(api_key)
        try:
            passed = True
            async for outcome in run_backfill(
                conn, client, league=league, seasons=seasons, restart=restart, current=current,
                raw=RawCache(raw_dir, league),
            ):
                print(describe(outcome), flush=True)
                passed = passed and outcome.passed
            return passed
        finally:
            await client.aclose()
    finally:
        await conn.close()


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.backfill", description="Walk BALLDONTLIE seasons into the history tables."
    )
    parser.add_argument(
        "seasons", nargs="*", metavar="SEASON",
        help="a start year (2025 is 2025-26) or a range (2000-2026); opening commands have a default",
    )
    parser.add_argument(
        "--data",
        choices=["games_stats", "opening_odds", "opening_props"],
        default="games_stats",
        help="games_stats, opening_odds (default 2020-2025), or opening_props (default 2024-2025)",
    )
    parser.add_argument(
        "--restart-season", type=int, action="append", default=[], metavar="SEASON",
        help="walk this season again from page one (repeatable)",
    )
    parser.add_argument("--league", choices=["nba"], default="nba")
    parser.add_argument(
        "--dsn-env", default="DATABASE_URL", help="environment variable that holds the PostgreSQL DSN"
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("bdl-raw"), help="where fetched pages are kept (git-ignored)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="read every page and print counts; no database is used"
    )
    parser.add_argument("--verbose", action="store_true", help="log every page")
    args = parser.parse_args(argv)

    try:
        seasons = parse_seasons(args.seasons)
    except ValueError as exc:
        parser.error(str(exc))
    if args.data == "games_stats":
        if not seasons and not args.restart_season:
            parser.error("give a season: a start year (2025 is 2025-26) or a range (2000-2026)")
    elif not seasons and not args.restart_season:
        from app.backfill.opening import default_seasons

        seasons = default_seasons(args.data)
    seasons = sorted(set(seasons) | set(args.restart_season))
    current = current_season(today or date.today())
    later = [season for season in seasons if season > current]
    if later:
        parser.error(f"season {later[0]} has not started; the current season is {current}")
    dsn = os.environ.get(args.dsn_env, "").strip()
    opening = args.data != "games_stats"
    if not dsn and (opening or not args.dry_run):
        parser.error(f"{args.dsn_env} is not set")
    api_key = os.environ.get(_API_KEY_ENV, "").strip()
    if not api_key:
        parser.error(f"{_API_KEY_ENV} is not set")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    secrets = tuple(value for value in (urlsplit(dsn).password or "", api_key) if len(value) >= 4)
    redactor = _SecretFilter(secrets)
    _install_secret_filter(redactor)
    try:
        if args.data == "games_stats" and args.dry_run:
            asyncio.run(_preview(api_key, league=args.league, seasons=seasons, raw_dir=args.raw_dir))
            return 0
        if args.data == "games_stats":
            passed = asyncio.run(_run(
                dsn, api_key, league=args.league, seasons=seasons,
                restart=frozenset(args.restart_season), current=current, raw_dir=args.raw_dir,
            ))
        elif args.dry_run:
            asyncio.run(_preview_opening(
                dsn, api_key, league=args.league, data_type=args.data, seasons=seasons,
                raw_dir=args.raw_dir,
            ))
            return 0
        else:
            passed = asyncio.run(_run_opening(
                dsn, api_key, league=args.league, data_type=args.data, seasons=seasons,
                restart=frozenset(args.restart_season), current=current, raw_dir=args.raw_dir,
                secrets=secrets,
            ))
    except Exception as exc:  # noqa: BLE001 - the CLI boundary reports every failure the same way
        print(f"backfill stopped: {type(exc).__name__}: {redact_secrets(str(exc), secrets)}", file=sys.stderr)
        return 1
    finally:
        _remove_secret_filter(redactor)
    return 0 if passed else 1
