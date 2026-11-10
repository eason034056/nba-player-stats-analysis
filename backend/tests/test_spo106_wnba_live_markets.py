"""SPO-106 live WNBA coverage for rebounds, assists, threes, and combos.

The live class is ``@pytest.mark.integration`` and is skipped unless
``RUN_INTEGRATION=1``. A default ``pytest`` run does not call The Odds
API. Do not set that variable in CI.

When it does run, the module fixture makes two calls:

- ``GET /v4/sports/basketball_wnba/events`` — free. An empty list skips
  the module with a reason. No odds call is made in that case.
- one ``GET /v4/sports/basketball_wnba/events/{id}/odds`` with every
  market below in a single ``markets=`` parameter.

Each market that a book posts is de-vigged with ``american_to_prob`` and
``devig`` from ``app.services.prob``. Those are the functions
``nba.py`` and ``wnba.py`` call on an Over/Under pair. The two fair
probabilities sum to 1. A market with no complete pair produces an
empty board. The helper does not fill in a line.

The two tests above the live class do not touch the network. They run
the same helper on the recorded NBA ``player_points`` body (shape only;
the market key stays ``player_points``) and on an empty bookmaker list.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.prob import american_to_prob, devig  # noqa: E402
from tests.fixtures.odds_api import (  # noqa: E402
    RECORDED_PLAYER_POINTS,
    load_odds_fixture,
)

# WNBA markets this ticket adds live coverage for. One odds call carries
# all of them. player_points is already covered by test_wnba_odds_integration.
WNBA_LIVE_MARKETS: tuple[str, ...] = (
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_points_rebounds_assists",
    "player_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPORT = "basketball_wnba"


def devig_board(payload: dict[str, Any], market_key: str) -> list[dict[str, Any]]:
    """Fair Over/Under rows for one market, or an empty list.

    Pairing matches ``calculate_no_vig`` in ``nba.py`` and ``wnba.py``:
    the last Over and the last Under for a player win, both prices must
    be non-zero, and the line is the Over ``point`` (the Under ``point``
    only if Over did not carry one). A missing side, a missing line, or
    a zero price drops that player. Nothing in this function writes a
    default line.

    The fair pair is ``devig(american_to_prob(over), american_to_prob(under))``.
    """
    rows: list[dict[str, Any]] = []
    for bookmaker in payload.get("bookmakers") or []:
        book_key = bookmaker.get("key", "unknown")
        for market in bookmaker.get("markets") or []:
            if market.get("key") != market_key:
                continue
            by_player: dict[str, dict[str, dict[str, Any]]] = {}
            for outcome in market.get("outcomes") or []:
                player_name = outcome.get("description") or ""
                side = (outcome.get("name") or "").lower()
                if not player_name or side not in ("over", "under"):
                    continue
                by_player.setdefault(player_name, {})[side] = outcome
            for player_name, sides in by_player.items():
                over = sides.get("over")
                under = sides.get("under")
                if over is None or under is None:
                    continue
                line = over.get("point")
                if line is None:
                    line = under.get("point")
                if line is None:
                    continue
                over_odds = over.get("price", 0)
                under_odds = under.get("price", 0)
                if over_odds == 0 or under_odds == 0:
                    continue
                try:
                    p_over = american_to_prob(float(over_odds))
                    p_under = american_to_prob(float(under_odds))
                    fair_over, fair_under = devig(p_over, p_under)
                except (ValueError, ZeroDivisionError):
                    continue
                rows.append(
                    {
                        "bookmaker": book_key,
                        "player": player_name,
                        "line": line,
                        "p_over_fair": fair_over,
                        "p_under_fair": fair_under,
                    }
                )
    return rows


def _assert_fair_pairs(board: list[dict[str, Any]]) -> None:
    """Each row is a real line and a fair pair that sums to 1."""
    for row in board:
        assert row["line"] is not None
        assert 0 < row["p_over_fair"] < 1
        assert 0 < row["p_under_fair"] < 1
        assert abs(row["p_over_fair"] + row["p_under_fair"] - 1) < 1e-9


def test_empty_bookmakers_produce_an_empty_board() -> None:
    """An empty market is an empty board. No line is filled in."""
    empty = {"id": "none", "bookmakers": []}
    for market_key in WNBA_LIVE_MARKETS:
        assert devig_board(empty, market_key) == []


def test_recorded_player_points_devig_sums_to_one() -> None:
    """The helper de-vigs the recorded NBA player_points body.

    This is the SPO-98 capture, not a WNBA body. It locks the same
    ``american_to_prob`` / ``devig`` pair the live WNBA tests use, on a
    market that is already on disk. Dropping every bookmaker is the
    empty-market case of that same body.
    """
    event = load_odds_fixture(RECORDED_PLAYER_POINTS)
    board = devig_board(event, "player_points")
    assert board, "recorded player_points body produced no complete pair"
    _assert_fair_pairs(board)

    # Derivation: drop every bookmaker from the recorded event.
    emptied = copy.deepcopy(event)
    emptied["bookmakers"] = []
    assert devig_board(emptied, "player_points") == []


def _load_env_file(path: Path) -> None:
    """Copy KEY=VALUE lines into the environment. Existing values win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _http_get(path: str, params: dict[str, str], api_key: str) -> tuple[int, Any]:
    """GET one Odds API path. ``api_key`` is sent as a query param only."""
    query = dict(params)
    query["apiKey"] = api_key
    base = os.environ.get("ODDS_API_BASE_URL", "https://api.the-odds-api.com").rstrip(
        "/"
    )
    url = f"{base}{path}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode("utf-8", errors="replace")}


