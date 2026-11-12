"""QA checks for SPO-135: leftover env, missing projection blend, CSV ranks."""

from __future__ import annotations

import pytest

from app.services.daily_analysis import read_tier
from app.services.pick_signals import (
    adjustment_total,
    build_nba_signals,
    combined_probability,
    projection_adjustment,
)


def test_leftover_sportsdata_env_is_ignored(monkeypatch):
    """Deployed SPORTSDATA_* leftover vars must not fail Settings (extra=ignore)."""
    monkeypatch.setenv("SPORTSDATA_API_KEY", "leftover-must-not-crash")
    monkeypatch.setenv("SPORTSDATA_BASE_URL", "https://api.sportsdata.io")
    monkeypatch.setenv("CACHE_TTL_PROJECTIONS", "7200")
    from app.settings import Settings

    loaded = Settings()
    assert not hasattr(loaded, "sportsdata_api_key")
    assert not hasattr(loaded, "sportsdata_base_url")
    assert not hasattr(loaded, "cache_ttl_projections")


def test_missing_projection_adds_zero_and_stays_in_unit_interval():
    """Removing the projection term adds 0; other weights are not renormalized.

    combined_probability stays inside (0, 1). A known edge changes only the
    projection adjustment. Out still blocks; a null injury_status does not.
    """
    shared = dict(
        side="over",
        line=24.5,
        player_name="Test Player",
        market_probability=0.58,
        last10_values=[30, 30, 30, 30, 30, 30, 10, 10, 10, 10],
        history_rate=0.62,
        opponent_rank=8,
        opponent_position_rank=None,
    )
    _signals_missing, missing_p, missing_adj = build_nba_signals(
        projected_value=None, injury_status=None, **shared
    )
    _signals_edge, with_p, with_adj = build_nba_signals(
        projected_value=27.5, injury_status=None, **shared
    )
    expected_missing = adjustment_total(
        last10_hits=6,
        history_rate=0.62,
        defense_rank_value=8,
        edge_for_side=None,
        side="over",
    )
    expected_with = adjustment_total(
        last10_hits=6,
        history_rate=0.62,
        defense_rank_value=8,
        edge_for_side=3.0,
        side="over",
    )
    assert missing_adj == pytest.approx(expected_missing)
    assert with_adj == pytest.approx(expected_with)
    assert with_adj - missing_adj == pytest.approx(projection_adjustment(3.0))
    assert missing_p is not None and with_p is not None
    assert 0.0 < missing_p < 1.0
    assert 0.0 < with_p < 1.0
    assert read_tier(missing_p) is not None
    # Null injury does not trip the Out gate used on DailyPick.
    assert (
        combined_probability(
            side="over",
            market_probability=0.58,
            adjustment=missing_adj,
            injury_status=None,
        )
        == missing_p
    )
    assert (
        combined_probability(
            side="over",
            market_probability=0.58,
            adjustment=missing_adj,
            injury_status="Out",
        )
        is None
    )


def test_daily_picks_fill_csv_defense_ranks_on_the_recorded_slate(monkeypatch):
    """The shipped NBA game log, not a projection row, fills opponent ranks."""
    from tests.test_spo135_remove_sportsdataio import (
        _FakeCache,
        _Snap,
        _recorded_event,
    )
    import asyncio
    import httpx
    from app.main import app

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
    monkeypatch.setattr("app.services.daily_analysis.cache_service.get", _FakeCache().get)
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
    ranked = [
        pick
        for pick in response.json()["picks"]
        if pick.get("opponent_rank") is not None
    ]
    assert ranked
    for pick in ranked:
        assert pick["opponent_rank_source"] == "csv"
        assert pick["has_projection"] is False
        assert pick["edge"] is None
