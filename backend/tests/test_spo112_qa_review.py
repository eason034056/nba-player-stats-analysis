"""QA pins for SPO-112 signal verdicts and combined probability.

Market prices come from the recorded Odds API fixture via
``tests.fixtures.odds_api.load_odds_fixture``. A case that the capture does
not contain (a modal-line tie, a book missing one side) is a filter of that
capture. Prices and player names are not retyped.
"""

from __future__ import annotations

import asyncio
import json
import math
from unittest.mock import AsyncMock

import pytest

from app.models.schemas import DailyPick, DailyPicksResponse
from app.services.daily_analysis import DailyAnalysisService, _with_nba_signal_verdicts
from app.services.pick_signal_constants import PLATT_A, PLATT_B
from app.services.pick_signals import (
    _logit,
    _sigmoid,
    american_pairs_at_line,
    build_nba_signals,
    combined_probability,
    no_vig_consensus,
)
from app.services.prob import american_to_prob, calculate_mode_threshold, devig
from tests.fixtures.odds_api import load_odds_fixture

RECORDED = "odds_api_event_odds__player_points.json"
LUKA = "Luka Doncic"


def _filtered_books(payload: dict, keep) -> list[dict]:
    """Books from ``payload`` whose outcomes pass ``keep``.

    ``keep`` receives ``(book, outcome)``. Outcome objects stay the recorded
    dicts. Only the book and market wrappers are rebuilt, so a price cannot
    be invented here.
    """
    selected: list[dict] = []
    for book in payload["bookmakers"]:
        markets = []
        for market in book.get("markets") or []:
            outcomes = [
                outcome
                for outcome in market.get("outcomes") or []
                if keep(book, outcome)
            ]
            if not outcomes:
                continue
            copied = dict(market)
            copied["outcomes"] = outcomes
            markets.append(copied)
        if not markets:
            continue
        copied_book = dict(book)
        copied_book["markets"] = markets
        selected.append(copied_book)
    return selected


def _pair(bookmakers: list[dict], player: str, point: float, book_key: str) -> tuple[float, float]:
    """The recorded ``(over, under)`` American pair for one book at ``point``."""
    for book in bookmakers:
        if book.get("key") != book_key:
            continue
        over_price = under_price = None
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                if outcome.get("description") != player or outcome.get("point") != point:
                    continue
                name = str(outcome.get("name") or "")
                if name == "Over" and over_price is None:
                    over_price = outcome["price"]
                elif name == "Under" and under_price is None:
                    under_price = outcome["price"]
        if over_price is None or under_price is None:
            raise AssertionError(f"{book_key} has no two-sided {player} {point} in the fixture")
        return float(over_price), float(under_price)
    raise AssertionError(f"{book_key} is not in the filtered books")


def _additive_devig(p_over: float, p_under: float) -> tuple[float, float]:
    """Split the overround equally. This is not what ``prob.devig`` does."""
    vig = (p_over + p_under) - 1.0
    return (p_over - vig / 2.0, p_under - vig / 2.0)


def _legacy_pick() -> dict:
    """A DailyPick JSON object from before ``signals`` existed."""
    return {
        "player_name": "Luka Doncic",
        "event_id": "07361a8381206817e27bd2697fad7479",
        "home_team": "Atlanta Hawks",
        "away_team": "Los Angeles Lakers",
        "commence_time": "2026-11-10T00:10:00Z",
        "metric": "points",
        "threshold": 36.5,
        "direction": "over",
        "probability": 0.71,
        "n_games": 40,
        "bookmakers_count": 6,
    }


