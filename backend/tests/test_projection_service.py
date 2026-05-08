import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.projection_service import (
    ProjectionService,
    _build_projections_key,
    _build_projections_meta_key,
)
from app.services.projection_provider import SportsDataProjectionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fresh_meta():
    """Return meta dict with a freshly-fetched timestamp (not stale)."""
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "player_count": 2,
    }


def _stale_meta():
    """Return meta dict with a timestamp far in the past (stale)."""
    return {
        "fetched_at": "2020-01-01T00:00:00+00:00",
        "player_count": 2,
    }


def _sample_projections_dict():
    """Return a sample projections dict keyed by player name."""
    return {
        "Stephen Curry": {
            "player_name": "Stephen Curry",
            "team": "GS",
            "points": 29.3,
            "rebounds": 5.1,
            "assists": 6.2,
            "pra": 40.6,
        },
        "LeBron James": {
            "player_name": "LeBron James",
            "team": "LAL",
            "points": 27.0,
            "rebounds": 7.5,
            "assists": 7.8,
            "pra": 42.3,
        },
    }


def _sample_projections_list():
    """Return projections as a list (what the provider returns)."""
    return list(_sample_projections_dict().values())


@pytest.fixture
def service():
    """Create a ProjectionService with a short stale threshold for testing."""
    return ProjectionService(max_stale_minutes=120)


@pytest.fixture
def mock_cache(monkeypatch):
    """
    Replace cache_service.get / cache_service.set with controllable AsyncMocks.
    Returns a dict-backed fake that tests can configure.
    """
    store: Dict[str, Any] = {}

    async def _get(key):
        return store.get(key)

    async def _set(key, value, ttl=None):
        store[key] = value

    import app.services.projection_service as svc_module

    mock = MagicMock()
    mock.get = AsyncMock(side_effect=_get)
    mock.set = AsyncMock(side_effect=_set)
    monkeypatch.setattr(svc_module, "cache_service", mock)
    return store, mock


@pytest.fixture
def mock_db(monkeypatch):
    """
    Replace db_service with an AsyncMock.
    - is_connected defaults to True
    - fetch / execute / executemany are AsyncMocks
    """
    import app.services.projection_service as svc_module

    mock = MagicMock()
    mock.is_connected = True
    mock.fetch = AsyncMock(return_value=[])
    mock.execute = AsyncMock()
    mock.executemany = AsyncMock()
    monkeypatch.setattr(svc_module, "db_service", mock)
    return mock


@pytest.fixture
def mock_provider(monkeypatch):
    """
    Replace projection_provider with an AsyncMock.
    fetch_projections_by_date returns sample data by default.
    """
    import app.services.projection_service as svc_module

    mock = MagicMock()
    mock.fetch_projections_by_date = AsyncMock(return_value=_sample_projections_list())
    monkeypatch.setattr(svc_module, "projection_provider", mock)
    return mock


# =====================================================================
# Tests for get_projections
# =====================================================================


