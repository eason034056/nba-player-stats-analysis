"""
test_db.py - Unit tests for the DatabaseService (asyncpg pool wrapper)

Uses pytest + pytest-asyncio with a mock asyncpg pool/connection to avoid real
PostgreSQL connections.

Coverage:
1. is_connected returns False before init
2. execute delegates to pool
3. fetch delegates to pool
4. fetchrow delegates to pool
5. executemany delegates to pool
6. close sets pool to None
7. is_connected returns True when pool exists
8. execute/fetch/fetchrow/executemany raise RuntimeError when pool is None
9. init() success path (creates pool, runs schema)
10. init() failure path (sets pool to None)
"""

import pytest
import sys
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to Python path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import DatabaseService, SCHEMA_SQL


# ---------------------------------------------------------------------------
# Fake asyncpg connection and pool
# ---------------------------------------------------------------------------

class FakeConnection:
    """
    Mimics an asyncpg Connection with async methods.
    Records all calls for assertion.
    """

    def __init__(self):
        self.execute_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []
        self.executemany_calls: list[tuple] = []

        # Default return values - can be overridden per test
        self.execute_return = "INSERT 0 1"
        self.fetch_return = [{"id": 1, "name": "Curry"}]
        self.fetchrow_return = {"id": 1, "name": "Curry"}
        self.executemany_return = None

    async def execute(self, query, *args):
        self.execute_calls.append((query, *args))
        return self.execute_return

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, *args))
        return self.fetch_return

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, *args))
        return self.fetchrow_return

    async def executemany(self, query, args_list):
        self.executemany_calls.append((query, args_list))
        return self.executemany_return


class FakePool:
    """
    Mimics an asyncpg Pool whose acquire() returns a FakeConnection
    via an async context manager.
    """

    def __init__(self, connection: FakeConnection = None):
        self.connection = connection or FakeConnection()
        self.closed = False

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_conn():
    """A fresh FakeConnection."""
    return FakeConnection()


@pytest.fixture
def fake_pool(fake_conn):
    """A FakePool wired to fake_conn."""
    return FakePool(fake_conn)


@pytest.fixture
def db_service(fake_pool):
    """A DatabaseService with a pre-injected pool (bypasses init)."""
    svc = DatabaseService()
    svc._pool = fake_pool
    return svc


@pytest.fixture
def db_no_pool():
    """A DatabaseService with no pool (not initialized)."""
    return DatabaseService()


# ===========================================================================
# 1 & 7. is_connected property
# ===========================================================================

class TestIsConnected:
    """Tests for DatabaseService.is_connected property."""

    def test_is_connected_false_before_init(self, db_no_pool):
        """is_connected should be False when pool has not been created."""
        assert db_no_pool.is_connected is False

    def test_is_connected_true_when_pool_exists(self, db_service):
        """is_connected should be True when pool is set."""
        assert db_service.is_connected is True

    def test_is_connected_false_after_pool_reset(self):
        """is_connected should be False after pool is set back to None."""
        svc = DatabaseService()
        svc._pool = FakePool()
        assert svc.is_connected is True
        svc._pool = None
        assert svc.is_connected is False


# ===========================================================================
# 2. execute()
# ===========================================================================