class TestCombinedProbabilityShape:
    """logit(combined) = logit(p_market) + PLATT_A + PLATT_B * adjustment."""

    def test_result_stays_inside_the_open_unit_interval(self):
        markets = (0.0, 1e-6, 0.01, 0.5, 0.73, 0.99, 1.0 - 1e-6, 1.0)
        adjustments = (-5.0, -0.35, -0.1, 0.0, 0.1, 0.35, 5.0)
        for market in markets:
            previous = None
            for adjustment in adjustments:
                got = combined_probability(
                    side="over",
                    market_probability=market,
                    adjustment=adjustment,
                )
                assert got is not None
                assert 0.0001 <= got <= 0.9999
                assert 0.0 < got < 1.0
                if previous is not None:
                    # PLATT_B is positive, so a larger adjustment cannot lower the result.
                    # Rounding to 4 decimals may leave a step flat. It must not reverse.
                    assert got + 1e-12 >= previous
                previous = got

    def test_moderate_adjustments_are_strictly_increasing(self):
        assert PLATT_B > 0
        values = [
            combined_probability(side="under", market_probability=0.42, adjustment=adjustment)
            for adjustment in (-0.35, -0.1, 0.0, 0.1, 0.35)
        ]
        assert values == sorted(values)
        assert len(set(values)) == len(values)

    def test_zero_intercept_and_zero_adjustment_returns_the_market(self, monkeypatch):
        # b in the review note is the intercept. The stored intercept is not 0.
        monkeypatch.setattr("app.services.pick_signals.PLATT_A", 0.0)
        monkeypatch.setattr("app.services.pick_signals.PLATT_B", 0.0)
        for market in (0.5, 0.25, 0.37, 0.62, 0.8):
            got = combined_probability(
                side="over",
                market_probability=market,
                adjustment=0.0,
            )
            expected = round(min(max(_sigmoid(_logit(market)), 1e-4), 1.0 - 1e-4), 4)
            assert got == expected
        assert combined_probability(side="under", market_probability=0.5, adjustment=0.0) == 0.5

    def test_stored_intercept_shifts_a_coin_flip_even_when_adjustment_is_zero(self):
        # Training used p_market = 0.5, so this intercept is applied on top of
        # every live price, including a price that is already 0.5.
        got = combined_probability(side="over", market_probability=0.5, adjustment=0.0)
        expected = round(min(max(_sigmoid(PLATT_A), 1e-4), 1.0 - 1e-4), 4)
        assert got == expected
        assert got != 0.5

    def test_live_formula_matches_logit_market_plus_platt_of_the_adjustment(self):
        market = 0.71
        adjustment = 0.12
        got = combined_probability(
            side="over",
            market_probability=market,
            adjustment=adjustment,
        )
        expected = round(
            min(max(_sigmoid(_logit(market) + PLATT_A + PLATT_B * adjustment), 1e-4), 1.0 - 1e-4),
            4,
        )
        assert got == expected
        # The same shift is not the market multiplied by PLATT_B.
        scaled_market = round(
            min(max(_sigmoid(PLATT_B * _logit(market) + PLATT_A + adjustment), 1e-4), 1.0 - 1e-4),
            4,
        )
        assert got != scaled_market

    @pytest.mark.parametrize(
        "market",
        [0.0, 1.0, float("nan"), float("inf"), float("-inf")],
    )
    def test_extreme_market_inputs(self, market):
        got = combined_probability(side="over", market_probability=market, adjustment=0.0)
        if market == 0.0:
            assert got == 0.0001
        elif market == 1.0:
            assert got == 0.9999
        else:
            assert got is None
            assert not isinstance(market, bool)
            assert not math.isfinite(market)

    @pytest.mark.xfail(
        reason=(
            "A NaN adjustment is clipped to the positive rail and published "
            "as 0.9999. Missing information must not become a probability."
        ),
        strict=False,
    )
    def test_nan_adjustment_is_not_published_as_a_probability(self):
        got = combined_probability(
            side="over",
            market_probability=0.5,
            adjustment=float("nan"),
        )
        assert got is None


