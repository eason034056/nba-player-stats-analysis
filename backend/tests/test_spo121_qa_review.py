"""QA coverage for SPO-121: combined-probability tier, the NBA board, and the reads route.

Odds API bodies come from ``tests/fixtures`` through the recorded loader
(``odds_api_event_odds__player_points.json``). Stored picks below are our
own ``DailyPick`` rows, not Odds API responses.
"""

from __future__ import annotations

import asyncio
import copy

import httpx
import pytest
from unittest.mock import AsyncMock

from app.main import app
from app.models.schemas import DailyPick, DailyPicksResponse
from app.services.daily_analysis import (
    DailyAnalysisService,
    _with_nba_signal_verdicts,
    board_score,
    present_daily_picks,
    read_tier,
    select_daily_picks,
    sort_stored_picks,
)
from app.services.event_reads import (
    EVENT_READS_CACHE_TTL_SECONDS,
    assemble_event_reads,
    event_reads_cache_key,
    get_event_reads,
)
from app.services.odds_snapshot_service import OddsSnapshotService
from tests.fixtures.odds_api import load_odds_fixture
from datetime import datetime, timezone

_SNAPSHOT_AT = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
_ROW_KEYS = (
    "snapshot_at", "date", "event_id", "home_team", "away_team", "player_name",
    "market", "bookmaker", "line", "over_odds", "under_odds", "vig",
    "over_fair_prob", "under_fair_prob",
)


def _points_rows() -> tuple[str, list[dict]]:
    payload = load_odds_fixture("odds_api_event_odds__player_points.json")
    rows = OddsSnapshotService().rows_from_bookmakers(
        payload["bookmakers"],
        event_id=payload["id"],
        home_team=payload.get("home_team", ""),
        away_team=payload.get("away_team", ""),
        date="2026-11-09",
        snapshot_at=_SNAPSHOT_AT,
    )
    return payload["id"], [dict(zip(_ROW_KEYS, row)) for row in rows]


def _stored_picks() -> list[DailyPick]:
    payload = load_odds_fixture("odds_api_event_odds__player_points.json")
    service = DailyAnalysisService()

    async def props(event_id, market_key, league="nba"):
        if market_key != "player_points":
            return []
        return copy.deepcopy(payload["bookmakers"])

    service._get_props_for_market = props
    picks, _players, _props = asyncio.run(
        service._analyze_single_event(
            event_id=payload["id"],
            home_team=payload.get("home_team", ""),
            away_team=payload.get("away_team", ""),
            commence_time=payload.get("commence_time", ""),
            projections={},
            league="nba",
        )
    )
    return picks


class _FakeDB:
    def __init__(self, rows, *, connected=True):
        self.rows = rows
        self.is_connected = connected
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return self.rows


class _FakeCache:
    def __init__(self, *, fail_projections=False):
        self.store = {}
        self.sets = []
        self.gets = []
        self.fail_projections = fail_projections

    async def get(self, key):
        self.gets.append(key)
        if self.fail_projections and key.startswith("projections:"):
            raise ConnectionError("redis down")
        return self.store.get(key)

    async def set(self, key, value, ttl):
        self.sets.append((key, ttl))
        self.store[key] = value
        return True


def _pick(*, probability, combined, direction="over", n_games=20, name="P"):
    return DailyPick(
        player_name=name,
        event_id="evt",
        home_team="Home",
        away_team="Away",
        commence_time="2026-11-10T00:00:00Z",
        metric="points",
        threshold=20.5,
        direction=direction,
        probability=probability,
        n_games=n_games,
        bookmakers_count=2,
        combined_probability=combined,
        tier=read_tier(combined),
    )


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.middleware.rate_limit import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


