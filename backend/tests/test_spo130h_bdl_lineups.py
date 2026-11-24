"""NBA lineups read from recorded BALLDONTLIE projected_lineups bodies.

The HTTP objects are the files under ``tests/fixtures/bdl/``. A non-confirmed
status is a constructed snapshot dict, not a fabricated response body.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from app.api.lineups import get_lineups
from app.services.cache import cache_service
from app.services.db import db_service
from app.services.event_fields import event_lineup_status
from app.services.lineup_provider_bdl import (
    SLATE_GAMES_CACHE_TTL_SECONDS,
    fetch_nba_lineups,
    slate_games_cache_key,
)
from app.services.lineup_service import confirmation_status, lineup_service
from app.services.lineup_source_support import (
    normalize_balldontlie_player_candidate,
    normalize_rotogrinders_player_candidate,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bdl"

POR_STARTERS = [
    "Damian Lillard",
    "Deni Avdija",
    "Toumani Camara",
    "Sidy Cissoko",
    "Donovan Clingan",
]
OKC_STARTERS = [
    "Shai Gilgeous-Alexander",
    "Jared McCain",
    "Ajay Mitchell",
    "Kenrich Williams",
    "Isaiah Hartenstein",
]


def _response(name: str) -> dict:
    """The ``response`` object a ``BdlClient`` method returns."""
    capture = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return capture["response"]


def _json_list(value: object) -> list:
    """asyncpg returns jsonb as text unless a codec is installed."""
    if isinstance(value, str):
        loaded = json.loads(value)
        return list(loaded)
    return list(value or [])


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.sets: list[tuple[str, int]] = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, ttl: int) -> bool:
        self.values[key] = value
        self.sets.append((key, ttl))
        return True


class _FakeClient:
    def __init__(self, games: dict, lineups: dict) -> None:
        self._games = games
        self._lineups = lineups
        self.game_calls: list[dict] = []
        self.lineup_calls: list[list[int]] = []
        self.closed = False

    async def list_games(self, *, dates=None, per_page: int = 100):
        self.game_calls.append({"dates": list(dates or []), "per_page": per_page})
        return self._games

    async def list_projected_lineups(self, *, game_ids: list[int]):
        self.lineup_calls.append(list(game_ids))
        return self._lineups

    async def aclose(self) -> None:
        self.closed = True


def _install_cache(monkeypatch, cache: _MemoryCache) -> None:
    monkeypatch.setattr(cache_service, "get", cache.get)
    monkeypatch.setattr(cache_service, "set", cache.set)
    monkeypatch.setattr(cache_service, "clear_daily_picks_cache", _async_zero)


async def _async_zero(*_args, **_kwargs) -> int:
    return 0


def _bind_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(
        "app.services.lineup_provider_bdl.open_lineup_client",
        lambda: client,
    )


@pytest.mark.asyncio
async def test_confirmed_okc_at_por_lineup_reaches_the_api(monkeypatch):
    """The recorded OKC at POR body is two confirmed fives on the lineup route."""
    games = _response("games_2026-11-10.json")
    lineups = _response("projected_lineups_21718080.json")
    client = _FakeClient(games, lineups)
    cache = _MemoryCache()
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, cache)

    await lineup_service.fetch_and_store("2026-11-10")
    response = await get_lineups(date="2026-11-10")
    by_team = {item.team: item for item in response.lineups}

    assert set(by_team) == {"POR", "OKC"}
    assert by_team["POR"].starters == POR_STARTERS
    assert by_team["OKC"].starters == OKC_STARTERS
    assert by_team["POR"].opponent == "OKC"
    assert by_team["POR"].home_or_away == "HOME"
    assert by_team["OKC"].opponent == "POR"
    assert by_team["OKC"].home_or_away == "AWAY"
    assert by_team["POR"].confirmation_status == "confirmed"
    assert by_team["OKC"].confirmation_status == "confirmed"
    assert by_team["POR"].sources == ["balldontlie"]
    assert by_team["OKC"].sources == ["balldontlie"]
    assert by_team["POR"].source_disagreement is False
    assert by_team["OKC"].source_disagreement is False
    assert by_team["POR"].confidence == "medium"
    assert by_team["OKC"].confidence == "medium"
    assert by_team["POR"].status == "projected"
    assert by_team["POR"].source_snapshots["balldontlie"]["status"] == "confirmed"
    assert by_team["POR"].source_snapshots["balldontlie"]["updated_at"] == "2026-11-11T03:40:01.879Z"

    game_ids = [game["id"] for game in games["data"]]
    assert client.game_calls == [{"dates": ["2026-11-10"], "per_page": 100}]
    assert [game_id for call in client.lineup_calls for game_id in call] == game_ids
    assert all(len(call) <= 12 for call in client.lineup_calls)
    assert len(game_ids) <= 12
    assert client.lineup_calls == [game_ids]
    assert cache.sets[0][0] == slate_games_cache_key("2026-11-10")
    assert cache.sets[0][1] == SLATE_GAMES_CACHE_TTL_SECONDS
    assert SLATE_GAMES_CACHE_TTL_SECONDS == 36 * 60 * 60


@pytest.mark.asyncio
async def test_empty_projected_lineups_leave_no_badge(monkeypatch):
    """WAS at IND was recorded with an empty data list. The badge stays null."""
    client = _FakeClient(
        _response("games_2026-11-11.json"),
        _response("projected_lineups_21718081.json"),
    )
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())

    await lineup_service.fetch_and_store("2026-11-11")
    response = await get_lineups(date="2026-11-11")
    peeked = await lineup_service.peek_lineups("2026-11-11")
    badge = event_lineup_status("Indiana Pacers", "Washington Wizards", peeked)

    assert response.lineups == []
    assert response.team_count == 0
    assert peeked == {}
    assert badge.home is None
    assert badge.away is None
    assert confirmation_status(None) is None


@pytest.mark.asyncio
async def test_second_fetch_reuses_the_slate_game_cache(monkeypatch):
    client = _FakeClient(
        _response("games_2026-11-10.json"),
        _response("projected_lineups_21718080.json"),
    )
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())

    await fetch_nba_lineups("2026-11-10")
    await fetch_nba_lineups("2026-11-10")

    assert len(client.game_calls) == 1
    assert len(client.lineup_calls) == 2


@pytest.mark.asyncio
async def test_more_than_twelve_games_are_split_across_calls(monkeypatch):
    """Thirteen copies of a recorded game stay inside the 12-id calls."""
    games = copy.deepcopy(_response("games_2026-11-10.json"))
    template = games["data"][0]
    cloned = []
    for offset in range(13):
        game = copy.deepcopy(template)
        game["id"] = int(template["id"]) + offset
        cloned.append(game)
    games["data"] = cloned
    client = _FakeClient(games, _response("projected_lineups_21718081.json"))
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())

    await fetch_nba_lineups("2026-11-10")

    assert [len(call) for call in client.lineup_calls] == [12, 1]
    assert [game_id for call in client.lineup_calls for game_id in call] == [
        game["id"] for game in cloned
    ]


@pytest.mark.asyncio
async def test_unknown_starter_name_is_unresolved(monkeypatch):
    """An abbreviated name that is not on the roster is unresolved, not dropped."""
    lineups = copy.deepcopy(_response("projected_lineups_21718080.json"))
    lineups["data"][0]["lineup"][0]["player"]["first_name"] = "Z."
    lineups["data"][0]["lineup"][0]["player"]["last_name"] = "Notonroster"
    client = _FakeClient(_response("games_2026-11-10.json"), lineups)
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())

    fetched = await fetch_nba_lineups("2026-11-10")
    por = fetched.lineups["POR"]
    snapshot = por["source_snapshots"]["balldontlie"]

    assert "Z. Notonroster" in snapshot["unresolved_starters"]
    assert por["confidence"] == "low"
    assert por["status"] == "partial"
    assert por["source_disagreement"] is False


@pytest.mark.asyncio
async def test_balldontlie_name_keeps_a_position_token_and_a_digit(monkeypatch):
    """A projected-lineup name is not cut by the RotoGrinders salary cleaner."""
    position_name = "Tyrese Haliburton PG"
    digit_name = "Shai Gilgeous-Alexander 2"
    assert normalize_rotogrinders_player_candidate(position_name) == "Tyrese Haliburton"
    assert normalize_balldontlie_player_candidate(position_name) == position_name
    assert normalize_rotogrinders_player_candidate(digit_name) == "Shai Gilgeous-Alexander"
    assert normalize_balldontlie_player_candidate(digit_name) == digit_name

    lineups = copy.deepcopy(_response("projected_lineups_21718080.json"))
    lineups["data"][0]["lineup"][0]["player"]["first_name"] = "Tyrese"
    lineups["data"][0]["lineup"][0]["player"]["last_name"] = "Haliburton PG"
    lineups["data"][1]["lineup"][0]["player"]["first_name"] = "Shai"
    lineups["data"][1]["lineup"][0]["player"]["last_name"] = "Gilgeous-Alexander 2"
    client = _FakeClient(_response("games_2026-11-10.json"), lineups)
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())

    fetched = await fetch_nba_lineups("2026-11-10")

    assert position_name in fetched.lineups["POR"]["starters"]
    assert digit_name in fetched.lineups["OKC"]["starters"]


@pytest.mark.asyncio
async def test_cached_empty_games_list_is_refetched(monkeypatch):
    """A stored ``{"games": []}`` entry is a miss, not a 36-hour slate."""
    client = _FakeClient(
        _response("games_2026-11-10.json"),
        _response("projected_lineups_21718080.json"),
    )
    cache = _MemoryCache()
    cache.values[slate_games_cache_key("2026-11-10")] = {"games": []}
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, cache)

    fetched = await fetch_nba_lineups("2026-11-10")

    assert len(client.game_calls) == 1
    assert "POR" in fetched.lineups
    stored = cache.values[slate_games_cache_key("2026-11-10")]
    assert isinstance(stored, dict)
    assert stored["games"]


@pytest.mark.asyncio
async def test_unknown_team_id_is_omitted(monkeypatch):
    lineups = copy.deepcopy(_response("projected_lineups_21718080.json"))
    lineups["data"][0]["team_id"] = 999999
    client = _FakeClient(_response("games_2026-11-10.json"), lineups)
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())

    fetched = await fetch_nba_lineups("2026-11-10")

    assert "POR" not in fetched.lineups
    assert fetched.lineups["OKC"]["starters"] == OKC_STARTERS
    assert fetched.misses >= 1


def test_expected_snapshot_is_projected_confirmation():
    """``expected`` is not a recorded HTTP body. The confirmation rule still maps it."""
    lineup = {
        "starters": ["Damian Lillard"],
        "source_snapshots": {"balldontlie": {"status": "expected", "updated_at": "2026-11-11T03:40:01.879Z"}},
    }
    assert confirmation_status(lineup) == "projected"


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


async def _parents(conn, *, game: bool, players: bool) -> None:
    await conn.execute(
        """
        INSERT INTO seasons (league, season_start_year, label)
        VALUES ('nba', 2026, '2026-27');
        INSERT INTO teams (league, bdl_team_id, abbreviation)
        VALUES ('nba', 25, 'POR'), ('nba', 21, 'OKC');
        """
    )
    if game:
        await conn.execute(
            """
            INSERT INTO games (
                league, bdl_game_id, season, date, season_type, home_team_id, visitor_team_id
            ) VALUES ('nba', 21718080, 2026, '2026-11-10', 'regular_season', 25, 21)
            """
        )
    if players:
        rows = _response("projected_lineups_21718080.json")["data"]
        await conn.executemany(
            """
            INSERT INTO players (league, bdl_player_id, first_name, last_name, display_name)
            VALUES ('nba', $1, $2, $3, $4)
            """,
            [
                (
                    slot["player"]["id"],
                    slot["player"]["first_name"],
                    slot["player"]["last_name"],
                    f"{slot['player']['first_name']} {slot['player']['last_name']}",
                )
                for row in rows
                for slot in row["lineup"]
            ],
        )


async def _fetch_into(conn, monkeypatch) -> None:
    client = _FakeClient(
        _response("games_2026-11-10.json"),
        _response("projected_lineups_21718080.json"),
    )
    _bind_client(monkeypatch, client)
    _install_cache(monkeypatch, _MemoryCache())
    monkeypatch.setattr(db_service, "_pool", _Pool(conn))
    await lineup_service.fetch_and_store("2026-11-10")


@pytest_asyncio.fixture
async def migrated(scratch_conn):
    from app.migrations.runner import upgrade

    assert await upgrade(scratch_conn) == ["001", "002", "003", "004", "005", "006", "007"]
    return scratch_conn


@pytest.mark.asyncio
async def test_parents_present_writes_snapshot_and_projected_lineups(migrated, monkeypatch):
    await _parents(migrated, game=True, players=True)
    await _fetch_into(migrated, monkeypatch)

    snapshots = await migrated.fetch(
        """
        SELECT team, opponent, home_or_away, sources, source_disagreement, confidence
        FROM team_lineup_snapshots
        WHERE date = '2026-11-10'
        ORDER BY team
        """
    )
    assert [(row["team"], row["opponent"], row["home_or_away"]) for row in snapshots] == [
        ("OKC", "POR", "AWAY"),
        ("POR", "OKC", "HOME"),
    ]
    assert all(row["source_disagreement"] is False for row in snapshots)
    assert all(row["confidence"] == "medium" for row in snapshots)
    assert all(_json_list(row["sources"]) == ["balldontlie"] for row in snapshots)

    versions = await migrated.fetch(
        """
        SELECT bdl_team_id, status FROM projected_lineups
        ORDER BY bdl_team_id
        """
    )
    assert [(row["bdl_team_id"], row["status"]) for row in versions] == [
        (21, "confirmed"),
        (25, "confirmed"),
    ]
    assert await migrated.fetchval("SELECT count(*) FROM projected_lineup_players") == 10
    assert await migrated.fetchval("SELECT count(*) FROM game_lineups") == 0
    refresh = await migrated.fetchrow(
        """
        SELECT complete, rows_written, error
        FROM source_refreshes
        WHERE source = 'projected_lineups'
        """
    )
    assert refresh["complete"] is True
    assert refresh["rows_written"] == 2
    assert refresh["error"] is None
    first_seen = await migrated.fetchval("SELECT min(first_seen_at) FROM projected_lineups")
    assert isinstance(first_seen, datetime)
    assert first_seen.tzinfo is not None
    assert first_seen <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_missing_game_keeps_the_live_snapshot_and_skips_002(migrated, monkeypatch):
    await _parents(migrated, game=False, players=True)
    await _fetch_into(migrated, monkeypatch)

    assert await migrated.fetchval(
        "SELECT count(*) FROM team_lineup_snapshots WHERE date = '2026-11-10'"
    ) == 2
    assert await migrated.fetchval("SELECT count(*) FROM projected_lineups") == 0
    assert await migrated.fetchval("SELECT count(*) FROM projected_lineup_players") == 0
    assert await migrated.fetchval("SELECT count(*) FROM game_lineups") == 0
    refresh = await migrated.fetchrow(
        "SELECT complete, rows_written FROM source_refreshes WHERE source = 'projected_lineups'"
    )
    assert refresh["complete"] is False
    assert refresh["rows_written"] == 0


@pytest.mark.asyncio
async def test_missing_players_keeps_the_live_snapshot_and_skips_002(migrated, monkeypatch):
    await _parents(migrated, game=True, players=False)
    await _fetch_into(migrated, monkeypatch)

    assert await migrated.fetchval(
        "SELECT count(*) FROM team_lineup_snapshots WHERE date = '2026-11-10'"
    ) == 2
    assert await migrated.fetchval("SELECT count(*) FROM projected_lineups") == 0
    refresh = await migrated.fetchrow(
        "SELECT complete FROM source_refreshes WHERE source = 'projected_lineups'"
    )
    assert refresh["complete"] is False
