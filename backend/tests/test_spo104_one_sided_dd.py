"""SPO-104: one-sided double-double quotes and market-kind flags.

Prices come from the recorded no-vig fixture (FanDuel Yes only) and the
recorded Odds API ``player_points`` body. Nothing here invents an odds
payload.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from app.models.schemas import NoVigRequest
from app.services.odds_gateway import MarketSnapshotResult
from app.services.prob import DEFAULT_BINARY_VIG

_REPO = Path(__file__).resolve().parents[2]
_DD_FIXTURE = _REPO / "frontend" / "test" / "fixtures" / "props-no-vig" / "player-double-double.json"
_OU_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "odds_api_event_odds__player_points.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bookmakers_from_dd_fixture(payload: dict) -> list[dict]:
    """Yes/No outcomes taken from the recorded route fixture's posted prices.

    ``yes_price`` and ``no_price`` are the posted legs. A null ``no_price``
    stays off the outcome list. The copied ``under_odds`` in that fixture
    is the old contract and is not used as an input.
    """
    player = payload["player_name"]
    market = payload["market"]
    books = []
    for row in payload["results"]:
        outcomes = []
        if row.get("yes_price") is not None:
            outcomes.append(
                {"name": "Yes", "description": player, "price": row["yes_price"]}
            )
        if row.get("no_price") is not None:
            outcomes.append(
                {"name": "No", "description": player, "price": row["no_price"]}
            )
        books.append(
            {"key": row["bookmaker"], "markets": [{"key": market, "outcomes": outcomes}]}
        )
    return books


def _snapshot(data: dict) -> MarketSnapshotResult:
    return MarketSnapshotResult(
        data=data,
        fetched_at=datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
        data_age_seconds=12,
        cache_state="fresh",
        source="snapshot_cache",
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/props/no-vig",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def _post(module, body: NoVigRequest, data: dict):
    from app.middleware.rate_limit import limiter

    snapshot = _snapshot(data)
    limiter.enabled = False
    try:
        with patch.object(
            module.odds_gateway,
            "get_market_snapshot",
            new=AsyncMock(return_value=snapshot),
        ):
            return asyncio.run(module.calculate_no_vig(_request(), body))
    finally:
        limiter.enabled = True


def _by_book(response):
    return {row.bookmaker: row for row in response.results}


@pytest.fixture(scope="module")
def dd_payload() -> dict:
    return _load(_DD_FIXTURE)


@pytest.fixture(scope="module")
def ou_payload() -> dict:
    return _load(_OU_FIXTURE)


@pytest.mark.parametrize("module_path", ["app.api.nba", "app.api.wnba"])
def test_one_sided_dd_leaves_under_empty(dd_payload, module_path):
    import importlib

    module = importlib.import_module(module_path)
    body = NoVigRequest(
        event_id=dd_payload["event_id"],
        player_name=dd_payload["player_name"],
        market=dd_payload["market"],
    )
    response = _post(module, body, {"bookmakers": _bookmakers_from_dd_fixture(dd_payload)})
    books = _by_book(response)

    fanduel = books["fanduel"]
    assert fanduel.over_odds == -240
    assert fanduel.yes_price == -240
    assert fanduel.under_odds is None
    assert fanduel.no_price is None
    assert fanduel.p_no_imp is None
    assert fanduel.p_under_imp is None
    assert fanduel.line == 0.5
    assert fanduel.line_is_synthetic is True
    assert fanduel.market_kind == "binary"
    assert fanduel.vig == round(DEFAULT_BINARY_VIG, 4)
    assert fanduel.p_under_fair == fanduel.no_fair_prob
    assert fanduel.no_fair_prob == 0.3245
    assert abs((fanduel.yes_fair_prob or 0) + (fanduel.no_fair_prob or 0) - 1) < 1e-4

    draftkings = books["draftkings"]
    assert draftkings.over_odds == -250
    assert draftkings.under_odds == 200
    assert draftkings.no_price == 200
    assert draftkings.p_under_imp == 0.3333
    assert draftkings.p_no_imp == 0.3333
    assert draftkings.line_is_synthetic is True
    assert draftkings.market_kind == "binary"

    posted_under = [row.under_odds for row in response.results if row.under_odds is not None]
    assert posted_under == [200.0]
    assert response.consensus is not None
    assert response.consensus.p_yes_fair == 0.6787
    assert response.consensus.p_no_fair == 0.3213


@pytest.mark.parametrize("module_path", ["app.api.nba", "app.api.wnba"])
def test_over_under_line_is_not_synthetic(ou_payload, module_path):
    import importlib

    module = importlib.import_module(module_path)
    body = NoVigRequest(
        event_id=ou_payload["id"],
        player_name="Jalen Johnson",
        market="player_points",
    )
    response = _post(module, body, ou_payload)
    assert response.results
    for row in response.results:
        assert row.line_is_synthetic is False
        assert row.market_kind == "over_under"
        assert row.under_odds is not None
        assert row.p_under_imp is not None
        assert row.yes_price is None
        assert row.line != 0.5
