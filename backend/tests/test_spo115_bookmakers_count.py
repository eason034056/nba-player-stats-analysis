"""SPO-115: one bookmaker, one main line.

The recorded body is ``tests/fixtures/odds_api_event_odds__player_points.json``
(Lakers @ Hawks, event ``07361a8381206817e27bd2697fad7479``). Every
outcome below is taken from that file. Nothing here invents an Odds API
shape.

``_group_props_by_player`` used to append Over and Under, so
``bookmakers_count`` was the outcome-row count. It is now the number of
distinct bookmakers that post the player. Bovada's alternate ladder
votes once, at the rung closest to a coin flip.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import DailyAnalysisService
from app.services.prob import calculate_mode_threshold


_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "odds_api_event_odds__player_points.json"
)


def _event() -> dict:
    return json.loads(_FIXTURE.read_text())


def _service() -> DailyAnalysisService:
    return DailyAnalysisService()


def _distinct_books(event: dict) -> dict[str, set[str]]:
    """Bookmaker keys that post a numeric point for each player.

    Counted from the fixture directly, not from the function under test.
    """
    books: dict[str, set[str]] = defaultdict(set)
    for bookmaker in event["bookmakers"]:
        book_key = bookmaker["key"]
        for market in bookmaker["markets"]:
            for outcome in market["outcomes"]:
                name = outcome.get("description")
                if name and outcome.get("point") is not None:
                    books[name].add(book_key)
    return books


def _every_outcome_point(event: dict) -> dict[str, list[float]]:
    """The pre-fix list: both sides, and every alternate rung."""
    points: dict[str, list[float]] = defaultdict(list)
    for bookmaker in event["bookmakers"]:
        for market in bookmaker["markets"]:
            for outcome in market["outcomes"]:
                name = outcome.get("description") or ""
                point = outcome.get("point")
                if name and point is not None:
                    points[name].append(float(point))
    return points


def _book(event: dict, key: str) -> dict:
    return next(book for book in event["bookmakers"] if book["key"] == key)


def _player_outcomes(book: dict, player: str) -> list[dict]:
    found: list[dict] = []
    for market in book["markets"]:
        for outcome in market["outcomes"]:
            if outcome.get("description") == player:
                found.append(outcome)
    return found


class TestRecordedPlayerPoints:
    """Lakers @ Hawks player_points, six US books, recorded 2026-11-09."""

    def test_fixture_is_the_recorded_six_book_slate(self):
        event = _event()
        assert event["id"] == "07361a8381206817e27bd2697fad7479"
        assert event["home_team"] == "Atlanta Hawks"
        assert event["away_team"] == "Los Angeles Lakers"
        assert [book["key"] for book in event["bookmakers"]] == [
            "fanduel",
            "draftkings",
            "betrivers",
            "betmgm",
            "betonlineag",
            "bovada",
        ]
        assert {market["key"] for book in event["bookmakers"] for market in book["markets"]} == {
            "player_points"
        }

    def test_count_equals_distinct_bookmakers(self):
        event = _event()
        grouped = _service()._group_props_by_player(event["bookmakers"])
        distinct = _distinct_books(event)
        legacy = _every_outcome_point(event)

        assert set(grouped) == set(distinct)
        for player, books in distinct.items():
            lines = grouped[player]
            # One float per book, not one float per Over/Under row.
            assert len(lines) == len(books)
            assert len(set(lines)) <= len(books)
            # The old list is at least twice as long: every rung in this
            # file is two-sided, and Bovada adds extra rungs.
            assert len(legacy[player]) >= 2 * len(books)
            # On this slate the modal line does not move. Equal
            # double-counting preserves a mode; Bovada's rungs are spread
            # so no single alternate outvotes the consensus point.
            assert calculate_mode_threshold(lines) == calculate_mode_threshold(
                legacy[player]
            )

    def test_known_book_counts_and_modes(self):
        """Pinned to the recorded file so a main-line change is visible.

        BetMGM does not post McCollum, Mamukelashvili, or Ziaire Williams.
        Everyone else is on all six books. The mode is the consensus
        main line, which the pre-fix count also produced.
        """
        grouped = _service()._group_props_by_player(_event()["bookmakers"])
        six = {
            "Aaron Wiggins": 13.5,
            "Austin Reaves": 21.5,
            "Dyson Daniels": 10.5,
            "Jake LaRavia": 6.5,
            "Jalen Johnson": 20.5,
            "Kingston Flemings": 8.5,
            "Luguentz Dort": 7.5,
            "Luka Doncic": 36.5,
            "Matisse Thybulle": 6.5,
            "Nickeil Alexander-Walker": 19.5,
            "Onyeka Okongwu": 13.5,
            "Walker Kessler": 14.5,
        }
        five = {
            "C.J. McCollum": 12.5,
            "Sandro Mamukelashvili": 8.5,
            "Ziaire Williams": 8.5,
        }
        assert set(grouped) == set(six) | set(five)
        for player, mode in six.items():
            assert len(grouped[player]) == 6
            assert calculate_mode_threshold(grouped[player]) == mode
        for player, mode in five.items():
            assert len(grouped[player]) == 5
            assert calculate_mode_threshold(grouped[player]) == mode
        # BetMGM's Luka is 37.5. The other five books are 36.5.
        assert sorted(grouped["Luka Doncic"]) == [36.5, 36.5, 36.5, 36.5, 36.5, 37.5]

    def test_over_and_under_at_the_same_point_count_once(self):
        event = _event()
        fanduel = _book(event, "fanduel")
        outcomes = _player_outcomes(fanduel, "Dyson Daniels")
        assert [outcome["name"] for outcome in outcomes] == ["Over", "Under"]
        assert {outcome["point"] for outcome in outcomes} == {10.5}
        book = {
            "key": fanduel["key"],
            "title": fanduel["title"],
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": outcomes,
                }
            ],
        }
        grouped = _service()._group_props_by_player([book])
        assert grouped["Dyson Daniels"] == [10.5]

    def test_bovada_ladder_votes_the_even_money_rung(self):
        event = _event()
        bovada = _book(event, "bovada")
        grouped = _service()._group_props_by_player([bovada])

        # Aaron Wiggins: 13.5 is -105/-125. The rungs on either side are
        # further from a coin flip. The ladder is seven points.
        wiggins = _player_outcomes(bovada, "Aaron Wiggins")
        wiggins_points = {outcome["point"] for outcome in wiggins}
        assert len(wiggins_points) == 7
        assert grouped["Aaron Wiggins"] == [13.5]

        # Luka's -115/-115 rung is 36.5. Eleven rungs collapse to that one.
        luka_points = {outcome["point"] for outcome in _player_outcomes(bovada, "Luka Doncic")}
        assert len(luka_points) == 11
        assert grouped["Luka Doncic"] == [36.5]

        # Onyeka's balanced Bovada rung is 12.5, not the 13.5 the other
        # books post. He still contributes one number.
        assert len({outcome["point"] for outcome in _player_outcomes(bovada, "Onyeka Okongwu")}) == 6
        assert grouped["Onyeka Okongwu"] == [12.5]

    def test_different_points_are_not_averaged(self):
        """Over 36.5 and Under 37.5 are two real Bovada Luka rows.

        They are not a pair at one number. The function keeps the side
        closer to even money (Over -115 at 36.5) and does not publish 37.0.
        """
        event = _event()
        bovada = _book(event, "bovada")
        outcomes = [
            outcome
            for outcome in _player_outcomes(bovada, "Luka Doncic")
            if (outcome["name"] == "Over" and outcome["point"] == 36.5)
            or (outcome["name"] == "Under" and outcome["point"] == 37.5)
        ]
        assert {outcome["point"] for outcome in outcomes} == {36.5, 37.5}
        book = {
            "key": bovada["key"],
            "markets": [{"key": "player_points", "outcomes": outcomes}],
        }
        grouped = _service()._group_props_by_player([book])
        assert grouped["Luka Doncic"] == [36.5]

    def test_unpriced_points_stay_on_a_posted_number(self):
        """Strip the prices off two real Bovada rungs at the ends of a ladder.

        10.5 and 16.5 with no price must not become their average, 13.5.
        With no prices the lower of the two central posted points is kept.
        """
        event = _event()
        bovada = _book(event, "bovada")
        ends = []
        for outcome in _player_outcomes(bovada, "Aaron Wiggins"):
            if outcome["name"] != "Over":
                continue
            if outcome["point"] not in (10.5, 16.5):
                continue
            bare = dict(outcome)
            bare.pop("price", None)
            ends.append(bare)
        assert {outcome["point"] for outcome in ends} == {10.5, 16.5}
        book = {
            "key": bovada["key"],
            "markets": [{"key": "player_points", "outcomes": ends}],
        }
        grouped = _service()._group_props_by_player([book])
        assert grouped["Aaron Wiggins"] == [10.5]


class TestDailyPickConsumers:
    """The count and the line list have two consumers in daily analysis.

    ``calculate_mode_threshold`` sets ``DailyPick.threshold``.
    ``len(lines)`` sets ``DailyPick.bookmakers_count``. There is no
    min-bookmaker filter: a player on five books is still a pick when
    the historical rate clears 0.65.
    """

    def _picks(self):
        event = _event()

        async def props_for_market(event_id, market, league="nba"):
            if market != "player_points":
                return []
            return event["bookmakers"]

        service = _service()
        service._get_props_for_market = props_for_market
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value={
                "p_over": 0.80,
                "p_under": 0.15,
                "n_games": 40,
                "game_logs": [{"team": "Hawks"}],
            }
        )
        picks, player_count, prop_count = asyncio.run(
            service._analyze_single_event(
                event_id=event["id"],
                home_team=event["home_team"],
                away_team=event["away_team"],
                commence_time=event["commence_time"],
                projections={},
            )
        )
        return picks, player_count, prop_count, service

    def test_pick_count_matches_distinct_books_and_the_mode_is_unchanged(self):
        event = _event()
        picks, player_count, prop_count, service = self._picks()
        distinct = _distinct_books(event)
        legacy = _every_outcome_point(event)
        grouped = service._group_props_by_player(event["bookmakers"])

        assert player_count == len(distinct) == 15
        assert prop_count == 15
        assert len(picks) == 15
        by_name = {pick.player_name: pick for pick in picks}
        assert set(by_name) == set(distinct)

        for player, books in distinct.items():
            pick = by_name[player]
            assert pick.metric == "points"
            assert pick.bookmakers_count == len(books)
            assert pick.all_lines == sorted(grouped[player])
            assert pick.threshold == calculate_mode_threshold(grouped[player])
            assert pick.threshold == calculate_mode_threshold(legacy[player])
            assert pick.direction == "over"
            assert pick.probability == 0.80

        # History was queried at the new mode, which equals the old mode,
        # so the side decision on this fixture does not change.
        queried = {
            call.kwargs["player_name"]: call.kwargs["threshold"]
            for call in service.csv_service.get_player_stats.call_args_list
        }
        assert set(queried) == set(distinct)
        for player, threshold in queried.items():
            assert threshold == calculate_mode_threshold(legacy[player])

        # Five books is enough. Nothing drops McCollum for a short book list.
        assert by_name["C.J. McCollum"].bookmakers_count == 5