@dataclass
class WnbaSlate:
    """One WNBA event and the single batched odds body."""

    event_id: str
    payload: dict[str, Any]
    calls: dict[str, int] = field(default_factory=dict)

    def posted(self, market_key: str) -> bool:
        """True when some bookmaker returned this market key."""
        for bookmaker in self.payload.get("bookmakers") or []:
            for market in bookmaker.get("markets") or []:
                if market.get("key") == market_key:
                    return True
        return False


@pytest.fixture(scope="module")
def wnba_slate() -> WnbaSlate:
    """One free events call, then one odds call, or a skip.

    Skips when no WNBA event is listed. That is the offseason case:
    there is nothing to price, and the odds call is not made.
    """
    _load_env_file(_REPO_ROOT / ".env")
    _load_env_file(_REPO_ROOT / "backend" / ".env")
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        pytest.skip("ODDS_API_KEY is not set; live WNBA odds call was not made")

    calls = {"events": 0, "odds": 0}
    status, events = _http_get(f"/v4/sports/{SPORT}/events", {}, api_key)
    calls["events"] += 1
    if status != 200:
        pytest.fail(f"WNBA events list returned HTTP {status}: {events!r}")
    if not isinstance(events, list) or not events or not events[0].get("id"):
        pytest.skip(
            "No WNBA event is listed. basketball_wnba has no upcoming "
            "slate, so the odds call was not made."
        )

    event_id = str(events[0]["id"])
    status, payload = _http_get(
        f"/v4/sports/{SPORT}/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": ",".join(WNBA_LIVE_MARKETS),
            "oddsFormat": "american",
        },
        api_key,
    )
    calls["odds"] += 1
    if status != 200 or not isinstance(payload, dict):
        pytest.fail(f"WNBA odds call returned HTTP {status}: {payload!r}")
    return WnbaSlate(event_id=event_id, payload=payload, calls=calls)


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason=(
        "RUN_INTEGRATION=1 not set; skipping live The Odds API WNBA "
        "market tests (CLAUDE.md External API Wrappers rule 2)"
    ),
)
def test_wnba_live_odds_call_is_batched(wnba_slate: WnbaSlate) -> None:
    """The fixture paid for one odds call covering every market in the tuple."""
    assert wnba_slate.calls["events"] == 1
    assert wnba_slate.calls["odds"] == 1
    assert wnba_slate.payload.get("sport_key") == SPORT


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason=(
        "RUN_INTEGRATION=1 not set; skipping live The Odds API WNBA "
        "market tests (CLAUDE.md External API Wrappers rule 2)"
    ),
)
@pytest.mark.parametrize("market_key", WNBA_LIVE_MARKETS)
def test_wnba_live_market_devigs_or_is_empty(
    wnba_slate: WnbaSlate, market_key: str
) -> None:
    """A posted market de-vigs to pairs that sum to 1. An absent one is empty.

    The empty check also runs on a copy of this response with
    ``bookmakers`` removed, so a posted market still proves the helper
    does not invent a line when the book list is empty.
    """
    board = devig_board(wnba_slate.payload, market_key)
    if not wnba_slate.posted(market_key):
        assert board == [], (
            f"{market_key} was not in the live body but the board has "
            f"{len(board)} row(s)"
        )
    else:
        _assert_fair_pairs(board)

    emptied = copy.deepcopy(wnba_slate.payload)
    emptied["bookmakers"] = []
    assert devig_board(emptied, market_key) == []
