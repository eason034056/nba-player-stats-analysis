"""SPO-112 signal verdicts, nulls, modal-line consensus, and the DailyPick shape."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.schemas import DailyPick, PickSignal
from app.services.daily_analysis import (
    DailyAnalysisService,
    _with_nba_signal_verdicts,
)
from app.services.pick_signal_constants import (
    ADJUSTMENT_CAP,
    PLATT_A,
    TOTAL_ADJUSTMENT_CAP,
)
from app.services.pick_signals import (
    SIGNAL_SPECS,
    adjustment_total,
    american_pairs_at_line,
    build_nba_signals,
    combined_probability,
    no_vig_consensus,
)
from app.services.prob import american_to_prob, calculate_mode_threshold, devig

FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_event_odds__player_points.json"
KEYS = [key for key, _label in SIGNAL_SPECS]


def signal_map(**overrides):
    payload = dict(
        side="over",
        line=20.5,
        player_name="Luka Doncic",
        market_probability=0.50,
        last10_values=[21, 22, 23, 24, 25, 19, 18, 17, 16, 15],
        history_rate=0.70,
        projected_value=21.0,
        opponent_rank=15,
        opponent_position_rank=15,
        injury_status=None,
    )
    payload.update(overrides)
    signals, combined, _total = build_nba_signals(**payload)
    return {signal.key: signal for signal in signals}, combined, signals


def _verdict(key: str, **overrides) -> str | None:
    found, _combined, _rows = signal_map(**overrides)
    return found[key].verdict


class TestVerdictBoundaries:
    """Each cut, on both sides. The value just inside the band is neutral."""

    @pytest.mark.parametrize("side", ["over", "under"])
    def test_market_cuts(self, side):
        assert _verdict("market", side=side, market_probability=0.52) == "supports"
        assert _verdict("market", side=side, market_probability=0.519999) == "neutral"
        assert _verdict("market", side=side, market_probability=0.50) == "neutral"
        assert _verdict("market", side=side, market_probability=0.480001) == "neutral"
        assert _verdict("market", side=side, market_probability=0.48) == "against"

    @pytest.mark.parametrize("side", ["over", "under"])
    def test_last10_cuts(self, side):
        line = 10.5
        # Hits are values on the pick's side. The other numbers miss.
        def values(hits: int) -> list[float]:
            if side == "over":
                return [11.0] * hits + [10.0] * (10 - hits)
            return [10.0] * hits + [11.0] * (10 - hits)

        assert _verdict("last10", side=side, line=line, last10_values=values(6)) == "supports"
        assert _verdict("last10", side=side, line=line, last10_values=values(5)) == "neutral"
        assert _verdict("last10", side=side, line=line, last10_values=values(4)) == "against"
        found, _combined, _signals = signal_map(
            side=side, line=line, last10_values=values(6)
        )
        assert found["last10"].value == "6/10"

    @pytest.mark.parametrize("side", ["over", "under"])
    def test_history_cuts(self, side):
        assert _verdict("history", side=side, history_rate=0.55) == "supports"
        assert _verdict("history", side=side, history_rate=0.549999) == "neutral"
        assert _verdict("history", side=side, history_rate=0.50) == "neutral"
        assert _verdict("history", side=side, history_rate=0.450001) == "neutral"
        assert _verdict("history", side=side, history_rate=0.45) == "against"

    @pytest.mark.parametrize("side", ["over", "under"])
    def test_projection_cuts_use_the_side_direction(self, side):
        # Stored edge is projection - line. Under flips it.
        line = 20.0
        assert (
            _verdict(
                "projection",
                side=side,
                line=line,
                projected_value=20.5 if side == "over" else 19.5,
            )
            == "supports"
        )
        assert (
            _verdict(
                "projection",
                side=side,
                line=line,
                projected_value=20.499 if side == "over" else 19.501,
            )
            == "neutral"
        )
        assert (
            _verdict(
                "projection",
                side=side,
                line=line,
                projected_value=19.5 if side == "over" else 20.5,
            )
            == "against"
        )
        found, _combined, _signals = signal_map(
            side=side, line=line, projected_value=21.25
        )
        assert found["projection"].value == "21.3"

    @pytest.mark.parametrize(
        ("rank", "over_verdict", "under_verdict"),
        [
            (10, "supports", "against"),
            (11, "neutral", "neutral"),
            (20, "neutral", "neutral"),
            (21, "against", "supports"),
        ],
    )
    def test_defense_cuts_mirror_across_sides(self, rank, over_verdict, under_verdict):
        assert (
            _verdict("defense", side="over", opponent_position_rank=rank, opponent_rank=None)
            == over_verdict
        )
        assert (
            _verdict("defense", side="under", opponent_position_rank=rank, opponent_rank=None)
            == under_verdict
        )
        found, _combined, _signals = signal_map(
            side="over", opponent_position_rank=rank, opponent_rank=None
        )
        assert found["defense"].value == f"#{rank}"

    def test_position_rank_wins_over_overall_rank(self):
        # Position 25 is a strong defense. Overall 5 would have supported an over.
        assert (
            _verdict(
                "defense",
                side="over",
                opponent_position_rank=25,
                opponent_rank=5,
            )
            == "against"
        )


class TestMissingInputs:
    def test_each_missing_input_is_null_not_neutral(self):
        found, combined, signals = signal_map(
            market_probability=None,
            bookmakers=None,
            last10_values=None,
            history_rate=None,
            projected_value=None,
            opponent_rank=None,
            opponent_position_rank=None,
        )
        assert [signal.key for signal in signals] == KEYS
        for signal in signals:
            assert signal.value is None
            assert signal.verdict is None
        assert combined is None

    def test_a_short_last10_window_is_missing(self):
        found, _combined, _signals = signal_map(last10_values=[1, 2, 3, 4, 5, 6, 7, 8, 9])
        assert found["last10"].value is None
        assert found["last10"].verdict is None

    def test_one_present_input_does_not_fill_the_others(self):
        found, _combined, _signals = signal_map(
            market_probability=None,
            bookmakers=None,
            last10_values=None,
            history_rate=0.70,
            projected_value=None,
            opponent_rank=None,
            opponent_position_rank=None,
        )
        assert found["history"].verdict == "supports"
        assert found["history"].value == "70.0%"
        for key in ("market", "last10", "projection", "defense"):
            assert found[key].value is None
            assert found[key].verdict is None

    def test_overall_rank_is_the_fallback(self):
        found, _combined, _signals = signal_map(
            opponent_position_rank=None, opponent_rank=8
        )
        assert found["defense"].value == "#8"
        assert found["defense"].verdict == "supports"

    def test_out_and_doubtful_drop_the_combined_probability_only(self):
        for status in ("Out", "out", " Doubtful ", "DOUBTFUL"):
            found, combined, signals = signal_map(
                injury_status=status, market_probability=0.55
            )
            assert len(signals) == 5
            assert found["market"].verdict == "supports"
            assert combined is None

    def test_probable_keeps_the_combined_probability(self):
        _found, combined, _signals = signal_map(
            injury_status="Probable", market_probability=0.55
        )
        assert combined is not None
        assert 0.0 < combined < 1.0

    def test_no_market_price_is_none_even_with_the_other_signals(self):
        _found, combined, _signals = signal_map(market_probability=None, bookmakers=[])
        assert combined is None

    def test_adjustment_total_is_capped_and_missing_terms_add_nothing(self):
        extreme = adjustment_total(
            last10_hits=10,
            history_rate=0.99,
            defense_rank_value=1,
            edge_for_side=20.0,
            side="over",
        )
        assert extreme == pytest.approx(TOTAL_ADJUSTMENT_CAP)
        assert extreme < 4 * ADJUSTMENT_CAP
        assert (
            adjustment_total(
                last10_hits=None,
                history_rate=None,
                defense_rank_value=None,
                edge_for_side=None,
                side="over",
            )
            == 0.0
        )

    def test_fair_market_and_no_features_is_the_platt_intercept(self):
        # logit(0.5) is 0, the adjustment is 0, so only PLATT_A remains.
        probability = combined_probability(
            side="over", market_probability=0.5, adjustment=0.0
        )
        from app.services.pick_signals import _sigmoid

        expected = round(min(max(_sigmoid(PLATT_A), 1e-4), 1 - 1e-4), 4)
        assert probability == pytest.approx(expected)


class TestModalLineConsensus:
    def test_books_off_the_modal_line_are_excluded(self):
        bookmakers = [
            {
                "key": "a",
                "markets": [
                    {
                        "outcomes": [
                            {"name": "Over", "description": "Ayo Dosunmu", "price": -110, "point": 10.5},
                            {"name": "Under", "description": "Ayo Dosunmu", "price": -110, "point": 10.5},
                        ]
                    }
                ],
            },
            {
                "key": "b",
                "markets": [
                    {
                        "outcomes": [
                            {"name": "Over", "description": "Ayo Dosunmu", "price": -120, "point": 10.5},
                            {"name": "Under", "description": "Ayo Dosunmu", "price": 100, "point": 10.5},
                        ]
                    }
                ],
            },
            {
                "key": "c",
                "markets": [
                    {
                        "outcomes": [
                            {"name": "Over", "description": "Ayo Dosunmu", "price": -130, "point": 12.5},
                            {"name": "Under", "description": "Ayo Dosunmu", "price": 110, "point": 12.5},
                        ]
                    }
                ],
            },
        ]
        lines = [10.5, 10.5, 10.5, 10.5, 12.5, 12.5]
        assert calculate_mode_threshold(lines) == 10.5
        pairs = american_pairs_at_line(bookmakers, "Ayo Dosunmu", 10.5)
        assert pairs == [(-110.0, -110.0), (-120.0, 100.0)]
        consensus = no_vig_consensus(pairs)
        fair_a = devig(american_to_prob(-110), american_to_prob(-110))
        fair_b = devig(american_to_prob(-120), american_to_prob(100))
        assert consensus[0] == pytest.approx((fair_a[0] + fair_b[0]) / 2)

    def test_recorded_odds_api_fixture_uses_only_the_modal_line(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bookmakers = payload["bookmakers"]
        grouped = DailyAnalysisService()._group_props_by_player(bookmakers)
        mode = calculate_mode_threshold(grouped["Luka Doncic"])
        assert mode == 36.5

        def fairs_at(line: float) -> list[tuple[float, float]]:
            found = []
            for book in bookmakers:
                over_price = under_price = None
                for market in book["markets"]:
                    for outcome in market["outcomes"]:
                        if outcome["description"] != "Luka Doncic" or outcome["point"] != line:
                            continue
                        if outcome["name"] == "Over" and over_price is None:
                            over_price = outcome["price"]
                        elif outcome["name"] == "Under" and under_price is None:
                            under_price = outcome["price"]
                if over_price is not None and under_price is not None:
                    found.append(devig(american_to_prob(over_price), american_to_prob(under_price)))
            return found

        at_mode = fairs_at(mode)
        off_mode = fairs_at(37.5)
        assert len(at_mode) == 5
        assert off_mode
        pairs = american_pairs_at_line(bookmakers, "Luka Doncic", mode)
        consensus = no_vig_consensus(pairs)
        assert consensus is not None
        assert consensus[0] == pytest.approx(sum(item[0] for item in at_mode) / len(at_mode))
        assert consensus[1] == pytest.approx(sum(item[1] for item in at_mode) / len(at_mode))
        # BetMGM's 37.5 price is not part of that mean.
        widened = no_vig_consensus(pairs + [(-105.0, -125.0)])
        assert widened[0] != pytest.approx(consensus[0])


class TestDailyPickShape:
    def _bare(self) -> DailyPick:
        return DailyPick(
            player_name="Luka Doncic",
            event_id="evt",
            home_team="Atlanta Hawks",
            away_team="Los Angeles Lakers",
            commence_time="2026-11-10T00:10:00Z",
            metric="points",
            threshold=36.5,
            direction="over",
            probability=0.71,
            n_games=40,
            bookmakers_count=6,
        )

    def test_json_shape_and_defaults(self):
        bare = self._bare()
        assert bare.signals is None
        assert bare.combined_probability is None
        dumped = bare.model_dump()
        assert dumped["signals"] is None
        assert dumped["combined_probability"] is None
        assert dumped["probability"] == 0.71

        found, combined, signals = signal_map(market_probability=0.55, history_rate=0.71)
        pick = self._bare().model_copy(
            update={"signals": signals, "combined_probability": combined}
        )
        payload = pick.model_dump()
        assert [row["key"] for row in payload["signals"]] == KEYS
        assert [row["label"] for row in payload["signals"]] == [label for _key, label in SIGNAL_SPECS]
        assert payload["signals"][2]["verdict"] == "supports"
        assert payload["combined_probability"] == combined
        for row in payload["signals"]:
            assert row["verdict"] in (None, "supports", "neutral", "against")
        again = DailyPick.model_validate(payload)
        assert again.signals[0].key == "market"
        assert isinstance(again.signals[0], PickSignal)

    def test_a_cached_payload_without_the_new_fields_still_parses(self):
        legacy = self._bare().model_dump()
        legacy.pop("signals")
        legacy.pop("combined_probability")
        parsed = DailyPick.model_validate(legacy)
        assert parsed.signals is None
        assert parsed.combined_probability is None
        assert parsed.probability == 0.71


class TestLeagueWiring:
    def test_wnba_pick_stays_null(self):
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
        bookmakers = [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "outcomes": [
                            {"name": "Over", "description": "A'ja Wilson", "price": -130, "point": 14.5},
                            {"name": "Under", "description": "A'ja Wilson", "price": 110, "point": 14.5},
                        ]
                    }
                ],
            }
        ]
        returned = _with_nba_signal_verdicts(
            pick,
            league="wnba",
            bookmakers_data=bookmakers,
            game_logs=[{"value": 20}] * 12,
        )
        assert returned is pick
        assert pick.signals is None
        assert pick.combined_probability is None

    def test_nba_analyze_attaches_five_signals_from_the_fetched_books(self):
        service = DailyAnalysisService()
        service._get_props_for_market = AsyncMock(
            return_value=[
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "outcomes": [
                                {"name": "Over", "description": "Stephen Curry", "price": -110, "point": 28.5},
                                {"name": "Under", "description": "Stephen Curry", "price": -110, "point": 28.5},
                            ]
                        }
                    ],
                }
            ]
        )
        # Oldest first, matching get_player_stats. The last 10 are six overs.
        logs = [{"team": "Warriors", "value": value} for value in [10, 30, 31, 32, 33, 34, 35, 20, 21, 22, 23]]
        service.csv_service = MagicMock()
        service.csv_service.get_player_stats = MagicMock(
            return_value={
                "p_over": 0.72,
                "p_under": 0.21,
                "n_games": 11,
                "game_logs": logs,
            }
        )
        picks, _players, _props = asyncio.run(
            service._analyze_single_event(
                event_id="evt-1",
                home_team="Team A",
                away_team="Team B",
                commence_time="2026-03-30T02:00:00Z",
                projections={
                    "Stephen Curry": {
                        "team": "GSW",
                        "points": 30.0,
                        "rebounds": 6.0,
                        "assists": 7.0,
                        "pra": 43.0,
                        "minutes": 35.0,
                        "opponent_rank": 22,
                        "opponent_position_rank": 8,
                        "injury_status": "Probable",
                    }
                },
                league="nba",
            )
        )
        points = [pick for pick in picks if pick.metric == "points"]
        assert len(points) == 1
        pick = points[0]
        assert [signal.key for signal in pick.signals] == KEYS
        assert pick.signals[0].verdict == "neutral"  # -110/-110 is 0.50
        assert pick.signals[1].value == "6/10"
        assert pick.signals[2].value == "72.0%"
        assert pick.signals[2].verdict == "supports"
        assert pick.signals[4].value == "#8"
        assert pick.combined_probability is not None
        assert pick.bookmakers_count == 2
