"""SPO-130f: NBA event routes read the odds gateway.

Bodies are the recorded files under tests/fixtures/. Nothing here types
an Odds API or BALLDONTLIE response. The default provider stays
theoddsapi. balldontlie is set only inside a test.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.middleware.rate_limit import limiter
from app.services.bdl_odds_provider import BdlOddsProvider, odds_api_team_name
from app.services.bdl_player_directory import BdlPlayerDirectory
from app.services.bdl_props_adapter import VENDOR_TITLES
from app.services.bulk_props import event_id_is_well_formed
from app.services.cache import CacheService, cache_service
from app.services.odds_theoddsapi import TheOddsAPIProvider, odds_provider
from app.settings import settings
from tests.fixtures.odds_api import load_odds_fixture

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
_SLATE = "2026-11-10"
_ET = -300
_OKC_GAME_ID = "21718080"


def _load(name: str) -> dict:
    """One recorded capture. The file is ``{request, status, response}``."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _window(date: str, offset_minutes: int) -> tuple[datetime, datetime]:
    """The same UTC window ``get_events`` has always sent."""
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    local_start = datetime.combine(date_obj.date(), datetime.min.time())
    utc_start = local_start - timedelta(minutes=offset_minutes)
    local_end = datetime.combine(date_obj.date(), time(23, 59, 59))
    utc_end = local_end - timedelta(minutes=offset_minutes)
    return utc_start - timedelta(hours=1), utc_end + timedelta(hours=1)


def _on_local_date(commence_time: str, date: str, offset_minutes: int) -> bool:
    moment = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    local = moment + timedelta(minutes=offset_minutes)
    return local.strftime("%Y-%m-%d") == date


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict = {}

    async def get(self, key: str):
        value = self.values.get(key)
        return copy.deepcopy(value) if value is not None else None

    async def set(self, key: str, value, ttl: int):
        self.values[key] = copy.deepcopy(value)
        return True

    async def acquire_lock(self, key: str, ttl: int) -> bool:
        return True

    async def release_lock(self, key: str) -> bool:
        return True

    async def increment_sorted_set(self, key: str, member: str, amount: float = 1.0) -> float:
        return amount


def _install_cache(monkeypatch) -> _MemoryCache:
    cache = _MemoryCache()
    monkeypatch.setattr(cache_service, "get", cache.get)
    monkeypatch.setattr(cache_service, "set", cache.set)
    monkeypatch.setattr(cache_service, "acquire_lock", cache.acquire_lock)
    monkeypatch.setattr(cache_service, "release_lock", cache.release_lock)
    monkeypatch.setattr(cache_service, "increment_sorted_set", cache.increment_sorted_set)

    async def peek(_date: str):
        return {}

    monkeypatch.setattr("app.api.nba.lineup_service.peek_lineups", peek)
    return cache


