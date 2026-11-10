"""QA coverage for SPO-114 bulk props.

These tests add edges the route's own file does not pin: latest-capture
ties, the 60s cache key, Redis and Postgres failures, vig math on the
recorded Odds API body, and parity with SPO-115's ``_main_book_line``.

Prices and outcome objects come from
``backend/tests/fixtures/odds_api_event_odds__player_points.json`` and
from the recorded no-vig file
``player-double-double-one-sided.json``. Stored-row dicts below are the
``odds_line_snapshots`` shape the route reads. They are not Odds API
payloads. The no-vig file is not passed through ``rows_from_bookmakers``.
"""

from __future__ import annotations

import ast
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
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
    bulk_props_cache_key,
    event_id_is_well_formed,
    get_event_bulk_props,
)
from app.services.odds_snapshot_service import (
    BINARY_MARKET_KEYS,
    OVER_UNDER_MARKET_KEYS,
    OddsSnapshotService,
)
from app.services.prob import (
    american_to_prob,
    calculate_vig,
    devig,
    posted_american_odds,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_POINTS = _FIXTURES / "odds_api_event_odds__player_points.json"
_ONE_SIDED = _FIXTURES / "player-double-double-one-sided.json"
_BACKEND = Path(__file__).resolve().parents[1]
_SNAPSHOT_AT = datetime(2026, 11, 9, 21, 34, tzinfo=timezone.utc)
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
    return json_loads(path)


def json_loads(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _as_dicts(rows: list[tuple]) -> list[dict]:
    return [dict(zip(_ROW_KEYS, row)) for row in rows]


def _outcomes_by_player(book: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for outcome in book["markets"][0]["outcomes"]:
        grouped[outcome["description"]].append(outcome)
    return grouped


def _rung_rows(book: dict, player: str, outcomes: list[dict]) -> list[dict]:
    """One stored row per recorded point, using that point's own prices."""
    sides: dict[float, dict[str, dict]] = defaultdict(dict)
    for outcome in outcomes:
        sides[float(outcome["point"])][outcome["name"].lower()] = outcome
    rows = []
    for point, pair in sides.items():
        over = pair.get("over")
        under = pair.get("under")
        rows.append(
            {
                "bookmaker": book["key"],
                "player_name": player,
                "market": book["markets"][0]["key"],
                "line": point,
                "over_odds": None if over is None else over["price"],
                "under_odds": None if under is None else under["price"],
            }
        )
    return rows


# --- SPO-115 reference, copied from daily_analysis.py on
# origin/feature/SPO-115-bookmakers-count (ec3c012). Not imported: that
# branch is not on this PR. The copy is the parity oracle. ---


def _spo115_even_money_distance(over: float | None, under: float | None) -> float:
    if over is not None and under is not None:
        p_over = american_to_prob(over)
        p_under = american_to_prob(under)
        total = p_over + p_under
        if total <= 0:
            return 1.0
        return abs((p_over / total) - 0.5)
    price = over if over is not None else under
    if price is None:
        return 1.0
    return abs(american_to_prob(price) - 0.5)


def _spo115_posted_point(points: list[float]) -> float:
    rounded = [round(point, 1) for point in points]
    counts = Counter(rounded)
    most = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == most)
    if len(modes) % 2 == 1:
        return float(modes[len(modes) // 2])
    return float(modes[(len(modes) // 2) - 1])


def _spo115_main_book_line(outcomes: list[dict[str, Any]]) -> float | None:
    rungs: dict[float, dict[str, float | None]] = {}
    bare_points: list[float] = []
    for outcome in outcomes:
        raw_point = outcome.get("point")
        if raw_point is None:
            continue
        try:
            point = round(float(raw_point), 1)
        except (TypeError, ValueError):
            continue
        bare_points.append(point)
        side = str(outcome.get("name") or "").strip().lower()
        price = posted_american_odds(outcome.get("price"))
        rung = rungs.setdefault(point, {"over": None, "under": None})
        if side in ("over", "under") and price is not None:
            previous = rung[side]
            if (
                previous is None
                or _spo115_even_money_distance(price, None)
                < _spo115_even_money_distance(previous, None)
            ):
                rung[side] = price
    if not bare_points:
        return None
    two_sided = [
        point
        for point, rung in rungs.items()
        if rung["over"] is not None and rung["under"] is not None
    ]
    priced = [
        point
        for point, rung in rungs.items()
        if rung["over"] is not None or rung["under"] is not None
    ]
    candidates = two_sided or priced
    if not candidates:
        return _spo115_posted_point(bare_points)

    def _sort_key(point: float) -> tuple[float, float]:
        rung = rungs[point]
        return (_spo115_even_money_distance(rung["over"], rung["under"]), point)

    return float(min(candidates, key=_sort_key))


def _origin_dev_inline_rows(
    service: OddsSnapshotService,
    bookmakers_data: list[dict],
    *,
    event_id: str,
    home_team: str,
    away_team: str,
    date: str,
    snapshot_at: datetime,
) -> list[tuple]:
    """Parser body of ``_process_event`` on origin/dev (a14370d).

    The loop is the code that lived inline after the gateway fetch, before
    SPO-114 moved it into ``rows_from_bookmakers``. ``_parse_binary_market``
    is called on the service because that helper was not part of the move
    and is byte-identical with origin/dev. The player_points recording has
    no binary market, so this suite's fixture comparison exercises the
    moved Over/Under loop.
    """
    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    rows: list[tuple] = []
    for bookmaker in bookmakers_data:
        bookmaker_key = bookmaker.get("key", "unknown")
        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            if market_key in BINARY_MARKET_KEYS:
                rows.extend(
                    service._parse_binary_market(
                        market=market,
                        market_key=market_key,
                        bookmaker_key=bookmaker_key,
                        snapshot_at=snapshot_at,
                        date_obj=date_obj,
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                    )
                )
                continue
            if market_key not in OVER_UNDER_MARKET_KEYS:
                continue
            player_outcomes: dict[str, dict[str, Any]] = {}
            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description", "")
                direction = outcome.get("name", "").lower()
                if not player_name or direction not in ("over", "under"):
                    continue
                player_outcomes.setdefault(player_name, {})[direction] = outcome
            for player_name, directions in player_outcomes.items():
                over_out = directions.get("over")
                under_out = directions.get("under")
                if not over_out or not under_out:
                    continue
                line = over_out.get("point")
                over_price = over_out.get("price", 0)
                under_price = under_out.get("price", 0)
                if line is None or over_price == 0 or under_price == 0:
                    continue
                try:
                    p_over_imp = american_to_prob(over_price)
                    p_under_imp = american_to_prob(under_price)
                    vig = calculate_vig(p_over_imp, p_under_imp)
                    p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)
                    rows.append(
                        (
                            snapshot_at,
                            date_obj,
                            event_id,
                            home_team,
                            away_team,
                            player_name,
                            market_key,
                            bookmaker_key,
                            float(line),
                            int(over_price),
                            int(under_price),
                            round(vig, 6),
                            round(p_over_fair, 6),
                            round(p_under_fair, 6),
                        )
                    )
                except (ValueError, ZeroDivisionError):
                    continue
    return rows


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
        self.gets: list[str] = []

    async def get(self, key: str):
        self.gets.append(key)
        return self.store.get(key)

    async def set(self, key: str, value, ttl: int) -> bool:
        self.sets.append((key, value, ttl))
        self.store[key] = value
        return True


class _Snapshot:
    def __init__(self, data: dict):
        self.data = data


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.middleware.rate_limit import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def odds_spies(monkeypatch):
    """Patch the live Odds API call sites and count every use."""
    from app.services.odds_gateway import OddsMarketGateway, odds_gateway
    from app.services.odds_theoddsapi import TheOddsAPIProvider, odds_provider
    import app.services.odds_snapshot_service as snap_mod
    import app.services.odds_theoddsapi as odds_mod
    import app.api.nba as nba_api

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
    spies["sites"] = {
        "snapshot_gateway": snap_mod.odds_gateway.get_market_snapshot,
        "snapshot_event_odds": snap_mod.odds_provider.get_event_odds,
        "snapshot_events": snap_mod.odds_provider.get_events,
        "snapshot_usage": snap_mod.odds_provider.get_event_odds_with_usage,
        "route_gateway": nba_api.odds_gateway.get_market_snapshot,
        "route_event_odds": nba_api.odds_provider.get_event_odds,
        "httpx": odds_mod.httpx.AsyncClient,
    }
    return spies


def _assert_no_live_calls(spies: dict) -> None:
    for name, mock in spies.items():
        if name == "sites":
            continue
        assert mock.call_count == 0, name
        if isinstance(mock, AsyncMock):
            assert mock.await_count == 0, name


def _install(monkeypatch, db: _FakeDB, cache: _FakeCache) -> None:
    monkeypatch.setattr("app.services.bulk_props.db_service", db)
    monkeypatch.setattr("app.services.bulk_props.cache_service", cache)


@pytest.fixture
def points_payload() -> dict:
    return _load(_POINTS)


@pytest.fixture
def one_sided_payload() -> dict:
    return _load(_ONE_SIDED)


@pytest.fixture
def service() -> OddsSnapshotService:
    return OddsSnapshotService()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _parse(service: OddsSnapshotService, payload: dict, snapshot_at: datetime) -> list[dict]:
    rows = service.rows_from_bookmakers(
        payload["bookmakers"],
        event_id=payload["id"],
        home_team=payload["home_team"],
        away_team=payload["away_team"],
        date=_DATE,
        snapshot_at=snapshot_at,
    )
    return _as_dicts(rows)


def test_odds_spies_sit_on_the_live_call_sites(odds_spies):
    sites = odds_spies["sites"]
    assert sites["snapshot_gateway"] is odds_spies["gateway"]
    assert sites["snapshot_event_odds"] is odds_spies["event_odds"]
    assert sites["snapshot_events"] is odds_spies["events"]
    assert sites["snapshot_usage"] is odds_spies["usage"]
    assert sites["route_gateway"] is odds_spies["gateway"]
    assert sites["route_event_odds"] is odds_spies["event_odds"]
    assert sites["httpx"] is odds_spies["httpx"]


@pytest.mark.asyncio
async def test_a_snapshot_gateway_call_increments_the_spy(odds_spies):
    import app.services.odds_snapshot_service as snap_mod

    await snap_mod.odds_gateway.get_market_snapshot(
        sport="basketball_nba",
        event_id="07361a8381206817e27bd2697fad7479",
    )
    assert odds_spies["gateway"].await_count == 1
    assert odds_spies["usage"].await_count == 0
    assert odds_spies["httpx"].call_count == 0


def test_bulk_props_source_cannot_name_an_http_client():
    source = (_BACKEND / "app" / "services" / "bulk_props.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "httpx" not in source
    assert "wnba" not in source.lower()
    assert "basketball_wnba" not in source
    for token in (
        "get_market_snapshot",
        "get_event_odds",
        "the-odds-api",
        "odds_gateway",
        "odds_provider",
        "httpx",
        "requests",
    ):
        assert token not in source
    assert {"httpx", "app.services.odds_gateway", "app.services.odds_theoddsapi"}.isdisjoint(
        imported
    )


def test_latest_sql_keeps_only_the_max_snapshot_for_that_event():
    assert "MAX(snapshot_at)" in LATEST_EVENT_SNAPSHOT_SQL
    assert LATEST_EVENT_SNAPSHOT_SQL.count("event_id = $1") == 2
    assert "league" not in LATEST_EVENT_SNAPSHOT_SQL.lower()
    schema = (_BACKEND / "app" / "services" / "db.py").read_text(encoding="utf-8")
    assert "UNIQUE(snapshot_at, event_id, player_name, market, bookmaker)" in schema


def test_rows_from_bookmakers_matches_the_dev_inline_parser(service, points_payload):
    kwargs = dict(
        event_id=points_payload["id"],
        home_team=points_payload["home_team"],
        away_team=points_payload["away_team"],
        date=_DATE,
        snapshot_at=_SNAPSHOT_AT,
    )
    moved = service.rows_from_bookmakers(points_payload["bookmakers"], **kwargs)
    dev_rows = _origin_dev_inline_rows(service, points_payload["bookmakers"], **kwargs)
    assert moved == dev_rows
    assert moved

    bovada = next(book for book in points_payload["bookmakers"] if book["key"] == "bovada")
    last_over = None
    for outcome in bovada["markets"][0]["outcomes"]:
        if outcome["description"] == "Luka Doncic" and outcome["name"] == "Over":
            last_over = outcome
    stored = next(
        row
        for row in _as_dicts(moved)
        if row["bookmaker"] == "bovada" and row["player_name"] == "Luka Doncic"
    )
    assert stored["line"] == float(last_over["point"])
    assert stored["over_odds"] == int(last_over["price"])
    assert len(
        [
            row
            for row in _as_dicts(moved)
            if row["bookmaker"] == "bovada" and row["player_name"] == "Luka Doncic"
        ]
    ) == 1


def test_recorded_rows_use_multiplicative_devig_and_drop_one_sided_pairs(service, points_payload):
    rows = _parse(service, points_payload, _SNAPSHOT_AT)
    assert rows
    for row in rows:
        assert math.isfinite(row["vig"])
        assert math.isfinite(row["over_fair_prob"])
        assert math.isfinite(row["under_fair_prob"])
        p_over = american_to_prob(row["over_odds"])
        p_under = american_to_prob(row["under_odds"])
        fair_over, fair_under = devig(p_over, p_under)
        assert row["vig"] == pytest.approx(round(calculate_vig(p_over, p_under), 6))
        assert row["over_fair_prob"] == pytest.approx(round(fair_over, 6))
        assert row["under_fair_prob"] == pytest.approx(round(fair_under, 6))
        assert row["over_fair_prob"] + row["under_fair_prob"] == pytest.approx(1.0)
        assert not math.isnan(row["over_fair_prob"])

    equal = next(row for row in rows if row["over_odds"] == row["under_odds"])
    assert equal["over_fair_prob"] == pytest.approx(0.5)
    assert equal["under_fair_prob"] == pytest.approx(0.5)

    fanduel = next(book for book in points_payload["bookmakers"] if book["key"] == "fanduel")
    overs_only = {
        "key": fanduel["key"],
        "markets": [
            {
                "key": fanduel["markets"][0]["key"],
                "outcomes": [
                    outcome
                    for outcome in fanduel["markets"][0]["outcomes"]
                    if outcome["name"] == "Over"
                ],
            }
        ],
    }
    assert service.rows_from_bookmakers(
        [overs_only],
        event_id=points_payload["id"],
        home_team=points_payload["home_team"],
        away_team=points_payload["away_team"],
        date=_DATE,
        snapshot_at=_SNAPSHOT_AT,
    ) == []


@pytest.mark.asyncio
async def test_process_event_delegates_and_stays_on_nba(monkeypatch, service, points_payload, odds_spies):
    import app.services.odds_snapshot_service as snap_mod

    calls = []

    async def _fake_snapshot(**kwargs):
        calls.append(kwargs)
        return _Snapshot({"bookmakers": points_payload["bookmakers"]})

    monkeypatch.setattr(snap_mod.odds_gateway, "get_market_snapshot", _fake_snapshot)
    delegated = await service._process_event(
        points_payload["id"],
        points_payload["home_team"],
        points_payload["away_team"],
        _DATE,
        _SNAPSHOT_AT,
    )
    direct = service.rows_from_bookmakers(
        points_payload["bookmakers"],
        event_id=points_payload["id"],
        home_team=points_payload["home_team"],
        away_team=points_payload["away_team"],
        date=_DATE,
        snapshot_at=_SNAPSHOT_AT,
    )
    assert delegated == direct
    assert calls[0]["sport"] == "basketball_nba"
    assert calls[0]["event_id"] == points_payload["id"]
    assert odds_spies["httpx"].call_count == 0
    assert odds_spies["usage"].await_count == 0


def test_recorded_fixture_line_parity_with_spo115(points_payload):
    """Every recorded (book, player) vote matches the SPO-115 oracle.

    Luka's Bovada vote is the two-sided 36.5 at -115/-115. The previous
    pin recorded seven Bovada ladders where a raw Over-implied distance
    picked the next total up. That difference is the bug this fixes.
    """
    seen = {}
    luka = None
    for book in points_payload["bookmakers"]:
        for player, outcomes in _outcomes_by_player(book).items():
            chosen = _main_book_line(_rung_rows(book, player, outcomes))
            local = float(chosen["line"])
            other = _spo115_main_book_line(outcomes)
            seen[(book["key"], player)] = (local, other)
            if book["key"] == "bovada" and player == "Luka Doncic":
                luka = chosen

    disagreements = {
        key: lines for key, lines in seen.items() if lines[0] != pytest.approx(lines[1])
    }
    assert disagreements == {}
    assert len(seen) == 87
    assert luka is not None
    assert float(luka["line"]) == pytest.approx(36.5)
    assert luka["over_odds"] == -115
    assert luka["under_odds"] == -115


def test_tie_break_lower_point_agrees_when_both_sides_match(points_payload):
    bovada = next(book for book in points_payload["bookmakers"] if book["key"] == "bovada")
    luka = _outcomes_by_player(bovada)["Luka Doncic"]
    by_point = defaultdict(dict)
    for outcome in luka:
        by_point[float(outcome["point"])][outcome["name"].lower()] = outcome
    even = by_point[36.5]
    higher_point = 37.5
    rows = [
        {
            "line": 36.5,
            "over_odds": even["over"]["price"],
            "under_odds": even["under"]["price"],
        },
        {
            "line": higher_point,
            "over_odds": even["over"]["price"],
            "under_odds": even["under"]["price"],
        },
    ]
    outcomes = [
        {"name": "Over", "point": 36.5, "price": even["over"]["price"]},
        {"name": "Under", "point": 36.5, "price": even["under"]["price"]},
        {"name": "Over", "point": higher_point, "price": even["over"]["price"]},
        {"name": "Under", "point": higher_point, "price": even["under"]["price"]},
    ]
    assert float(_main_book_line(rows)["line"]) == pytest.approx(36.5)
    assert _spo115_main_book_line(outcomes) == pytest.approx(36.5)


def test_equal_devig_distance_keeps_the_lower_point():
    """+100/-100 and -100/+100 are the same price after the vig is removed.

    The distances tie, so both helpers keep the lower posted point.
    The previous pin expected the local helper to prefer the price
    nearer -110 (11.5). That tie-break is not the SPO-115 rule.
    """
    rows = [
        {"line": 10.5, "over_odds": 100, "under_odds": -100},
        {"line": 11.5, "over_odds": -100, "under_odds": 100},
    ]
    outcomes = [
        {"name": "Over", "point": 10.5, "price": 100},
        {"name": "Under", "point": 10.5, "price": -100},
        {"name": "Over", "point": 11.5, "price": -100},
        {"name": "Under", "point": 11.5, "price": 100},
    ]
    assert float(_main_book_line(rows)["line"]) == pytest.approx(10.5)
    assert _spo115_main_book_line(outcomes) == pytest.approx(10.5)


def test_two_sided_rung_beats_a_one_sided_over(points_payload):
    bovada = next(book for book in points_payload["bookmakers"] if book["key"] == "bovada")
    by_point = defaultdict(dict)
    for outcome in _outcomes_by_player(bovada)["Luka Doncic"]:
        by_point[float(outcome["point"])][outcome["name"].lower()] = outcome
    one_sided_point = 37.5
    two_sided_point = 36.5
    rows = [
        {
            "line": one_sided_point,
            "over_odds": by_point[one_sided_point]["over"]["price"],
            "under_odds": None,
        },
        {
            "line": two_sided_point,
            "over_odds": by_point[two_sided_point]["over"]["price"],
            "under_odds": by_point[two_sided_point]["under"]["price"],
        },
    ]
    outcomes = [
        {
            "name": "Over",
            "point": one_sided_point,
            "price": by_point[one_sided_point]["over"]["price"],
        },
        {
            "name": "Over",
            "point": two_sided_point,
            "price": by_point[two_sided_point]["over"]["price"],
        },
        {
            "name": "Under",
            "point": two_sided_point,
            "price": by_point[two_sided_point]["under"]["price"],
        },
    ]
    assert float(_main_book_line(rows)["line"]) == pytest.approx(two_sided_point)
    assert _spo115_main_book_line(outcomes) == pytest.approx(two_sided_point)


def test_duplicate_same_side_keeps_the_price_closer_to_even(points_payload):
    bovada = next(book for book in points_payload["bookmakers"] if book["key"] == "bovada")
    by_point = defaultdict(dict)
    for outcome in _outcomes_by_player(bovada)["Luka Doncic"]:
        by_point[float(outcome["point"])][outcome["name"].lower()] = outcome
    closer = by_point[36.5]["over"]["price"]
    farther = by_point[41.5]["over"]["price"]
    under = by_point[36.5]["under"]["price"]
    rows = [
        {"line": 36.5, "over_odds": farther, "under_odds": under},
        {"line": 36.5, "over_odds": closer, "under_odds": under},
    ]
    outcomes = [
        {"name": "Over", "point": 36.5, "price": farther},
        {"name": "Over", "point": 36.5, "price": closer},
        {"name": "Under", "point": 36.5, "price": under},
    ]
    assert _main_book_line(rows)["over_odds"] == closer
    assert _spo115_main_book_line(outcomes) == pytest.approx(36.5)
    assert _spo115_even_money_distance(closer, None) < _spo115_even_money_distance(farther, None)


def test_posted_point_fallback_is_the_mode(points_payload):
    bovada = next(book for book in points_payload["bookmakers"] if book["key"] == "bovada")
    points = []
    for outcome in _outcomes_by_player(bovada)["Luka Doncic"]:
        if outcome["name"] == "Over" and float(outcome["point"]) in (36.5, 37.5):
            points.append(float(outcome["point"]))
    assert points.count(37.5) == 1
    rows = [
        {"line": 36.5, "over_odds": None, "under_odds": None},
        {"line": 37.5, "over_odds": None, "under_odds": None},
        {"line": 37.5, "over_odds": None, "under_odds": None},
    ]
    outcomes = [
        {"name": "Over", "point": 36.5, "price": None},
        {"name": "Under", "point": 37.5, "price": None},
        {"name": "Over", "point": 37.5, "price": None},
    ]
    assert float(_main_book_line(rows)["line"]) == pytest.approx(37.5)
    assert _spo115_main_book_line(outcomes) == pytest.approx(37.5)


def test_non_finite_over_price_does_not_raise():
    """NaN and Infinity are missing prices. Neither raises.

    The previous pin expected ``OverflowError`` from ``int(float("inf"))``.
    ``_as_int`` now returns None for both, so the two-sided finite rung
    is the vote.
    """
    chosen = _main_book_line(
        [
            {"line": 41.5, "over_odds": float("nan"), "under_odds": -110},
            {"line": 36.5, "over_odds": -115, "under_odds": -115},
        ]
    )
    assert chosen["line"] == pytest.approx(36.5)
    infinite = _main_book_line(
        [
            {"line": 36.5, "over_odds": float("inf"), "under_odds": -115},
            {"line": 37.5, "over_odds": -115, "under_odds": -115},
        ]
    )
    assert infinite["line"] == pytest.approx(37.5)


def test_writer_stores_the_last_rung_so_the_read_collapse_never_sees_it(service, points_payload):
    rows = _parse(service, points_payload, _SNAPSHOT_AT)
    payload = assemble_bulk_props(points_payload["id"], rows, now=_SNAPSHOT_AT)
    market = payload.markets[0]
    assert market.market == "player_points"
    for player_name in ("Luka Doncic", "Aaron Wiggins", "Austin Reaves"):
        bovada = next(book for book in points_payload["bookmakers"] if book["key"] == "bovada")
        last_over = None
        for outcome in bovada["markets"][0]["outcomes"]:
            if outcome["description"] == player_name and outcome["name"] == "Over":
                last_over = outcome
        player = next(item for item in market.players if item.player == player_name)
        book = next(item for item in player.books if item.bookmaker == "bovada")
        main = _spo115_main_book_line(_outcomes_by_player(bovada)[player_name])
        assert book.line == pytest.approx(float(last_over["point"]))
        assert book.line != pytest.approx(main)
        assert player.bookmakers_count == len(player.books) == 6


def test_response_contract_fields_are_present(service, points_payload):
    rows = _parse(service, points_payload, _SNAPSHOT_AT)
    payload = assemble_bulk_props(
        points_payload["id"],
        rows,
        now=_SNAPSHOT_AT + timedelta(seconds=12),
    )
    body = payload.model_dump(mode="json")
    assert set(body) == {"event_id", "snapshot_at", "data_age_seconds", "source", "markets"}
    assert body["source"] == "snapshot"
    assert body["data_age_seconds"] == 12
    assert body["snapshot_at"].startswith("2026-11-09T21:34:00")
    book = body["markets"][0]["players"][0]["books"][0]
    assert set(book) == {
        "bookmaker",
        "line",
        "over_odds",
        "under_odds",
        "yes_odds",
        "no_odds",
    }
    assert book["yes_odds"] is None
    assert book["no_odds"] is None
    names = [item["player"] for item in body["markets"][0]["players"]]
    assert names == sorted(names, key=str.casefold)
    books = [item["bookmaker"] for item in body["markets"][0]["players"][0]["books"]]
    assert books == sorted(books, key=str.casefold)


def test_binary_stored_rows_keep_yes_and_leave_a_missing_no_null(one_sided_payload):
    rows = []
    for result in one_sided_payload["results"]:
        rows.append(
            {
                "snapshot_at": _SNAPSHOT_AT,
                "player_name": one_sided_payload["player_name"],
                "market": one_sided_payload["market"],
                "bookmaker": result["bookmaker"],
                "line": result["line"],
                "over_odds": result["yes_price"],
                "under_odds": result["no_price"],
            }
        )
    payload = assemble_bulk_props("evt-spo104-one-sided", rows, now=_SNAPSHOT_AT)
    body = payload.model_dump(mode="json")
    assert [market["market"] for market in body["markets"]] == ["player_double_double"]
    player = body["markets"][0]["players"][0]
    assert player["line"] == pytest.approx(0.5)
    by_book = {book["bookmaker"]: book for book in player["books"]}
    for result in one_sided_payload["results"]:
        book = by_book[result["bookmaker"]]
        assert book["yes_odds"] == (None if result["yes_price"] is None else int(result["yes_price"]))
        assert book["no_odds"] == (None if result["no_price"] is None else int(result["no_price"]))
        assert book["over_odds"] is None
        assert book["under_odds"] is None
        assert book["line"] == pytest.approx(result["line"])


def test_same_instant_tie_keeps_both_rows_and_an_older_capture_does_not_vote(points_payload):
    fanduel = next(book for book in points_payload["bookmakers"] if book["key"] == "fanduel")
    luka = _outcomes_by_player(fanduel)["Luka Doncic"]
    over = next(outcome for outcome in luka if outcome["name"] == "Over")
    under = next(outcome for outcome in luka if outcome["name"] == "Under")
    same_instant = _SNAPSHOT_AT.astimezone(timezone(timedelta(hours=-5)))
    assert same_instant == _SNAPSHOT_AT
    assert same_instant.utcoffset() != _SNAPSHOT_AT.utcoffset()
    rows = [
        {
            "snapshot_at": _SNAPSHOT_AT - timedelta(hours=6),
            "player_name": "Luka Doncic",
            "market": "player_points",
            "bookmaker": "fanduel",
            "line": 20.5,
            "over_odds": over["price"],
            "under_odds": under["price"],
        },
        {
            "snapshot_at": _SNAPSHOT_AT,
            "player_name": "Luka Doncic",
            "market": "player_points",
            "bookmaker": "fanduel",
            "line": float(over["point"]),
            "over_odds": over["price"],
            "under_odds": under["price"],
        },
        {
            "snapshot_at": same_instant,
            "player_name": "Luka Doncic",
            "market": "player_points",
            "bookmaker": "fanduel",
            "line": float(over["point"]) + 1,
            "over_odds": over["price"],
            "under_odds": under["price"],
        },
    ]
    payload = assemble_bulk_props(points_payload["id"], rows, now=_SNAPSHOT_AT)
    player = payload.markets[0].players[0]
    assert player.bookmakers_count == 1
    assert player.books[0].line == pytest.approx(float(over["point"]))
    assert payload.snapshot_at == _SNAPSHOT_AT


def test_cache_key_includes_event_player_and_markets():
    assert BULK_PROPS_CACHE_TTL_SECONDS == 60
    full = bulk_props_cache_key("event-a", None, None)
    other = bulk_props_cache_key("event-b", None, None)
    assert full != other
    assert "event-a" in full
    assert full.startswith("nba:bulk-props:v1:")
    assert bulk_props_cache_key("event-a", None, "Luka Doncic") == bulk_props_cache_key(
        "event-a", None, "luka doncic"
    )
    filtered = bulk_props_cache_key(
        "event-a",
        frozenset({"player_rebounds", "player_points"}),
        None,
    )
    assert "m=player_points,player_rebounds" in filtered
    assert filtered != full


@pytest.mark.asyncio
async def test_empty_capture_is_cached_and_errors_are_not(client, monkeypatch, odds_spies):
    event_id = "07361a8381206817e27bd2697fad7479"
    empty_db = _FakeDB([])
    cache = _FakeCache()
    _install(monkeypatch, empty_db, cache)

    first = await client.get(f"/api/nba/events/{event_id}/props")
    assert first.status_code == 200
    assert first.json()["markets"] == []
    assert len(cache.sets) == 1
    assert cache.sets[0][0] == f"nba:bulk-props:v1:{event_id}:m=*:p=*"
    assert cache.sets[0][2] == 60

    empty_db.rows = [
        {
            "snapshot_at": _SNAPSHOT_AT,
            "player_name": "Luka Doncic",
            "market": "player_points",
            "bookmaker": "fanduel",
            "line": 36.5,
            "over_odds": -110,
            "under_odds": -110,
        }
    ]
    second = await client.get(f"/api/nba/events/{event_id}/props")
    assert second.status_code == 200
    assert second.json()["markets"] == []
    assert len(empty_db.calls) == 1

    broken = _FakeDB([], error=RuntimeError("connection reset"))
    broken_cache = _FakeCache()
    _install(monkeypatch, broken, broken_cache)
    failed = await client.get(f"/api/nba/events/{event_id}/props")
    assert failed.status_code == 500
    assert broken_cache.sets == []

    down = _FakeDB([], connected=False)
    down_cache = _FakeCache()
    _install(monkeypatch, down, down_cache)
    unavailable = await client.get(f"/api/nba/events/{event_id}/props")
    assert unavailable.status_code == 503
    assert down.calls == []
    assert down_cache.sets == []
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_redis_down_still_reads_postgres_and_does_not_call_odds(
    monkeypatch, odds_spies, service, points_payload
):
    from app.services.cache import cache_service

    class _Down:
        async def get(self, key):
            raise ConnectionError("redis down")

        async def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

    async def _client():
        return _Down()

    monkeypatch.setattr(cache_service, "get_client", _client)
    monkeypatch.setattr("app.services.bulk_props.cache_service", cache_service)
    rows = _parse(service, points_payload, _SNAPSHOT_AT)
    db = _FakeDB(rows)
    monkeypatch.setattr("app.services.bulk_props.db_service", db)

    payload = await get_event_bulk_props(
        points_payload["id"],
        now=_SNAPSHOT_AT + timedelta(seconds=3),
    )
    assert payload.source == "snapshot"
    assert payload.markets
    assert payload.data_age_seconds == 3
    assert len(db.calls) == 1
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_id",
    ["-leading", "_leading", "a" * 129, "has space"],
)
async def test_more_malformed_ids_are_404_without_a_query(client, monkeypatch, odds_spies, event_id):
    db = _FakeDB([])
    _install(monkeypatch, db, _FakeCache())
    response = await client.get(f"/api/nba/events/{event_id}/props")
    assert response.status_code == 404
    assert response.json()["detail"] == "Malformed event_id"
    assert db.calls == []
    assert not event_id_is_well_formed(event_id)
    _assert_no_live_calls(odds_spies)


@pytest.mark.asyncio
async def test_well_formed_unknown_event_is_empty_200_and_wnba_route_is_absent(
    client, monkeypatch, odds_spies
):
    event_id = "a" * 128
    assert event_id_is_well_formed(event_id)
    db = _FakeDB([])
    _install(monkeypatch, db, _FakeCache())
    response = await client.get(f"/api/nba/events/{event_id}/props")
    assert response.status_code == 200
    assert response.json()["markets"] == []
    assert response.json()["source"] == "snapshot"
    missing = await client.get(f"/api/wnba/events/{event_id}/props")
    assert missing.status_code == 404
    _assert_no_live_calls(odds_spies)
