"""Load stored official injury-report PDFs into Postgres.

Run from the repository root::

    python -m backend.scripts.ingest_injury_reports
    python -m backend.scripts.ingest_injury_reports --dry-run

The cache directory is ``INJURY_PDF_DIR``. ``--dry-run`` parses and
prints counts. It does not insert. A PDF that will not parse is counted
as failed and the rest of the cache is still loaded. The database URL
is never printed. There is no HTTP route in this module.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.dsn import redact_secrets  # noqa: E402
from app.services.injury_report_ingest import ingest_store  # noqa: E402
from app.services.injury_report_store import LocalInjuryReportStore  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.ingest_injury_reports",
        description="Parse stored official injury-report PDFs into Postgres.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print counts; do not insert",
    )
    return parser


def _store() -> LocalInjuryReportStore:
    from app.settings import settings

    return LocalInjuryReportStore(Path(settings.injury_pdf_dir))


async def _run(*, dry_run: bool) -> int:
    import asyncpg

    from app.settings import settings

    dsn = settings.database_url
    try:
        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:
        password = urlsplit(dsn).password or ""
        print(redact_secrets(str(exc), (password,)), file=sys.stderr)
        return 1
    try:
        outcomes = await ingest_store(conn, _store(), dry_run=dry_run)
    finally:
        await conn.close()
    failed = 0
    for outcome in outcomes:
        if outcome.tag == "failed":
            failed += 1
        print(
            f"{outcome.tag} {outcome.filename} "
            f"rows_seen={outcome.rows_seen} rows_written={outcome.rows_written}"
        )
    print(f"reports {len(outcomes)} failed {failed}", file=sys.stderr)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and ingest the cache. Returns a process exit code.

    0 means every stored PDF parsed. 1 means the database connection
    failed or at least one PDF did not parse. ``--dry-run`` still
    returns 1 when a PDF does not parse, and it does not insert.
    """
    args = _parser().parse_args(argv)
    return asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