class TestGetProjections:
    @pytest.mark.asyncio
    async def test_returns_cached_data_on_redis_hit_fresh(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, cache_mock = mock_cache
        date = "2026-02-08"
        store[_build_projections_key(date)] = _sample_projections_dict()
        store[_build_projections_meta_key(date)] = _fresh_meta()

        result = await service.get_projections(date)

        assert "Stephen Curry" in result
        assert result["Stephen Curry"]["points"] == 29.3
        # Provider should NOT have been called
        mock_provider.fetch_projections_by_date.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_background_refresh_when_stale(
        self, service, mock_cache, mock_db, mock_provider, monkeypatch
    ):
        store, cache_mock = mock_cache
        date = "2026-02-08"
        store[_build_projections_key(date)] = _sample_projections_dict()
        store[_build_projections_meta_key(date)] = _stale_meta()

        # Capture whether _trigger_background_refresh was called
        triggered = []
        original = service._trigger_background_refresh

        def _spy(d):
            triggered.append(d)
            # Don't actually create a background task in tests
            pass

        monkeypatch.setattr(service, "_trigger_background_refresh", _spy)

        result = await service.get_projections(date)

        # Should still return the stale cached data immediately
        assert "Stephen Curry" in result
        # Background refresh should have been triggered
        assert triggered == [date]

    @pytest.mark.asyncio
    async def test_falls_back_to_postgres_on_redis_miss_and_api_error(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, _ = mock_cache
        date = "2026-02-08"
        # Cache is empty -- Redis miss

        # API call will fail
        mock_provider.fetch_projections_by_date = AsyncMock(
            side_effect=SportsDataProjectionError(500, "Server error")
        )

        # PostgreSQL has data
        pg_rows = [
            {"player_name": "Stephen Curry", "points": 28.0, "date": "2026-02-08"},
            {"player_name": "LeBron James", "points": 26.0, "date": "2026-02-08"},
        ]
        mock_db.fetch = AsyncMock(return_value=pg_rows)

        result = await service.get_projections(date)

        assert "Stephen Curry" in result
        assert result["Stephen Curry"]["points"] == 28.0

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_nothing_available(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, _ = mock_cache
        date = "2026-02-08"
        # Cache is empty

        # API call fails
        mock_provider.fetch_projections_by_date = AsyncMock(
            side_effect=SportsDataProjectionError(500, "Server error")
        )

        # PostgreSQL not connected
        mock_db.is_connected = False

        result = await service.get_projections(date)

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetches_synchronously_on_cache_miss(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, _ = mock_cache
        date = "2026-02-08"
        # Cache is empty -- will trigger synchronous fetch

        result = await service.get_projections(date)

        # Provider should have been called
        mock_provider.fetch_projections_by_date.assert_called_once_with(date)
        assert "Stephen Curry" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_unexpected_exception(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, _ = mock_cache
        date = "2026-02-08"

        # API call raises an unexpected (non-SportsData) error
        mock_provider.fetch_projections_by_date = AsyncMock(
            side_effect=RuntimeError("unexpected")
        )

        result = await service.get_projections(date)

        assert result == {}


# =====================================================================
# Tests for fetch_and_store
# =====================================================================


class TestFetchAndStore:
    @pytest.mark.asyncio
    async def test_fetches_and_writes_to_both_stores(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, cache_mock = mock_cache
        date = "2026-02-08"

        result = await service.fetch_and_store(date)

        # Verify provider was called
        mock_provider.fetch_projections_by_date.assert_called_once_with(date)

        # Verify result is dict keyed by player name
        assert "Stephen Curry" in result
        assert "LeBron James" in result

        # Verify Redis was written (cache_service.set called for data + meta)
        assert cache_mock.set.call_count >= 2

        # Verify PostgreSQL was written
        mock_db.executemany.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_provider_error(
        self, service, mock_cache, mock_db, mock_provider
    ):
        date = "2026-02-08"

        mock_provider.fetch_projections_by_date = AsyncMock(
            side_effect=SportsDataProjectionError(500, "API down")
        )

        with pytest.raises(SportsDataProjectionError) as exc_info:
            await service.fetch_and_store(date)

        assert exc_info.value.status_code == 500

        # Fetch log should still be written (in the finally block)
        # db_service.execute is called for the fetch log
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_wraps_unexpected_error_as_projection_error(
        self, service, mock_cache, mock_db, mock_provider
    ):
        date = "2026-02-08"

        mock_provider.fetch_projections_by_date = AsyncMock(
            side_effect=ValueError("bad data")
        )

        with pytest.raises(SportsDataProjectionError) as exc_info:
            await service.fetch_and_store(date)

        assert exc_info.value.status_code == 0
        assert "Unexpected error" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_postgres_write_failure_does_not_block(
        self, service, mock_cache, mock_db, mock_provider
    ):
        store, cache_mock = mock_cache
        date = "2026-02-08"

        # PostgreSQL write fails
        mock_db.executemany = AsyncMock(side_effect=Exception("DB write error"))

        # Should still succeed and return data
        result = await service.fetch_and_store(date)

        assert "Stephen Curry" in result
        # Redis was still written
        assert cache_mock.set.call_count >= 2

    @pytest.mark.asyncio
    async def test_logs_fetch_even_on_success(
        self, service, mock_cache, mock_db, mock_provider
    ):
        date = "2026-02-08"

        await service.fetch_and_store(date)

        # db_service.execute should have been called for the fetch log
        mock_db.execute.assert_called_once()
        # Verify the log status is "success"
        call_args = mock_db.execute.call_args
        # Positional args: (SQL, parsed_date, now, player_count, status, error_msg, duration_ms)
        # Index 4 is the status string
        assert call_args[0][4] == "success"


# =====================================================================
# Tests for get_historical_projections
# =====================================================================


class TestGetHistoricalProjections:
    @pytest.mark.asyncio
    async def test_returns_data_from_postgres(self, service, mock_db):
        rows = [
            {"player_name": "Stephen Curry", "date": "2026-02-07", "points": 30.0},
            {"player_name": "Stephen Curry", "date": "2026-02-06", "points": 28.5},
        ]
        mock_db.fetch = AsyncMock(return_value=rows)

        result = await service.get_historical_projections("Stephen Curry", n_days=7)

        assert len(result) == 2
        assert result[0]["points"] == 30.0
        mock_db.fetch.assert_called_once()
        # Verify correct args passed (player_name and n_days)
        call_args = mock_db.fetch.call_args
        assert call_args[0][1] == "Stephen Curry"
        assert call_args[0][2] == 7

    @pytest.mark.asyncio
    async def test_returns_empty_when_db_not_connected(self, service, mock_db):
        mock_db.is_connected = False

        result = await service.get_historical_projections("Stephen Curry")

        assert result == []
        # fetch should not have been called
        mock_db.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_on_db_error(self, service, mock_db):
        mock_db.fetch = AsyncMock(side_effect=Exception("DB connection lost"))

        result = await service.get_historical_projections("Stephen Curry")

        assert result == []

    @pytest.mark.asyncio
    async def test_default_n_days_is_30(self, service, mock_db):
        mock_db.fetch = AsyncMock(return_value=[])

        await service.get_historical_projections("Stephen Curry")

        call_args = mock_db.fetch.call_args
        assert call_args[0][2] == 30


# =====================================================================
# Tests for internal helper: _is_stale
# =====================================================================


class TestIsStale:
    def test_fresh_meta_is_not_stale(self):
        svc = ProjectionService(max_stale_minutes=120)
        assert svc._is_stale(_fresh_meta()) is False

    def test_old_meta_is_stale(self):
        svc = ProjectionService(max_stale_minutes=120)
        assert svc._is_stale(_stale_meta()) is True

    def test_missing_fetched_at_is_stale(self):
        svc = ProjectionService(max_stale_minutes=120)
        assert svc._is_stale({"player_count": 5}) is True

    def test_invalid_fetched_at_is_stale(self):
        svc = ProjectionService(max_stale_minutes=120)
        assert svc._is_stale({"fetched_at": "not-a-date"}) is True


# =====================================================================
# Tests for Redis key builders
# =====================================================================


class TestKeyBuilders:
    def test_build_projections_key(self):
        assert _build_projections_key("2026-02-08") == "projections:nba:2026-02-08"

    def test_build_projections_meta_key(self):
        assert (
            _build_projections_meta_key("2026-02-08")
            == "projections:nba:2026-02-08:meta"
        )
