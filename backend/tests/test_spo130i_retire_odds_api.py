"""Guard and one-time cache flush after NBA odds moved to BALLDONTLIE.

The retired module name is built from pieces so this file does not name it.
"""

from __future__ import annotations

import ast
import importlib
import logging
import sys
from pathlib import Path

import pytest

RETIRED_MODULE = "app.services." + "odds_" + "the" + "oddsapi"
RETIRED_CLASS = "The" + "Odds" + "API" + "Provider"
APP_ROOT = Path(__file__).resolve().parents[1] / "app"
SURFACES = (
    "app.api.nba",
    "app.api.metrics",
    "app.main",
    "app.services.daily_analysis",
    "app.services.odds_snapshot_service",
    "app.services.odds_gateway",
    "app.services.scheduler",
    "app.services.odds_cache_flush",
)


def test_nba_provider_is_balldontlie() -> None:
    """Every NBA route, job, and service import leaves the registry on BALLDONTLIE."""
    for name in SURFACES:
        importlib.import_module(name)
    from app.services.odds_gateway import PROVIDERS

    assert PROVIDERS["nba"].name == "balldontlie"
    assert RETIRED_MODULE not in sys.modules


def test_app_source_does_not_import_the_retired_module() -> None:
    """No file under backend/app imports the retired odds client."""
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append(node.module)
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name in {RETIRED_MODULE, RETIRED_CLASS} or RETIRED_MODULE in name:
                    offenders.append(f"{path.name}:{name}")
    assert offenders == []


