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
from urllib.parse import parse_qs, urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

_CI_URL = "postgresql://novig:novig@localhost:5432/novig_nba"
# Case-insensitive. A comma-separated netloc host is local only when every
# entry matches. [::1] is compared as ::1.
# `postgres` is the Compose service name. Leftover risk: this does not resolve
# DNS, so that name can point at a remote address and still pass. CI's
# workflow uses localhost, not this name.
_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


def _host_key(host: str) -> str:
    """Fold case and strip a bracketed IPv6 form down to the address."""
    text = host.strip().lower()
    if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def _netloc_host_is_local(hostname: str) -> bool:
    """True when every comma-separated entry is on the allow-list."""
    parts = [part.strip() for part in hostname.split(",")]
    if not parts or any(part == "" for part in parts):
        return False
    return all(_host_key(part) in _LOCAL_DB_HOSTS for part in parts)


def _query_sets_host(url: str) -> bool:
    """True when the URL carries host= or hostaddr=.

    The values are not read. asyncpg ignores host= once the netloc has a
    host, and duplicate host= parameters are last-wins.
    """
    keys = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return "host" in keys or "hostaddr" in keys


def _named_env_host(name: str) -> str:
    """A PGHOST value safe to put in a refusal, or the variable name."""
    value = os.environ.get(name, "").strip()
    if value and "://" not in value and "@" not in value and " " not in value:
        return value
    return name


def _refusal_host(url: str) -> str:
    """Host text for a refusal. Never the URL."""
    hostname = urlsplit(url).hostname
    if hostname and not _netloc_host_is_local(hostname):
        return hostname
    for name in ("PGHOST", "PGHOSTADDR"):
        if name in os.environ:
            return _named_env_host(name)
    if _query_sets_host(url):
        return "query host parameter"
    return hostname or "unknown"


def _migration_refusal_host(url: str) -> str | None:
    """Return the host to name when this URL must not be migrated.

    None means the fixture may connect. ``ALLOW_REMOTE_TEST_DB=1`` is handled
    by the caller. A host-less URL with no host= and no PGHOST/PGHOSTADDR is
    a local unix socket.
    """
    if _query_sets_host(url):
        return _refusal_host(url)
    if "PGHOST" in os.environ or "PGHOSTADDR" in os.environ:
        return _refusal_host(url)
    hostname = urlsplit(url).hostname
    if hostname is None or hostname.strip() == "":
        return None
    if _netloc_host_is_local(hostname):
        return None
    return hostname


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
    Any ``host=`` or ``hostaddr=`` query parameter is refused, and so is a
    set ``PGHOST`` or ``PGHOSTADDR``. In CI the refusal fails the session.
    """
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return
    url = _admin_url()
    if os.environ.get("ALLOW_REMOTE_TEST_DB", "").strip() != "1":
        host = _migration_refusal_host(url)
        if host is not None:
            message = (
                "refusing to migrate non-local database host "
                f"{host} during pytest; set ALLOW_REMOTE_TEST_DB=1 to override"
            )
            ci = os.environ.get("CI")
            if ci is not None and ci.strip() != "" and ci.strip().lower() not in {"false", "0"}:
                pytest.fail(message)
            pytest.skip(message)

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
