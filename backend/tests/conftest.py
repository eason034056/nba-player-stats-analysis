"""
conftest.py - scratch PostgreSQL databases for the SPO-138 schema tests.

The server is ``DATABASE_URL`` (the postgres:16 service in CI). A test that
asks for one of these fixtures skips when no server answers, like
``test_spo132c_migrate_verify.py``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

_CI_URL = "postgresql://novig:novig@localhost:5432/novig_nba"
# CI's workflow uses localhost. `postgres` is the compose service name.
_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


def _migration_target_host(url: str) -> str | None:
    """Return the host this URL would connect to.

    None means a unix socket: an empty host, or a host that is a filesystem
    path. A libpq ``host`` query parameter overrides the authority.
    """
    parts = urlsplit(url)
    from_query = parse_qs(parts.query, keep_blank_values=True).get("host")
    raw = from_query[0] if from_query is not None else parts.hostname
    if raw is None:
        return None
    host = unquote(raw).strip()
    if host == "":
        return None
    return host


def _is_local_test_database(url: str) -> bool:
    """True when pytest may migrate this URL without an explicit override."""
    host = _migration_target_host(url)
    if host is None or host.startswith("/"):
        return True
    return host.lower() in _LOCAL_DB_HOSTS


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip() or _CI_URL
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix):]
    return raw


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, ""))


@pytest.fixture(scope="session", autouse=True)
def apply_shipped_migrations() -> None:
    """Apply 001 and 002 to the database named by ``DATABASE_URL``.

    ``DatabaseService.init`` confirms ``schema_migrations`` is at head and
    does not run ``SCHEMA_SQL``. CI sets ``DATABASE_URL`` to the postgres
    service. Tests that open that database and read the legacy tables need
    the files applied first. Scratch databases stay empty. When
    ``DATABASE_URL`` is unset the fixture does nothing, and those tests skip.

    A non-local host is refused before any connection, unless
    ``ALLOW_REMOTE_TEST_DB=1``. The refusal names the host and not the URL.
    """
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return
    url = _admin_url()
    if os.environ.get("ALLOW_REMOTE_TEST_DB", "").strip() != "1":
        if not _is_local_test_database(url):
            host = _migration_target_host(url) or "unknown"
            pytest.skip(
                "refusing to migrate non-local database host "
                f"{host} during pytest; set ALLOW_REMOTE_TEST_DB=1 to override"
            )

    async def _run() -> None:
        from app.migrations.runner import upgrade

        conn = await asyncpg.connect(_admin_url(), timeout=10)
        try:
            await upgrade(conn)
        finally:
            await conn.close()

    asyncio.run(_run())


@pytest_asyncio.fixture
async def scratch_dsn() -> AsyncIterator[str]:
    """DSN of an empty database that is dropped after the test."""
    admin_url = _admin_url()
    try:
        admin = await asyncpg.connect(admin_url, timeout=5)
    except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
        pytest.skip("Postgres is not reachable")
    name = f"spo138_test_{uuid.uuid4().hex[:12]}"
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield _with_database(admin_url, name)
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()


@pytest_asyncio.fixture
async def scratch_conn(scratch_dsn: str) -> AsyncIterator[asyncpg.Connection]:
    """A connection to ``scratch_dsn``, closed before the database is dropped."""
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        yield conn
    finally:
        await conn.close()