class _FixtureClient:
    """Returns recorded ``response`` objects. It does not build a body."""

    def __init__(self, props_name: str) -> None:
        self.calls: list[tuple] = []
        self.games = _load("games_2026-11-10.json")["response"]
        self.props = _load(props_name)["response"]
        self.players = _load("backend_players_batch45.json")["response"]

    def rate_status(self) -> dict[str, int | None]:
        return {"limit": None, "remaining": None, "reset": None}

    async def list_games(self, *, dates: list[str], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_games", list(dates)))
        return self.games

    async def get_player_props(self, *, game_id: int):
        self.calls.append(("get_player_props", game_id))
        return self.props

    async def list_players(self, *, player_ids: list[int], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_players", list(player_ids)))
        wanted = set(player_ids)
        data = [player for player in self.players["data"] if player["id"] in wanted]
        return {"data": data, "meta": dict(self.players.get("meta") or {})}

    async def get_game(self, *, game_id: int):
        self.calls.append(("get_game", game_id))
        for game in self.games["data"]:
            if game["id"] == game_id:
                return {"data": game}
        raise AssertionError(f"recorded games file has no game {game_id}")


def _install_bdl(monkeypatch, props_name: str) -> _FixtureClient:
    client = _FixtureClient(props_name)
    directory = BdlPlayerDirectory(client, aliases={})
    provider = BdlOddsProvider(client, directory=directory)
    monkeypatch.setattr("app.services.bdl_odds_provider._SINGLETON", provider)
    monkeypatch.setattr(settings, "nba_odds_provider", "balldontlie")

    async def odds_api_must_not_run(*_args, **_kwargs):
        raise AssertionError("odds_provider.get_events ran under balldontlie")

    monkeypatch.setattr(odds_provider, "get_events", odds_api_must_not_run)
    return client


def _shai(props: dict, players: dict) -> tuple[int, str, set[float]]:
    """Player id, recorded name, and recorded points totals for that id."""
    names = {
        player["id"]: f"{player['first_name']} {player['last_name']}"
        for player in players["data"]
        if isinstance(player.get("id"), int)
    }
    lines: set[float] = set()
    chosen: tuple[int, str] | None = None
    for row in props["data"]:
        if row.get("prop_type") != "points":
            continue
        market = row.get("market") if isinstance(row.get("market"), dict) else {}
        if market.get("type") != "over_under":
            continue
        player_id = row.get("player_id")
        name = names.get(player_id)
        if not isinstance(name, str) or "Gilgeous" not in name:
            continue
        chosen = (player_id, name)
        lines.add(float(row["line_value"]))
    if chosen is None or not lines:
        raise AssertionError("recorded props have no points over/under for that player")
    return chosen[0], chosen[1], lines


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _events_key(date: str, regions: str, offset: int) -> str:
    return f"{CacheService.build_events_key(date, regions)}:tz{offset}"


@pytest.mark.asyncio
async def test_default_events_keep_the_odds_api_request_and_hex_ids(client, monkeypatch):
    """Unset provider: same events URL and params, hex ids, historical cache key."""
    cache = _install_cache(monkeypatch)
    recorded = load_odds_fixture("odds_api_events__basketball_nba.json")
    captured: dict = {"n": 0}

    async def fake_request(_self, endpoint, params):
        captured["n"] += 1
        captured["endpoint"] = endpoint
        captured["params"] = dict(params)
        return copy.deepcopy(recorded), None

    monkeypatch.setattr(TheOddsAPIProvider, "_make_request", fake_request)
    date_from, date_to = _window(_SLATE, 0)

    response = await client.get(
        "/api/nba/events",
        params={"date": _SLATE, "regions": "us", "tz_offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == _SLATE
    expected_ids = [
        event["id"]
        for event in recorded
        if _on_local_date(event["commence_time"], _SLATE, 0)
    ]
    assert expected_ids
    assert [event["event_id"] for event in body["events"]] == expected_ids
    assert all(not event_id.isdigit() for event_id in expected_ids)
    assert captured["endpoint"] == "/v4/sports/basketball_nba/events"
    assert set(captured["params"]) == {"commenceTimeFrom", "commenceTimeTo"}
    assert captured["params"]["commenceTimeFrom"] == date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert captured["params"]["commenceTimeTo"] == date_to.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "apiKey" not in captured["params"]
    assert list(cache.values) == [_events_key(_SLATE, "us", 0)]

    again = await client.get(
        "/api/nba/events",
        params={"date": _SLATE, "regions": "us", "tz_offset": 0},
    )
    assert again.status_code == 200
    assert again.json()["events"][0]["event_id"] == expected_ids[0]
    assert captured["n"] == 1


@pytest.mark.asyncio
async def test_default_events_forward_regions_without_putting_them_on_the_query(client, monkeypatch):
    cache = _install_cache(monkeypatch)
    recorded = load_odds_fixture("odds_api_events__basketball_nba.json")
    captured: dict = {}

    async def fake_request(_self, endpoint, params):
        captured["params"] = dict(params)
        return copy.deepcopy(recorded), None

    monkeypatch.setattr(TheOddsAPIProvider, "_make_request", fake_request)
    response = await client.get(
        "/api/nba/events",
        params={"date": _SLATE, "regions": "uk", "tz_offset": 0},
    )
    assert response.status_code == 200
    assert "regions" not in captured["params"]
    assert list(cache.values) == [_events_key(_SLATE, "uk", 0)]


@pytest.mark.asyncio
async def test_bdl_slate_returns_digit_ids_and_does_not_read_the_odds_api_key(client, monkeypatch):
    cache = _install_cache(monkeypatch)
    fixture = _install_bdl(monkeypatch, "props_live_21718080_OKC@POR_pregame.json")
    games = fixture.games["data"]

    response = await client.get(
        "/api/nba/events",
        params={"date": _SLATE, "regions": "us", "tz_offset": _ET},
    )

    assert response.status_code == 200
    body = response.json()
    ids = [event["event_id"] for event in body["events"]]
    assert ids
    assert all(event_id.isdigit() for event_id in ids)
    assert _OKC_GAME_ID in ids
    game = next(item for item in games if str(item["id"]) == _OKC_GAME_ID)
    listed = next(event for event in body["events"] if event["event_id"] == _OKC_GAME_ID)
    assert listed["home_team"] == odds_api_team_name(game["home_team"]["full_name"])
    assert listed["away_team"] == odds_api_team_name(game["visitor_team"]["full_name"])
    assert listed["sport_key"] == "basketball_nba"
    clippers = next(item for item in games if item["visitor_team"]["full_name"] == "LA Clippers")
    clippers_row = next(event for event in body["events"] if event["event_id"] == str(clippers["id"]))
    assert clippers_row["away_team"] == "Los Angeles Clippers"
    assert fixture.calls[0][0] == "list_games"
    assert _SLATE in fixture.calls[0][1]
    assert list(cache.values) == [_events_key(_SLATE, "us", _ET) + ":balldontlie"]

    detail = await client.get(
        f"/api/nba/events/{_OKC_GAME_ID}",
        params={"date": _SLATE, "regions": "us", "tz_offset": _ET},
    )
    assert detail.status_code == 200
    assert detail.json()["event_id"] == _OKC_GAME_ID
    assert detail.json()["home_team"] == listed["home_team"]
    # The detail read reused the list cache. No second games call.
    assert [call for call in fixture.calls if call[0] == "list_games"] == [fixture.calls[0]]


@pytest.mark.asyncio
async def test_bdl_cache_does_not_serve_a_hex_payload(client, monkeypatch):
    """A flag flip must not return the other provider's event ids."""
    cache = _install_cache(monkeypatch)
    recorded = load_odds_fixture("odds_api_events__basketball_nba.json")
    seeded = recorded[0]
    historical = _events_key(_SLATE, "us", _ET)
    cache.values[historical] = {
        "date": _SLATE,
        "events": [
            {
                "event_id": seeded["id"],
                "sport_key": seeded["sport_key"],
                "home_team": seeded["home_team"],
                "away_team": seeded["away_team"],
                "commence_time": seeded["commence_time"],
            }
        ],
    }
    _install_bdl(monkeypatch, "props_live_21718080_OKC@POR_pregame.json")

    response = await client.get(
        "/api/nba/events",
        params={"date": _SLATE, "regions": "us", "tz_offset": _ET},
    )

    assert response.status_code == 200
    ids = [event["event_id"] for event in response.json()["events"]]
    assert seeded["id"] not in ids
    assert _OKC_GAME_ID in ids
    assert cache.values[historical]["events"][0]["event_id"] == seeded["id"]
    assert _events_key(_SLATE, "us", _ET) + ":balldontlie" in cache.values


@pytest.mark.asyncio
async def test_default_cache_does_not_serve_a_digit_payload(client, monkeypatch):
    cache = _install_cache(monkeypatch)
    game = next(item for item in _load("games_2026-11-10.json")["response"]["data"] if str(item["id"]) == _OKC_GAME_ID)
    bdl_key = _events_key(_SLATE, "us", 0) + ":balldontlie"
    cache.values[bdl_key] = {
        "date": _SLATE,
        "events": [
            {
                "event_id": str(game["id"]),
                "sport_key": "basketball_nba",
                "home_team": game["home_team"]["full_name"],
                "away_team": game["visitor_team"]["full_name"],
                "commence_time": game["datetime"],
            }
        ],
    }
    recorded = load_odds_fixture("odds_api_events__basketball_nba.json")
    calls = {"n": 0}

    async def fake_request(_self, endpoint, params):
        calls["n"] += 1
        return copy.deepcopy(recorded), None

    monkeypatch.setattr(TheOddsAPIProvider, "_make_request", fake_request)
    response = await client.get(
        "/api/nba/events",
        params={"date": _SLATE, "regions": "us", "tz_offset": 0},
    )
    assert response.status_code == 200
    ids = [event["event_id"] for event in response.json()["events"]]
    assert _OKC_GAME_ID not in ids
    assert calls["n"] == 1
    assert cache.values[bdl_key]["events"][0]["event_id"] == _OKC_GAME_ID


@pytest.mark.asyncio
async def test_bdl_malformed_event_id_is_404_and_a_missing_digit_id_is_404(client, monkeypatch):
    fixture = _install_bdl(monkeypatch, "props_live_21718080_OKC@POR_pregame.json")
    _install_cache(monkeypatch)
    malformed = await client.get(
        "/api/nba/events/!!!",
        params={"date": _SLATE, "tz_offset": _ET},
    )
    assert malformed.status_code == 404
    assert malformed.json()["detail"] == "Malformed event_id"
    assert fixture.calls == []

    missing_id = "21718193"
    assert event_id_is_well_formed(missing_id)
    assert missing_id.isdigit()
    assert all(str(game["id"]) != missing_id for game in fixture.games["data"])
    missing = await client.get(
        f"/api/nba/events/{missing_id}",
        params={"date": _SLATE, "tz_offset": _ET},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Event not found"


@pytest.mark.asyncio
async def test_bdl_empty_local_day_is_200(client, monkeypatch):
    _install_cache(monkeypatch)
    _install_bdl(monkeypatch, "props_live_21718080_OKC@POR_pregame.json")
    response = await client.get(
        "/api/nba/events",
        params={"date": "2026-07-01", "regions": "us", "tz_offset": _ET},
    )
    assert response.status_code == 200
    assert response.json()["events"] == []


@pytest.mark.asyncio
async def test_bdl_no_vig_and_suggest_use_recorded_points(client, monkeypatch):
    _install_cache(monkeypatch)
    fixture = _install_bdl(monkeypatch, "props_live_21718080_OKC@POR_pregame.json")
    _player_id, name, lines = _shai(fixture.props, fixture.players)

    no_vig = await client.post(
        "/api/nba/props/no-vig",
        json={"event_id": _OKC_GAME_ID, "player_name": name, "market": "player_points"},
    )
    assert no_vig.status_code == 200, no_vig.text
    body = no_vig.json()
    assert body["event_id"] == _OKC_GAME_ID
    assert body["player_name"] == name
    assert body["results"]
    for result in body["results"]:
        assert result["bookmaker"] in VENDOR_TITLES
        assert result["line"] in lines
        assert 0 < result["p_over_fair"] < 1
        assert result["p_over_fair"] + result["p_under_fair"] == pytest.approx(1, abs=0.001)
    assert ("get_player_props", int(_OKC_GAME_ID)) in fixture.calls

    suggest = await client.get(
        "/api/nba/players/suggest",
        params={"event_id": _OKC_GAME_ID, "q": name.split()[0], "market": "player_points"},
    )
    assert suggest.status_code == 200, suggest.text
    assert name in suggest.json()["players"]


@pytest.mark.asyncio
async def test_bdl_digit_id_with_no_prop_rows_is_empty_200(client, monkeypatch):
    _install_cache(monkeypatch)
    fixture = _install_bdl(monkeypatch, "props_empty.json")
    assert fixture.props["data"] == []
    player = next(item for item in fixture.players["data"] if item["id"] == 175)
    name = f"{player['first_name']} {player['last_name']}"

    no_vig = await client.post(
        "/api/nba/props/no-vig",
        json={"event_id": _OKC_GAME_ID, "player_name": name, "market": "player_points"},
    )
    assert no_vig.status_code == 200
    assert no_vig.json()["results"] == []

    suggest = await client.get(
        "/api/nba/players/suggest",
        params={"event_id": _OKC_GAME_ID, "market": "player_points"},
    )
    assert suggest.status_code == 200
    assert suggest.json()["players"] == []


@pytest.mark.asyncio
async def test_bdl_non_digit_id_on_props_routes_is_404(client, monkeypatch):
    _install_cache(monkeypatch)
    fixture = _install_bdl(monkeypatch, "props_live_21718080_OKC@POR_pregame.json")
    recorded = load_odds_fixture("odds_api_event_odds__player_points.json")
    hex_id = recorded["id"]
    assert not hex_id.isdigit()

    no_vig = await client.post(
        "/api/nba/props/no-vig",
        json={"event_id": hex_id, "player_name": "Luka Doncic", "market": "player_points"},
    )
    assert no_vig.status_code == 404
    assert no_vig.json()["detail"] == "Malformed event_id"
    suggest = await client.get(
        "/api/nba/players/suggest",
        params={"event_id": "!!!", "market": "player_points"},
    )
    assert suggest.status_code == 404
    assert suggest.json()["detail"] == "Malformed event_id"
    assert all(call[0] != "get_player_props" for call in fixture.calls)


@pytest.mark.asyncio
async def test_default_no_vig_and_suggest_use_the_recorded_odds_api_board(client, monkeypatch):
    _install_cache(monkeypatch)
    board = load_odds_fixture("odds_api_event_odds__player_points.json")
    assert not str(board["id"]).isdigit()

    async def fake_odds(**_kwargs):
        return copy.deepcopy(board), None

    # Patch the instance. An earlier test can leave this attribute on the
    # singleton, and a class assignment would not replace it.
    monkeypatch.setattr(odds_provider, "get_event_odds_with_usage", fake_odds)
    player = "Luka Doncic"
    assert any(
        outcome.get("description") == player
        for book in board["bookmakers"]
        for market in book["markets"]
        for outcome in market["outcomes"]
    )
    books = {book["key"] for book in board["bookmakers"]}

    no_vig = await client.post(
        "/api/nba/props/no-vig",
        json={"event_id": board["id"], "player_name": player, "market": "player_points"},
    )
    assert no_vig.status_code == 200, no_vig.text
    body = no_vig.json()
    assert body["event_id"] == board["id"]
    assert body["player_name"] == player
    assert body["results"]
    assert {result["bookmaker"] for result in body["results"]} <= books

    suggest = await client.get(
        "/api/nba/players/suggest",
        params={"event_id": board["id"], "q": "luka", "market": "player_points"},
    )
    assert suggest.status_code == 200, suggest.text
    assert player in suggest.json()["players"]