class TestExecute:
    """Tests for DatabaseService.execute()."""

    @pytest.mark.asyncio
    async def test_execute_delegates_to_pool(self, db_service, fake_conn):
        """execute() should acquire a connection and call conn.execute()."""
        result = await db_service.execute(
            "INSERT INTO logs (date, status) VALUES ($1, $2)",
            "2026-02-08",
            "success",
        )
        assert result == "INSERT 0 1"
        assert len(fake_conn.execute_calls) == 1
        query, arg1, arg2 = fake_conn.execute_calls[0]
        assert "INSERT INTO logs" in query
        assert arg1 == "2026-02-08"
        assert arg2 == "success"

    @pytest.mark.asyncio
    async def test_execute_no_args(self, db_service, fake_conn):
        """execute() should work with no positional args."""
        await db_service.execute("DELETE FROM tmp")
        assert len(fake_conn.execute_calls) == 1
        assert fake_conn.execute_calls[0] == ("DELETE FROM tmp",)

    @pytest.mark.asyncio
    async def test_execute_raises_when_not_initialized(self, db_no_pool):
        """execute() should raise RuntimeError if pool is None."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db_no_pool.execute("SELECT 1")


# ===========================================================================
# 3. fetch()
# ===========================================================================

class TestFetch:
    """Tests for DatabaseService.fetch()."""

    @pytest.mark.asyncio
    async def test_fetch_delegates_to_pool(self, db_service, fake_conn):
        """fetch() should acquire a connection and call conn.fetch(), returning dicts."""
        # FakeConnection.fetch returns list of dicts already; real asyncpg returns Records.
        # The actual code does [dict(row) for row in rows], which works on dicts too.
        fake_conn.fetch_return = [
            {"id": 1, "player_name": "Curry"},
            {"id": 2, "player_name": "LeBron"},
        ]
        result = await db_service.fetch("SELECT * FROM player_projections WHERE date = $1", "2026-02-08")

        assert len(result) == 2
        assert result[0]["player_name"] == "Curry"
        assert result[1]["player_name"] == "LeBron"
        assert len(fake_conn.fetch_calls) == 1

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_list(self, db_service, fake_conn):
        """fetch() should return an empty list when no rows match."""
        fake_conn.fetch_return = []
        result = await db_service.fetch("SELECT * FROM t WHERE 1=0")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_raises_when_not_initialized(self, db_no_pool):
        """fetch() should raise RuntimeError if pool is None."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db_no_pool.fetch("SELECT 1")


# ===========================================================================
# 4. fetchrow()
# ===========================================================================

class TestFetchrow:
    """Tests for DatabaseService.fetchrow()."""

    @pytest.mark.asyncio
    async def test_fetchrow_delegates_to_pool(self, db_service, fake_conn):
        """fetchrow() should return a single dict row."""
        fake_conn.fetchrow_return = {"id": 42, "player_name": "Doncic"}
        result = await db_service.fetchrow(
            "SELECT * FROM player_projections WHERE id = $1", 42
        )
        assert result == {"id": 42, "player_name": "Doncic"}
        assert len(fake_conn.fetchrow_calls) == 1

    @pytest.mark.asyncio
    async def test_fetchrow_returns_none_when_no_match(self, db_service, fake_conn):
        """fetchrow() should return None when there is no matching row."""
        fake_conn.fetchrow_return = None
        result = await db_service.fetchrow("SELECT * FROM t WHERE id = $1", 999)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetchrow_raises_when_not_initialized(self, db_no_pool):
        """fetchrow() should raise RuntimeError if pool is None."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db_no_pool.fetchrow("SELECT 1")


# ===========================================================================
# 5. executemany()
# ===========================================================================

class TestExecutemany:
    """Tests for DatabaseService.executemany()."""

    @pytest.mark.asyncio
    async def test_executemany_delegates_to_pool(self, db_service, fake_conn):
        """executemany() should call conn.executemany with query and args_list."""
        args_list = [("a", 1), ("b", 2), ("c", 3)]
        await db_service.executemany(
            "INSERT INTO t (col1, col2) VALUES ($1, $2)",
            args_list,
        )
        assert len(fake_conn.executemany_calls) == 1
        query, passed_args = fake_conn.executemany_calls[0]
        assert "INSERT INTO t" in query
        assert passed_args == args_list

    @pytest.mark.asyncio
    async def test_executemany_with_empty_list(self, db_service, fake_conn):
        """executemany() should handle an empty args list gracefully."""
        await db_service.executemany("INSERT INTO t (col) VALUES ($1)", [])
        assert len(fake_conn.executemany_calls) == 1

    @pytest.mark.asyncio
    async def test_executemany_raises_when_not_initialized(self, db_no_pool):
        """executemany() should raise RuntimeError if pool is None."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db_no_pool.executemany("INSERT INTO t (c) VALUES ($1)", [("x",)])


# ===========================================================================
# 6. close()
# ===========================================================================

