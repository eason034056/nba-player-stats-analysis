"""
test_migration_001_baseline.py - 001_baseline.sql is SCHEMA_SQL.

001 is the text of ``SCHEMA_SQL`` in ``app/services/db.py``. Applied to an
empty database, it produces the same schema. Applied to a database that
already ran ``SCHEMA_SQL``, it changes nothing: the statements are
``IF NOT EXISTS`` or guarded ALTERs, which is what RDS already runs on boot.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from app.services.db import SCHEMA_SQL

BACKEND = Path(__file__).resolve().parents[1]
BASELINE = BACKEND / "app" / "migrations" / "001_baseline.sql"
_MARKER = "-- One lock for this whole script."


def _baseline_body() -> str:
    text = BASELINE.read_text(encoding="utf-8")
    start = text.index(_MARKER)
    return text[start:]


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip() or "postgresql://novig:novig@localhost:5432/novig_nba"
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix):]
    return raw


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, ""))


def test_baseline_text_is_schema_sql() -> None:
    assert _baseline_body() == SCHEMA_SQL.strip() + "\n"


_PG_ATTVER_LINE = re.compile(r"ALTER TABLE .* SET \(pg_attver=\d+\);")


def _normalize_dump(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.startswith("\\"):
            continue
        if stripped.startswith("SET ") or stripped.startswith("SELECT pg_catalog.set_config"):
            continue
        # pg_dump emits a per-database attribute version. Two databases built
        # with the same statements get different numbers, so it is not schema.
        if _PG_ATTVER_LINE.fullmatch(stripped):
            continue
        kept.append(stripped)
    return "\n".join(kept) + "\n"


def _pg_dump(dsn: str) -> str:
    result = subprocess.run(
        [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            dsn,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    password = urlsplit(dsn).password or ""
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).replace(password, "***")
        raise AssertionError(detail)
    return _normalize_dump(result.stdout)


async def _catalog(conn: asyncpg.Connection) -> tuple[list[tuple], list[tuple], list[tuple]]:
    columns = await conn.fetch(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    )
    constraints = await conn.fetch(
        """
        SELECT conrelid::regclass::text AS table_name, conname, pg_get_constraintdef(oid) AS def
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
        ORDER BY 1, 2
        """
    )
    indexes = await conn.fetch(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY 1, 2
        """
    )
    return (
        [tuple(row) for row in columns],
        [tuple(row) for row in constraints],
        [tuple(row) for row in indexes],
    )


async def _signature(dsn: str) -> object:
    if shutil.which("pg_dump"):
        return _pg_dump(dsn)
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        return await _catalog(conn)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_empty_database_baseline_matches_schema_sql(scratch_dsn: str) -> None:
    """001 on an empty database matches executing SCHEMA_SQL on another."""
    parts = urlsplit(scratch_dsn)
    sibling = (parts.path.lstrip("/") or "db") + "_schema"
    other = urlunsplit((parts.scheme, parts.netloc, f"/{sibling}", parts.query, ""))
    admin = await asyncpg.connect(_admin_url(), timeout=5)
    await admin.execute(f'CREATE DATABASE "{sibling}"')
    baseline = await asyncpg.connect(scratch_dsn, timeout=5)
    schema = await asyncpg.connect(other, timeout=5)
    try:
        await baseline.execute(BASELINE.read_text(encoding="utf-8"))
        await schema.execute(SCHEMA_SQL)
        assert await _signature(scratch_dsn) == await _signature(other)
        if shutil.which("pg_dump"):
            left = await asyncpg.connect(scratch_dsn, timeout=5)
            right = await asyncpg.connect(other, timeout=5)
            try:
                assert await _catalog(left) == await _catalog(right)
            finally:
                await left.close()
                await right.close()
    finally:
        await baseline.close()
        await schema.close()
        await admin.execute(f'DROP DATABASE "{sibling}" WITH (FORCE)')
        await admin.close()


@pytest.mark.asyncio
async def test_baseline_is_a_no_op_on_a_schema_sql_database(scratch_dsn: str) -> None:
    """The file is what RDS already ran. Applying it again does not change the schema."""
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        await conn.execute(SCHEMA_SQL)
        before = await _catalog(conn)
        before_dump = _pg_dump(scratch_dsn) if shutil.which("pg_dump") else None
        await conn.execute(BASELINE.read_text(encoding="utf-8"))
        after = await _catalog(conn)
    finally:
        await conn.close()
    assert before == after
    if before_dump is not None:
        assert before_dump == _pg_dump(scratch_dsn)


@pytest.mark.asyncio
async def test_line_stays_nullable_and_in_the_legacy_unique_key(scratch_dsn: str) -> None:
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        await conn.execute(BASELINE.read_text(encoding="utf-8"))
        nullable = await conn.fetchval(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'odds_line_snapshots'
              AND column_name = 'line'
            """
        )
        definition = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'public.odds_line_snapshots'::regclass
              AND conname = 'odds_line_snapshots_book_line_key'
            """
        )
    finally:
        await conn.close()
    assert nullable == "YES"
    assert definition is not None
    assert "line" in definition


@pytest.mark.asyncio
async def test_upgrade_after_schema_sql_then_again_is_a_no_op(scratch_dsn: str) -> None:
    """An existing six-table database takes 001 as a no-op, then 002 and 004, then nothing."""
    from app.migrations.runner import upgrade

    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        await conn.execute(SCHEMA_SQL)
        before = await _catalog(conn)
        assert await upgrade(conn) == ["001", "002", "004"]
        legacy = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'odds_line_snapshots'
            ORDER BY ordinal_position
            """
        )
        before_line = [row for row in before[0] if row[0] == "odds_line_snapshots"]
        assert [tuple(row) for row in legacy] == [
            (column, data_type, nullable)
            for _table, column, data_type, nullable, _default in before_line
        ]
        assert await upgrade(conn) == []
        versions = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
    finally:
        await conn.close()
    assert [row["version"] for row in versions] == ["001", "002", "004"]


@pytest.mark.asyncio
async def test_init_does_not_create_tables_on_an_empty_database(
    scratch_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.db as db_module

    monkeypatch.setattr(db_module.settings, "database_url", scratch_dsn)
    service = db_module.DatabaseService()
    with pytest.raises(db_module.SchemaNotAtHead):
        await service.init()
    assert service.is_connected is False
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        assert await conn.fetchval("SELECT to_regclass('public.odds_line_snapshots')") is None
        assert await conn.fetchval("SELECT to_regclass('public.schema_migrations')") is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_init_connects_when_migrations_are_at_head(
    scratch_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.migrations.runner import upgrade

    import app.services.db as db_module

    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        await upgrade(conn)
    finally:
        await conn.close()
    monkeypatch.setattr(db_module.settings, "database_url", scratch_dsn)
    service = db_module.DatabaseService()
    try:
        await service.init()
        assert service.is_connected is True
        row = await service.fetchrow("SELECT to_regclass('public.odds_line_snapshots') AS name")
    finally:
        await service.close()
    assert row is not None
    assert row["name"] == "odds_line_snapshots"
