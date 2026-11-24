"""Fetch official NBA injury-report PDFs.

Run from the repository root::

    python -m backend.scripts.fetch_injury_reports backfill --season 2021-22
    python -m backend.scripts.fetch_injury_reports backfill --season 2021-22 --dry-run
    python -m backend.scripts.fetch_injury_reports current
    python -m backend.scripts.fetch_injury_reports current --dry-run

``backfill`` reads tip times from Postgres for that one season (2021-22 or
later), keeps one URL per shared tip, and fetches each URL once.
``current`` fetches the slot for now. ``current --dry-run`` prints that
one URL. It does not open a database connection and it does not open a
CDN socket. backfill --dry-run reads tip times from Postgres, because
those tips are what the URLs are built from, and then prints the URLs.
It does not open a CDN socket. ``--at`` sets the clock for ``current``
(an aware ISO timestamp). The database URL is never printed.

Seasons before 2021-22 are refused. There is no HTTP route in this module.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.dsn import redact_secrets  # noqa: E402
from app.services.injury_report_fetcher import (  # noqa: E402
    SystemClock,
    build_client,
    fetch_urls,
)
from app.services.injury_report_games import tip_times_for_season  # noqa: E402
from app.services.injury_report_slots import (  # noqa: E402
    parse_season_start_year,
    report_slot,
    slots_for_tips,
)
from app.services.injury_report_store import LocalInjuryReportStore  # noqa: E402


def _parse_moment(text: str | None) -> datetime:
    """Aware instant from ``--at``. None means the current UTC time."""
    if text is None:
        return datetime.now(timezone.utc)
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        raise ValueError("pass a timezone on --at, for example 2025-12-23T21:00:00Z")
    return moment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.fetch_injury_reports",
        description="Fetch official NBA injury-report PDFs into a private cache.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill", help="one season of tip-minus-3-hour reports")
    backfill.add_argument("--season", required=True, help="2021-22 or a later season")
    backfill.add_argument(
        "--dry-run",
        action="store_true",
        help="print URLs from Postgres tips; no CDN",
    )
    current = sub.add_parser("current", help="the report slot for now")
    current.add_argument(
        "--dry-run",
        action="store_true",
        help="print the URL; no database and no CDN",
    )
    current.add_argument("--at", default=None, help="aware ISO time instead of now")
    return parser


def _store() -> LocalInjuryReportStore:
    from app.settings import settings

    return LocalInjuryReportStore(Path(settings.injury_pdf_dir))


async def _load_tips(season_start_year: int) -> list[datetime]:
    import asyncpg

    from app.settings import settings

    dsn = settings.database_url
    try:
        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:
        password = urlsplit(dsn).password or ""
        print(redact_secrets(str(exc), (password,)), file=sys.stderr)
        raise
    try:
        return await tip_times_for_season(conn, season_start_year)
    finally:
        await conn.close()


async def _run_backfill(season_start_year: int, *, dry_run: bool) -> int:
    try:
        tips = await _load_tips(season_start_year)
    except Exception:
        return 1
    slots = slots_for_tips(tips)
    if dry_run:
        for slot in slots:
            print(slot.url)
        return 0
    clock = SystemClock()
    async with build_client() as client:
        report = await fetch_urls(
            [slot.url for slot in slots],
            store=_store(),
            clock=clock,
            client=client,
            recheck_missing=False,
        )
    print(f"requests {report.requests_made}", file=sys.stderr)
    return 1 if report.paused else 0


async def _run_current(moment: datetime, *, dry_run: bool) -> int:
    slot = report_slot(moment)
    if dry_run:
        print(slot.url)
        return 0
    clock = SystemClock()
    async with build_client() as client:
        report = await fetch_urls(
            [slot.url],
            store=_store(),
            clock=clock,
            client=client,
            recheck_missing=True,
        )
    print(f"requests {report.requests_made}", file=sys.stderr)
    return 1 if report.paused else 0


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and run one command. Returns a process exit code.

    0 means the run finished (a 403 recorded as missing is still 0).
    1 means the database read failed or the fetcher paused.
    2 means the arguments are wrong, including a season before 2021-22.
    """
    args = _parser().parse_args(argv)
    try:
        if args.command == "backfill":
            year = parse_season_start_year(args.season)
            return asyncio.run(_run_backfill(year, dry_run=args.dry_run))
        moment = _parse_moment(args.at)
        return asyncio.run(_run_current(moment, dry_run=args.dry_run))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
