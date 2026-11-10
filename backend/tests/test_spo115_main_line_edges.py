"""SPO-115 edge cases for one main line per bookmaker.

Every Odds API body comes from
``tests/fixtures/odds_api_event_odds__player_points.json``
(Lakers @ Hawks, event ``07361a8381206817e27bd2697fad7479``) via
``tests.fixtures.odds_api.load_odds_fixture``. Prices and points are
read off that capture. A test may drop a side or a ``point`` to reach
a one-sided or Yes/No shape; it does not type a new price.

What is checked:

- Two rungs equally far from a coin flip resolve to the lower point,
  and the same slice in reverse order resolves to that same point.
- Over-only, Under-only, and a missing price stay on a posted rung.
- The rung that is kept is the one closest after vig is removed.
  Ranking by raw American distance from +/-100 picks a different rung
  on this capture, and that rung is not the line the other books post.
- One book with one rung votes that rung. An empty bookmaker list
  votes nobody. The same book key votes once. Two blank keys stay apart.
- Yes/No rows with no ``point`` (the double-double shape) add no line.
  Daily analysis does not request ``player_double_double``.
- On a ladder, the fair probability and the consensus average are taken
  from the main rung of each book, and the modal line is the mode of
  those same rungs.
- Pick selection on this capture is the same set of players, lines,
  directions, and probabilities before and after the count fix.
  ``bookmakers_count`` is the part that changes (20-32 down to 5-6).
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
from collections import defaultdict
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import (  # noqa: E402
    BINARY_MARKETS,
    MIN_SAMPLE_GAMES,
    SUPPORTED_MARKETS,
    DailyAnalysisService,
    _main_book_line,
    choose_daily_pick_side,
)
from app.services.prob import (  # noqa: E402
    american_to_prob,
    calculate_consensus_mean,
    calculate_mode_threshold,
    devig,
    posted_american_odds,
)
from tests.fixtures.odds_api import load_odds_fixture  # noqa: E402

_RECORDED = "odds_api_event_odds__player_points.json"
_EVENT_ID = "07361a8381206817e27bd2697fad7479"
_UNDER_PLAYER = "Jake LaRavia"


def _event() -> dict:
    return load_odds_fixture(_RECORDED)


def _service() -> DailyAnalysisService:
    return DailyAnalysisService()


def _book(event: dict, key: str) -> dict:
    return next(book for book in event["bookmakers"] if book["key"] == key)


def _player_outcomes(book: dict, player: str) -> list[dict]:
    found: list[dict] = []
    for market in book.get("markets") or []:
        for outcome in market.get("outcomes") or []:
            if outcome.get("description") == player:
                found.append(outcome)
    return found


def _legacy_points(event: dict) -> dict[str, list[float]]:
    """Pre-fix list: every outcome ``point``, both sides and every alt."""
    points: dict[str, list[float]] = defaultdict(list)
    for book in event["bookmakers"]:
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                name = outcome.get("description") or ""
                point = outcome.get("point")
                if name and point is not None:
                    points[name].append(float(point))
    return points


def _rungs(outcomes: list[dict]) -> dict[float, dict[str, float | None]]:
    """Group one player's outcomes by posted point.

    The price kept on a side is the recorded number ``posted_american_odds``
    accepts. A missing price, a null, or 0 leaves that side empty.
    """
    rungs: dict[float, dict[str, float | None]] = {}
    for outcome in outcomes:
        raw_point = outcome.get("point")
        if raw_point is None:
            continue
        point = round(float(raw_point), 1)
        side = str(outcome.get("name") or "").strip().lower()
        price = posted_american_odds(outcome.get("price"))
        rung = rungs.setdefault(point, {"over": None, "under": None})
        if side in ("over", "under") and price is not None:
            rung[side] = price
    return rungs


def _devig_distance(over: float, under: float) -> float:
    """Distance from a coin flip after the vig is removed.

    ``devig`` normalizes the two implied probabilities so they sum to 1.
    The distance is ``|p_over_fair - 0.5|``. Over -110 / Under -110
    scores 0. This is not the distance of the American number from 100.
    """
    fair_over, _fair_under = devig(american_to_prob(over), american_to_prob(under))
    return abs(fair_over - 0.5)


def _one_sided_distance(price: float) -> float:
    """Raw implied distance from 0.5. Used only when one side is absent."""
    return abs(american_to_prob(price) - 0.5)


def _raw_american_distance(over: float | None, under: float | None) -> float:
    """How close a posted American price sits to even money (+100 / -100).

    Even money is the number 100, either sign. The score is the smaller
    ``|abs(price) - 100|`` of the sides that were posted. A rung at
    -105 / -125 scores 5. A rung at -115 / -115 scores 15.
    """
    distances = [
        abs(abs(price) - 100)
        for price in (over, under)
        if price is not None
    ]
    if not distances:
        return 10_000.0
    return float(min(distances))


def _ranked_point(
    rungs: dict[float, dict[str, float | None]],
    *,
    how: str,
) -> float | None:
    """Pick a rung the way the spec describes, without calling production code.

    ``how="devig"`` ranks two-sided rungs by ``_devig_distance`` and
    one-sided rungs by ``_one_sided_distance``. Two-sided rungs are the
    only candidates when any exist. ``how="raw"`` ranks every priced
    rung by ``_raw_american_distance``. An equal score keeps the lower
    point in both rankings.
    """
    two_sided = [
        point
        for point, rung in rungs.items()
        if rung["over"] is not None and rung["under"] is not None
    ]
    priced = [
        point
        for point, rung in rungs.items()
        if rung["over"] is not None or rung["under"] is not None
    ]
    if how == "devig":
        candidates = two_sided or priced
    elif how == "raw":
        candidates = priced
    else:
        raise ValueError(how)
    if not candidates:
        return None

    def _key(point: float) -> tuple[float, float]:
        rung = rungs[point]
        over, under = rung["over"], rung["under"]
        if how == "raw":
            return (_raw_american_distance(over, under), point)
        if over is not None and under is not None:
            return (_devig_distance(over, under), point)
        price = over if over is not None else under
        assert price is not None
        return (_one_sided_distance(price), point)

    return min(candidates, key=_key)


def _wrap(book: dict, outcomes: list[dict], market_key: str | None = None) -> dict:
    """One bookmaker object whose outcomes are the slice passed in.

    ``key`` and the market key are copied off the recorded book. The
    outcomes are the recorded objects (or a copy the caller already edited).
    """
    recorded_key = book["markets"][0]["key"]
    return {
        "key": book["key"],
        "title": book.get("title"),
        "markets": [
            {
                "key": recorded_key if market_key is None else market_key,
                "outcomes": outcomes,
            }
        ],
    }


def _fair_pair(over: float, under: float) -> tuple[float, float]:
    return devig(american_to_prob(over), american_to_prob(under))


def _select_picks(
    lines_by_player: dict[str, list[float]],
    legacy_modes: dict[str, float],
) -> dict[str, dict]:
    """Apply the daily-pick gate to a line list.

    History clears 0.65 only at the pre-fix modal line. A moved line
    drops the player. Jake LaRavia clears on Under; everyone else clears
    on Over. That makes a direction change visible.
    """
    selected: dict[str, dict] = {}
    for player, lines in lines_by_player.items():
        threshold = calculate_mode_threshold(lines)
        if threshold is None:
            continue
        if threshold == legacy_modes[player]:
            if player == _UNDER_PLAYER:
                p_over, p_under = 0.10, 0.82
            else:
                p_over, p_under = 0.80, 0.12
        else:
            p_over, p_under = 0.42, 0.42
        n_games = 40
        if n_games < MIN_SAMPLE_GAMES:
            continue
        side, probability = choose_daily_pick_side(p_over, p_under)
        if side is None or probability is None:
            continue
        selected[player] = {
            "threshold": threshold,
            "direction": side,
            "probability": probability,
            "n_games": n_games,
            "bookmakers_count": len(lines),
            "all_lines": sorted(lines),
        }
    return selected


class TestDistanceAndTies:
    """Which rung is the main line, including an equal-distance pair."""

    def test_equal_devig_distance_keeps_the_lower_recorded_point(self):
        """Luka 35.5 (-135 / +105) and 37.5 (+105 / -135) are one pair.

        The two fair Overs are complements, so the distances match.
        The lower posted point is the one that has to win, in either
        outcome order.
        """
        event = _event()
        bovada = _book(event, "bovada")
        pair = [
            outcome
            for outcome in _player_outcomes(bovada, "Luka Doncic")
            if outcome["point"] in (35.5, 37.5)
        ]
        assert {outcome["point"] for outcome in pair} == {35.5, 37.5}
        assert {outcome["name"] for outcome in pair} == {"Over", "Under"}

        rungs = _rungs(pair)
        distance_low = _devig_distance(rungs[35.5]["over"], rungs[35.5]["under"])
        distance_high = _devig_distance(rungs[37.5]["over"], rungs[37.5]["under"])
        assert distance_low == distance_high
        assert _ranked_point(rungs, how="devig") == 35.5

        assert _main_book_line(pair) == 35.5
        assert _main_book_line(list(reversed(pair))) == 35.5
        grouped = _service()._group_props_by_player([_wrap(bovada, pair)])
        assert grouped["Luka Doncic"] == [35.5]

    def test_two_sided_rank_uses_devig_not_raw_american_odds(self):
        """Closest to a coin flip is the vig-free Over, not +/-100.

        On Bovada's Luka ladder the -115 / -115 rung is a fair 0.5.
        The American numbers on that rung are 15 away from 100, while
        35.5 is only 5 away (-135 / +105). Ranking by the American
        number picks 35.5, which no other book posts. Ranking after
        the vig is removed picks 36.5, which is the line the rest of
        the capture posts (BetMGM excepted, at 37.5).

        Austin Reaves and C.J. McCollum are the clean cases: every
        other book posts one rung, and that rung is the de-vigged
        Bovada rung, not the raw-American rung.
        """
        event = _event()
        bovada = _book(event, "bovada")
        disagreements: dict[str, tuple[float, float]] = {}
        for player in {outcome["description"] for book in event["bookmakers"] for market in book["markets"] for outcome in market["outcomes"]}:
            outcomes = _player_outcomes(bovada, player)
            if not outcomes:
                continue
            rungs = _rungs(outcomes)
            if len(rungs) < 2:
                continue
            devig_point = _ranked_point(rungs, how="devig")
            raw_point = _ranked_point(rungs, how="raw")
            assert _main_book_line(outcomes) == devig_point
            if devig_point != raw_point:
                disagreements[player] = (devig_point, raw_point)

        assert "Luka Doncic" in disagreements
        assert "Austin Reaves" in disagreements
        assert "C.J. McCollum" in disagreements

        luka = _rungs(_player_outcomes(bovada, "Luka Doncic"))
        balanced = [point for point, rung in luka.items() if rung["over"] == rung["under"]]
        assert balanced == [36.5]
        fair_over, fair_under = _fair_pair(luka[36.5]["over"], luka[36.5]["under"])
        assert fair_over == 0.5
        assert fair_under == 0.5
        assert _devig_distance(luka[36.5]["over"], luka[36.5]["under"]) == 0.0
        assert disagreements["Luka Doncic"] == (36.5, 35.5)
        # 35.5 is closer to +/-100 and further from a fair coin flip.
        assert _raw_american_distance(luka[35.5]["over"], luka[35.5]["under"]) < (
            _raw_american_distance(luka[36.5]["over"], luka[36.5]["under"])
        )
        assert _devig_distance(luka[35.5]["over"], luka[35.5]["under"]) > 0.0

        for player, (devig_point, raw_point) in (
            ("Austin Reaves", disagreements["Austin Reaves"]),
            ("C.J. McCollum", disagreements["C.J. McCollum"]),
        ):
            other_points = set()
            for book in event["bookmakers"]:
                if book["key"] == "bovada":
                    continue
                points = {outcome["point"] for outcome in _player_outcomes(book, player)}
                if not points:
                    continue
                assert len(points) == 1
                other_points |= points
            assert other_points == {devig_point}
            assert raw_point not in other_points


class TestOneSidedAndMissingPrice:
    """A book that did not post both sides of a rung."""

    def test_over_only_and_under_only_use_the_posted_side(self):
        """Aaron Wiggins, Bovada, one side at a time.

        Over -105 at 13.5 is the Over closest to a raw 0.5. Under +105
        at 12.5 is the Under closest to a raw 0.5. They are not the same
        rung. With both sides present, the two-sided rule keeps 13.5.
        """
        bovada = _book(_event(), "bovada")
        outcomes = _player_outcomes(bovada, "Aaron Wiggins")
        overs = [outcome for outcome in outcomes if outcome["name"] == "Over"]
        unders = [outcome for outcome in outcomes if outcome["name"] == "Under"]
        assert len(overs) == len(unders) == 7

        over_rungs = _rungs(overs)
        under_rungs = _rungs(unders)
        over_point = _ranked_point(over_rungs, how="devig")
        under_point = _ranked_point(under_rungs, how="devig")
        assert over_point == 13.5
        assert under_point == 12.5
        assert over_point != under_point
        assert _main_book_line(overs) == over_point
        assert _main_book_line(unders) == under_point
        assert _main_book_line(outcomes) == 13.5

    def test_missing_price_on_the_balanced_rung_falls_through_to_the_next(self):
        """Drop the Under price on Wiggins 13.5. Leave every other row.

        13.5 is no longer two-sided. The next two-sided rung by vig-free
        distance is 12.5. The missing price is the recorded row with the
        price key removed, and the same row with a null price.
        """
        bovada = _book(_event(), "bovada")
        outcomes = _player_outcomes(bovada, "Aaron Wiggins")

        removed = object()

        def _without_under(price_stand_in: object) -> list[dict]:
            edited = []
            for outcome in outcomes:
                if outcome["point"] == 13.5 and outcome["name"] == "Under":
                    bare = dict(outcome)
                    if price_stand_in is removed:
                        bare.pop("price", None)
                    else:
                        bare["price"] = price_stand_in
                    edited.append(bare)
                else:
                    edited.append(outcome)
            return edited

        for stand_in in (removed, None):
            edited = _without_under(stand_in)
            assert _ranked_point(_rungs(edited), how="devig") == 12.5
            assert _main_book_line(edited) == 12.5

    def test_zero_price_is_treated_as_not_posted(self):
        """0 is not a recorded price. ``posted_american_odds`` rejects it.

        The Over row is otherwise the recorded Dyson Daniels main rung
        from FanDuel (one point, both sides). Zeroing the Over leaves
        the Under, and the vote stays on that posted point.
        """
        fanduel = _book(_event(), "fanduel")
        outcomes = _player_outcomes(fanduel, "Dyson Daniels")
        assert {outcome["point"] for outcome in outcomes} == {10.5}
        edited = []
        for outcome in outcomes:
            row = dict(outcome)
            if row["name"] == "Over":
                row["price"] = 0
            edited.append(row)
        assert _main_book_line(edited) == 10.5

    def test_no_prices_keep_a_posted_point(self):
        """Wiggins' seven rungs with every price removed.

        Each point was posted twice (Over and Under). Seven tied points,
        odd count, so the middle posted point is kept. That point is
        13.5, which is on the ladder. It is not an average.
        """
        bovada = _book(_event(), "bovada")
        bare = []
        for outcome in _player_outcomes(bovada, "Aaron Wiggins"):
            row = dict(outcome)
            row.pop("price", None)
            bare.append(row)
        points = sorted({outcome["point"] for outcome in bare})
        assert len(points) == 7
        assert points[len(points) // 2] == 13.5
        assert _main_book_line(bare) == 13.5


class TestBookShape:
    """How many votes one payload produces."""

    def test_empty_bookmakers_and_a_book_with_no_markets(self):
        event = _event()
        fanduel = _book(event, "fanduel")
        service = _service()
        assert service._group_props_by_player([]) == {}
        empty = dict(fanduel)
        empty["markets"] = []
        assert service._group_props_by_player([empty]) == {}

    def test_single_rung_book_votes_that_rung_once(self):
        event = _event()
        service = _service()
        for book in event["bookmakers"]:
            if book["key"] == "bovada":
                continue
            grouped = service._group_props_by_player([book])
            assert grouped
            for player, lines in grouped.items():
                points = {outcome["point"] for outcome in _player_outcomes(book, player)}
                assert len(points) == 1
                assert lines == [round(float(next(iter(points))), 1)]
                assert len(_player_outcomes(book, player)) == 2

    def test_same_book_key_votes_once_and_blank_keys_stay_separate(self):
        fanduel = _book(_event(), "fanduel")
        service = _service()
        doubled = service._group_props_by_player([fanduel, fanduel])
        assert doubled["Luka Doncic"] == [36.5]

        first = copy.deepcopy(fanduel)
        second = copy.deepcopy(fanduel)
        for book in (first, second):
            book["key"] = ""
            book["title"] = "  "
        separate = service._group_props_by_player([first, second])
        assert separate["Luka Doncic"] == [36.5, 36.5]

    def test_two_market_keys_are_two_votes(self):
        """Daily analysis requests one market per call.

        The grouper itself does not collapse markets. A second market
        key on the same recorded outcomes is a second vote. The points
        are still the recorded points rows; only the key differs, and
        the key is one ``SUPPORTED_MARKETS`` already fetches.
        """
        fanduel = copy.deepcopy(_book(_event(), "fanduel"))
        extra = copy.deepcopy(fanduel["markets"][0])
        assert extra["key"] == "player_points"
        extra["key"] = "player_rebounds"
        assert ("player_rebounds", "rebounds") in SUPPORTED_MARKETS
        fanduel["markets"].append(extra)
        grouped = _service()._group_props_by_player([fanduel])
        assert grouped["Luka Doncic"] == [36.5, 36.5]


class TestDoubleDouble:
    """Yes/No markets have no ``point``. They must not become a line."""

    def test_yes_no_without_a_point_adds_no_vote(self):
        fanduel = _book(_event(), "fanduel")
        outcomes = []
        for outcome, side in zip(
            _player_outcomes(fanduel, "Luka Doncic"),
            ("Yes", "No"),
        ):
            row = dict(outcome)
            row["name"] = side
            row.pop("point", None)
            outcomes.append(row)
        assert all(outcome.get("point") is None for outcome in outcomes)
        assert {outcome["name"] for outcome in outcomes} == {"Yes", "No"}
        # The prices are the recorded FanDuel Luka prices, not new numbers.
        assert {outcome["price"] for outcome in outcomes} == {
            outcome["price"] for outcome in _player_outcomes(fanduel, "Luka Doncic")
        }
        grouped = _service()._group_props_by_player([_wrap(fanduel, outcomes)])
        assert grouped == {}

    def test_stripping_every_point_drops_the_whole_capture(self):
        event = copy.deepcopy(_event())
        for book in event["bookmakers"]:
            for market in book["markets"]:
                for outcome in market["outcomes"]:
                    outcome.pop("point", None)
        assert _service()._group_props_by_player(event["bookmakers"]) == {}

    def test_daily_analysis_does_not_request_the_binary_market(self):
        supported = {market for market, _metric in SUPPORTED_MARKETS}
        binary = {market for market, _metric in BINARY_MARKETS}
        assert "player_double_double" in binary
        assert "player_double_double" not in supported

        event = _event()
        requested: list[str] = []

        async def props_for_market(event_id, market, league="nba"):
            requested.append(market)
            if market == "player_points":
                return event["bookmakers"]
            return []

        service = _service()
        service._get_props_for_market = props_for_market
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value={
                "p_over": 0.80,
                "p_under": 0.12,
                "n_games": 40,
                "game_logs": [{"team": "Hawks"}],
            }
        )
        asyncio.run(
            service._analyze_single_event(
                event_id=event["id"],
                home_team=event["home_team"],
                away_team=event["away_team"],
                commence_time=event["commence_time"],
                projections={},
            )
        )
        assert "player_double_double" not in requested
        assert "player_points" in requested


class TestLadderRows:
    """Consensus, fair probability, and the modal line share one row per book."""

    def test_main_rung_is_the_row_for_fair_prob_consensus_and_mode(self):
        event = _event()
        assert event["id"] == _EVENT_ID
        service = _service()
        grouped = service._group_props_by_player(event["bookmakers"])

        for player in sorted(grouped):
            main_lines: list[float] = []
            fair_pairs: list[tuple[float, float]] = []
            bovada_index: int | None = None
            bovada_last: tuple[float, float] | None = None
            bovada_last_point: float | None = None

            for book in event["bookmakers"]:
                outcomes = _player_outcomes(book, player)
                if not outcomes:
                    continue
                rungs = _rungs(outcomes)
                main = _ranked_point(rungs, how="devig")
                assert main is not None
                assert _main_book_line(outcomes) == main
                over = rungs[main]["over"]
                under = rungs[main]["under"]
                # The capture's main rungs are two-sided, so the fair
                # pair is the vig-free price of that rung alone.
                assert over is not None and under is not None
                pair = _fair_pair(over, under)
                assert abs(pair[0] + pair[1] - 1.0) < 1e-12
                if book["key"] == "bovada" and len(rungs) >= 2:
                    last_over = next(
                        outcome
                        for outcome in reversed(outcomes)
                        if outcome["name"] == "Over"
                    )
                    last_under = next(
                        outcome
                        for outcome in reversed(outcomes)
                        if outcome["name"] == "Under"
                    )
                    bovada_index = len(fair_pairs)
                    bovada_last_point = round(float(last_over["point"]), 1)
                    bovada_last = _fair_pair(last_over["price"], last_under["price"])
                    assert bovada_last_point != main
                main_lines.append(main)
                fair_pairs.append(pair)

            assert grouped[player] == main_lines
            modal = calculate_mode_threshold(main_lines)
            assert modal == calculate_mode_threshold(grouped[player])
            consensus = calculate_consensus_mean(fair_pairs)
            assert consensus is not None

            # The last file-order pair is the alternate the no-vig parser
            # keeps (it overwrites Over, then Under, as it walks the
            # array). That pair is a different row. Swapping it in moves
            # the average. The modal line stays on the main rungs.
            assert bovada_index is not None and bovada_last is not None
            assert bovada_last != fair_pairs[bovada_index]
            assert bovada_last_point != main_lines[bovada_index]
            swapped = list(fair_pairs)
            swapped[bovada_index] = bovada_last
            swapped_consensus = calculate_consensus_mean(swapped)
            assert swapped_consensus is not None
            assert swapped_consensus != consensus


class TestPickSelectionRegression:
    """Same picks on the recorded slate. The count is the only change."""

    def test_selection_matches_the_pre_fix_lines(self):
        event = _event()
        assert event["id"] == _EVENT_ID
        assert event["home_team"] == "Atlanta Hawks"
        assert event["away_team"] == "Los Angeles Lakers"

        legacy = _legacy_points(event)
        new_lines = _service()._group_props_by_player(event["bookmakers"])
        assert set(legacy) == set(new_lines)
        assert len(legacy) == 15

        legacy_modes = {
            player: calculate_mode_threshold(points)
            for player, points in legacy.items()
        }
        before = _select_picks(legacy, legacy_modes)
        after = _select_picks(new_lines, legacy_modes)

        assert set(before) == set(after) == set(legacy)
        for player in legacy:
            assert 20 <= len(legacy[player]) <= 32
            assert len(new_lines[player]) in (5, 6)
            assert len(new_lines[player]) < len(legacy[player])
            assert before[player]["threshold"] == after[player]["threshold"]
            assert before[player]["direction"] == after[player]["direction"]
            assert before[player]["probability"] == after[player]["probability"]
            assert before[player]["n_games"] == after[player]["n_games"]
            assert before[player]["bookmakers_count"] == len(legacy[player])
            assert after[player]["bookmakers_count"] == len(new_lines[player])
            assert after[player]["all_lines"] == sorted(new_lines[player])
            # The old list is not the new list. Both still share a mode,
            # which is why the gate does not drop or retarget anyone.
            assert before[player]["all_lines"] != after[player]["all_lines"]
            assert before[player]["threshold"] == legacy_modes[player]

        assert after[_UNDER_PLAYER]["direction"] == "under"
        assert before[_UNDER_PLAYER]["direction"] == "under"
        overs = [player for player, pick in after.items() if player != _UNDER_PLAYER]
        assert overs
        assert all(after[player]["direction"] == "over" for player in overs)

        async def props_for_market(event_id, market, league="nba"):
            if market != "player_points":
                return []
            return event["bookmakers"]

        service = _service()
        service._get_props_for_market = props_for_market

        def get_player_stats(player_name, metric, threshold, **kwargs):
            if (
                metric == "points"
                and threshold == legacy_modes[player_name]
            ):
                if player_name == _UNDER_PLAYER:
                    p_over, p_under = 0.10, 0.82
                else:
                    p_over, p_under = 0.80, 0.12
            else:
                p_over, p_under = 0.42, 0.42
            return {
                "p_over": p_over,
                "p_under": p_under,
                "n_games": 40,
                "game_logs": [{"team": "Hawks"}],
            }

        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(side_effect=get_player_stats)
        picks, player_count, prop_count = asyncio.run(
            service._analyze_single_event(
                event_id=event["id"],
                home_team=event["home_team"],
                away_team=event["away_team"],
                commence_time=event["commence_time"],
                projections={},
            )
        )
        assert player_count == prop_count == len(picks) == 15
        by_name = {pick.player_name: pick for pick in picks}
        assert set(by_name) == set(after)
        for player, expected in after.items():
            pick = by_name[player]
            assert pick.metric == "points"
            assert pick.threshold == expected["threshold"]
            assert pick.direction == expected["direction"]
            assert pick.probability == expected["probability"]
            assert pick.n_games == expected["n_games"]
            assert pick.bookmakers_count == expected["bookmakers_count"]
            assert pick.all_lines == expected["all_lines"]
            # Five books is still a pick. Nothing filters on the count.
            if player in {"C.J. McCollum", "Sandro Mamukelashvili", "Ziaire Williams"}:
                assert pick.bookmakers_count == 5
