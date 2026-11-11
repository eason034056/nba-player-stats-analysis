"""SPO-135: no projection client, and the projection routes are gone.

Odds bodies are the recorded player_points capture. The events list is
the recorded NBA events fixture, sliced to that one game. Nothing here
calls the Odds API or any other live feed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.main import app
from app.services.odds_snapshot_service import OddsSnapshotService
from tests.fixtures.odds_api import load_odds_fixture

_APP = Path(__file__).resolve().parents[1] / "app"
_SNAPSHOT_AT = datetime(2026, 11, 9, 21, 34, tzinfo=timezone.utc)
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


class _Snap:
    def __init__(self, bookmakers):
        self.data = {"bookmakers": bookmakers}


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.is_connected = True

    async def fetch(self, query, *args):
        return self.rows


class _FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl):
        self.store[key] = value
        return True


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.middleware.rate_limit import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


def _recorded_event():
    points = load_odds_fixture("odds_api_event_odds__player_points.json")
    events = load_odds_fixture("odds_api_events__basketball_nba.json")
    match = next(event for event in events if event["id"] == points["id"])
    return points, match


def test_only_db_schema_names_the_retained_projection_tables():
    """The tables stay in SCHEMA_SQL. No other backend module names them."""
    offenders = []
    for path in sorted(_APP.rglob("*.py")):
        if path.name == "db.py":
            continue
        text = path.read_text()
        for name in ("player_projections", "projection_fetch_logs"):
            if name in text:
                offenders.append(f"{path.relative_to(_APP.parent)}:{name}")
    assert offenders == []
    schema = (_APP / "services" / "db.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS player_projections" in schema
    assert "CREATE TABLE IF NOT EXISTS projection_fetch_logs" in schema


def test_projection_routes_are_not_registered():
    transport = httpx.ASGITransport(app=app)

    async def _call():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            listed = await http.get("/api/nba/projections", params={"date": "2026-11-10"})
            one = await http.get("/api/nba/projections/Luka%20Doncic")
            refresh = await http.post("/api/nba/projections/refresh")
            return listed, one, refresh

    listed, one, refresh = asyncio.run(_call())
    assert listed.status_code == 404
    assert one.status_code == 404
    assert refresh.status_code == 404


def test_nba_daily_picks_keep_null_projection_fields(monkeypatch):
    """Recorded books and the shipped log. Projection fields stay null.

    combined_probability is still computed from the signals that remain.
    """
    points, event = _recorded_event()

    async def events(**kwargs):
        return [event]

    async def snapshot(**kwargs):
        if kwargs.get("markets") == "player_points":
            return _Snap(points["bookmakers"])
        return _Snap([])

    monkeypatch.setattr("app.services.daily_analysis.odds_provider.get_events", events)
    monkeypatch.setattr(
        "app.services.daily_analysis.odds_gateway.get_market_snapshot", snapshot
    )
    monkeypatch.setattr(
        "app.services.daily_analysis.cache_service.get", _FakeCache().get
    )
    cache = _FakeCache()
    monkeypatch.setattr("app.services.daily_analysis.cache_service.set", cache.set)

    transport = httpx.ASGITransport(app=app)

    async def _call():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.get(
                "/api/nba/daily-picks",
                params={
                    "date": "2026-11-10",
                    "tz_offset": 480,
                    "min_probability": 0.5,
                    "min_games": 5,
                },
            )

    response = asyncio.run(_call())
    assert response.status_code == 200
    body = response.json()
    assert body["picks"]
    for pick in body["picks"]:
        assert pick["has_projection"] is False
        assert pick["projected_value"] is None
        assert pick["edge"] is None
        assert pick["projected_minutes"] is None
        assert pick["injury_status"] is None
        assert pick["lineup_confirmed"] is None
    scored = [pick for pick in body["picks"] if pick["combined_probability"] is not None]
    assert scored
    assert all(pick["signals"] for pick in scored)
    for pick in scored:
        keys = [signal["key"] for signal in pick["signals"]]
        assert "projection" not in keys
        assert keys == ["market", "last10", "history", "defense"]


def test_event_reads_from_the_recorded_snapshot_omit_a_projection(monkeypatch):
    points, _event = _recorded_event()
    rows = OddsSnapshotService().rows_from_bookmakers(
        points["bookmakers"],
        event_id=points["id"],
        home_team=points["home_team"],
        away_team=points["away_team"],
        date="2026-11-09",
        snapshot_at=_SNAPSHOT_AT,
    )
    stored = [dict(zip(_ROW_KEYS, row)) for row in rows]
    monkeypatch.setattr("app.services.event_reads.db_service", _FakeDB(stored))
    monkeypatch.setattr("app.services.event_reads.cache_service", _FakeCache())

    transport = httpx.ASGITransport(app=app)

    async def _call():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            health = await http.get("/api/health")
            reads = await http.get(
                f"/api/nba/events/{points['id']}/reads",
                params={"market": "player_points"},
            )
            return health, reads

    health, reads = asyncio.run(_call())
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert reads.status_code == 200
    body = reads.json()
    assert body["source"] == "snapshot"
    assert body["reads"]
    for item in body["reads"]:
        if not item["signals"]:
            continue
        assert all(signal["key"] != "projection" for signal in item["signals"])
        assert [signal["key"] for signal in item["signals"]] == [
            "market",
            "last10",
            "history",
            "defense",
        ]
        assert item["combined_probability"] is not None