class TestCombinedTierAndBoard:
    @pytest.mark.parametrize("direction", ["over", "under"])
    @pytest.mark.parametrize(
        ("combined", "tier", "on_board"),
        [
            (0.5599, None, False),
            (0.56, "Lean", False),
            (0.6499, "Lean", False),
            (0.65, "Playable", True),
            (0.6999, "Playable", True),
            (0.70, "Strong play", True),
        ],
    )
    def test_boundaries_are_inclusive_on_both_sides(self, direction, combined, tier, on_board):
        pick = _pick(probability=0.60, combined=combined, direction=direction)
        assert pick.tier == tier
        assert (pick in select_daily_picks([pick])) is on_board

    def test_low_historical_high_combined_is_strong_and_on_board(self):
        pick = _pick(probability=0.57, combined=0.72, direction="under")
        assert pick.tier == "Strong play"
        assert select_daily_picks([pick]) == [pick]

    def test_high_historical_low_combined_leaves_the_board_with_no_tier(self):
        pick = _pick(probability=0.80, combined=0.50)
        assert pick.tier is None
        assert select_daily_picks([pick]) == []
        assert select_daily_picks([pick], min_probability=0.5, min_games=0) == [pick]

    @pytest.mark.parametrize("combined", [None, float("nan")])
    def test_missing_combined_never_falls_back_even_at_the_lowest_floor(self, combined):
        pick = _pick(probability=0.95, combined=None)
        if combined is not None:
            pick.combined_probability = combined
        assert board_score(pick) is None
        assert select_daily_picks([pick], min_probability=0.5, min_games=0) == []

    def test_present_daily_picks_default_league_is_nba(self):
        on = _pick(probability=0.58, combined=0.66, name="on")
        off = _pick(probability=0.90, combined=0.60, name="off")
        result = DailyPicksResponse(
            date="2026-11-10", analyzed_at="2026-11-10T00:00:00Z",
            total_picks=2, picks=[off, on],
        )
        presented = present_daily_picks(result)
        assert [p.player_name for p in presented.picks] == ["on"]
        assert presented.total_picks == 1

    def test_nba_order_follows_the_blend_and_a_missing_blend_sorts_last(self):
        high_blend = _pick(probability=0.58, combined=0.80, name="blend")
        high_history = _pick(probability=0.90, combined=0.60, name="history")
        missing = _pick(probability=0.95, combined=None, name="missing")
        picks = [high_history, missing, high_blend]
        sort_stored_picks(picks, "nba")
        assert [pick.player_name for pick in picks] == ["blend", "history", "missing"]

        wnba = [
            _pick(probability=0.66, combined=None, name="lower"),
            _pick(probability=0.80, combined=0.40, name="higher"),
        ]
        for pick in wnba:
            pick.tier = read_tier(pick.probability)
        sort_stored_picks(wnba, "wnba")
        assert [pick.player_name for pick in wnba] == ["higher", "lower"]

    def test_signal_failure_leaves_a_null_tier_off_the_board(self, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("signals failed")

        monkeypatch.setattr(
            "app.services.daily_analysis.build_nba_signals",
            explode,
        )
        picks = _stored_picks()
        assert picks
        for pick in picks:
            assert pick.combined_probability is None
            assert pick.tier is None
            assert pick.signals is None
        assert select_daily_picks(picks, min_probability=0.0, min_games=0) == []


class TestWnbaUnchanged:
    def test_wnba_board_ignores_combined(self):
        pick = _pick(probability=0.66, combined=None)
        pick.tier = read_tier(pick.probability)
        assert select_daily_picks([pick], league="wnba") == [pick]
        assert select_daily_picks([pick], league="WNBA") == [pick]
        low = _pick(probability=0.64, combined=0.90)
        assert select_daily_picks([low], league="wnba") == []

    def test_wnba_signal_step_keeps_the_historical_tier(self):
        pick = _pick(probability=0.72, combined=None)
        pick.tier = read_tier(pick.probability)
        out = _with_nba_signal_verdicts(pick, league="wnba", bookmakers_data=[], game_logs=[])
        assert out.tier == "Strong play"
        assert out.combined_probability is None
        assert out.signals is None


class TestRecordedCapture:
    def test_reads_route_agrees_with_the_daily_pick_on_line_side_and_tier(self):
        picks = _stored_picks()
        assert picks
        event_id, rows = _points_rows()
        reads = {
            item.player: item
            for item in assemble_event_reads(
                event_id, rows, market="player_points", projections={}
            ).reads
        }
        for pick in picks:
            read = reads[pick.player_name]
            assert read.line == pick.threshold
            assert read.side == pick.direction
            assert read.tier == pick.tier
            # Snapshots keep one Over/Under pair per book. Bovada can post
            # a two-sided alternate at the consensus line that daily
            # analysis counts and /reads does not. On this capture the
            # gap stays inside 0.01, and line, side, and tier still match.
            assert read.combined_probability == pytest.approx(
                pick.combined_probability, abs=0.01
            )
        gaps = [
            abs(reads[pick.player_name].combined_probability - pick.combined_probability)
            for pick in picks
            if pick.combined_probability is not None
            and reads[pick.player_name].combined_probability is not None
        ]
        assert max(gaps) == pytest.approx(0.0069, abs=0.0001)
        walker = next(pick for pick in picks if pick.player_name == "Nickeil Alexander-Walker")
        assert walker.combined_probability == pytest.approx(0.6730)
        assert reads[walker.player_name].combined_probability == pytest.approx(0.6661)
        assert walker.tier == "Playable"
        assert reads[walker.player_name].tier == "Playable"

    def test_under_pick_tier_is_from_the_under_side_blend(self):
        picks = {pick.player_name: pick for pick in _stored_picks()}
        thybulle = picks["Matisse Thybulle"]
        assert thybulle.direction == "under"
        assert thybulle.probability == pytest.approx(0.7333)
        assert thybulle.combined_probability == pytest.approx(0.6386)
        assert thybulle.tier == "Lean"
        assert thybulle not in select_daily_picks(list(picks.values()))


class TestReadsRoute:
    def _patch(self, monkeypatch, rows, cache):
        db = _FakeDB(rows)
        monkeypatch.setattr("app.services.event_reads.db_service", db)
        monkeypatch.setattr("app.services.event_reads.cache_service", cache)
        from app.services.odds_gateway import odds_gateway
        from app.services.odds_theoddsapi import odds_provider
        from app.services.projection_service import projection_service

        spies = {
            "gateway": AsyncMock(),
            "event_odds": AsyncMock(),
            "events": AsyncMock(),
            "projections": AsyncMock(),
        }
        monkeypatch.setattr(odds_gateway, "get_market_snapshot", spies["gateway"])
        monkeypatch.setattr(odds_provider, "get_event_odds", spies["event_odds"])
        monkeypatch.setattr(odds_provider, "get_events", spies["events"])
        monkeypatch.setattr(projection_service, "get_projections", spies["projections"])
        return db, spies

    def _get(self, path, params=None):
        transport = httpx.ASGITransport(app=app)

        async def _call():
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                return await http.get(path, params=params)

        return asyncio.run(_call())

    def test_market_validation(self, monkeypatch):
        event_id, rows = _points_rows()
        self._patch(monkeypatch, rows, _FakeCache())
        base = f"/api/nba/events/{event_id}/reads"
        assert self._get(base, {"market": "not_a_market"}).status_code == 400
        assert self._get(base, {"market": "player_points,player_rebounds"}).status_code == 400
        assert self._get(base, {"market": "Player_Points"}).status_code == 400
        assert self._get(base, {"market": "player_points"}).status_code == 200
        assert self._get(base, {"market": ""}).status_code == 200

    def test_no_odds_api_or_sportsdata_call_on_projection_miss_or_redis_error(self, monkeypatch):
        event_id, rows = _points_rows()
        cache = _FakeCache(fail_projections=True)
        db, spies = self._patch(monkeypatch, rows, cache)
        response = self._get(f"/api/nba/events/{event_id}/reads", {"market": "player_points"})
        assert response.status_code == 200
        assert response.json()["reads"]
        for spy in spies.values():
            assert spy.await_count == 0
        assert any(key.startswith("projections:nba:2026-11-09") for key in cache.gets)

    def test_empty_snapshot_is_200_and_cached(self, monkeypatch):
        cache = _FakeCache()
        db, spies = self._patch(monkeypatch, [], cache)
        event_id = "07361a8381206817e27bd2697fad7479"
        response = self._get(f"/api/nba/events/{event_id}/reads")
        assert response.status_code == 200
        body = response.json()
        assert body["reads"] == [] and body["snapshot_at"] is None
        assert cache.sets == [(event_reads_cache_key(event_id, None), 60)]
        for spy in spies.values():
            assert spy.await_count == 0

    def test_cache_key_and_ttl(self, monkeypatch):
        assert EVENT_READS_CACHE_TTL_SECONDS == 60
        a = event_reads_cache_key("e1", "player_points")
        assert a != event_reads_cache_key("e2", "player_points")
        assert a != event_reads_cache_key("e1", "player_rebounds")
        assert a != event_reads_cache_key("e1", None)
        event_id, rows = _points_rows()
        cache = _FakeCache()
        self._patch(monkeypatch, rows, cache)
        asyncio.run(get_event_reads(event_id, market="player_points", projections={}))
        assert cache.sets == [(event_reads_cache_key(event_id, "player_points"), 60)]

    def test_wnba_routes_have_no_reads_endpoint(self):
        paths = {getattr(route, "path", "") for route in app.routes}
        assert "/api/nba/events/{event_id}/reads" in paths
        assert not any(path.startswith("/api/wnba") and path.endswith("/reads") for path in paths)