class TestRecordedMarketConsensus:
    def test_modal_line_consensus_is_multiplicative_devig(self):
        payload = load_odds_fixture(RECORDED)
        books = _filtered_books(
            payload,
            lambda book, outcome: outcome.get("description") == LUKA and outcome.get("point") == 36.5,
        )
        pairs = american_pairs_at_line(books, LUKA, 36.5)
        assert sorted(book["key"] for book in books) == [
            "betonlineag",
            "betrivers",
            "bovada",
            "draftkings",
            "fanduel",
        ]
        assert len(pairs) == 5
        consensus = no_vig_consensus(pairs)
        assert consensus is not None
        fairs = [devig(american_to_prob(over), american_to_prob(under)) for over, under in pairs]
        assert consensus[0] == pytest.approx(sum(item[0] for item in fairs) / len(fairs))
        assert consensus[1] == pytest.approx(sum(item[1] for item in fairs) / len(fairs))
        assert consensus[0] + consensus[1] == pytest.approx(1.0)

        implied = [(american_to_prob(over), american_to_prob(under)) for over, under in pairs]
        raw_over = sum(item[0] for item in implied) / len(implied)
        additive = [_additive_devig(over, under) for over, under in implied]
        additive_over = sum(item[0] for item in additive) / len(additive)
        # The recorded 36.5 ladder is not symmetric, so the two de-vig rules disagree.
        assert raw_over != pytest.approx(consensus[0])
        assert additive_over != pytest.approx(consensus[0])
        assert sum(item[0] + item[1] for item in implied) / len(implied) > 1.0

    def test_one_lopsided_recorded_pair_matches_devig_not_the_additive_split(self):
        payload = load_odds_fixture(RECORDED)
        over_price, under_price = _pair(payload["bookmakers"], LUKA, 31.5, "bovada")
        implied_over = american_to_prob(over_price)
        implied_under = american_to_prob(under_price)
        fair = devig(implied_over, implied_under)
        additive = _additive_devig(implied_over, implied_under)
        assert fair != pytest.approx(additive)
        consensus = no_vig_consensus([(over_price, under_price)])
        assert consensus == pytest.approx(fair)
        assert consensus != pytest.approx(additive)

    def test_a_recorded_book_missing_one_side_is_dropped(self):
        payload = load_odds_fixture(RECORDED)

        def keep(book, outcome):
            if outcome.get("description") != LUKA or outcome.get("point") != 36.5:
                return False
            if book.get("key") == "draftkings" and outcome.get("name") == "Under":
                return False
            return True

        books = _filtered_books(payload, keep)
        pairs = american_pairs_at_line(books, LUKA, 36.5)
        keys_with_both = []
        for book in books:
            over_seen = under_seen = False
            for market in book["markets"]:
                for outcome in market["outcomes"]:
                    if outcome.get("name") == "Over":
                        over_seen = True
                    elif outcome.get("name") == "Under":
                        under_seen = True
            if over_seen and under_seen:
                keys_with_both.append(book["key"])
            if book["key"] == "draftkings":
                assert over_seen and not under_seen
        assert "draftkings" not in keys_with_both
        assert len(pairs) == 4
        consensus = no_vig_consensus(pairs)
        fairs = [devig(american_to_prob(over), american_to_prob(under)) for over, under in pairs]
        assert consensus[0] == pytest.approx(sum(item[0] for item in fairs) / len(fairs))

    def test_tied_modal_lines_average_to_a_price_nobody_posted(self):
        payload = load_odds_fixture(RECORDED)
        # Two recorded books at 36.5 and two at 37.5. Each book contributes
        # Over and Under, so the two points tie at four outcomes each.
        keep_at = {36.5: {"fanduel", "draftkings"}, 37.5: {"betmgm", "bovada"}}

        def keep(book, outcome):
            point = outcome.get("point")
            return (
                outcome.get("description") == LUKA
                and point in keep_at
                and book.get("key") in keep_at[point]
            )

        books = _filtered_books(payload, keep)
        lines = []
        for book in books:
            for market in book["markets"]:
                for outcome in market["outcomes"]:
                    lines.append(float(outcome["point"]))
        assert lines.count(36.5) == lines.count(37.5) == 4
        mode = calculate_mode_threshold(lines)
        assert mode == pytest.approx(37.0)
        assert american_pairs_at_line(books, LUKA, mode) == []
        at_low = american_pairs_at_line(books, LUKA, 36.5)
        at_high = american_pairs_at_line(books, LUKA, 37.5)
        assert len(at_low) == 2
        assert len(at_high) == 2
        signals, combined, _total = build_nba_signals(
            side="over",
            line=mode,
            player_name=LUKA,
            bookmakers=books,
            history_rate=0.7,
        )
        assert signals[0].key == "market"
        assert signals[0].value is None
        assert signals[0].verdict is None
        assert combined is None


class TestCachedDailyPickAndWnba:
    def test_json_without_the_new_fields_parses_as_none(self):
        raw = json.dumps(_legacy_pick())
        parsed = DailyPick.model_validate_json(raw)
        assert "signals" not in json.loads(raw)
        assert "combined_probability" not in json.loads(raw)
        assert parsed.signals is None
        assert parsed.combined_probability is None
        assert parsed.probability == 0.71

        explicit_null = json.loads(raw)
        explicit_null["signals"] = None
        explicit_null["combined_probability"] = None
        again = DailyPick.model_validate(explicit_null)
        assert again.signals is None
        assert again.combined_probability is None

    def test_redis_cache_hit_keeps_legacy_picks_null(self, monkeypatch):
        cached = {
            "date": "2026-11-10",
            "analyzed_at": "2026-11-10T01:00:00+00:00",
            "total_picks": 1,
            "picks": [json.loads(json.dumps(_legacy_pick()))],
            "stats": None,
            "message": None,
        }
        assert "signals" not in cached["picks"][0]
        monkeypatch.setattr(
            "app.services.daily_analysis.cache_service.get",
            AsyncMock(return_value=cached),
        )
        service = DailyAnalysisService()
        service._get_events_for_date = AsyncMock(
            side_effect=AssertionError("a cache hit must not fetch events")
        )
        result = asyncio.run(
            service.run_daily_analysis(date="2026-11-10", use_cache=True, league="nba")
        )
        assert isinstance(result, DailyPicksResponse)
        assert result.total_picks == 1
        assert result.picks[0].signals is None
        assert result.picks[0].combined_probability is None
        assert result.picks[0].player_name == "Luka Doncic"
        service._get_events_for_date.assert_not_called()

    def test_wnba_stays_null_when_the_recorded_books_are_passed_in(self):
        payload = load_odds_fixture(RECORDED)
        pick = DailyPick(
            player_name="A'ja Wilson",
            event_id="wnba-evt-1",
            home_team="Toronto Tempo",
            away_team="Seattle Storm",
            commence_time="2026-05-14T23:00:00Z",
            metric="points",
            threshold=14.5,
            direction="over",
            probability=0.74,
            n_games=18,
            bookmakers_count=3,
        )
        returned = _with_nba_signal_verdicts(
            pick,
            league="wnba",
            bookmakers_data=payload["bookmakers"],
            game_logs=[{"value": 22.0}] * 12,
        )
        assert returned is pick
        assert pick.signals is None
        assert pick.combined_probability is None
