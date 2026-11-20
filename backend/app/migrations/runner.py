"""
runner.py - apply the numbered SQL files in this package to PostgreSQL.

A file is named ``NNN_description.sql`` and ``NNN`` is the version recorded in
``schema_migrations``. Each pending file runs in one transaction together with
the row that records it. A failure leaves neither the file's objects nor its
row behind, so the next run starts again at that file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent

_FILE_NAME = re.compile(r"(?P<version>\d{3})_[a-z0-9_]+\.sql")

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """The migration files cannot be put in one order."""


@dataclass(frozen=True)
class Migration:
    """One SQL file and the version it records."""

    version: str
    path: Path


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Return the ``.sql`` files in ``directory`` in version order.

    Raises:
        MigrationError: a ``.sql`` file is not named ``NNN_description.sql``,
            or two files share a version. The runner would otherwise skip a
            file or apply two files in an order nobody chose.
    """
    migrations: dict[str, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"{path.name} is not named NNN_description.sql")
        version = match["version"]
        if version in migrations:
            raise MigrationError(
                f"{migrations[version].path.name} and {path.name} share version {version}"
            )
        migrations[version] = Migration(version, path)
    return list(migrations.values())


async def upgrade(conn: asyncpg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every file whose version is not yet in ``schema_migrations``.

    Returns:
        The versions this call applied, in order. Empty when the schema is
        already at the newest file.

    Raises:
        MigrationError: from ``discover``, before any SQL runs.
        asyncpg.PostgresError: a file failed. Its transaction rolled back;
            the files before it stay applied.
    """
    migrations = discover(directory)
    await conn.execute(_BOOTSTRAP)
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    applied = {row["version"] for row in rows}

    newly_applied: list[str] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        async with conn.transaction():
            await conn.execute(migration.path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)", migration.version
            )
        newly_applied.append(migration.version)
    return newly_applied
