"""
SPO-101 — Phase 4 live integration tests for the /event 12-tile surface.

Gated behind ``RUN_INTEGRATION=1`` (CLAUDE.md, External API Wrappers rule 2).
With the variable unset, every test in this module is skipped and no Odds
API call is made. With the variable set but ``ODDS_API_KEY`` missing, the
shared fixture skips the tests instead of failing.

What this file proves, against one live NBA event:

1. Each of the 12 market keys the event page serves
   (``MarketSelect`` / ``SNAPSHOT_MARKETS``) can be requested, and
   ``OddsSnapshotService._process_event`` parses the real response.
   ``player_frees_made`` (FTM) and ``player_field_goals`` (FGM) have
   historically come back with no bookmakers. An empty market is a
   successful empty state: the parser writes zero rows and does not
   invent a line. A populated market must produce one row per complete
   quote, with fair probabilities in (0, 1) that sum to about 1.
2. Double-double round trip on that same payload: the binary parser,
   then ``POST /api/nba/props/no-vig`` (DD branch), then
   ``GET /api/nba/player-dd-history``. No-vig probabilities stay in
   (0, 1) and the two sides sum to about 1. The history route is the
   CSV rate, not a second odds quote.

Quota budget per run (one event, deduped):

- ``GET /v4/sports/basketball_nba/events`` — 0 paid units. The events
  list is free (SPO-12). Exactly one call.
- ``GET /v4/sports/basketball_nba/events/{id}/odds?markets=<all 12>`` —
  exactly one HTTP call. The Odds API bills 1 unit per market in that
  URL that comes back with a bookmaker, and 0 units for a market that
  does not (SPO-12 §2.4). Expected cost is 10 units when FTM and FGM
  are empty and the other 10 markets are posted. Ceiling is 12 units
  if every market is posted. Floor is 0 if the slate has no props yet.
- ``POST /api/nba/props/no-vig`` and ``GET /api/nba/player-dd-history``
  do not make another Odds API call. The route reads the payload this
  fixture already fetched (the gateway is patched with that live body).
  History reads the local CSV.

Do not run these in CI without the opt-in flag. The monthly quota is finite.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


# Collected and reported as skipped unless the operator opts in.
# The fixture below is not executed while this marker skips the test,
# so a default ``pytest`` run burns 0 Odds API units.
_RUN_LIVE = os.environ.get("RUN_INTEGRATION") == "1"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _RUN_LIVE,
        reason=(
            "RUN_INTEGRATION=1 not set; skipping live The Odds API "
            "event-page tests (CLAUDE.md External API Wrappers rule 2)"
        ),
    ),
]


# The 12 tiles on /event/[eventId], in MarketSelect order.
# Single: PTS, REB, AST, 3PM, STL, FTM, FGM.
# Combo: PRA, R+A, P+R, P+A.
# Binary: DD.
EVENT_PAGE_MARKETS: tuple[str, ...] = (
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_frees_made",
    "player_field_goals",
    "player_points_rebounds_assists",
    "player_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_double_double",
)

# Schema-valid markets that Scout's curl (SPO-12) saw with bookmakers: [].
# Empty remains a pass. Populated, when a book finally posts, is also a pass.
HISTORICALLY_EMPTY_MARKETS = frozenset({"player_frees_made", "player_field_goals"})
BINARY_MARKETS = frozenset({"player_double_double"})

# _process_event / _parse_binary_market row layout (UPSERT $1..$14).
_COL_PLAYER = 5
_COL_MARKET = 6
_COL_BOOK = 7
_COL_LINE = 8
_COL_OVER_ODDS = 9
_COL_UNDER_ODDS = 10
_COL_VIG = 11
_COL_OVER_FAIR = 12
_COL_UNDER_FAIR = 13

# Parser stores round(p, 6); the route stores round(p, 4).
# 1e-5 covers the 6-decimal pair. 1e-3 is "about 1" after 4-decimal rounding.
_PARSER_SUM_TOLERANCE = 1e-5
_ROUTE_SUM_TOLERANCE = 1e-3
_ROUTE_VS_PARSER_TOLERANCE = 6e-4

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    """Copy KEY=VALUE lines into the process environment.

    ``setdefault`` so an already-exported ODDS_API_KEY wins over the file.
    Missing files are ignored: CI and this VM often have no .env at all.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _odds_api_key() -> str:
    """Return the Odds API key, or '' when the operator did not provide one."""
    _load_env_file(_REPO_ROOT / ".env")
    _load_env_file(_REPO_ROOT / "backend" / ".env")
    return os.environ.get("ODDS_API_KEY", "").strip()


