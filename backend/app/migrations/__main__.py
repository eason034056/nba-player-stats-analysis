"""
python -m app.migrations upgrade [--dsn-env NAME]

The DSN is read from the environment variable NAME (default ``DATABASE_URL``),
so the password is never on a command line or in shell history. Nothing this
command prints contains the DSN or its password.

Exit codes: 0 applied or already up to date, 1 the upgrade failed, 2 usage.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlsplit

import asyncpg

from app.dsn import redact_secrets
from app.migrations.runner import upgrade


async def _upgrade(dsn: str) -> list[str]:
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        return await upgrade(conn)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrations")
    parser.add_argument("command", choices=["upgrade"])
    parser.add_argument(
        "--dsn-env",
        default="DATABASE_URL",
        help="environment variable that holds the PostgreSQL DSN",
    )
    args = parser.parse_args(argv)

    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        parser.error(f"{args.dsn_env} is not set")

    try:
        applied = asyncio.run(_upgrade(dsn))
    except Exception as exc:  # noqa: BLE001 - the CLI boundary reports every failure the same way
        password = urlsplit(dsn).password or ""
        secrets = (password,) if len(password) >= 4 else ()
        message = redact_secrets(str(exc), secrets)
        print(f"upgrade failed: {type(exc).__name__}: {message}", file=sys.stderr)
        return 1

    for version in applied:
        print(f"applied {version}")
    if not applied:
        print("schema is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