class TestClose:
    """Tests for DatabaseService.close()."""

    @pytest.mark.asyncio
    async def test_close_closes_pool_and_resets(self, db_service, fake_pool):
        """close() should call pool.close() and set _pool to None."""
        assert db_service.is_connected is True
        await db_service.close()
        assert fake_pool.closed is True
        assert db_service._pool is None
        assert db_service.is_connected is False

    @pytest.mark.asyncio
    async def test_close_noop_when_no_pool(self, db_no_pool):
        """close() should do nothing if pool is already None."""
        await db_no_pool.close()  # Should not raise
        assert db_no_pool._pool is None


# ===========================================================================
# 9. init() success path
# ===========================================================================

class TestInit:
    """Tests for DatabaseService.init()."""

    @pytest.mark.asyncio
    async def test_init_creates_pool_and_runs_schema(self, monkeypatch):
        """init() should create a pool and execute the schema SQL."""
        fake_conn = FakeConnection()
        fake_pool = FakePool(fake_conn)

        # Patch asyncpg.create_pool to return our fake pool
        import app.services.db as db_module

        async def mock_create_pool(**kwargs):
            return fake_pool

        monkeypatch.setattr(db_module.asyncpg, "create_pool", mock_create_pool)

        svc = DatabaseService()
        assert svc.is_connected is False

        await svc.init()

        assert svc.is_connected is True
        assert svc._pool is fake_pool
        # The schema SQL should have been executed
        assert len(fake_conn.execute_calls) == 1
        assert fake_conn.execute_calls[0][0] == SCHEMA_SQL

    @pytest.mark.asyncio
    async def test_init_sets_pool_none_on_failure(self, monkeypatch):
        """init() should catch exceptions and leave pool as None."""
        import app.services.db as db_module

        async def mock_create_pool(**kwargs):
            raise ConnectionRefusedError("Cannot connect to PostgreSQL")

        monkeypatch.setattr(db_module.asyncpg, "create_pool", mock_create_pool)

        svc = DatabaseService()
        await svc.init()  # Should not raise

        assert svc.is_connected is False
        assert svc._pool is None

    @pytest.mark.asyncio
    async def test_init_passes_correct_dsn_and_pool_sizes(self, monkeypatch):
        """init() should pass the correct DSN, min_size, and max_size."""
        import app.services.db as db_module

        captured_kwargs = {}

        async def mock_create_pool(**kwargs):
            captured_kwargs.update(kwargs)
            return FakePool()

        monkeypatch.setattr(db_module.asyncpg, "create_pool", mock_create_pool)

        svc = DatabaseService()
        await svc.init()

        assert "dsn" in captured_kwargs
        assert captured_kwargs["min_size"] == 2
        assert captured_kwargs["max_size"] == 10


# ===========================================================================
# Edge cases: query parameters are passed correctly
# ===========================================================================

class TestQueryParameterPassing:
    """Ensure *args are correctly forwarded to the underlying connection."""

    @pytest.mark.asyncio
    async def test_execute_multiple_args(self, db_service, fake_conn):
        """execute() should pass all positional args through to conn.execute()."""
        await db_service.execute("UPDATE t SET a=$1, b=$2, c=$3 WHERE id=$4", 1, 2, 3, 99)
        call = fake_conn.execute_calls[0]
        assert call == ("UPDATE t SET a=$1, b=$2, c=$3 WHERE id=$4", 1, 2, 3, 99)

    @pytest.mark.asyncio
    async def test_fetch_with_multiple_args(self, db_service, fake_conn):
        """fetch() should pass all positional args through to conn.fetch()."""
        fake_conn.fetch_return = []
        await db_service.fetch("SELECT * FROM t WHERE a=$1 AND b=$2", "x", "y")
        call = fake_conn.fetch_calls[0]
        assert call == ("SELECT * FROM t WHERE a=$1 AND b=$2", "x", "y")

    @pytest.mark.asyncio
    async def test_fetchrow_with_multiple_args(self, db_service, fake_conn):
        """fetchrow() should pass all positional args through to conn.fetchrow()."""
        fake_conn.fetchrow_return = None
        await db_service.fetchrow("SELECT * FROM t WHERE a=$1 AND b=$2", 10, 20)
        call = fake_conn.fetchrow_calls[0]
        assert call == ("SELECT * FROM t WHERE a=$1 AND b=$2", 10, 20)
