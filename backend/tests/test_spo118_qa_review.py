"""QA checks for SPO-118 (PR #47): limiter fallback and the bulk-props vote.

Prices come from the recorded Odds API fixture. No response body is typed.
"""

from __future__ import annotations

import math

import pytest

from app.services.bulk_props import _main_book_line, assemble_bulk_props
from app.settings import settings
from tests.test_spo114_qa_review import (  # noqa: F401  (fixtures)
    _FakeCache,
    _FakeDB,
    _SNAPSHOT_AT,
    _install,
    _outcomes_by_player,
    _parse,
    client,
    points_payload,
    service,
)


def _props_limit() -> int:
    count, _, _unit = settings.rate_limit_props.partition("/")
    return int(count)


@pytest.mark.asyncio
async def test_fallback_still_enforces_the_props_limit_when_redis_is_down(
    client, monkeypatch, service, points_payload
):
    """Redis down: the in-memory fallback must still return 429 past the limit.

    The PR comment says the fallback keeps the same limits for this
    process. The PR test only checks a single 200.
    """
    from app.middleware.rate_limit import limiter

    rows = _parse(service, points_payload, _SNAPSHOT_AT)
    _install(monkeypatch, _FakeDB(rows), _FakeCache())
    previous_enabled = limiter.enabled
    previous_dead = limiter._storage_dead
    limiter.enabled = True
    limiter._storage_dead = False
    limiter._fallback_storage.reset()

    def _down(*_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(limiter._limiter, "hit", _down)
    monkeypatch.setattr(limiter._storage, "check", lambda: False)
    url = f"/api/nba/events/{points_payload['id']}/props"
    limit = _props_limit()
    try:
        codes = [(await client.get(url)).status_code for _ in range(limit + 1)]
    finally:
        limiter.enabled = previous_enabled
        limiter._storage_dead = previous_dead
        limiter._fallback_storage.reset()

    assert codes[:limit] == [200] * limit
    assert codes[limit] == 429


def test_non_finite_stored_line_never_becomes_the_vote(points_payload):
    """A NaN line is not a posted point. The finite rung must be the vote.

    Recorded DraftKings Luka prices. The NaN row gets the coin-flip pair.
    On dev the local vote kept that row and the book line was NaN. The
    shared helper puts each NaN outcome on its own one-sided rung, so the
    finite two-sided rung wins. This guards that behavior.
    """
    dk = next(book for book in points_payload["bookmakers"] if book["key"] == "draftkings")
    outcomes = _outcomes_by_player(dk)["Luka Doncic"]
    by_point: dict[float, dict[str, int]] = {}
    for outcome in outcomes:
        by_point.setdefault(float(outcome["point"]), {})[outcome["name"].lower()] = outcome["price"]
    point, prices = next(
        (p, s) for p, s in sorted(by_point.items()) if "over" in s and "under" in s
    )
    base = {
        "bookmaker": "draftkings",
        "player_name": "Luka Doncic",
        "market": "player_points",
        "snapshot_at": _SNAPSHOT_AT,
    }
    rows = [
        {**base, "line": float("nan"), "over_odds": -110, "under_odds": -110},
        {**base, "line": point, "over_odds": prices["over"], "under_odds": prices["under"]},
    ]
    chosen = _main_book_line(rows)
    assert math.isfinite(float(chosen["line"]))
    assert float(chosen["line"]) == pytest.approx(point)

    payload = assemble_bulk_props("evt", rows, now=_SNAPSHOT_AT)
    lines = [book.line for market in payload.markets for p in market.players for book in p.books]
    assert lines and all(math.isfinite(line) for line in lines)
