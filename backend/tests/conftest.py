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
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

_CI_URL = "postgresql://novig:novig@localhost:5432/novig_nba"


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip() or _CI_URL
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix):]
    return raw


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, ""))


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
