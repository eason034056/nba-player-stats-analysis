"""SPO-106: the recorded NBA bodies, and the sides that were not posted.

Three Odds API bodies are on disk: the SPO-98 events list, the SPO-98
``player_points`` capture, and the 2026-11-10 expanded NBA capture.
``player_frees_made`` and ``player_field_goals`` were requested and
neither book posted them. Double-double was posted as Yes only.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fixtures.odds_api import (  # noqa: E402
    NBA_EXPANDED_MARKETS,
    RECORDED_NBA_EVENTS,
    RECORDED_PLAYER_POINTS,
    first_posted_market,
    fixture_path,
    load_odds_fixture,
    odds_fixture_exists,
)
from tests.fixtures.odds_api.record_fixtures import strip_api_key  # noqa: E402

# Markets both FanDuel and DraftKings returned on the expanded capture.
POSTED_EXPANDED_MARKETS = (
    "player_assists",
    "player_double_double",
    "player_points_assists",
    "player_points_rebounds",
    "player_points_rebounds_assists",
    "player_rebounds",
    "player_rebounds_assists",
    "player_steals",
    "player_threes",
)

# Requested in the same call. Neither book returned an outcome.
NOT_POSTED_EXPANDED_MARKETS = (
    "player_frees_made",
    "player_field_goals",
)


def test_recorded_bodies_are_nba_events_and_player_points() -> None:
    """Inventory of the files that are actually in git."""
    assert odds_fixture_exists(RECORDED_NBA_EVENTS)
    assert odds_fixture_exists(RECORDED_PLAYER_POINTS)

    events = load_odds_fixture(RECORDED_NBA_EVENTS)
    assert isinstance(events, list) and events
    assert {row["sport_key"] for row in events} == {"basketball_nba"}

    odds = load_odds_fixture(RECORDED_PLAYER_POINTS)
    assert odds["sport_key"] == "basketball_nba"
    markets = {
        market["key"]
        for book in odds["bookmakers"]
        for market in book["markets"]
    }
    assert markets == {"player_points"}
    assert odds["id"] == events[0]["id"]


def test_expanded_nba_recording_matches_the_committed_body() -> None:
    """The Celtics at 76ers capture is the file the loader reads."""
    assert odds_fixture_exists(NBA_EXPANDED_MARKETS)
    raw = fixture_path(NBA_EXPANDED_MARKETS).read_bytes()
    assert b"apiKey" not in raw

    odds = load_odds_fixture(NBA_EXPANDED_MARKETS)
    assert odds["sport_key"] == "basketball_nba"
    assert odds["id"] == "cfa503c66cd505776a910921875ef7dd"
    assert odds["home_team"] == "Philadelphia 76ers"
    assert odds["away_team"] == "Boston Celtics"
    assert odds["commence_time"] == "2026-11-11T01:10:00Z"
    assert [book["key"] for book in odds["bookmakers"]] == ["fanduel", "draftkings"]

    for book in odds["bookmakers"]:
        assert {market["key"] for market in book["markets"]} == set(POSTED_EXPANDED_MARKETS)
    for market_key in POSTED_EXPANDED_MARKETS:
        assert first_posted_market(NBA_EXPANDED_MARKETS, market_key) is not None
    for market_key in NOT_POSTED_EXPANDED_MARKETS:
        assert first_posted_market(NBA_EXPANDED_MARKETS, market_key) is None

    _book_key, rebounds = first_posted_market(NBA_EXPANDED_MARKETS, "player_rebounds")
    rebound_names = {outcome["name"] for outcome in rebounds["outcomes"]}
    assert rebound_names == {"Over", "Under"}

    _book_key, double_double = first_posted_market(
        NBA_EXPANDED_MARKETS, "player_double_double"
    )
    assert {outcome["name"] for outcome in double_double["outcomes"]} == {"Yes"}

    meta_path = fixture_path(NBA_EXPANDED_MARKETS).with_suffix(".meta.json")
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text())
    assert meta["event"]["id"] == odds["id"]
    assert meta["event"]["sport_key"] == "basketball_nba"
    assert meta["recorded_at"] == "2026-11-10T19:02:40Z"
    assert meta["http_status"] == 200
    assert meta["headers"]["x-requests-used"] == "59"
    assert meta["headers"]["x-requests-remaining"] == "441"
    assert meta["headers"]["x-requests-last"] == "9"
    assert "apiKey" not in meta["query_parameters"]
    assert set(meta["markets_returned_per_book"]["fanduel"]) == set(POSTED_EXPANDED_MARKETS)
    assert set(meta["markets_returned_per_book"]["draftkings"]) == set(POSTED_EXPANDED_MARKETS)


def test_strip_api_key_removes_only_the_key() -> None:
    """The recorder's only edit: the key bytes come out, the body stays."""
    raw = b'{"id":"abc","note":"secret-key-value"}'
    stripped = strip_api_key(raw, "secret-key-value")
    assert stripped == b'{"id":"abc","note":""}'
    assert strip_api_key(raw, "") == raw


def test_strip_api_key_leaves_a_body_that_does_not_contain_the_key() -> None:
    raw = b'{"id":"abc","sport_key":"basketball_nba"}'
    assert strip_api_key(raw, "not-in-body") == raw
