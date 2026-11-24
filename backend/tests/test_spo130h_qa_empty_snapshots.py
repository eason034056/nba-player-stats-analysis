"""QA-only: empty BALLDONTLIE projected_lineups versus rows already stored.

Not part of the PR. The recorded 21718081 body is ``data: []``. A slate that
already has ``team_lineup_snapshots`` must keep those rows. An empty games
list must not be cached as the slate and must not delete those rows either.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
import pytest_asyncio

from pathlib import Path

from app.services.cache import cache_service
from app.services.db import db_service
from app.services.lineup_provider_bdl import slate_games_cache_key
from app.services.lineup_service import lineup_service

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bdl"


def _response(name: str) -> dict:
    capture = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return capture["response"]


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, ttl: int) -> bool:
        self.values[key] = value
        return True


class _FakeClient:
    def __init__(self, games: dict, lineups: dict) -> None:
        self._games = games
        self._lineups = lineups
        self.lineup_calls: list[list[int]] = []

    async def list_games(self, *, dates=None, per_page: int = 100):
        return self._games

    async def list_projected_lineups(self, *, game_ids: list[int]):
        self.lineup_calls.append(list(game_ids))
        return self._lineups

    async def aclose(self) -> None:
        return None


class _Acquire:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc) -> bool:
        return False


class _Pool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


async def _async_zero(*_args, **_kwargs) -> int:
    return 0


def _bind_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(
        "app.services.lineup_provider_bdl.open_lineup_client",
        lambda: client,
    )


def _install_cache(monkeypatch, cache: _MemoryCache) -> None:
    monkeypatch.setattr(cache_service, "get", cache.get)
    monkeypatch.setattr(cache_service, "set", cache.set)
    monkeypatch.setattr(cache_service, "clear_daily_picks_cache", _async_zero)


@pytest_asyncio.fixture
async def migrated(scratch_conn):
    from app.migrations.runner import upgrade

    assert await upgrade(scratch_conn) == ["001", "002", "003", "004", "005", "006"]
    return scratch_conn


async def _seed(conn) -> None:
    await conn.executemany(
        """
        INSERT INTO team_lineup_snapshots (
            date, team, opponent, home_or_away, status,
            starters, bench_candidates, sources, source_disagreement,
            confidence, updated_at, source_snapshots, league
        ) VALUES (
            $1::date, $2, $3, $4, 'projected',
            $5::jsonb, '[]'::jsonb, '["balldontlie"]'::jsonb, false,
            'medium', now(), '{"balldontlie": {"status": "confirmed"}}'::jsonb, $6
        )
        """,
        [
            (date(2026, 11, 11), "IND", "WAS", "HOME", json.dumps(["Tyrese Haliburton"]), "nba"),
            (date(2026, 11, 11), "WAS", "IND", "AWAY", json.dumps(["CJ McCollum"]), "nba"),
            (date(2026, 11, 10), "POR", "OKC", "HOME", json.dumps(["Damian Lillard"]), "nba"),
            (date(2026, 11, 11), "NYK", "BOS", "HOME", json.dumps(["Jalen Brunson"]), "wnba"),
        ],
    )


def _rows(records) -> list[tuple[str, str, str]]:
    return [(row["date"], row["team"], row["league"]) for row in records]


@pytest.mark.asyncio
async def test_empty_projected_lineups_keep_snapshots_already_stored(migrated, monkeypatch):
    """Recorded ``data: []`` is pre-release, not a request to drop stored lineups."""
    await _seed(migrated)
    client = _FakeClient(
        _response("games_2026-11-11.json"),
        _response("projected_lineups_21718081.json"),
    )
    cache = _MemoryCache()
    cache.values["lineups:nba:2026-11-11"] = {
        "IND": {"team": "IND", "starters": ["Tyrese Haliburton"]},
        "WAS": {"team": "WAS", "starters": ["CJ McCollum"]},
    }
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, cache)
    monkeypatch.setattr(db_service, "_pool", _Pool(migrated))

    await lineup_service.fetch_and_store("2026-11-11")

    kept = await migrated.fetch(
        """
        SELECT date::text AS date, team, league
        FROM team_lineup_snapshots
        ORDER BY date, league, team
        """
    )
    cached = cache.values.get("lineups:nba:2026-11-11")
    assert {
        "snapshots": _rows(kept),
        "redis_teams": sorted(cached) if isinstance(cached, dict) else None,
        "projected_lineups": await migrated.fetchval("SELECT count(*) FROM projected_lineups"),
        "source_refreshes": await migrated.fetchval(
            "SELECT count(*) FROM source_refreshes WHERE source = 'projected_lineups'"
        ),
        "lineup_calls": len(client.lineup_calls),
    } == {
        "snapshots": [
            ("2026-11-10", "POR", "nba"),
            ("2026-11-11", "IND", "nba"),
            ("2026-11-11", "WAS", "nba"),
            ("2026-11-11", "NYK", "wnba"),
        ],
        "redis_teams": ["IND", "WAS"],
        "projected_lineups": 0,
        "source_refreshes": 0,
        "lineup_calls": 1,
    }


@pytest.mark.asyncio
async def test_empty_games_list_does_not_wipe_snapshots_or_stick_for_36h(migrated, monkeypatch):
    """A recorded empty games page must not become the 36-hour slate cache."""
    await _seed(migrated)
    empty_games = json.loads((FIXTURES / "games__season1900_empty.json").read_text())["response"]
    client = _FakeClient(empty_games, _response("projected_lineups_21718081.json"))
    cache = _MemoryCache()
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, cache)
    monkeypatch.setattr(db_service, "_pool", _Pool(migrated))

    await lineup_service.fetch_and_store("2026-11-11")

    kept = await migrated.fetch(
        """
        SELECT date::text AS date, team, league
        FROM team_lineup_snapshots
        ORDER BY date, league, team
        """
    )
    slate_key = slate_games_cache_key("2026-11-11")
    assert {
        "snapshots": _rows(kept),
        "slate_cached": slate_key in cache.values,
        "slate_games": cache.values.get(slate_key),
        "redis_lineups": cache.values.get("lineups:nba:2026-11-11"),
        "lineup_calls": client.lineup_calls,
    } == {
        "snapshots": [
            ("2026-11-10", "POR", "nba"),
            ("2026-11-11", "IND", "nba"),
            ("2026-11-11", "WAS", "nba"),
            ("2026-11-11", "NYK", "wnba"),
        ],
        "slate_cached": False,
        "slate_games": None,
        "redis_lineups": None,
        "lineup_calls": [],
    }
