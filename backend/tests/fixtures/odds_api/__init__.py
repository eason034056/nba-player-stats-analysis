"""Load recorded The Odds API bodies for unit tests.

The JSON files live in ``backend/tests/fixtures/`` (the parent of this
package), one file per capture. ``load_odds_fixture`` reads a file by
its basename and returns the parsed JSON. It does not rewrite fields.

A test that needs a smaller case copies that object and changes only
the fields the case controls (drop a bookmaker, drop one side, relabel
a player). Those copies are named at the call site. This module does
not invent a response.

Recorded today (SPO-98, 2026-11-09):

- ``odds_api_events__basketball_nba.json`` — ``GET /v4/sports/basketball_nba/events``.
  League ``basketball_nba`` only. No markets.
- ``odds_api_event_odds__player_points.json`` — one NBA event, market
  ``player_points`` only. Lakers at Hawks.

Not recorded (``record_fixtures.py`` writes these when ``ODDS_API_KEY``
is set; both are absent until that run):

- ``odds_api_event_odds__nba_expanded_markets.json`` — one NBA event,
  the markets that were not in the SPO-98 capture.
- ``odds_api_event_odds__wnba_expanded_markets.json`` — one WNBA event,
  written only when the free WNBA events list is non-empty.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# Parent of this package: backend/tests/fixtures/
FIXTURES_DIR = Path(__file__).resolve().parent.parent

# SPO-98 captures. Both files are in git.
RECORDED_NBA_EVENTS = "odds_api_events__basketball_nba.json"
RECORDED_PLAYER_POINTS = "odds_api_event_odds__player_points.json"

# Written by record_fixtures.py. Absent until that script runs with a key.
NBA_EXPANDED_MARKETS = "odds_api_event_odds__nba_expanded_markets.json"
WNBA_EXPANDED_MARKETS = "odds_api_event_odds__wnba_expanded_markets.json"

# Markets the recorder requests in one ``markets=`` parameter.
# player_points is already on disk, so it is not requested again.
UNRECORDED_MARKET_KEYS: tuple[str, ...] = (
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_frees_made",
    "player_field_goals",
    "player_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_points_rebounds_assists",
    "player_double_double",
)


def fixture_path(name: str) -> Path:
    """Absolute path of a fixture file. ``name`` is the basename."""
    return FIXTURES_DIR / name


def odds_fixture_exists(name: str) -> bool:
    """True when ``name`` is a file under ``backend/tests/fixtures/``."""
    return fixture_path(name).is_file()


def load_odds_fixture(name: str) -> Any:
    """Parse one recorded body.

    Args:
        name: Basename, for example ``odds_api_event_odds__player_points.json``.

    Returns:
        The JSON value (object or list). A fresh parse each call, so
        callers can mutate the result without touching the file.

    Raises:
        FileNotFoundError: the recording is not on disk.
    """
    path = fixture_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"recorded Odds API fixture not found: {path}")
    return json.loads(path.read_text())


def derive_line_board(
    books: list[dict[str, list[float]]],
    fixture_name: str = RECORDED_PLAYER_POINTS,
) -> list[dict[str, Any]]:
    """Copy recorded bookmakers and rewrite player names and lines.

    ``books[i]`` becomes bookmaker ``i`` from the recording. Each
    ``(player, line)`` is a copy of that recording's first outcome:
    ``description`` and ``point`` are replaced, and ``name``, ``price``,
    the bookmaker key, and the market key stay as recorded.

    The first outcome in the player_points capture is FanDuel's Dyson
    Daniels Over (price -113, point 10.5). Callers that need a specific
    line pass that line here; they do not retype the bookmaker shell.

    Args:
        books: One mapping per bookmaker, player name to posted lines.
            Order is the order of outcomes inside that bookmaker.
        fixture_name: Which recorded event to copy. Defaults to the
            NBA ``player_points`` capture.

    Returns:
        A ``bookmakers`` list shaped like The Odds API.
    """
    event = load_odds_fixture(fixture_name)
    recorded_books = event.get("bookmakers") or []
    if len(books) > len(recorded_books):
        raise ValueError(
            f"{fixture_name} has {len(recorded_books)} bookmakers; "
            f"cannot derive {len(books)}"
        )
    template = _first_outcome(recorded_books)
    derived: list[dict[str, Any]] = []
    for index, player_lines in enumerate(books):
        book = copy.deepcopy(recorded_books[index])
        market = copy.deepcopy(book["markets"][0])
        outcomes: list[dict[str, Any]] = []
        for player_name, lines in player_lines.items():
            for line in lines:
                outcome = copy.deepcopy(template)
                outcome["description"] = player_name
                outcome["point"] = line
                outcomes.append(outcome)
        market["outcomes"] = outcomes
        book["markets"] = [market]
        derived.append(book)
    return derived


def first_posted_market(
    fixture_name: str, market_key: str
) -> tuple[str, dict[str, Any]] | None:
    """Return ``(bookmaker key, market)`` once a recording posts ``market_key``.

    None when the file is absent, or when the file exists but no
    bookmaker returned that market with at least one outcome. Callers
    keep their inline builder on None. The returned market is a copy.
    """
    if not odds_fixture_exists(fixture_name):
        return None
    event = load_odds_fixture(fixture_name)
    if not isinstance(event, dict):
        return None
    for book in event.get("bookmakers") or []:
        book_key = book.get("key") or "unknown"
        for market in book.get("markets") or []:
            if market.get("key") != market_key:
                continue
            if not market.get("outcomes"):
                continue
            return book_key, copy.deepcopy(market)
    return None


def _first_outcome(bookmakers: list[dict[str, Any]]) -> dict[str, Any]:
    """The first outcome on the first bookmaker of a recorded event."""
    for book in bookmakers:
        for market in book.get("markets") or []:
            outcomes = market.get("outcomes") or []
            if outcomes:
                return outcomes[0]
    raise ValueError("recorded event has no outcomes to copy")