class _Cache:
    """Small stand-in whose ``get_client`` returns one Redis client."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def get_client(self) -> object:
        return self._client


class _Down:
    """A cache whose client cannot be opened."""

    async def get_client(self) -> object:
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_flush_deletes_matching_keys_once_and_keeps_the_rest() -> None:
    """Matching keys go away. Other keys stay. A second run deletes nothing."""
    import fakeredis.aioredis

    from app.services.odds_cache_flush import SPO130I_FLUSH_MARKER, flush_retired_odds_cache

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        await client.set("daily_picks:nba:v2:x", "1")
        await client.set("odds_snapshot:v2:old", "1")
        await client.set("odds_snapshot_meta:v2:old", "1")
        await client.set("events:nba:2026-11-10:us", "1")
        await client.set("events:wnba:2026-11-10:us", "1")
        await client.set("lineups:wnba:slate", "1")
        await client.set("odds:quota_usage:v1", "1")
        await client.set("keep:other", "1")
        await client.set("daily_picks:other", "1")

        deleted = await flush_retired_odds_cache(_Cache(client))
        assert deleted == 7
        assert await client.get("keep:other") == "1"
        assert await client.get("daily_picks:other") == "1"
        assert await client.get("daily_picks:nba:v2:x") is None
        assert await client.get("odds_snapshot:v2:old") is None
        assert await client.get("odds_snapshot_meta:v2:old") is None
        assert await client.get("events:nba:2026-11-10:us") is None
        assert await client.get("events:wnba:2026-11-10:us") is None
        assert await client.get("lineups:wnba:slate") is None
        assert await client.get("odds:quota_usage:v1") is None
        assert await client.get(SPO130I_FLUSH_MARKER) == "1"

        await client.set("events:nba:new", "1")
        again = await flush_retired_odds_cache(_Cache(client))
        assert again == 0
        assert await client.get("events:nba:new") == "1"
        assert await client.get("keep:other") == "1"
    finally:
        await client.close()


class _DeleteFails:
    """Redis stand-in whose first data delete raises, then works."""

    def __init__(self, client: object) -> None:
        self._client = client
        self.failed = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)

    async def delete(self, key: str) -> int:
        if key != "migrations:spo130i:odds_flush_lock" and not self.failed:
            self.failed = True
            raise ConnectionError("delete failed")
        return await self._client.delete(key)


@pytest.mark.asyncio
async def test_flush_retries_when_a_delete_fails_midway() -> None:
    """A failed delete leaves the done marker unset, so the next start finishes."""
    import fakeredis.aioredis

    from app.services.odds_cache_flush import SPO130I_FLUSH_MARKER, flush_retired_odds_cache

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        await client.set("daily_picks:nba:v2:x", "1")
        await client.set("odds_snapshot:v2:old", "1")
        await client.set("odds_snapshot_meta:v2:old", "1")
        await client.set("events:nba:2026-11-10:us", "1")
        await client.set("odds:quota_usage:v1", "1")

        flaky = _DeleteFails(client)
        first = await flush_retired_odds_cache(_Cache(flaky))
        assert first == 0
        assert await client.get(SPO130I_FLUSH_MARKER) is None

        second = await flush_retired_odds_cache(_Cache(client))
        assert await client.get("daily_picks:nba:v2:x") is None
        assert await client.get("odds_snapshot:v2:old") is None
        assert await client.get("odds_snapshot_meta:v2:old") is None
        assert await client.get("events:nba:2026-11-10:us") is None
        assert await client.get("odds:quota_usage:v1") is None
        assert await client.get(SPO130I_FLUSH_MARKER) == "1"
        assert second > 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_flush_lock_holder_skips_without_the_done_marker() -> None:
    """A replica that already holds the lock does not set the done marker."""
    import fakeredis.aioredis

    from app.services.odds_cache_flush import SPO130I_FLUSH_MARKER, flush_retired_odds_cache

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        await client.set("migrations:spo130i:odds_flush_lock", "1")
        await client.set("odds:quota_usage:v1", "1")
        await client.set("events:nba:2026-11-10:us", "1")

        deleted = await flush_retired_odds_cache(_Cache(client))
        assert deleted == 0
        assert await client.get(SPO130I_FLUSH_MARKER) is None
        assert await client.get("odds:quota_usage:v1") == "1"
        assert await client.get("events:nba:2026-11-10:us") == "1"
    finally:
        await client.close()


def test_ignored_odds_env_warns_without_the_value(caplog: pytest.LogCaptureFixture) -> None:
    """A leftover odds env var is named in the warning and its value is not."""
    import os

    from app.main import _warn_ignored_odds_env

    sentinel = "odds-value-should-not-be-logged"
    previous_provider = os.environ.get("NBA_ODDS_PROVIDER")
    previous_key = os.environ.get("ODDS_API_KEY")
    os.environ["NBA_ODDS_PROVIDER"] = sentinel
    os.environ["ODDS_API_KEY"] = sentinel
    try:
        with caplog.at_level("WARNING"):
            _warn_ignored_odds_env()
    finally:
        if previous_provider is None:
            os.environ.pop("NBA_ODDS_PROVIDER", None)
        else:
            os.environ["NBA_ODDS_PROVIDER"] = previous_provider
        if previous_key is None:
            os.environ.pop("ODDS_API_KEY", None)
        else:
            os.environ["ODDS_API_KEY"] = previous_key
    text = caplog.text
    assert "NBA_ODDS_PROVIDER is set but ignored" in text
    assert "ODDS_API_KEY is set but ignored" in text
    assert sentinel not in text


def test_game_id_rejects_unicode_digits() -> None:
    """Arabic-Indic digits are not a BALLDONTLIE game id."""
    from app.services.bdl_odds_provider import _game_id

    with pytest.raises(ValueError):
        _game_id("١٢٣")
    assert _game_id("21718080") == 21718080


@pytest.mark.asyncio
async def test_metrics_rate_status_error_returns_null(monkeypatch) -> None:
    """A rate-status failure is a null field, not a 500."""
    class _Boom:
        name = "balldontlie"

        async def rate_status(self) -> object:
            raise RuntimeError("rate header unreadable")

    monkeypatch.setattr(
        "app.services.bdl_odds_provider.get_bdl_odds_provider",
        lambda: _Boom(),
    )
    from app.api.metrics import get_metrics

    body = await get_metrics()
    assert body["bdl_rate"] is None


@pytest.mark.asyncio
async def test_flush_error_does_not_leave_startup() -> None:
    """A Redis error is logged and returns 0. It does not raise."""
    from app.services.odds_cache_flush import flush_retired_odds_cache

    with pytest.raises(ConnectionError):
        await _Down().get_client()

    deleted = await flush_retired_odds_cache(_Down())
    assert deleted == 0