@dataclass
class LiveSlate:
    """One live event plus the single odds response and its parsed rows.

    ``http_calls`` is the mutable counter the provider wrappers increment.
    The DD test reads it after the route runs and asserts ``odds`` is
    still 1, which is the dedupe check.
    """

    event_id: str
    payload: dict[str, Any]
    rows: list[tuple[Any, ...]]
    usage_last: int | None
    posted_keys: set[str]
    http_calls: dict[str, int] = field(default_factory=dict)


def _posted_market_keys(payload: dict[str, Any]) -> set[str]:
    """Market keys that at least one bookmaker actually returned.

    A key that is absent is the empty state. Billing follows this set:
    SPO-12 measured ``x-requests-last`` equal to the number of populated
    markets in the URL, and 0 when ``bookmakers`` is empty.
    """
    keys: set[str] = set()
    for bookmaker in payload.get("bookmakers") or []:
        for market in bookmaker.get("markets") or []:
            key = market.get("key")
            if key:
                keys.add(key)
    return keys


def _group_outcomes(
    market: dict[str, Any], allowed: set[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Group a market's outcomes by player, then by side name.

    Mirrors the last-write-wins grouping in ``_process_event`` and
    ``_parse_binary_market``: a repeated side for the same player
    replaces the previous one, it does not become a second row.
    """
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for outcome in market.get("outcomes") or []:
        player_name = outcome.get("description", "")
        side = outcome.get("name", "").lower()
        if not player_name or side not in allowed:
            continue
        grouped.setdefault(player_name, {})[side] = outcome
    return grouped


def _expected_ou_pairs(
    payload: dict[str, Any], market_key: str
) -> list[tuple[str, str]]:
    """(bookmaker, player) pairs the Over/Under parser must emit.

    A pair is complete when both sides survived grouping, the Over
    carries a ``point``, and neither American price is 0. That is the
    same filter ``_process_event`` uses before ``devig``.
    """
    expected: list[tuple[str, str]] = []
    for bookmaker in payload.get("bookmakers") or []:
        book_key = bookmaker.get("key", "unknown")
        for market in bookmaker.get("markets") or []:
            if market.get("key") != market_key:
                continue
            grouped = _group_outcomes(market, {"over", "under"})
            for player_name, sides in grouped.items():
                over = sides.get("over")
                under = sides.get("under")
                if not over or not under:
                    continue
                if over.get("point") is None:
                    continue
                if over.get("price", 0) == 0 or under.get("price", 0) == 0:
                    continue
                expected.append((book_key, player_name))
    return expected


def _expected_dd_players(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """(bookmaker, player) pairs the binary parser must emit.

    The parser emits one row per player who has a non-zero Yes price,
    including the row it stores with NULL fair probabilities when the
    single-leg prior cannot be applied.
    """
    expected: list[tuple[str, str]] = []
    for bookmaker in payload.get("bookmakers") or []:
        book_key = bookmaker.get("key", "unknown")
        for market in bookmaker.get("markets") or []:
            if market.get("key") != "player_double_double":
                continue
            grouped = _group_outcomes(market, {"yes", "no"})
            for player_name, sides in grouped.items():
                yes = sides.get("yes")
                if not yes or yes.get("price", 0) == 0:
                    continue
                expected.append((book_key, player_name))
    return expected


def _rows_for(rows: list[tuple[Any, ...]], market_key: str) -> list[tuple[Any, ...]]:
    """Return parser rows whose market column equals ``market_key``."""
    return [row for row in rows if row[_COL_MARKET] == market_key]


def _assert_fair_pair(over_fair: float, under_fair: float, tolerance: float) -> None:
    """Both sides are probabilities in (0, 1) and sum to about 1.

    Summing to 1 is the vig-removal check: implied probabilities sum to
    more than 1 by the book's margin; ``devig`` normalizes that margin away.
    """
    assert 0 < over_fair < 1, over_fair
    assert 0 < under_fair < 1, under_fair
    assert abs((over_fair + under_fair) - 1) <= tolerance, (
        over_fair,
        under_fair,
    )


def _assert_ou_rows(
    rows: list[tuple[Any, ...]], payload: dict[str, Any], market_key: str
) -> None:
    """Parser output for one Over/Under market matches the live quotes."""
    expected = _expected_ou_pairs(payload, market_key)
    got = {(row[_COL_BOOK], row[_COL_PLAYER]) for row in rows}
    assert (
        got == set(expected)
    ), f"{market_key}: parser rows {sorted(got)} != complete live quotes {sorted(set(expected))}"
    for row in rows:
        assert isinstance(row[_COL_LINE], float)
        assert row[_COL_OVER_ODDS] != 0
        assert row[_COL_UNDER_ODDS] != 0
        _assert_fair_pair(
            row[_COL_OVER_FAIR], row[_COL_UNDER_FAIR], _PARSER_SUM_TOLERANCE
        )


def _assert_dd_rows(rows: list[tuple[Any, ...]], payload: dict[str, Any]) -> None:
    """Binary parser output: 0.5 sentinel line, no invented fair probability."""
    expected = _expected_dd_players(payload)
    got = {(row[_COL_BOOK], row[_COL_PLAYER]) for row in rows}
    assert got == set(expected), (
        "player_double_double: parser rows "
        f"{sorted(got)} != live Yes quotes {sorted(set(expected))}"
    )
    for row in rows:
        # 0.5 is the storage sentinel, not a bookmaker point. Consumers
        # dispatch on the market key.
        assert row[_COL_LINE] == 0.5
        assert row[_COL_OVER_ODDS] != 0
        over_fair = row[_COL_OVER_FAIR]
        under_fair = row[_COL_UNDER_FAIR]
        if over_fair is None or under_fair is None:
            # Prior could not be applied. The parser stores NULL instead
            # of a made-up probability, and it does not invent a No price.
            assert over_fair is None and under_fair is None
            assert row[_COL_UNDER_ODDS] is None
            continue
        _assert_fair_pair(over_fair, under_fair, _PARSER_SUM_TOLERANCE)


def _assert_fgm_signature(payload: dict[str, Any]) -> None:
    """When FGM is posted, the median line must look like makes, not attempts.

    Decision Addendum 1 Override 3: FGM lines cluster under 10; FGA
    clusters at 10-20. No inventory means there is nothing to classify,
    which the caller treats as the empty state rather than a failure.
    """
    points: list[float] = []
    for bookmaker in payload.get("bookmakers") or []:
        for market in bookmaker.get("markets") or []:
            if market.get("key") != "player_field_goals":
                continue
            for outcome in market.get("outcomes") or []:
                point = outcome.get("point")
                if point is not None:
                    points.append(float(point))
    if not points:
        return
    median = statistics.median(points)
    assert median < 10, (
        f"player_field_goals median point={median:.1f} looks like FGA "
        "(median >= 10), not FGM. Escalate with the live payload; do not "
        "rename the metric from this test."
    )


@pytest.fixture(scope="module")
def live_slate():
    """Fetch one NBA event and all 12 markets, then parse that body once.

    Skips cleanly when the key is absent or the slate has no event.
    A 422 from the odds call is not a skip: that means a market key in
    the 12-tile list was rejected, which is the failure this ticket exists
    to catch.

    Odds API cost: 1 events call (0 units) + 1 odds call
    (1 unit per posted market, ceiling 12). See the module docstring.
    """
    key = _odds_api_key()
    if not key:
        pytest.skip(
            "ODDS_API_KEY is not set; live Odds API tests skipped without "
            "calling the network"
        )

    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))

    from app.services.odds_gateway import MarketSnapshotResult
    from app.services.odds_provider import OddsAPIError
    from app.services.odds_snapshot_service import (
        SNAPSHOT_MARKETS,
        OddsSnapshotService,
    )
    from app.services.odds_theoddsapi import odds_provider
    from app.settings import settings

    settings.odds_api_key = key
    odds_provider.api_key = key
    base_url = os.environ.get("ODDS_API_BASE_URL", "").strip()
    if base_url:
        settings.odds_api_base_url = base_url
        odds_provider.base_url = base_url

    requested = tuple(part for part in SNAPSHOT_MARKETS.split(",") if part)
    assert set(requested) == set(EVENT_PAGE_MARKETS), (
        "SNAPSHOT_MARKETS drifted from the 12 event-page tiles: "
        f"snapshot={requested} tiles={EVENT_PAGE_MARKETS}"
    )

    counter = {"events": 0, "odds": 0}
    original_events = odds_provider.get_events
    original_odds = odds_provider.get_event_odds_with_usage

    async def _counted_events(*args: Any, **kwargs: Any) -> Any:
        counter["events"] += 1
        return await original_events(*args, **kwargs)

    async def _counted_odds(*args: Any, **kwargs: Any) -> Any:
        counter["odds"] += 1
        return await original_odds(*args, **kwargs)

    async def _load() -> LiveSlate | None:
        events = await odds_provider.get_events(sport="basketball_nba", regions="us")
        event = next((item for item in events if item.get("id")), None)
        if event is None:
            return None
        event_id = str(event["id"])
        try:
            payload, usage = await odds_provider.get_event_odds_with_usage(
                sport="basketball_nba",
                event_id=event_id,
                regions="us",
                markets=SNAPSHOT_MARKETS,
                odds_format="american",
            )
        except OddsAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

        commence = str(event.get("commence_time") or payload.get("commence_time") or "")
        if len(commence) >= 10:
            slate_date = commence[:10]
        else:
            slate_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        snapshot = MarketSnapshotResult(
            data=payload,
            fetched_at=datetime.now(timezone.utc),
            data_age_seconds=0,
            cache_state="refreshed",
            source="upstream",
            usage=usage,
        )

        async def _return_live(**kwargs: Any) -> MarketSnapshotResult:
            # The parser must ask for the same 12-market batch we paid for.
            assert kwargs.get("markets") == SNAPSHOT_MARKETS
            return snapshot

        service = OddsSnapshotService()
        # Patch the name ``_process_event`` looks up. The body it receives
        # is the live response from the call above, not a second fetch.
        from unittest.mock import patch

        with patch(
            "app.services.odds_snapshot_service.odds_gateway.get_market_snapshot",
            new=_return_live,
        ):
            rows = await service._process_event(
                event_id=event_id,
                home_team=str(payload.get("home_team") or event.get("home_team") or ""),
                away_team=str(payload.get("away_team") or event.get("away_team") or ""),
                date=slate_date,
                snapshot_at=snapshot.fetched_at,
            )

        usage_last = None if usage is None else usage.last
        return LiveSlate(
            event_id=event_id,
            payload=payload,
            rows=rows,
            usage_last=usage_last,
            posted_keys=_posted_market_keys(payload),
            http_calls=counter,
        )

    # Wrappers stay installed until this module's tests finish, so the
    # DD route test can prove it did not call the provider again.
    odds_provider.get_events = _counted_events
    odds_provider.get_event_odds_with_usage = _counted_odds
    try:
        slate = asyncio.run(_load())
        if slate is None:
            pytest.skip("No live NBA event with an id is available right now")
        yield slate
    finally:
        odds_provider.get_events = original_events
        odds_provider.get_event_odds_with_usage = original_odds


@pytest.mark.parametrize("market_key", EVENT_PAGE_MARKETS)
def test_event_page_market_parses_live_response(
    live_slate: LiveSlate, market_key: str
) -> None:
    """One event-page market key, parsed from the shared live response.

    The request itself is the module fixture's single 12-market call, so
    this test adds 0 Odds API units. Expected cost of the whole module
    is 10 paid units (FTM and FGM empty); the ceiling is 12.

    Empty bookmakers — the historical FTM and FGM result, and a legal
    result for any other key on a quiet slate — must produce zero parser
    rows. Populated Over/Under keys must produce one de-vigged row per
    complete quote. Populated DD must produce one binary row per Yes quote.
    """
    rows = _rows_for(live_slate.rows, market_key)
    if market_key not in live_slate.posted_keys:
        # FTM and FGM are the historically empty keys. Any other key that
        # a book did not post on this event is the same success: zero rows,
        # no fabricated line.
        kind = (
            "historically empty"
            if market_key in HISTORICALLY_EMPTY_MARKETS
            else "not posted on this event"
        )
        assert rows == [], (
            f"{market_key} ({kind}) was absent from the live bookmaker "
            f"list but the parser wrote {len(rows)} row(s)"
        )
        return

    if market_key in BINARY_MARKETS:
        _assert_dd_rows(rows, live_slate.payload)
        return

    _assert_ou_rows(rows, live_slate.payload, market_key)
    if market_key == "player_field_goals":
        _assert_fgm_signature(live_slate.payload)


def test_batched_twelve_market_call_stays_inside_quota(live_slate: LiveSlate) -> None:
    """The module paid for one odds call, and the header matches the body.

    Budget, repeated here so a reader of this test does not have to hunt:

    - 1 free ``/events`` call (``http_calls['events'] == 1``).
    - 1 odds call covering all 12 keys (``http_calls['odds'] == 1``).
    - ``x-requests-last`` equals the number of market keys present in
      the body, which is between 0 and 12. Empty FTM/FGM contribute 0.

    The DD route test reuses this body and must not move ``odds`` off 1.
    """
    assert live_slate.http_calls["events"] == 1
    assert live_slate.http_calls["odds"] == 1
    assert (
        live_slate.usage_last is not None
    ), "x-requests-last was missing; the quota budget cannot be checked"
    assert live_slate.usage_last == len(live_slate.posted_keys), (
        f"x-requests-last={live_slate.usage_last} but "
        f"{len(live_slate.posted_keys)} market keys were in the body "
        f"({sorted(live_slate.posted_keys)}). Per-market billing from "
        "SPO-12 no longer matches this response."
    )
    assert 0 <= live_slate.usage_last <= len(EVENT_PAGE_MARKETS)
    assert live_slate.posted_keys <= set(EVENT_PAGE_MARKETS)


def test_double_double_round_trip_parser_no_vig_and_history(
    live_slate: LiveSlate,
) -> None:
    """Live DD quote through the parser, /props/no-vig, and /player-dd-history.

    Odds API cost: 0 additional units. The route's gateway is fed the
    fixture's live body, and history is computed from the CSV. If this
    test's provider counter is not still 1, the route fetched DD again.

    When the event has no Yes prices, the test skips. The parametrized
    market test already asserted that empty DD writes zero rows.

    No-vig math, for every bookmaker row the route emits: ``yes_fair_prob``
    and ``no_fair_prob`` are in (0, 1) and sum to about 1 (tolerance 1e-3
    because the route rounds each side to 4 decimals). Those values agree
    with the parser row for the same bookmaker. History returns the CSV
    shape ``{player, n_games, dd_games, prob_dd}`` with no threshold.
    """
    dd_rows = _rows_for(live_slate.rows, "player_double_double")
    if not dd_rows:
        pytest.skip(
            "player_double_double has no Yes prices on this event; "
            "empty state is covered by test_event_page_market_parses_live_response"
        )

    priced = [row for row in dd_rows if row[_COL_OVER_FAIR] is not None]
    # Prefer a two-sided quote so vig is measured from the leg pair.
    two_sided = [row for row in priced if row[_COL_UNDER_ODDS] is not None]
    subject = (two_sided or priced or dd_rows)[0]
    player_name = str(subject[_COL_PLAYER])

    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))

    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import nba as nba_api
    from app.middleware.rate_limit import limiter
    from app.services.odds_gateway import MarketSnapshotResult

    snapshot = MarketSnapshotResult(
        data=live_slate.payload,
        fetched_at=datetime.now(timezone.utc),
        data_age_seconds=0,
        cache_state="refreshed",
        source="upstream",
    )

    async def _return_live(**kwargs: Any) -> MarketSnapshotResult:
        assert kwargs.get("markets") == "player_double_double"
        assert kwargs.get("event_id") == live_slate.event_id
        return snapshot

    limiter.enabled = False
    app = FastAPI()
    app.include_router(nba_api.router)
    try:
        with patch.object(
            nba_api.odds_gateway, "get_market_snapshot", new=_return_live
        ):
            client = TestClient(app)
            no_vig = client.post(
                "/api/nba/props/no-vig",
                json={
                    "event_id": live_slate.event_id,
                    "player_name": player_name,
                    "market": "player_double_double",
                    "regions": "us",
                    "odds_format": "american",
                },
            )
            history = client.get(
                "/api/nba/player-dd-history",
                params={"player": player_name},
            )
    finally:
        limiter.enabled = True

    # The route must have consumed the live body, not issued a new odds call.
    assert live_slate.http_calls["odds"] == 1

    assert no_vig.status_code == 200, no_vig.text
    body = no_vig.json()
    assert body["event_id"] == live_slate.event_id
    assert body["market"] == "player_double_double"
    assert body["player_name"] == player_name

    by_book = {
        row[_COL_BOOK]: row for row in dd_rows if row[_COL_PLAYER] == player_name
    }
    results_by_book = {item["bookmaker"]: item for item in body["results"]}

    if not priced:
        # Every Yes quote failed the vig prior. The route must omit the
        # rows and say so, rather than emit a fair probability.
        assert results_by_book == {}
        assert body["message"]
        assert "not fabricated" in body["message"]
    else:
        assert results_by_book, body.get("message")
        for book_key, row in by_book.items():
            if row[_COL_OVER_FAIR] is None:
                assert book_key not in results_by_book
                continue
            result = results_by_book[book_key]
            assert result["line"] == 0.5
            assert result["yes_price"] == row[_COL_OVER_ODDS]
            if row[_COL_UNDER_ODDS] is None:
                assert result["no_price"] is None
            else:
                assert result["no_price"] == row[_COL_UNDER_ODDS]
            _assert_fair_pair(
                result["yes_fair_prob"],
                result["no_fair_prob"],
                _ROUTE_SUM_TOLERANCE,
            )
            assert result["p_over_fair"] == result["yes_fair_prob"]
            assert result["p_under_fair"] == result["no_fair_prob"]
            assert (
                abs(result["yes_fair_prob"] - row[_COL_OVER_FAIR])
                <= _ROUTE_VS_PARSER_TOLERANCE
            )
            assert (
                abs(result["no_fair_prob"] - row[_COL_UNDER_FAIR])
                <= _ROUTE_VS_PARSER_TOLERANCE
            )

        consensus = body.get("consensus")
        if consensus is not None:
            _assert_fair_pair(
                consensus["p_yes_fair"],
                consensus["p_no_fair"],
                _ROUTE_SUM_TOLERANCE,
            )
            assert consensus["p_over_fair"] == consensus["p_yes_fair"]
            assert consensus["p_under_fair"] == consensus["p_no_fair"]

    assert history.status_code == 200, history.text
    history_body = history.json()
    for required in ("player", "n_games", "dd_games", "prob_dd", "message", "season"):
        assert required in history_body
    assert "threshold" not in history_body
    assert history_body["n_games"] >= 0
    assert 0 <= history_body["dd_games"] <= history_body["n_games"]
    if history_body["n_games"] > 0:
        # Empirical rate. 0 and 1 are legal (never / always a double-double).
        # The open interval (0, 1) applies to the de-vigged book prices above.
        assert history_body["prob_dd"] is not None
        assert 0 <= history_body["prob_dd"] <= 1
        expected_rate = round(history_body["dd_games"] / history_body["n_games"], 4)
        assert history_body["prob_dd"] == expected_rate
    else:
        assert history_body["prob_dd"] is None
        assert history_body["message"]
