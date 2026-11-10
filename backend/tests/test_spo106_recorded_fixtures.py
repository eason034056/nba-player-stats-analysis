"""SPO-106: what is recorded, and the switch that waits on the rest.

The two SPO-98 files are the only Odds API bodies on disk. The expanded
NBA file is what ``record_fixtures.py`` writes. Tests that need those
markets keep an inline builder until ``first_posted_market`` can see
an outcome.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fixtures.odds_api import (  # noqa: E402
    NBA_EXPANDED_MARKETS,
    RECORDED_NBA_EVENTS,
    RECORDED_PLAYER_POINTS,
    UNRECORDED_MARKET_KEYS,
    first_posted_market,
    load_odds_fixture,
    odds_fixture_exists,
)
from tests.fixtures.odds_api.record_fixtures import strip_api_key  # noqa: E402


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


def test_expanded_recordings_are_absent_until_the_recorder_runs() -> None:
    """The switch stays on the inline builder while these files are missing."""
    assert not odds_fixture_exists(NBA_EXPANDED_MARKETS)
    for market_key in UNRECORDED_MARKET_KEYS:
        assert first_posted_market(NBA_EXPANDED_MARKETS, market_key) is None


def test_strip_api_key_removes_only_the_key() -> None:
    """The recorder's only edit: the key bytes come out, the body stays."""
    raw = b'{"id":"abc","note":"secret-key-value"}'
    stripped = strip_api_key(raw, "secret-key-value")
    assert stripped == b'{"id":"abc","note":""}'
    assert strip_api_key(raw, "") == raw


def test_strip_api_key_leaves_a_body_that_does_not_contain_the_key() -> None:
    raw = b'{"id":"abc","sport_key":"basketball_nba"}'
    assert strip_api_key(raw, "not-in-body") == raw
