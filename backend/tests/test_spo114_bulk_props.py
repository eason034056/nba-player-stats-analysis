"""SPO-114: bulk NBA props are read from stored snapshots only.

Point rows are built by ``OddsSnapshotService.rows_from_bookmakers`` from
the recorded Odds API ``player_points`` body. Binary rows are stored
snapshot rows: Yes in ``over_odds`` and No in ``under_odds``, with the
prices taken from the recorded one-sided double-double fixture. Nothing
in this module types an Odds API payload by hand, and nothing calls the
live Odds API.
"""

from __future__ import annotations

import ast
import inspect
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.services.bulk_props import (
    BULK_PROPS_CACHE_TTL_SECONDS,
    LATEST_EVENT_SNAPSHOT_SQL,
    _main_book_line,
    assemble_bulk_props,
    get_event_bulk_props,
)
from app.services.odds_snapshot_service import OddsSnapshotService
from app.services.prob import american_to_prob, calculate_mode_threshold

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_POINTS = _FIXTURES / "odds_api_event_odds__player_points.json"
_ONE_SIDED = _FIXTURES / "player-double-double-one-sided.json"
_SERVICE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "bulk_props.py"

_SNAPSHOT_AT = datetime(2026, 11, 9, 21, 34, tzinfo=timezone.utc)
_EARLIER = _SNAPSHOT_AT - timedelta(hours=6)
_DATE = "2026-11-09"

_ROW_KEYS = (
    "snapshot_at",
    "date",
    "event_id",
    "home_team",
    "away_team",
    "player_name",
    "market",
    "bookmaker",
    "line",
    "over_odds",
    "under_odds",
    "vig",
    "over_fair_prob",
    "under_fair_prob",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_dicts(rows: list[tuple]) -> list[dict]:
    return [dict(zip(_ROW_KEYS, row)) for row in rows]


def _binary_snapshot_rows(payload: dict, snapshot_at: datetime, event_id: str) -> list[dict]:
    """Stored ``odds_line_snapshots`` rows for one binary market.

    The snapshot writer puts Yes in ``over_odds`` and No in ``under_odds``.
    A missing No stays null. Prices are ``yes_price`` and ``no_price``
    from the recorded fixture. These dicts are our rows, not an Odds API
    bookmaker body, and they are passed to ``assemble_bulk_props``.
    """
    rows = []
    for result in payload["results"]:
        rows.append(
            {
                "snapshot_at": snapshot_at,
                "event_id": event_id,
                "player_name": payload["player_name"],
                "market": payload["market"],
                "bookmaker": result["bookmaker"],
                "line": result["line"],
                "over_odds": result["yes_price"],
                "under_odds": result["no_price"],
            }
        )
    return rows


def _parse(service: OddsSnapshotService, bookmakers: list[dict], event_id: str, payload: dict, snapshot_at: datetime) -> list[dict]:
    rows = service.rows_from_bookmakers(
        bookmakers,
        event_id=event_id,
        home_team=payload.get("home_team", ""),
        away_team=payload.get("away_team", ""),
        date=_DATE,
        snapshot_at=snapshot_at,
    )
    return _as_dicts(rows)


def _alternate_point_rows(service: OddsSnapshotService, payload: dict, snapshot_at: datetime) -> list[dict]:
    """One stored row per recorded (book, player, point) pair.

    The production parser keeps a single pair per book. Feeding each
    recorded pair through that same parser, one pair at a time, is how
    the test asks the read path to collapse alternates. The outcome
    objects are the fixture's objects.
    """
    rows: list[dict] = []
    event_id = payload["id"]
    for book in payload["bookmakers"]:
        market = book["markets"][0]
        grouped: dict[tuple[str, float], dict[str, dict]] = defaultdict(dict)
        for outcome in market["outcomes"]:
            grouped[(outcome["description"], outcome["point"])][outcome["name"]] = outcome
        for sides in grouped.values():
            over = sides.get("Over")
            under = sides.get("Under")
            if over is None or under is None:
                continue
            slim = {
                "key": book["key"],
                "markets": [{"key": market["key"], "outcomes": [over, under]}],
            }
            rows.extend(_parse(service, [slim], event_id, payload, snapshot_at))
    return rows


def _even_money_distance(over, under) -> float:
    """Independent copy of the de-vig distance used as the expected vote."""
    if over is not None and under is not None:
        p_over = american_to_prob(float(over))
        p_under = american_to_prob(float(under))
        total = p_over + p_under
        if total <= 0:
            return 1.0
        return abs((p_over / total) - 0.5)
    posted = over if over is not None else under
    if posted is None:
        return 1.0
    return abs(american_to_prob(float(posted)) - 0.5)


def _vote_key(row: dict) -> tuple:
    """Independent copy of the one-vote rule, used as the expected value.

    De-vig first. A two-sided row beats a one-sided row. Equal distances
    keep the lower line. Each alternate in this file is already one stored
    row per point, so the key does not have to merge a repeated side.
    """
    over = row["over_odds"]
    under = row["under_odds"]
    line = float(row["line"])
    both = over is not None and under is not None
    priced = over is not None or under is not None
    rank = 0 if both else (1 if priced else 2)
    distance = _even_money_distance(over, under) if priced else 1.0
    return (rank, distance, line)


def _expected_players(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Modal line and one book per (market, player) from stored rows."""
    latest = max(row["snapshot_at"] for row in rows)
    current = [row for row in rows if row["snapshot_at"] == latest]
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in current:
        grouped[(row["market"], row["player_name"], row["bookmaker"])].append(row)

    by_player: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for key, group in grouped.items():
        by_player[(key[0], key[1])].append(min(group, key=_vote_key))

    expected = {}
    for key, votes in by_player.items():
        votes = sorted(votes, key=lambda row: row["bookmaker"].casefold())
        expected[key] = {
            "line": calculate_mode_threshold([float(row["line"]) for row in votes]),
            "bookmakers_count": len(votes),
            "books": votes,
        }
    return expected


def _raw_over_points(payload: dict, player: str) -> int:
    """How many Over totals the fixture posts for ``player``, across books."""
    count = 0
    for book in payload["bookmakers"]:
        seen = set()
        for outcome in book["markets"][0]["outcomes"]:
            if outcome.get("description") == player and outcome.get("name") == "Over":
                seen.add(outcome.get("point"))
        count += len(seen)
    return count


class _FakeDB:
    def __init__(self, rows: list[dict], *, connected: bool = True, error: Exception | None = None):
        self.rows = rows
        self.is_connected = connected
        self.error = error
        self.calls: list[tuple] = []

    async def fetch(self, query: str, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return self.rows


class _FakeCache:
    def __init__(self):
        self.store: dict[str, object] = {}
        self.sets: list[tuple] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ttl: int) -> bool:
        self.sets.append((key, value, ttl))
        self.store[key] = value
        return True


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.middleware.rate_limit import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def odds_spies(monkeypatch):
    """Patch every Odds API entry the process could use, and count calls."""
    from app.services.odds_gateway import OddsMarketGateway, odds_gateway
    from app.services.odds_theoddsapi import TheOddsAPIProvider, odds_provider
    import app.services.odds_theoddsapi as odds_mod

    spies: dict[str, AsyncMock | MagicMock] = {}

    def _async_spy(name: str) -> AsyncMock:
        mock = AsyncMock(return_value={"bookmakers": []})
        spies[name] = mock
        return mock

    gateway = _async_spy("gateway")
    event_odds = _async_spy("event_odds")
    events = _async_spy("events")
    usage = _async_spy("usage")
    monkeypatch.setattr(odds_gateway, "get_market_snapshot", gateway)
    monkeypatch.setattr(OddsMarketGateway, "get_market_snapshot", gateway)
    monkeypatch.setattr(odds_provider, "get_event_odds", event_odds)
    monkeypatch.setattr(odds_provider, "get_events", events)
    monkeypatch.setattr(odds_provider, "get_event_odds_with_usage", usage)
    monkeypatch.setattr(TheOddsAPIProvider, "get_event_odds", event_odds)
    monkeypatch.setattr(TheOddsAPIProvider, "get_events", events)
    monkeypatch.setattr(TheOddsAPIProvider, "get_event_odds_with_usage", usage)
    http = MagicMock(name="AsyncClient")
    monkeypatch.setattr(odds_mod.httpx, "AsyncClient", http)
    spies["httpx"] = http
    return spies


def _assert_no_live_calls(spies: dict) -> None:
    for name, mock in spies.items():
        assert mock.call_count == 0, name
        if isinstance(mock, AsyncMock):
            assert mock.await_count == 0, name


@pytest.fixture
def points_payload() -> dict:
    return _load(_POINTS)


@pytest.fixture
def one_sided_payload() -> dict:
    return _load(_ONE_SIDED)


@pytest.fixture
def service() -> OddsSnapshotService:
    return OddsSnapshotService()


def _install(monkeypatch, db: _FakeDB, cache: _FakeCache) -> None:
    monkeypatch.setattr("app.services.bulk_props.db_service", db)
    monkeypatch.setattr("app.services.bulk_props.cache_service", cache)


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _player(body: dict, market: str, name: str) -> dict:
    found = next(item for item in body["markets"] if item["market"] == market)
    return next(item for item in found["players"] if item["player"] == name)


def _assert_matches_expected(body: dict, rows: list[dict], *, markets: set[str] | None = None, player: str | None = None) -> None:
    expected = _expected_players(rows)
    if markets is not None:
        expected = {key: value for key, value in expected.items() if key[0] in markets}
    if player is not None:
        wanted = player.casefold()
        expected = {key: value for key, value in expected.items() if key[1].casefold() == wanted}

    seen = {}
    for market in body["markets"]:
        for item in market["players"]:
            seen[(market["market"], item["player"])] = item
    assert set(seen) == set(expected)

    for key, spec in expected.items():
        actual = seen[key]
        assert actual["bookmakers_count"] == spec["bookmakers_count"]
        assert actual["bookmakers_count"] == len(actual["books"])
        assert actual["line"] == pytest.approx(spec["line"])
        assert [book["bookmaker"] for book in actual["books"]] == [
            row["bookmaker"] for row in spec["books"]
        ]
        for book, row in zip(actual["books"], spec["books"]):
            assert book["line"] == pytest.approx(float(row["line"]))
            if key[0] == "player_double_double":
                assert book["over_odds"] is None
                assert book["under_odds"] is None
                assert book["yes_odds"] == row["over_odds"]
                assert book["no_odds"] == row["under_odds"]
            else:
                assert book["over_odds"] == row["over_odds"]
                assert book["under_odds"] == row["under_odds"]
                assert book["yes_odds"] is None
                assert book["no_odds"] is None


@pytest.mark.asyncio
async def test_multiple_markets_one_stored_vote_per_book(
    client, monkeypatch, odds_spies, service, points_payload, one_sided_payload
):
    event_id = points_payload["id"]
    point_rows = _parse(service, points_payload["bookmakers"], event_id, points_payload, _SNAPSHOT_AT)
    dd_rows = _binary_snapshot_rows(one_sided_payload, _SNAPSHOT_AT, event_id)
    binary = assemble_bulk_props(event_id, dd_rows, now=_SNAPSHOT_AT)
    binary_body = binary.model_dump(mode="json")
    assert [market["market"] for market in binary_body["markets"]] == ["player_double_double"]
    jokic_direct = binary_body["markets"][0]["players"][0]
    direct_books = {book["bookmaker"]: book for book in jokic_direct["books"]}
    assert direct_books["fanduel"]["yes_odds"] == -240
    assert direct_books["fanduel"]["no_odds"] is None
    assert direct_books["fanduel"]["over_odds"] is None
    assert direct_books["draftkings"]["yes_odds"] == -250
    assert direct_books["draftkings"]["no_odds"] == 200
    assert jokic_direct["line"] == pytest.approx(0.5)
    rows = point_rows + dd_rows
    db = _FakeDB(rows)
    _install(monkeypatch, db, _FakeCache())

    response = await client.get(f"/api/nba/events/{event_id}/props")

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == event_id
    assert body["source"] == "snapshot"
    assert body["snapshot_at"] is not None
    assert body["data_age_seconds"] >= 0
    assert [market["market"] for market in body["markets"]] == [
        "player_points",
        "player_double_double",
    ]
    _assert_matches_expected(body, rows)

    wiggins = _player(body, "player_points", "Aaron Wiggins")
    raw_points = _raw_over_points(points_payload, "Aaron Wiggins")
    assert raw_points > wiggins["bookmakers_count"]
    assert wiggins["bookmakers_count"] == 6
    assert len({book["bookmaker"] for book in wiggins["books"]}) == 6

    jokic = _player(body, "player_double_double", "Nikola Jokic")
    by_book = {book["bookmaker"]: book for book in jokic["books"]}
    assert by_book["fanduel"]["yes_odds"] == -240
    assert by_book["fanduel"]["no_odds"] is None
    assert by_book["draftkings"]["yes_odds"] == -250
    assert by_book["draftkings"]["no_odds"] == 200
    assert jokic["line"] == pytest.approx(0.5)
    assert db.calls == [(LATEST_EVENT_SNAPSHOT_SQL, (event_id,))]
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_alternate_rows_count_one_vote_and_pick_the_main_line(
    client, monkeypatch, odds_spies, service, points_payload
):
    rows = _alternate_point_rows(service, points_payload, _SNAPSHOT_AT)
    event_id = points_payload["id"]
    db = _FakeDB(rows)
    _install(monkeypatch, db, _FakeCache())

    response = await client.get(f"/api/nba/events/{event_id}/props")

    assert response.status_code == 200
    body = response.json()
    _assert_matches_expected(body, rows)

    wiggins_rows = [
        row for row in rows
        if row["player_name"] == "Aaron Wiggins" and row["bookmaker"] == "bovada"
    ]
    assert len(wiggins_rows) > 1
    voted = min(wiggins_rows, key=_vote_key)
    last_line = wiggins_rows[-1]["line"]
    assert float(voted["line"]) != float(last_line)
    wiggins = _player(body, "player_points", "Aaron Wiggins")
    bovada = next(book for book in wiggins["books"] if book["bookmaker"] == "bovada")
    assert bovada["line"] == pytest.approx(float(voted["line"]))
    assert wiggins["bookmakers_count"] == 6
    assert wiggins["bookmakers_count"] < len(
        [row for row in rows if row["player_name"] == "Aaron Wiggins"]
    )
    direct = _main_book_line(wiggins_rows)
    assert direct["line"] == voted["line"]
    assert direct["bookmaker"] == "bovada"
    luka_rows = [
        row for row in rows
        if row["player_name"] == "Luka Doncic" and row["bookmaker"] == "bovada"
    ]
    luka = _main_book_line(luka_rows)
    assert float(luka["line"]) == pytest.approx(36.5)
    assert luka["over_odds"] == -115
    assert luka["under_odds"] == -115
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_markets_and_player_filters(
    client, monkeypatch, odds_spies, service, points_payload, one_sided_payload
):
    event_id = points_payload["id"]
    rows = _parse(service, points_payload["bookmakers"], event_id, points_payload, _SNAPSHOT_AT)
    rows += _binary_snapshot_rows(one_sided_payload, _SNAPSHOT_AT, event_id)
    db = _FakeDB(rows)
    _install(monkeypatch, db, _FakeCache())

    points = await client.get(
        f"/api/nba/events/{event_id}/props",
        params={"markets": "player_points"},
    )
    assert points.status_code == 200
    points_body = points.json()
    assert [market["market"] for market in points_body["markets"]] == ["player_points"]
    _assert_matches_expected(points_body, rows, markets={"player_points"})

    binary = await client.get(
        f"/api/nba/events/{event_id}/props",
        params={"markets": "player_points, player_double_double"},
    )
    assert binary.status_code == 200
    assert [market["market"] for market in binary.json()["markets"]] == [
        "player_points",
        "player_double_double",
    ]

    named = await client.get(
        f"/api/nba/events/{event_id}/props",
        params={"player": "luka doncic"},
    )
    assert named.status_code == 200
    named_body = named.json()
    assert named_body["snapshot_at"] is not None
    assert [market["market"] for market in named_body["markets"]] == ["player_points"]
    assert [item["player"] for item in named_body["markets"][0]["players"]] == ["Luka Doncic"]

    missing = await client.get(
        f"/api/nba/events/{event_id}/props",
        params={"player": "Nobody Here"},
    )
    assert missing.status_code == 200
    missing_body = missing.json()
    assert missing_body["markets"] == []
    assert missing_body["snapshot_at"] is not None
    assert missing_body["source"] == "snapshot"

    steals = await client.get(
        f"/api/nba/events/{event_id}/props",
        params={"markets": "player_steals"},
    )
    assert steals.status_code == 200
    assert steals.json()["markets"] == []
    assert steals.json()["snapshot_at"] is not None

    unknown = await client.get(
        f"/api/nba/events/{event_id}/props",
        params={"markets": "player_points,not_a_market"},
    )
    assert unknown.status_code == 400
    assert "not_a_market" in unknown.json()["detail"]
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_no_snapshot_is_empty_200(client, monkeypatch, odds_spies):
    event_id = "07361a8381206817e27bd2697fad7479"
    db = _FakeDB([])
    _install(monkeypatch, db, _FakeCache())

    response = await client.get(f"/api/nba/events/{event_id}/props")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "event_id": event_id,
        "snapshot_at": None,
        "data_age_seconds": None,
        "source": "snapshot",
        "markets": [],
    }
    assert db.calls == [(LATEST_EVENT_SNAPSHOT_SQL, (event_id,))]
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
@pytest.mark.parametrize("event_id", ["!!!", "bad id", "a.b", "a..b"])
async def test_malformed_event_id_is_404(client, monkeypatch, odds_spies, event_id):
    db = _FakeDB([{"snapshot_at": _SNAPSHOT_AT, "player_name": "Luka Doncic"}])
    _install(monkeypatch, db, _FakeCache())

    response = await client.get(f"/api/nba/events/{event_id}/props")

    assert response.status_code == 404
    assert response.json()["detail"] == "Malformed event_id"
    assert db.calls == []
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_database_down_and_query_failure_do_not_call_odds(client, monkeypatch, odds_spies):
    event_id = "abc123"
    down = _FakeDB([], connected=False)
    cache = _FakeCache()
    _install(monkeypatch, down, cache)

    unavailable = await client.get(f"/api/nba/events/{event_id}/props")
    assert unavailable.status_code == 503
    assert down.calls == []

    broken = _FakeDB([], error=RuntimeError("connection reset"))
    _install(monkeypatch, broken, _FakeCache())
    failed = await client.get(f"/api/nba/events/{event_id}/props")
    assert failed.status_code == 500
    assert failed.json()["detail"] == "Failed to read odds snapshots"
    assert broken.calls == [(LATEST_EVENT_SNAPSHOT_SQL, (event_id,))]
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_cache_skips_the_second_postgres_read_and_refreshes_age(
    monkeypatch, odds_spies, service, points_payload
):
    event_id = points_payload["id"]
    rows = _parse(service, points_payload["bookmakers"], event_id, points_payload, _SNAPSHOT_AT)
    db = _FakeDB(rows)
    cache = _FakeCache()
    _install(monkeypatch, db, cache)

    first_clock = _SNAPSHOT_AT + timedelta(seconds=10)
    first = await get_event_bulk_props(event_id, now=first_clock)
    assert first.data_age_seconds == 10
    assert len(db.calls) == 1
    assert cache.sets[0][2] == BULK_PROPS_CACHE_TTL_SECONDS == 60

    second_clock = _SNAPSHOT_AT + timedelta(seconds=40)
    second = await get_event_bulk_props(event_id, now=second_clock)
    assert second.data_age_seconds == 40
    assert second.snapshot_at == first.snapshot_at
    assert len(db.calls) == 1
    assert second.model_dump(exclude={"data_age_seconds"}) == first.model_dump(
        exclude={"data_age_seconds"}
    )
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_latest_snapshot_drops_older_books(
    client, monkeypatch, odds_spies, service, points_payload
):
    event_id = points_payload["id"]
    early = _parse(service, points_payload["bookmakers"], event_id, points_payload, _EARLIER)
    fanduel = [book for book in points_payload["bookmakers"] if book["key"] == "fanduel"]
    late = _parse(service, fanduel, event_id, points_payload, _SNAPSHOT_AT)
    db = _FakeDB(early + late)
    _install(monkeypatch, db, _FakeCache())

    response = await client.get(f"/api/nba/events/{event_id}/props")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_at"].startswith("2026-11-09T21:34:00")
    luka = _player(body, "player_points", "Luka Doncic")
    assert luka["bookmakers_count"] == 1
    assert luka["books"][0]["bookmaker"] == "fanduel"
    _assert_matches_expected(body, early + late)
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_unreadable_cache_entry_falls_through_to_postgres(
    monkeypatch, odds_spies, service, points_payload
):
    event_id = points_payload["id"]
    rows = _parse(service, points_payload["bookmakers"], event_id, points_payload, _SNAPSHOT_AT)
    db = _FakeDB(rows)
    cache = _FakeCache()
    cache.store[f"nba:bulk-props:v1:{event_id}:m=*:p=*"] = {"markets": "nope"}
    _install(monkeypatch, db, cache)

    payload = await get_event_bulk_props(event_id, now=_SNAPSHOT_AT + timedelta(seconds=5))

    assert payload.source == "snapshot"
    assert payload.markets
    assert len(db.calls) == 1
    _assert_no_live_calls(odds_spies)


def test_bulk_props_module_does_not_reference_the_odds_api():
    source = _SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    banned_modules = {
        "app.services.odds_gateway",
        "app.services.odds_provider",
        "app.services.odds_theoddsapi",
        "httpx",
    }
    assert banned_modules.isdisjoint(imported)
    for token in (
        "get_market_snapshot",
        "get_event_odds",
        "the-odds-api",
        "ODDS_API",
        "odds_gateway",
        "odds_provider",
    ):
        assert token not in source

    handler = inspect.getsource(
        inspect.unwrap(
            __import__("app.api.nba", fromlist=["get_event_props"]).get_event_props
        )
    )
    for token in ("odds_gateway", "odds_provider", "get_market_snapshot", "get_event_odds", "httpx"):
        assert token not in handler
